import fitz  # PyMuPDF
import cv2
import numpy as np
from PIL import Image
import io
import os
import csv
from datetime import datetime

# === Configuration ===
PDF_SCAN_DIR = r"C:\pdf_files"
OUTPUT_DIR = r"C:\pdf-output"
INK_PIXEL_MIN = 1000
DEBUG_OUTDIR = os.path.join(PDF_SCAN_DIR, "debug_bands")
os.makedirs(DEBUG_OUTDIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# === Output CSV path ===
timestamp = datetime.now().strftime("%y%m%d")
CSV_OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{timestamp}-results.csv")

# === Extract the signature band between "Signature:" and "Date:" ===
def extract_signature_band_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]

        sig_rects = page.search_for("Signature:")
        date_rects = page.search_for("Date:")

        if not sig_rects:
            print(f"⚠️ Could not find 'Signature:' in {pdf_path}")
            return None, None

        sig = sig_rects[0]
        sig_x0 = sig.x1
        sig_y0 = sig.y0 - 5
        sig_y1 = sig.y1 + 10

        if date_rects:
            date_x0 = date_rects[0].x0
        else:
            print(f"⚠️ 'Date:' not found in {pdf_path}, using fallback width")
            date_x0 = sig_x0 + 200

        x0 = min(sig_x0, date_x0)
        x1 = max(sig_x0, date_x0)

        band_rect = fitz.Rect(x0, sig_y0, x1, sig_y1)
        if band_rect.width <= 0 or band_rect.height <= 0:
            print(f"❌ Invalid crop rectangle in {pdf_path}")
            return None, None

        pix = page.get_pixmap(clip=band_rect, dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

        return np.array(img), band_rect

    except Exception as e:
        print(f"❌ Error processing {pdf_path}: {e}")
        return None, None

# === Analyze cropped band for ink ===
def analyze_signature_band(band_img, debug_img_path=None):
    gray = cv2.cvtColor(band_img, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)
    ink_pixels = cv2.countNonZero(binary)
    is_signed = ink_pixels >= INK_PIXEL_MIN

    if debug_img_path:
        debug_img = cv2.cvtColor(band_img, cv2.COLOR_RGB2BGR)
        debug_img[binary > 0] = [0, 0, 255]
        cv2.imwrite(debug_img_path, debug_img)

    return {"ink_pixels": ink_pixels, "is_signed": is_signed}

# === Check for '#' character in the Address line ===
def check_address_hash_in_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        label_rects = page.search_for("Address of Enrolling Person")

        if not label_rects:
            print(f"⚠️ Couldn't locate address label in {pdf_path}")
            return False

        label = label_rects[0]
        addr_rect = fitz.Rect(label.x1, label.y0 - 5, label.x1 + 400, label.y1 + 5)
        addr_text = page.get_textbox(addr_rect).strip()

        if not addr_text:
            print(f"⚠️ No address text found in {pdf_path}")
            return False

        return "#" in addr_text

    except Exception as e:
        print(f"❌ Error checking address in {pdf_path}: {e}")
        return False

# === Main logic to analyze all PDFs in a directory ===
def run_on_pdf_directory(directory):
    pdf_files = [os.path.join(directory, f) for f in os.listdir(directory) if f.lower().endswith(".pdf")]
    results = []

    if not pdf_files:
        print("❌ No PDF files found.")
        return

    for pdf_file in pdf_files:
        base_name = os.path.basename(pdf_file)
        print(f"\n--- Analyzing: {base_name}")
        band_img, _ = extract_signature_band_from_pdf(pdf_file)
        has_hash = check_address_hash_in_pdf(pdf_file)

        if band_img is None:
            print(f"❌ Could not extract band from {pdf_file}")
            continue

        debug_img_path = os.path.join(DEBUG_OUTDIR, base_name.replace(".pdf", "_sigdebug.png"))
        result = analyze_signature_band(band_img, debug_img_path)

        sig_status = "Signed" if result["is_signed"] else "Blank"
        hash_status = "⚠️ HASH FOUND" if has_hash else "✅ Clean"

        print(f"Signature check: {sig_status:7} (ink_pixels: {result['ink_pixels']})")
        print(f"Address line check: {hash_status}")

        results.append({
            "File_Name": base_name,
            "Hash_Found": "yes" if has_hash else "no",
            "Signature_Found": "yes" if result["is_signed"] else "no"
        })

    # Write to CSV
    with open(CSV_OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["File_Name", "Hash_Found", "Signature_Found"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✅ Results written to: {CSV_OUTPUT_FILE}")

# === Execute ===
run_on_pdf_directory(PDF_SCAN_DIR)
