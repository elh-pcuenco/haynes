import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ========== CONFIG ==========
SERVICE_ACCOUNT_FILE = r"C:\secrets\cloud-451915-444ee0af56ce.json"
IMPERSONATE_USER = "pcuenco@elhaynes.org"

SOURCE_CALENDAR_NAMES = [
    "pcuenco@elhaynes.org",  
    "operations@elhaynes.org",
    "prayamajhi@elhaynes.org",   
]

# This is an ID, not a name, so we use it directly below
TARGET_CALENDAR_ID = "c_64cd250fe9a8f14af5fb176a328f653d0360ed3b96bba7a30614fb8a26fe9e55@group.calendar.google.com"

SCOPES = ["https://www.googleapis.com/auth/calendar"]
DB_FILE = "mirror_map2.db"
PAST_DAYS = 30
FUTURE_DAYS = 45

# ========== AUTH ==========
def get_calendar_service():
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES,
        )
        delegated_creds = creds.with_subject(IMPERSONATE_USER)
        service = build("calendar", "v3", credentials=delegated_creds)
        return service
    except Exception as e:
        print(f"CRITICAL: Auth failed. Check Service Account / Delegation. Error: {e}")
        exit(1)

# ========== VERIFICATION BLOCK ==========
def verify_connection(service, source_ids):
    """Checks if auth works by grabbing first 2 events from each source."""
    print("--- Running Authorization Check ---")
    now = datetime.now(timezone.utc).isoformat()
    
    for name, cid in source_ids:
        try:
            print(f"Checking access to: {name} ({cid})...")
            events_result = service.events().list(
                calendarId=cid, 
                timeMin=now, 
                maxResults=2, 
                singleEvents=True
            ).execute()
            
            events = events_result.get('items', [])
            print(f"  SUCCESS: Found {len(events)} upcoming events.")
            for event in events:
                print(f"    - Found: {event.get('summary', '(No Title)')}")
        except HttpError as e:
            print(f"  FAILED: Could not access {name}. Error: {e}")
    print("--- End of Authorization Check ---\n")

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
        if not page_token:
            break
    return calendars

def find_calendar_id(calendars, identifier):
    # Check if it's already an ID (contains @ and group.calendar)
    if "@group.calendar.google.com" in identifier or "@" in identifier:
        return identifier
    
    key = identifier.lower()
    if key not in calendars:
        # Fallback: list all for debugging if not found
        print(f"Available calendars: {list(calendars.keys())}")
        raise Exception(f"Calendar not found by name: {identifier}")
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
        if not page_token:
            break
    return events

# ========== MAIN MIRROR LOGIC ==========
def main():
    service = get_calendar_service()
    conn = init_db()
    cur = conn.cursor()

    # Resolve IDs
    calendars = list_calendars(service)
    source_calendar_ids = []
    for name in SOURCE_CALENDAR_NAMES:
        cid = find_calendar_id(calendars, name)
        source_calendar_ids.append((name, cid))

    # RUN THE VERIFICATION
    verify_connection(service, source_calendar_ids)

    # Use constant ID for target
    target_calendar_id = TARGET_CALENDAR_ID

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=PAST_DAYS)).isoformat()
    time_max = (now + timedelta(days=FUTURE_DAYS)).isoformat()

    seen_source_keys = set()

    for source_name, source_cid in source_calendar_ids:
        print(f"Syncing from: {source_name}")
        events = get_events(service, source_cid, time_min, time_max)

        for ev in events:
            if ev.get("status") == "cancelled":
                continue

            source_event_id = ev["id"]
            seen_source_keys.add((source_cid, source_event_id))

            mirrored_event = {
                "summary": f"[{source_name}] {ev.get('summary', 'Busy')}",
                "start": ev["start"],
                "end": ev["end"],
                "location": ev.get("location", ""),
                "description": ev.get("description", ""),
            }

            cur.execute(
                "SELECT target_event_id FROM event_map WHERE source_calendar_id=? AND source_event_id=?",
                (source_cid, source_event_id)
            )
            row = cur.fetchone()

            try:
                if row:
                    target_event_id = row[0]
                    service.events().update(
                        calendarId=target_calendar_id,
                        eventId=target_event_id,
                        body=mirrored_event
                    ).execute()
                else:
                    created = service.events().insert(
                        calendarId=target_calendar_id,
                        body=mirrored_event
                    ).execute()
                    target_event_id = created["id"]
                    cur.execute(
                        "INSERT OR REPLACE INTO event_map VALUES (?, ?, ?)",
                        (source_cid, source_event_id, target_event_id)
                    )
                    conn.commit()
                # Optional small sleep to prevent rate limiting
                time.sleep(0.1)
            except HttpError as e:
                print(f"Error processing event {ev.get('summary')}: {e}")

    # Handle deletions
    cur.execute("SELECT source_calendar_id, source_event_id, target_event_id FROM event_map")
    rows = cur.fetchall()

    for s_cid, s_eid, t_eid in rows:
        if (s_cid, s_eid) not in seen_source_keys:
            print(f"Removing deleted event: {t_eid}")
            try:
                service.events().delete(calendarId=target_calendar_id, eventId=t_eid).execute()
            except Exception:
                pass
            cur.execute("DELETE FROM event_map WHERE source_calendar_id=? AND source_event_id=?", (s_cid, s_eid))
            conn.commit()

    print("Sync complete.")

if __name__ == "__main__":
    main()
