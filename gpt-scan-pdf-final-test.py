import os
import io
import csv
import fitz  # PyMuPDF
import cv2
import numpy as np
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = r"C:\secrets\cloud-451915-9a7a73426b73.json"
IMPERSONATE_USER = "pcuenco@elhaynes.org"
CSV_OUTPUT_FILE = "c:\pdf-output\scan_results.csv"
INK_PIXEL_MIN = 1000

# === Google Drive Setup ===
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
creds = creds.with_subject(IMPERSONATE_USER)
drive_service = build('drive', 'v3', credentials=creds)

# === PDF Analysis Functions ===
def extract_signature_band_from_bytes(pdf_bytes):
    try:
        doc = fitz.open("pdf", pdf_bytes)
        page = doc[0]

        sig_rects = page.search_for("Signature:")
        date_rects = page.search_for("Date:")

        if not sig_rects:
            return None

        sig = sig_rects[0]
        sig_x0 = sig.x1
        sig_y0 = sig.y0 - 5
        sig_y1 = sig.y1 + 10

        if date_rects:
            date_x0 = date_rects[0].x0
        else:
            date_x0 = sig_x0 + 200

        x0 = min(sig_x0, date_x0)
        x1 = max(sig_x0, date_x0)
        band_rect = fitz.Rect(x0, sig_y0, x1, sig_y1)

        if band_rect.width <= 0 or band_rect.height <= 0:
            return None

        pix = page.get_pixmap(clip=band_rect, dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        return np.array(img)

    except Exception as e:
        print(f"❌ Signature band error: {e}")
        return None

def analyze_signature_band(band_img):
    gray = cv2.cvtColor(band_img, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)
    ink_pixels = cv2.countNonZero(binary)
    return {
        "ink_pixels": ink_pixels,
        "is_signed": ink_pixels >= INK_PIXEL_MIN
    }

def check_address_hash_in_bytes(pdf_bytes):
    try:
        doc = fitz.open("pdf", pdf_bytes)
        page = doc[0]

        label_rects = page.search_for("Address of Enrolling Person")
        if not label_rects:
            return False

        label = label_rects[0]
        addr_rect = fitz.Rect(label.x1, label.y0 - 5, label.x1 + 400, label.y1 + 5)
        addr_text = page.get_textbox(addr_rect).strip()
        return "#" in addr_text
    except Exception as e:
        print(f"❌ Address hash error: {e}")
        return False

def has_required_header(pdf_bytes):
    try:
        doc = fitz.open("pdf", pdf_bytes)
        return bool(doc[0].search_for("DC Residency Verification Form"))
    except Exception as e:
        print(f"❌ Header check error: {e}")
        return False

# === Scan Drive for Eligible PDFs ===
def scan_my_drive():
    page_token = None
    results = []
    query = "mimeType='application/pdf' and 'me' in owners"

    while True:
        response = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='nextPageToken, files(id, name)',
            pageToken=page_token
        ).execute()

        for file in response.get('files', []):
            file_id = file['id']
            file_name = file['name']
            print(f"📄 Checking: {file_name}")

            try:
                request = drive_service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)

                done = False
                while not done:
                    status, done = downloader.next_chunk()

                fh.seek(0)
                pdf_bytes = fh.read()

                if not has_required_header(pdf_bytes):
                    continue

                band_img = extract_signature_band_from_bytes(pdf_bytes)
                sig_result = analyze_signature_band(band_img) if band_img is not None else {"ink_pixels": 0, "is_signed": False}
                has_hash = check_address_hash_in_bytes(pdf_bytes)

                results.append({
                    "file_name": file_name,
                    "hash_found": "yes" if has_hash else "no",
                    "signature_found": "yes" if sig_result['is_signed'] else "no"
                })

            except Exception as e:
                print(f"⚠️ Error processing {file_name}: {e}")

        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break

    return results

# === Output to CSV ===
def write_results_to_csv(results):
    with open(CSV_OUTPUT_FILE, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["file_name", "hash_found", "signature_found"])
        writer.writeheader()
        for row in results:
            writer.writerow(row)

# === Main Execution ===
if __name__ == "__main__":
    scan_results = scan_my_drive()
    write_results_to_csv(scan_results)
    print(f"\n✅ Scan complete. Results saved to {CSV_OUTPUT_FILE}")

