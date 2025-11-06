### Sample script to scan Google My Drive for SSNs in Google Docs files only
# pip install google-api-python-client google-auth google-auth-httplib2 tenacity

import csv, io, os, re
from datetime import datetime
from typing import Dict, Iterable, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ====== CONFIG ======
SERVICE_ACCOUNT_FILE = r"C:\secrets\cloud-451915-9a7a73426b73.json"
IMPERSONATE_USER     = "pcuenco@elhaynes.org"
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]
INCLUDE_SHARED_DRIVES = False  # My Drive only
REPORT_CSV = f"pii-ssn-docs-sheets-{IMPERSONATE_USER.replace('@','_')}-{datetime.now():%Y%m%d-%H%M%S}.csv"

GOOGLE_DOC  = "application/vnd.google-apps.document"
GOOGLE_SHEET= "application/vnd.google-apps.spreadsheet"
ALLOWED_MIMES = {GOOGLE_DOC, GOOGLE_SHEET}

# Strict SSN pattern: excludes 000/666/9xx areas, 00 group, 0000 serial
SSN_RE = re.compile(r"""
\b
(?!000|666|9\d\d)(\d{3})
[-\s]?
(?!00)\d{2}
[-\s]?
(?!0000)\d{4}
\b
""", re.VERBOSE)

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
    fields = "nextPageToken, files(id,name,mimeType,modifiedTime,owners(emailAddress),driveId,size,parents)"
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

def walk_mydrive(svc, root_name: str, root_id: str) -> Iterable[Dict]:
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
            yield item
            if is_folder(mime):
                stack.append({"id": iid, "path": path})

def export_to_text(svc, file_id: str, mime: str) -> str:
    """Export Docs→text/plain, Sheets→text/csv, return as decoded string."""
    export_mime = "text/plain" if mime == GOOGLE_DOC else "text/csv"
    data = svc.files().export(fileId=file_id, mimeType=export_mime).execute()
    if isinstance(data, bytes):
        try: return data.decode("utf-8", errors="ignore")
        except Exception: return data.decode("latin1", errors="ignore")
    return str(data)

def find_ssns(text: str):
    hits = []
    for m in SSN_RE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) != 9: continue
        norm = f"{digits[0:3]}-{digits[3:5]}-{digits[5:9]}"
        s, e = m.span()
        ctx = text[max(0, s-30): min(len(text), e+30)].replace("\n"," ")
        hits.append((norm, ctx))
    return hits

def main():
    svc = get_drive_service()
    who = svc.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    print(f"Impersonating: {who}")

    root_id = mydrive_root_id(svc)
    findings: List[Dict] = []

    for fmeta in walk_mydrive(svc, f"My Drive ({IMPERSONATE_USER})", root_id):
        mime = fmeta.get("mimeType", "")
        if mime not in ALLOWED_MIMES:   # <-- Docs + Sheets only
            continue

        try:
            text = export_to_text(svc, fmeta["id"], mime)
        except HttpError:
            continue  # skip on export errors

        for ssn, ctx in find_ssns(text):
            findings.append({
                "fileId": fmeta["id"],
                "filePath": fmeta["path"],
                "mimeType": mime,
                "page": "",      # N/A for Docs/Sheets exports
                "ssn": ssn,
                "context": ctx
            })

    # write report
    os.makedirs(os.path.dirname(REPORT_CSV) or ".", exist_ok=True)
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["fileId","filePath","mimeType","page","ssn","context"])
        writer.writeheader()
        writer.writerows(findings)

    print(f"Docs+Sheets scan complete. Findings: {len(findings)} → {REPORT_CSV}")

if __name__ == "__main__":
    main()
