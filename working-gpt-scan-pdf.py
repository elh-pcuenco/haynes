import fitz  # PyMuPDF
import cv2
import numpy as np
from PIL import Image
import io
import os

# Constants
THRESHOLD = 50        # How dark a pixel must be to count as "ink"
INK_PIXEL_MIN = 200   # Minimum ink pixel count to consider as a signature
DEBUG_OUTDIR = "debug_bands"
os.makedirs(DEBUG_OUTDIR, exist_ok=True)

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
            date = date_rects[0]
            date_x0 = date.x0
        else:
            print(f"⚠️ 'Date:' not found in {pdf_path}, using fallback width of 200px")
            date_x0 = sig_x0 + 200  # fallback width

        # Ensure width is positive
        x0 = min(sig_x0, date_x0)
        x1 = max(sig_x0, date_x0)

        band_rect = fitz.Rect(x0, sig_y0, x1, sig_y1)

        # ✅ Check for valid dimensions
        if (band_rect.width <= 0) or (band_rect.height <= 0):
            print(f"❌ Invalid crop rectangle in {pdf_path}, skipping.")
            return None, None

        pix = page.get_pixmap(clip=band_rect, dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

        return np.array(img), band_rect

    except Exception as e:
        print(f"❌ Error processing {pdf_path}: {e}")
        return None, None




def analyze_signature_band(band_img, debug_img_path=None, show_debug=False):
    gray = cv2.cvtColor(band_img, cv2.COLOR_RGB2GRAY)

    # Threshold for dark ink (black or dark blue)
    _, binary = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)

    # Count "ink" pixels
    ink_pixels = cv2.countNonZero(binary)

    # New threshold: tune based on observed data
    threshold = 1000
    is_signed = ink_pixels >= threshold

    if debug_img_path:
        debug_img = cv2.cvtColor(band_img, cv2.COLOR_RGB2BGR)
        debug_img[binary > 0] = [0, 0, 255]  # Mark ink in red
        cv2.imwrite(debug_img_path, debug_img)

    return {
        "ink_pixels": ink_pixels,
        "is_signed": is_signed
    }


def run_on_pdfs(pdf_list):
    for pdf_file in pdf_list:
        print(f"\n--- Analyzing: {pdf_file}")
        band_img, band_rect = extract_signature_band_from_pdf(pdf_file)

        if band_img is None:
            print(f"❌ Could not extract band from {pdf_file}")
            continue

        debug_img_path = os.path.join(DEBUG_OUTDIR, os.path.basename(pdf_file).replace(".pdf", "_sigdebug.png"))
        result = analyze_signature_band(band_img, debug_img_path)

        status_str = "Signed" if result["is_signed"] else "Blank"
        print(f"{os.path.basename(pdf_file):25} → {status_str:7}   {{'ink_pixels': {result['ink_pixels']}}}   debug={os.path.basename(debug_img_path)}")


# === PDF List to Check ===
run_on_pdfs([
    "signed-with-hash.pdf",
    "unsigned-with-hash.pdf",
    "unsigned-no-hash.pdf"
])
