# requirements:
#   pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib tenacity

import csv
import os
from typing import Dict, Iterable, List, Optional
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SERVICE_ACCOUNT_FILE = r"C:\secrets\cloud-451915-9a7a73426b73.json"
IMPERSONATE_USER = "pcuenco@elhaynes.org"   # user to act as
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

# Toggle to include Shared drives
INCLUDE_SHARED_DRIVES = False

# Optional: map Google-native docs to export MIME types if you plan to export later
EXPORT_MAP = {
    "application/vnd.google-apps.document": "application/pdf",      # Docs -> PDF
    "application/vnd.google-apps.spreadsheet": "text/csv",          # Sheets -> CSV
    "application/vnd.google-apps.presentation": "application/pdf",  # Slides -> PDF
}

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    delegated = creds.with_subject(IMPERSONATE_USER)
    return build("drive", "v3", credentials=delegated, cache_discovery=False)

def is_folder(mime_type: str) -> bool:
    return mime_type == "application/vnd.google-apps.folder"

@retry(
    retry=retry_if_exception_type(HttpError),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(6),
)
def _list_files_page(
    svc,
    q: str,
    page_token: Optional[str],
    fields: str,
    drive_id: Optional[str] = None,
):
    kwargs = {
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
        kwargs["driveId"] = drive_id

    return svc.files().list(**kwargs).execute()

def list_children(
    svc,
    parent_id: str,
    drive_id: Optional[str] = None,
) -> Iterable[Dict]:
    """Yield all immediate children (files/folders) under a parent."""
    fields = "nextPageToken, files(id,name,mimeType,modifiedTime,owners(emailAddress),driveId,size,parents)"
    q = f"'{parent_id}' in parents and trashed=false"
    token = None
    while True:
        resp = _list_files_page(svc, q, token, fields, drive_id)
        for f in resp.get("files", []):
            yield f
        token = resp.get("nextPageToken")
        if not token:
            break

def get_root_ids(svc) -> dict:
    """Return root IDs for My Drive (and, optionally, Shared drives)."""

    # My Drive root (use the 'root' alias, not about().rootFolderId)
    me = svc.about().get(fields="user(emailAddress),storageQuota").execute()
    my_drive_root = svc.files().get(fileId="root", fields="id").execute()["id"]

    roots = {"My Drive": my_drive_root}

    # Only enumerate Shared drives if enabled
    if INCLUDE_SHARED_DRIVES:
        token = None
        while True:
            resp = svc.drives().list(pageSize=100, pageToken=token).execute()
            for d in resp.get("drives", []):
                roots[d["name"]] = d["id"]
            token = resp.get("nextPageToken")
            if not token:
                break

    return roots



def walk_drive(
    svc,
    root_name: str,
    root_id: str,
    drive_id: Optional[str] = None,
) -> Iterable[Dict]:
    """
    Depth-first walk starting from root_id.
    Yields dicts with a materialized path and metadata.
    """
    stack: List[Dict] = [{"id": root_id, "name": root_name, "path": f"/{root_name}", "drive_id": drive_id}]
    seen = set()

    while stack:
        node = stack.pop()
        parent_path = node["path"]
        for item in list_children(svc, node["id"], node["drive_id"]):
            item_id = item["id"]
            if item_id in seen:
                continue
            seen.add(item_id)

            item_name = item.get("name", "")
            mime_type = item.get("mimeType", "")
            path = f"{parent_path}/{item_name}"
            yield {
                "id": item_id,
                "name": item_name,
                "path": path,
                "mimeType": mime_type,
                "modifiedTime": item.get("modifiedTime"),
                "owner": (item.get("owners") or [{}])[0].get("emailAddress", ""),
                "size": item.get("size", ""),  # empty for Google-native files
                "driveId": item.get("driveId", node["drive_id"]),
                "parents": ",".join(item.get("parents", [])),
            }

            if is_folder(mime_type):
                stack.append({"id": item_id, "name": item_name, "path": path, "drive_id": item.get("driveId")})

def write_csv(rows: Iterable[Dict], out_path: str):
    fields = [
        "id",
        "name",
        "path",
        "mimeType",
        "modifiedTime",
        "owner",
        "size",
        "driveId",
        "parents",
    ]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def main():
    svc = get_drive_service()
    who = svc.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    print(f"Impersonating: {who}")

    # Enumerate My Drive and (optionally) all Shared drives
    roots = get_root_ids(svc)

    all_rows: List[Dict] = []
    for root_name, root_id in roots.items():
        drive_id = None
        # If it's a Shared drive, root_id is the driveId (not the folder). To list top-level,
        # query parent is the actual root folder of that drive. A simple trick is to list with corpora="drive"
        # using driveId and start at that drive's root by asking for parents-less items, but we’ll
        # just walk from root_id’s children when root is a folder.
        #
        # To keep it simple, we add a synthetic 'root' row then walk its children:
        root_row = {
            "id": root_id,
            "name": root_name,
            "path": f"/{root_name}",
            "mimeType": "application/vnd.google-apps.folder",
            "modifiedTime": "",
            "owner": "",
            "size": "",
            "driveId": root_id if root_name != "My Drive" else "",
            "parents": "",
        }
        all_rows.append(root_row)

        # For My Drive, drive_id must be None; for Shared drives, use the drive’s ID
        drive_id = None if root_name == "My Drive" else root_id

        for r in walk_drive(svc, root_name, root_id, drive_id):
            all_rows.append(r)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_csv = f"drive-inventory-{timestamp}.csv"
    write_csv(all_rows, out_csv)
    print(f"Wrote: {out_csv}  (rows: {len(all_rows)})")

if __name__ == "__main__":
    main()
