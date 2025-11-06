# scan_pdf_rules_v2.py
# ------------------------------------------------------------
# pip install google-api-python-client google-auth google-auth-httplib2 tenacity pypdf pdf2image pytesseract pillow
#
# System deps:
#   - Poppler (pdftoppm.exe)  -> used by pdf2image
#   - Tesseract (tesseract.exe) -> used by pytesseract OCR
#
# Both must be installed on this machine.
# Update POPPLER_PATH below to point to the folder that actually contains pdftoppm.exe.

import csv, io, os, re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from pypdf import PdfReader
from PIL import Image, ImageOps
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

from pdf2image import convert_from_bytes

# ===== CONFIG YOU MUST SET =====
SERVICE_ACCOUNT_FILE = r"C:\secrets\cloud-451915-9a7a73426b73.json"
IMPERSONATE_USER     = "pcuenco@elhaynes.org"

POPPLER_PATH = r"C:\poppler\poppler-25.07.0\Library\bin"  # <-- make sure this is the *bin* with pdftoppm.exe

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

INCLUDE_SHARED_DRIVES = False
MAX_PDF_BYTES         = 25 * 1024 * 1024

REPORT_CSV = f"pdf-rule-findings-{IMPERSONATE_USER.replace('@','_')}-{datetime.now():%Y%m%d-%H%M%S}.csv"

PDF_MIME = "application/pdf"

# --- Address detection rule ---
# Only care about "#"
ADDRESS_FORBIDDEN_PATTERN = re.compile(r"#")

# --- Page render / ink detection tuning ---
OCR_DPI = 300
GRAY_THRESHOLD     = 245       # count faint ink as ink
MIN_INK_COVERAGE   = 0.0010    # 0.10% dark-ish pixels in region => "signed"
BAND_HEIGHT_PX     = 120       # height of the signature band above "Method B"
BAND_WIDTH_FRAC    = 0.60      # take 60% of page width, centered-ish to right side

# Debug output for troubleshooting crops/coverage
DEBUG_SIGNATURE = True
SCRIPT_DIR = Path(__file__).resolve().parent
DEBUG_DIR = SCRIPT_DIR / "signature_debug"


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
        "q": q,
        "spaces": "drive",
        "pageSize": 1000,
        "pageToken": page_token,
        "fields": fields,
        "includeItemsFromAllDrives": INCLUDE_SHARED_DRIVES,
        "supportsAllDrives": INCLUDE_SHARED_DRIVES,
        "corpora": "drive" if drive_id else "user",
    }
    if drive_id:
        args["driveId"] = drive_id
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
        if not token:
            break

def mydrive_root_id(svc) -> str:
    return svc.files().get(fileId="root", fields="id").execute()["id"]

def walk_mydrive_pdfs(svc, root_name: str, root_id: str) -> Iterable[Dict]:
    stack = [{"id": root_id, "path": f"/{root_name}"}]
    seen = set()
    while stack:
        node = stack.pop()
        for item in list_children(svc, node["id"]):
            iid = item["id"]
            if iid in seen:
                continue
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
    dl = MediaIoBaseDownload(buf, req, chunksize=1024 * 1024)
    done = False
    while not done:
        _, done = dl.next_chunk()
        if buf.tell() > MAX_PDF_BYTES:
            return None
    return buf.getvalue()


# ===== PDF TEXT & FORM HELPERS =====
def render_pages(pdf_bytes: bytes, dpi: int) -> List[Image.Image]:
    # Convert all pages to PIL Images using poppler
    return convert_from_bytes(
        pdf_bytes,
        dpi=dpi,
        fmt="png",
        poppler_path=POPPLER_PATH
    )

def ocr_page_data(img: Image.Image):
    """
    Run Tesseract to get bounding boxes for each word.
    Returns dict from pytesseract.image_to_data.
    """
    return pytesseract.image_to_data(img, output_type='dict')

def ocr_page_text(img: Image.Image) -> str:
    return pytesseract.image_to_string(img)

def pdf_text_all(reader: PdfReader) -> str:
    return "\n".join([(p.extract_text() or "") for p in reader.pages])

def _iter_acroform_fields(reader: PdfReader):
    try:
        root = reader.trailer["/Root"]
        if "/AcroForm" not in root:
            return
        form = root["/AcroForm"]
        for fref in form.get("/Fields", []):
            fobj = fref.get_object()
            name = fobj.get("/T")
            value = fobj.get("/V")
            if hasattr(name, "get_object"):
                name = name.get_object()
            if hasattr(value, "get_object"):
                value = value.get_object()
            yield (
                str(name) if name is not None else "",
                str(value) if value is not None else "",
                fobj,
            )
    except Exception:
        return


# ===== REQUIREMENT 1: Only scan "DC Residency Verification Form" =====
def is_dc_residency_form(pdf_bytes: bytes) -> bool:
    """
    Return True only if page 1 OCR (or extracted text) contains 'DC Residency Verification Form'.
    """
    # Strategy: try text extraction via pypdf first, then OCR image 1 as fallback.
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        first_page_text = (reader.pages[0].extract_text() or "")
    except Exception:
        first_page_text = ""

    header_hit = "dc residency verification form" in first_page_text.lower()

    if not header_hit:
        # OCR fallback
        try:
            imgs = render_pages(pdf_bytes, dpi=OCR_DPI)
            first_ocr = ocr_page_text(imgs[0]).lower()
            header_hit = "dc residency verification form" in first_ocr
        except Exception:
            header_hit = False

    return header_hit


# ===== REQUIREMENT 2: Address rule (now JUST looking for '#') =====
def extract_address_value(reader: PdfReader, full_text: str) -> str:
    # Prefer a form field that looks like the enrolling person's address
    for name, value, fobj in _iter_acroform_fields(reader):
        low = (name or "").lower()
        tu  = str(fobj.get("/TU", "")).lower()
        if (
            ("address" in low or "address" in tu)
            and ("enroll" in low or "enrolling" in low or "enroll" in tu or "enrolling" in tu)
        ):
            if value and value.strip():
                return value.strip()

    # Fallback to text scrape by label
    m = re.search(
        r"Address of enrolling person[:\s]*(.*)",
        full_text,
        flags=re.IGNORECASE,
    )
    if m:
        tail = m.group(1).strip()
        if len(tail) < 5:
            after = full_text[m.end():].splitlines()
            if after:
                tail += " " + after[0].strip()
        return tail.strip()

    return ""

def address_violations(pdf_bytes: bytes) -> List[str]:
    errs: List[str] = []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text_all = pdf_text_all(reader)
    except Exception:
        return errs

    addr = extract_address_value(reader, text_all)
    # ONLY care if "#" is present
    if addr and ADDRESS_FORBIDDEN_PATTERN.search(addr):
        errs.append(f"Address contains #: {addr!r}")

    return errs


# ===== SIGNATURE RULE =====
# "The signature field is in the SCHOOL OFFICIAL USE ONLY box,
#  and the signature line is above the text that reads:
#  'Method B: Select two documents'"

def find_method_b_band(img: Image.Image, page_index: int) -> Optional[Tuple[int,int,int,int]]:
    """
    OCR one page, try to locate the line that includes 'Method B' and 'Select' and 'documents'.
    Return (x1,y1,x2,y2) ABOVE that line.
    If not found on this page, return None.
    """
    data = pytesseract.image_to_data(img, output_type='dict')

    # bucket words by approximate line (10px vertical tolerance)
    lines_by_y = {}
    for i, word in enumerate(data["text"]):
        wtxt = word.strip()
        if not wtxt:
            continue
        y_top = data["top"][i]
        x_left = data["left"][i]
        w_w = data["width"][i]
        w_h = data["height"][i]

        line_key = y_top // 10
        lines_by_y.setdefault(line_key, []).append((x_left, y_top, w_w, w_h, wtxt))

    candidate_boxes = []
    for line_key, parts in lines_by_y.items():
        parts.sort(key=lambda z: z[0])
        line_text = " ".join(p[4] for p in parts).lower()

        # debug print so we can see what OCR thinks
        print(f"[DEBUG][p{page_index+1}] OCR line: {line_text}")

        # relaxed match: require these keywords to all appear somewhere in that line
        if ("method" in line_text and "b" in line_text and "select" in line_text and "document" in line_text):
            xs = [p[0] for p in parts]
            ys = [p[1] for p in parts]
            xe = [p[0] + p[2] for p in parts]
            ye = [p[1] + p[3] for p in parts]
            x1 = min(xs)
            y1 = min(ys)
            x2 = max(xe)
            y2 = max(ye)
            candidate_boxes.append((x1, y1, x2, y2))

    if not candidate_boxes:
        return None

    # use the topmost occurrence
    x1, y1, x2, y2 = sorted(candidate_boxes, key=lambda b: b[1])[0]

    # build band ABOVE that line
    page_w, page_h = img.size
    band_height = BAND_HEIGHT_PX  # how tall we scan for ink
    top_y = max(0, y1 - band_height)
    bot_y = max(0, y1 - 10)

    band_w = int(page_w * BAND_WIDTH_FRAC)      # horizontal width of band
    left_x = int(page_w * 0.30)                 # start ~30% across page
    right_x = min(page_w, left_x + band_w)

    band = (left_x, top_y, right_x, bot_y)
    print(f"[DEBUG][p{page_index+1}] Method B anchor at y≈{y1}, signature band={band}")
    return band


def _ink_coverage(img: Image.Image) -> float:
    gray = ImageOps.grayscale(img)
    hist = gray.histogram()
    dark = sum(hist[0:GRAY_THRESHOLD])
    total = sum(hist)
    return (dark / total) if total else 0.0

def signature_violations(pdf_bytes: bytes) -> List[str]:
    errs: List[str] = []

    # Render ALL pages at high DPI
    try:
        imgs = convert_from_bytes(
            pdf_bytes,
            dpi=OCR_DPI,
            fmt="png",
            poppler_path=POPPLER_PATH
        )
    except Exception:
        errs.append("Could not render PDF pages for signature check.")
        return errs

    found_band = False
    found_ink = False
    best_cov = 0.0
    best_debug_path = None

    for page_i, page_img in enumerate(imgs):
        # pass both the image and which page we're on
        band_box = find_method_b_band(page_img, page_i)
        if band_box is None:
            continue  # couldn't find "Method B" on this page; try next page

        found_band = True

        x1, y1, x2, y2 = band_box
        sig_crop = page_img.crop((x1, y1, x2, y2))

        cov = _ink_coverage(sig_crop)
        if cov > best_cov:
            best_cov = cov

        if DEBUG_SIGNATURE:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            debug_path = DEBUG_DIR / f"sigband_p{page_i+1}_{cov:.4f}_{x1}-{y1}-{x2}-{y2}.png"
            sig_crop.save(debug_path)
            best_debug_path = debug_path
            print(
                f"[DEBUG] sig coverage p{page_i+1}={cov:.4f} "
                f"(threshold {MIN_INK_COVERAGE}) → {debug_path}"
            )

        if cov >= MIN_INK_COVERAGE:
            found_ink = True
            break  # we consider the form signed if any page passes

    if not found_band:
        errs.append("Could not locate School Official signature area (no 'Method B' anchor).")
    elif not found_ink:
        errs.append("School official Signature line appears blank (no ink above 'Method B').")

    return errs



# ===== MAIN =====
def main():
    if DEBUG_SIGNATURE:
        print(f"Signature debug crops will be in: {DEBUG_DIR}")

    svc = get_drive_service()
    who = svc.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    print(f"Impersonating: {who}")

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

        # 1. Only continue if header says DC Residency Verification Form
        if not is_dc_residency_form(pdf_bytes):
            # skip this PDF completely; don't report anything
            continue

        # 2. Run checks
        issues: List[str] = []
        issues += address_violations(pdf_bytes)           # "#" check in address
        issues += signature_violations(pdf_bytes)         # ink check above "Method B"

        # 3. Record issues
        for issue in issues:
            findings.append({
                "fileId": fid,
                "fileName": fname,
                "filePath": fpath,
                "issue": issue
            })

    # 4. Write report
    os.makedirs(os.path.dirname(REPORT_CSV) or ".", exist_ok=True)
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["fileId","fileName","filePath","issue"])
        writer.writeheader()
        writer.writerows(findings)

    print(f"Scan complete. Issues found: {len(findings)}  →  {REPORT_CSV}")

if __name__ == "__main__":
    main()


