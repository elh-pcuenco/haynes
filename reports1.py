# ==============================
# PERSIST & MONTH-OVER-MONTH COMPARISON (SQLite)
# ==============================
import sqlite3
from datetime import datetime

# --- 1) Identify the period (YYYY-MM) for this run ---
if "entered" in df.columns and df["entered"].notna().any():
    period = str(df.loc[df["entered"].notna(), "entered"].dt.to_period("M").mode().iloc[0])  # e.g., '2025-09'
else:
    # Fallback: infer from filename like 'september2025.csv'
    # You can hardcode if you prefer: period = "2025-09"
    period = datetime.now().strftime("%Y-%m")

run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# --- 2) Reuse aggregates you already built ---
# total_tickets: already computed above
# daily_counts: already built above (may not exist if no date_col)
# Owner counts: you named the cleaned owner series variable `site_series` (ticket_owner); rebuild safely:
owner_counts_ser = None
if "ticket_owner" in df.columns:
    owner_counts_ser = (
        df["ticket_owner"].astype("string")
        .fillna("Unknown").str.strip().replace("", "Unknown")
        .value_counts().sort_values(ascending=False)
    )

# Site counts (if you want to track)
site_counts_ser = None
if "site" in df.columns:
    site_counts_ser = (
        df["site"].astype("string")
        .fillna("Unknown").str.strip().replace("", "Unknown")
        .value_counts().sort_values(ascending=False)
    )

# LSV total — use the value you computed earlier if available; otherwise 0
try:
    lsv_total = int(total_lost_stolen)  # from your LSV section
except Exception:
    lsv_total = 0

# Top-5 days (only if daily_counts exists)
try:
    top_days = daily_counts.sort_values(ascending=False).head(5)
except Exception:
    top_days = None

# Optional: Student tallies (if you have a DataFrame of student tickets w/ 'student_name')
try:
    student_tally = (
        student_df["student_name"]
        .value_counts()
        .head(20)  # keep it manageable
        if "student_df" in locals() and not student_df.empty and "student_name" in student_df
        else None
    )
except Exception:
    student_tally = None

# --- 3) Save to SQLite ---
db_path = Path("metrics.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Create tables if they don't exist
cur.executescript("""
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  period TEXT NOT NULL,          -- 'YYYY-MM'
  run_ts TEXT NOT NULL,          -- timestamp of this run
  total_tickets INTEGER NOT NULL,
  lsv_total INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_period ON runs(period);

CREATE TABLE IF NOT EXISTS owner_counts (
  run_id INTEGER NOT NULL,
  owner TEXT NOT NULL,
  count INTEGER NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS site_counts (
  run_id INTEGER NOT NULL,
  site TEXT NOT NULL,
  count INTEGER NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS top_days (
  run_id INTEGER NOT NULL,
  day TEXT NOT NULL,             -- 'YYYY-MM-DD'
  count INTEGER NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS student_name_counts (
  run_id INTEGER NOT NULL,
  student_name TEXT NOT NULL,
  count INTEGER NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id)
);
""")

# Upsert run row
# If a row for this period exists, replace it (so re-runs update metrics for the month)
cur.execute("""
INSERT INTO runs (period, run_ts, total_tickets, lsv_total)
VALUES (?, ?, ?, ?)
ON CONFLICT(period) DO UPDATE SET
  run_ts=excluded.run_ts,
  total_tickets=excluded.total_tickets,
  lsv_total=excluded.lsv_total
""", (period, run_ts, int(total_tickets), int(lsv_total)))

# Get run_id
cur.execute("SELECT id FROM runs WHERE period = ?", (period,))
run_id = cur.fetchone()[0]

# Wipe and re-insert detail rows for this run
cur.execute("DELETE FROM owner_counts WHERE run_id = ?", (run_id,))
if owner_counts_ser is not None:
    cur.executemany(
        "INSERT INTO owner_counts (run_id, owner, count) VALUES (?, ?, ?)",
        [(run_id, k if k is not None else "Unknown", int(v)) for k, v in owner_counts_ser.items()]
    )

cur.execute("DELETE FROM site_counts WHERE run_id = ?", (run_id,))
if site_counts_ser is not None:
    cur.executemany(
        "INSERT INTO site_counts (run_id, site, count) VALUES (?, ?, ?)",
        [(run_id, k if k is not None else "Unknown", int(v)) for k, v in site_counts_ser.items()]
    )

cur.execute("DELETE FROM top_days WHERE run_id = ?", (run_id,))
if top_days is not None:
    cur.executemany(
        "INSERT INTO top_days (run_id, day, count) VALUES (?, ?, ?)",
        [(run_id, d.strftime("%Y-%m-%d"), int(c)) for d, c in top_days.items()]
    )

cur.execute("DELETE FROM student_name_counts WHERE run_id = ?", (run_id,))
if student_tally is not None:
    cur.executemany(
        "INSERT INTO student_name_counts (run_id, student_name, count) VALUES (?, ?, ?)",
        [(run_id, name, int(cnt)) for name, cnt in student_tally.items()]
    )

conn.commit()

# --- 4) Compare to previous month (if present) ---
# Find previous period in DB (the max period < current)
cur.execute("SELECT period, id, total_tickets, lsv_total FROM runs WHERE period < ? ORDER BY period DESC LIMIT 1", (period,))
prev = cur.fetchone()

def pp_delta(label, now_val, prev_val):
    delta = now_val - prev_val
    sign = "+" if delta >= 0 else "-"
    print(f"{label}: {now_val} (prev {prev_val}, {sign}{abs(delta)})")

print("\n=== Month-over-Month Comparison ===")
print(f"Current period: {period}")
if prev:
    prev_period, prev_id, prev_total, prev_lsv = prev
    print(f"Previous period: {prev_period}")

    # Totals
    pp_delta("Total tickets", int(total_tickets), int(prev_total))
    pp_delta("LSV tickets", int(lsv_total), int(prev_lsv))

    # Owner deltas
    print("\nBy owner (delta vs previous):")
    # Load previous owner counts
    cur.execute("SELECT owner, count FROM owner_counts WHERE run_id = ?", (prev_id,))
    prev_owner = dict(cur.fetchall())
    cur.execute("SELECT owner, count FROM owner_counts WHERE run_id = ?", (run_id,))
    now_owner = dict(cur.fetchall())

    all_owners = sorted(set(prev_owner) | set(now_owner))
    for o in all_owners:
        now_c = now_owner.get(o, 0)
        prev_c = prev_owner.get(o, 0)
        delta = now_c - prev_c
        sign = "+" if delta >= 0 else "-"
        print(f"  {o}: {now_c} (prev {prev_c}, {sign}{abs(delta)})")

    # Site deltas (optional)
    cur.execute("SELECT site, count FROM site_counts WHERE run_id = ?", (prev_id,))
    prev_site = dict(cur.fetchall())
    cur.execute("SELECT site, count FROM site_counts WHERE run_id = ?", (run_id,))
    now_site = dict(cur.fetchall())

    if now_site or prev_site:
        print("\nBy site (delta vs previous):")
        all_sites = sorted(set(prev_site) | set(now_site))
        for s in all_sites:
            now_c = now_site.get(s, 0)
            prev_c = prev_site.get(s, 0)
            delta = now_c - prev_c
            sign = "+" if delta >= 0 else "-"
            print(f"  {s}: {now_c} (prev {prev_c}, {sign}{abs(delta)})")

else:
    print("No previous month found—saved current metrics; comparisons will appear next month.")

cur.close()
conn.close()
print(f"\nSaved metrics to {db_path.resolve()}")

