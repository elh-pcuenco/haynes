import os
import sqlite3
import time
import logging
from datetime import datetime, timedelta, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ========== CONFIG ==========
# Updated directory for Ubuntu deployment
BASE_DIR = "/opt/elh/cal_sync"
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "secrets/cloud-auth.json")
IMPERSONATE_USER = "pcuenco@elhaynes.org"

SOURCE_CALENDAR_NAMES = [
    "pcuenco@elhaynes.org",
    "operations@elhaynes.org",
]

TARGET_CALENDAR_ID = "c_64cd250fe9a8f14af5fb176a328f653d0360ed3b96bba7a30614fb8a26fe9e55@group.calendar.google.com"

SCOPES = ["https://www.googleapis.com/auth/calendar"]
DB_FILE = os.path.join(BASE_DIR, "mirror_map.db")
LOG_FILE = os.path.join(BASE_DIR, "sync.log")

PAST_DAYS = 30
FUTURE_DAYS = 45

# Logging configuration for headless operation
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ========== AUTH ==========
def get_calendar_service():
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES,
        )
        delegated_creds = creds.with_subject(IMPERSONATE_USER)
        return build("calendar", "v3", credentials=delegated_creds)
    except Exception as e:
        logging.error(f"Authentication failed: {e}")
        raise

# ========== DB ==========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_map (
            source_calendar_id TEXT,
            source_event_id TEXT,
            target_event_id TEXT,
            PRIMARY KEY (source_calendar_id, source_event_id)
        )
    """)
    conn.commit()
    return conn

# ========== HELPERS ==========
def list_calendars(service):
    calendars = {}
    page_token = None
    while True:
        resp = service.calendarList().list(pageToken=page_token).execute()
        for item in resp.get("items", []):
            calendars[item["summary"].lower()] = item["id"]
        page_token = resp.get("nextPageToken")
        if not page_token: break
    return calendars

def find_calendar_id(calendars, identifier):
    if "@" in identifier: return identifier
    key = identifier.lower()
    if key not in calendars:
        raise Exception(f"Calendar not found: {identifier}")
    return calendars[key]

def get_events(service, calendar_id, time_min, time_max):
    events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token
        ).execute()
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token: break
    return events

# ========== MAIN MIRROR LOGIC ==========
def main():
    logging.info("--- Sync Cycle Started ---")
    try:
        service = get_calendar_service()
        conn = init_db()
        cur = conn.cursor()

        calendars = list_calendars(service)
        source_calendar_ids = [(n, find_calendar_id(calendars, n)) for n in SOURCE_CALENDAR_NAMES]
        
        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=PAST_DAYS)).isoformat()
        time_max = (now + timedelta(days=FUTURE_DAYS)).isoformat()

        seen_source_keys = set()

        for source_name, source_cid in source_calendar_ids:
            events = get_events(service, source_cid, time_min, time_max)
            logging.info(f"Retrieved {len(events)} events from {source_name}")

            for ev in events:
                if ev.get("status") == "cancelled": continue

                s_eid = ev["id"]
                seen_source_keys.add((source_cid, s_eid))

                mirrored_event = {
                    "summary": f"[{source_name}] {ev.get('summary', 'Busy')}",
                    "start": ev["start"],
                    "end": ev["end"],
                    "location": ev.get("location", ""),
                    "description": ev.get("description", ""),
                }

                cur.execute("SELECT target_event_id FROM event_map WHERE source_calendar_id=? AND source_event_id=?", (source_cid, s_eid))
                row = cur.fetchone()

                try:
                    if row:
                        service.events().update(calendarId=TARGET_CALENDAR_ID, eventId=row[0], body=mirrored_event).execute()
                    else:
                        created = service.events().insert(calendarId=TARGET_CALENDAR_ID, body=mirrored_event).execute()
                        cur.execute("INSERT OR REPLACE INTO event_map VALUES (?, ?, ?)", (source_cid, s_eid, created["id"]))
                        conn.commit()
                    time.sleep(0.1)  # Throttle to avoid API rate limits
                except HttpError as e:
                    logging.warning(f"Event Sync Failed ({ev.get('summary')}): {e}")

        # Handle Source Deletions
        cur.execute("SELECT source_calendar_id, source_event_id, target_event_id FROM event_map")
        for s_cid, s_eid, t_eid in cur.fetchall():
            if (s_cid, s_eid) not in seen_source_keys:
                try:
                    service.events().delete(calendarId=TARGET_CALENDAR_ID, eventId=t_eid).execute()
                    logging.info(f"Removed deleted source event: {t_eid}")
                except Exception: pass
                cur.execute("DELETE FROM event_map WHERE source_calendar_id=? AND source_event_id=?", (s_cid, s_eid))
                conn.commit()

        logging.info("--- Sync Cycle Complete ---")
    except Exception as e:
        logging.error(f"Fatal error during sync: {e}")

if __name__ == "__main__":
    main()