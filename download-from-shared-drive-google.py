from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import fitz  # PyMuPDF
import os

# === CONFIGURATION ==========================================================
SERVICE_ACCOUNT_FILE = r"C:\secrets\cloud-451915-9a7a73426b73.json"
IMPERSONATE_USER = "pcuenco@elhaynes.org"
DOWNLOAD_DIR = r"C:\pdf_files"
REQUIRED_HEADER = "DC Residency Verification Form"
MIME_TYPE_PDF = "application/pdf"

# === AUTHENTICATE ===========================================================
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
delegated_creds = creds.with_subject(IMPERSONATE_USER)
drive_service = build('drive', 'v3', credentials=delegated_creds)

# === HELPER: Validate PDF content before download ===========================
def has_required_header(file_id):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        buffer.seek(0)
        doc = fitz.open(stream=buffer.read(), filetype="pdf")
        first_page_text = doc[0].get_text()
        doc.close()
        return REQUIRED_HEADER in first_page_text

    except Exception as e:
        print(f"❌ Failed header check for file {file_id}: {e}")
        return False

# === SEARCH + DOWNLOAD PDFs =================================================
def download_eligible_pdfs():
    page_token = None
    total_downloaded = 0
    folder_id = "1XzLTjo04NW1S6Nzftq5dGfyki78XQoDI"  # replace with your folder ID
    shared_drive_id = "1znmJCPGUBCX-_jmzjpj1rKzFYrnce6nR"  # replace with your shared drive ID
    while True:
        response = drive_service.files().list(
            q=f"mimeType='{MIME_TYPE_PDF}' and trashed=false and '{folder_id}' in parents",
            # FOLDER_ID = "your-folder-id-here"  # replace with your folder ID
            # q=f"mimeType='application/pdf' and trashed=false and '{folder_id}' in parents",
            spaces='drive',
            fields="nextPageToken, files(id, name)",
            pageToken=page_token
        ).execute()

        for file in response.get('files', []):
            file_id = file['id']
            file_name = file['name']

            print(f"🔍 Scanning: {file_name}")
            if has_required_header(file_id):
                print(f"✅ MATCHED HEADER — downloading {file_name}")
                request = drive_service.files().get_media(fileId=file_id)
                file_path = os.path.join(DOWNLOAD_DIR, file_name)

                with open(file_path, 'wb') as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                total_downloaded += 1
            else:
                print(f"⛔ Skipped: {file_name} — header not found.")

        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break

    print(f"\n🎯 Download complete: {total_downloaded} matching PDF(s) saved to {DOWNLOAD_DIR}")

# === RUN ====================================================================
if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    download_eligible_pdfs()
