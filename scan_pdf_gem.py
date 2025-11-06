# scan_pdf_rules.py
# ------------------------------------------------------------
# pip install google-api-python-client google-auth google-auth-httplib2 tenacity pypdf pdf2image pytesseract pillow
#
# Optional system deps (for OCR-guided signature detection):
# - Windows (choco): choco install tesseract poppler
# - Ensure tesseract.exe and pdftoppm.exe are on PATH

import csv, io, os, re
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from pypdf import PdfReader
from PIL import Image, ImageOps

# ---- Optional OCR (used only to locate the "Signature:" label) ----
try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# ===== CONFIG (edit these) =====
SERVICE_ACCOUNT_FILE = r"C:\secrets\cloud-451915-9a7a73426b73.json"
IMPERSONATE_USER     = "pcuenco@elhaynes.org"
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]
INCLUDE_SHARED_DRIVES = False       # My Drive only
MAX_PDF_BYTES         = 25 * 1024 * 1024
REPORT_CSV = f"pdf-rule-findings-{IMPERSONATE_USER.replace('@','_')}-{datetime.now():%Y%m%d-%H%M%S}.csv"

PDF_MIME = "application/pdf"

# Address keywords (case-insensitive). Fails if any appear in address.
ADDR_FORBIDDEN = re.compile(r"\b(apartment)\b|#", re.IGNORECASE)

# --- Signature ink-detection tuning (more permissive) ---
OCR_DPI = 300                 # higher DPI = better localization
SIGNATURE_BAND_WIDTH = 0.50   # search farther to the right
SIGNATURE_BAND_TALL  = 110    # taller band around label baseline
GRAY_THRESHOLD        = 245   # count lighter strokes as ink
MIN_INK_COVERAGE      = 0.0015  # 0.15% ink is enough

# FIXED TEMPLATE BOX FOR SCHOOL OFFICIAL SIGNATURE (Step Four)
# This bypasses the OCR label search for maximum reliability on this field.
TEMPLATE_SIGNATURE_BOX = {
    "page": 1,
    # (left, top, right, bottom) as fractions of page width & height
    # Set to cover the "School Official Use Only" signature line
    "box": (0.50, 0.90, 0.75, 0.94) 
}


# Debug: write crops so you can see what we’re measuring
DEBUG_SIGNATURE = True
DEBUG_DIR = "signature_debug"


# ===== DRIVE HELPERS =====
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    ).with_subject(IMPERSONATE_USER)
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def is_folder(mime: str) -> bool:
    return mime == "application/vnd.google-apps.folder"

@retry(retry=retry_if_exception_type(HttpError),
       wait=wait_exponential(multiplier=1, min=2, max=30),
       stop=stop_after_attempt(6))
def _list_files_page(svc, q: str, page_token: Optional[str], fields: str, drive_id: Optional[str] = None):
    args = {
        "q": q, "spaces": "drive", "pageSize": 1000, "pageToken": page_token, "fields": fields,
        "includeItemsFromAllDrives": INCLUDE_SHARED_DRIVES, "supportsAllDrives": INCLUDE_SHARED_DRIVES,
        "corpora": "drive" if drive_id else "user",
    }
    if drive_id: args["driveId"] = drive_id
    return svc.files().list(**args).execute()

def list_children(svc, parent_id: str, drive_id: Optional[str] = None) -> Iterable[Dict]:
    fields = "nextPageToken, files(id,name,mimeType,modifiedTime,size,parents,owners(emailAddress))"
    q = f"'{parent_id}' in parents and trashed=false"
    token = None
    while True:
        resp = _list_files_page(svc, q, token, fields, drive_id)
        for f in resp.get("files", []):
            yield f
        token = resp.get("nextPageToken")
        if not token: break

def mydrive_root_id(svc) -> str:
    return svc.files().get(fileId="root", fields="id").execute()["id"]

def walk_mydrive_pdfs(svc, root_name: str, root_id: str) -> Iterable[Dict]:
    stack = [{"id": root_id, "path": f"/{root_name}"}]
    seen = set()
    while stack:
        node = stack.pop()
        for item in list_children(svc, node["id"]):
            iid = item["id"]
            if iid in seen: continue
            seen.add(iid)
            mime = item.get("mimeType", "")
            name = item.get("name", "")
            path = f"{node['path']}/{name}"
            item["path"] = path
            if is_folder(mime):
                stack.append({"id": iid, "path": path})
            elif mime == PDF_MIME or name.lower().endswith(".pdf"):
                yield item

def _download_pdf_bytes(svc, file_id: str, *, size_hint: Optional[int]) -> Optional[bytes]:
    if size_hint:
        try:
            if int(size_hint) > MAX_PDF_BYTES:
                return None
        except Exception:
            pass
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req, chunksize=1024*1024)
    done = False
    while not done:
        status, done = dl.next_chunk()
        if buf.tell() > MAX_PDF_BYTES:
            return None
    return buf.getvalue()

# ===== ACROFORM + ADDRESS =====
def _iter_acroform_fields(reader: PdfReader):
    """Yield (name, value, obj) for each AcroForm field."""
    try:
        root = reader.trailer["/Root"]
        if "/AcroForm" not in root:
            return
        form = root["/AcroForm"]
        for fref in form.get("/Fields", []):
            fobj = fref.get_object()
            name = fobj.get("/T")
            value = fobj.get("/V")
            if hasattr(name, "get_object"): name = name.get_object()
            if hasattr(value, "get_object"): value = value.get_object()
            yield (str(name) if name is not None else "", str(value) if value is not None else "", fobj)
    except Exception:
        return

def extract_address_value(reader: PdfReader, fallback_text: str) -> str:
    """
    Prefer AcroForm field value for 'Address of enrolling person'.
    Fallback to label-based scrape in flattened PDFs.
    """
    # Prefer form fields (name or tooltip containing address + enroll)
    for name, value, fobj in _iter_acroform_fields(reader):
        low = (name or "").lower()
        tu  = str(fobj.get("/TU","")).lower()
        if ("address" in low or "address" in tu) and ("enroll" in low or "enrolling" in low or "enroll" in tu or "enrolling" in tu):
            if value and value.strip():
                return value.strip()

    # Fallback: regex near the label
    m = re.search(r"Address of enrolling person[:\s]*(.*)", fallback_text, flags=re.IGNORECASE)
    if m:
        tail = m.group(1).strip()
        if len(tail) < 5:
            after = fallback_text[m.end():].splitlines()
            if after:
                tail += " " + after[0].strip()
        return tail.strip()

    m2 = re.search(r"(Address of enrolling person.*?)(?:City:|State:|ZIP:)", fallback_text, flags=re.IGNORECASE|re.DOTALL)
    if m2:
        seg = m2.group(1)
        mm = re.search(r"Address of enrolling person[:\s]*(.*)", seg, flags=re.IGNORECASE)
        if mm:
            return mm.group(1).strip()

    return ""

def extract_address_violations(pdf_bytes: bytes) -> List[str]:
    errs: List[str] = []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join([(p.extract_text() or "") for p in reader.pages])
    except Exception:
        return errs
    addr = extract_address_value(reader, text)
    if addr and ADDR_FORBIDDEN.search(addr):
        errs.append(f"Address contains forbidden token: {addr!r}")
    return errs

# ===== SIGNATURE DETECTION =====
def has_digital_signature(reader: PdfReader) -> bool:
    """Detect /Sig AcroForm fields (digital signatures)."""
    try:
        root = reader.trailer["/Root"]
        if "/AcroForm" in root:
            form = root["/AcroForm"]
            for fref in form.get("/Fields", []):
                fobj = fref.get_object()
                if str(fobj.get("/FT")) == "/Sig":
                    return True
    except Exception:
        pass
    return False

# *** Use the path you found for the Poppler bin directory ***
# Ensure this path is correct and contains pdftoppm.exe
POPPLER_BIN_PATH = r"C:\poppler\poppler-25.07.0\Library\bin" 

def _page_images(pdf_bytes: bytes, dpi: int) -> List[Image.Image]:
    if not OCR_AVAILABLE:
        raise RuntimeError("PDF to image conversion requested, but OCR dependencies (Tesseract/Poppler) are not available.")
    
    # Use the poppler_path parameter to fix the "not in PATH" error
    return convert_from_bytes(
        pdf_bytes, 
        dpi=dpi, 
        fmt="png", 
        poppler_path=POPPLER_BIN_PATH 
    )

def _find_signature_label_boxes(img: Image.Image) -> List[Tuple[int,int,int,int]]:
    """Use Tesseract to locate 'Signature:' (or 'Signature') label boxes on the page."""
    data = pytesseract.image_to_data(img, output_type='dict')
    boxes = []
    for i, word in enumerate(data['text']):
        w = word.strip().lower()
        if w in ("signature:", "signature"):
            x, y, w_, h_ = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
            boxes.append((x, y, w_, h_))
    return boxes

def _ink_coverage(img: Image.Image) -> float:
    """Return fraction of non-white pixels in [0..1]."""
    gray = ImageOps.grayscale(img)
    hist = gray.histogram()  # 256 bins
    dark = sum(hist[0:GRAY_THRESHOLD])   # <= threshold counted as ink
    total = sum(hist)
    return (dark / total) if total else 0.0

def signature_present_via_ink(pdf_bytes: bytes) -> bool:
    """
    Detect ink using fixed template coordinates (preferred) or OCR-guided search.
    Includes error logging for template mode to help diagnose dependency issues.
    """
    if not OCR_AVAILABLE:
        print("[WARNING] Skipping ink-based signature check: OCR dependencies (Tesseract/Poppler) are missing.")
        return False
        
    # Fixed template mode (USE THIS FOR THE SCHOOL OFFICIAL SIGNATURE)
    if TEMPLATE_SIGNATURE_BOX is not None:
        try:
            images = _page_images(pdf_bytes, OCR_DPI)
            
            # Check if the page exists
            page_idx = max(0, TEMPLATE_SIGNATURE_BOX.get("page", 1) - 1)
            if not (0 <= page_idx < len(images)):
                print(f"[ERROR] Template page index {page_idx+1} out of bounds.")
                return False
                
            img = images[page_idx]
            W, H = img.width, img.height
            l, t, r, b = TEMPLATE_SIGNATURE_BOX["box"]
            
            # Convert fractional coordinates to pixel coordinates
            crop_box = (int(W*l), int(H*t), int(W*r), int(H*b))
            
            crop = img.crop(crop_box)
            cov = _ink_coverage(crop)
            
            if DEBUG_SIGNATURE:
                os.makedirs(DEBUG_DIR, exist_ok=True)
                tag = f"template_crop_p{page_idx+1}_{crop_box[0]}-{crop_box[1]}-{crop_box[2]}-{crop_box[3]}"
                crop.save(os.path.join(DEBUG_DIR, f"{tag}_{cov:.4f}.png"))
                print(f"[DEBUG] template ink coverage={cov:.4f}")
            
            return cov >= MIN_INK_COVERAGE
            
        except RuntimeError as e:
            # Catches the explicit 'dependencies not available' error from _page_images
            print(f"[ERROR] Dependency check failed for template mode: {e}")
            return False
        except Exception as e:
            # Catches other errors (e.g., crop operation failed)
            print(f"[ERROR] Template mode failed during processing: {e}")
            return False

    # OCR-guided mode (Fallback if TEMPLATE_SIGNATURE_BOX is None)
    try:
        images = _page_images(pdf_bytes, OCR_DPI)
    except Exception:
        return False

    if DEBUG_SIGNATURE:
        os.makedirs(DEBUG_DIR, exist_ok=True)

    def covered(crop_img: Image.Image, tag: str) -> bool:
        cov = _ink_coverage(crop_img)
        if DEBUG_SIGNATURE:
            fname = os.path.join(DEBUG_DIR, f"{tag}_{cov:.4f}.png")
            crop_img.save(fname)
            print(f"[DEBUG] {tag} ink coverage={cov:.4f}")
        return cov >= MIN_INK_COVERAGE

    for page_idx, img in enumerate(images, start=1):
        W, H = img.width, img.height
        boxes = _find_signature_label_boxes(img)
        for (x, y, w, h) in boxes:
            # Band A: around baseline (standard area)
            x1 = x + w + 10
            y1 = max(0, y - SIGNATURE_BAND_TALL // 2)
            x2 = min(W, int(x1 + SIGNATURE_BAND_WIDTH * W))
            y2 = min(H, y + h + SIGNATURE_BAND_TALL // 2)
            if x1 < x2 and y1 < y2:
                cropA = img.crop((x1, y1, x2, y2))
                if covered(cropA, f"p{page_idx}_A_{x1}-{y1}-{x2}-{y2}"):
                    return True

            # Band B: shifted UP (to catch cursive above the line)
            shift_up = int(0.06 * H)
            y1b = max(0, (y - SIGNATURE_BAND_TALL) - shift_up)
            y2b = min(H, (y + h) - shift_up + SIGNATURE_BAND_TALL)
            if x1 < x2 and y1b < y2b:
                cropB = img.crop((x1, y1b, x2, y2b))
                if covered(cropB, f"p{page_idx}_B_{x1}-{y1b}-{x2}-{y2b}"):
                    return True

    return False

def signature_violations(pdf_bytes: bytes) -> List[str]:
    errs: List[str] = []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if has_digital_signature(reader):
            return errs  # OK (digitally signed)
    except Exception:
        pass

    # Ink-based detection (OCR-guided or fixed template)
    if signature_present_via_ink(pdf_bytes):
        return errs

    errs.append("School official Signature line appears blank (no ink detected).")
    return errs

# ===== MAIN =====
def main():
    svc = get_drive_service()
    who = svc.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    print(f"Impersonating: {who} | OCR available: {OCR_AVAILABLE} "
          f"({'OK' if OCR_AVAILABLE else 'Install Tesseract + Poppler for best results'})")

    if OCR_AVAILABLE and DEBUG_SIGNATURE:
        print(f"Ink detection active. Debug files will be saved to: {DEBUG_DIR}")

    root_id = mydrive_root_id(svc)
    findings: List[Dict] = []

    for fmeta in walk_mydrive_pdfs(svc, f"My Drive ({IMPERSONATE_USER})", root_id):
        fid   = fmeta["id"]
        fname = fmeta.get("name","")
        fpath = fmeta.get("path","")
        sz    = fmeta.get("size")

        pdf_bytes = _download_pdf_bytes(svc, fid, size_hint=int(sz) if sz else None)
        if not pdf_bytes:
            continue
        # ------------------------------------------------------------------
        # NEW FILTERING LOGIC
        # ------------------------------------------------------------------
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            
            # Check for the required header text on the first page
            first_page_text = reader.pages[0].extract_text() or ""
            REQUIRED_HEADER = "DC Residency Verification Form"
            
            if REQUIRED_HEADER not in first_page_text:
                print(f"[SKIP] File {fname!r} does not contain header: {REQUIRED_HEADER}")
                continue  # Skip to the next file
            
        except Exception as e:
            # Skip if PyPDF fails to read the PDF structure (e.g., corrupt file)
            print(f"[ERROR] Failed to read structure of {fname!r}: {e}")
            continue
        # ------------------------------------------------------------------

        row_issues: List[str] = []
        row_issues += extract_address_violations(pdf_bytes)
        row_issues += signature_violations(pdf_bytes)

        for issue in row_issues:
            findings.append({
                "fileId": fid,
                "fileName": fname,
                "filePath": fpath,
                "issue": issue
            })

    # Write CSV
    os.makedirs(os.path.dirname(REPORT_CSV) or ".", exist_ok=True)
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["fileId","fileName","filePath","issue"])
        writer.writeheader()
        writer.writerows(findings)

    print(f"Scan complete. Issues found: {len(findings)}  →  {REPORT_CSV}")

if __name__ == "__main__":
    main()