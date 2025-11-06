from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter
import re 

csv_path = Path(r"C:\temp\october2025.csv")

# Read the CSV. Keep ticket numbers as strings so you don't lose leading zeros.
df = pd.read_csv(
    csv_path,
    dtype={"Ticket Number": "string", "Ticket Owner": "string", "Site": "string", "Contact": "string"},
    encoding="cp1252",           # try 'cp1252' if you see encoding errors utf-8-sig
    na_filter=True,
    parse_dates=["Entered"]
)

## Print the first 7 rows
print("--- First 7 Rows (df.head(7)) ---")
print(df.head(7))

# Normalize column names: "Ticket Number" -> "ticket_number", etc.
df.columns = (
    df.columns
      .str.strip()
      .str.lower()
      .str.replace(r"[^\w]+", "_", regex=True)
)


# Drop rows with empty ticket_owner
if "ticket_owner" in df.columns:
    df["ticket_owner"] = df["ticket_owner"].astype("string")
    mask_empty_owner = df["ticket_owner"].isna() | (df["ticket_owner"].str.strip() == "")
    dropped = int(mask_empty_owner.sum())
    if dropped:
        df = df[~mask_empty_owner].copy()
        print(f"Dropped {dropped} row(s) with empty ticket_owner.")

# --- Normalize special chars in comments -> single spaces ---
# Choose which column(s) to clean. We'll prefer 'comments' if present,
# otherwise any column that contains 'comment' in its name.
comment_cols = []
if "summary" in df.columns:
    comment_cols = ["summary"]
else:
    comment_cols = [c for c in df.columns if "summary" in c]

for col in comment_cols:
    # Ensure string dtype
    df[col] = df[col].astype("string")

    # # Replace any non-alphanumeric character with a space,
    # # collapse multiple spaces, and trim.
    # df[col] = (
    #     df[col]
    #     .str.replace(r"[^A-Za-z0-9\s]", " ", regex=True)  # turn special chars into spaces (e.g., ">>" -> " ")
    #     .str.replace(r"\s+", " ", regex=True)             # collapse runs of spaces/tabs/newlines
    #     .str.strip()                                      # trim edges
    # )

    
    df[col] = df[col].str.replace(r"[^A-Za-z0-9\s]", " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
    df[col] = df[col].str.replace(r"_+", " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()

# --- Normalize specific site names ---
if "site" in df.columns:
    # Replace "Middle School" (and close variants like "Middle  School", "middle school")
    mask_ms = df["site"].astype("string").str.contains(r"\bmiddle\s*school\b", case=False, na=False)
    df.loc[mask_ms, "site"] = "Georgia Campus"

    # (Optional) also catch the short form "MS" when it's the whole value
    df["site"] = (
        df["site"].astype("string")
        .str.replace(r"^\s*ms\s*$", "Georgia Campus", flags=re.I, regex=True)
        .str.strip()
    )


# Parse the date column safely
if "entered" in df.columns:
    df["entered"] = pd.to_datetime(df["entered"], errors="coerce")

# Quick sanity checks
# print("First 5 rows:\n", df.head(), "\n")
print("Column dtypes:\n", df.dtypes, "\n")
print("Tickets per site:\n", df["site"].value_counts(dropna=False), "\n")
print("Tickets per owner:\n", df.groupby("ticket_owner", dropna=True)["ticket_number"].count().sort_values(ascending=False))

# Show totals

total_tickets = int(len(df))


fig, ax = plt.subplots(figsize=(6, 3.2))
ax.axis("off")
ax.text(0.02, 0.70, "Total Tickets", fontsize=16, fontweight="bold", va="center")
ax.text(0.02, 0.22, f"{total_tickets:,}", fontsize=42, fontweight="bold", va="center")
#if subtitle:
    #ax.text(0.98, 0.10, subtitle, fontsize=10, ha="right", va="center")

plt.tight_layout()
plt.show()


# --- Tickets submitted per day ---
date_col = next((c for c in ("entered", "date_submitted", "created", "opened") if c in df.columns), None)

if date_col:
    # Make sure it's datetime and drop NaT rows for counting
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    dfg = df.dropna(subset=[date_col]).copy()

    # Continuous daily counts (resample fills missing days with 0)
    daily_counts = (
        dfg.set_index(date_col)
           .resample("D")
           .size()
           .rename("tickets")
           .astype("Int64")
    )
    top_days = daily_counts.sort_values(ascending=False).head(10)
    print("Top 10 days by tickets submitted:\n", top_days.to_string())
    # # Simple line chart
    # plt.figure(figsize=(10, 4))
    # plt.plot(daily_counts.index, daily_counts.values, marker="o")
    # plt.title("Tickets Submitted Per Day")
    # plt.xlabel("Date")
    # plt.ylabel("Number of Tickets")
    # plt.grid(True)
    # plt.tight_layout()
    # plt.show()


    # print("Tickets submitted per day:\n", daily_counts.to_string())

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

###################################################################################################################    
    
#     # Optional: save to CSV
#     # daily_counts.to_csv(r"C:\temp\tickets_per_day.csv", index_label="date")
# else:
#     print("No recognized date column ('entered' or 'date_submitted') found.")

# --- Pie chart: Tickets per site ---

# if "site" in df.columns:
#     # Clean up site values a bit
#     site_series = (
#         df["site"]
#         .astype("string")
#         .fillna("Unknown")
#         .str.strip()
#         .replace("", "Unknown")
#     )

#     counts = site_series.value_counts().sort_values(ascending=False)

#     # (Optional) keep chart readable by grouping smaller slices into "Other"
#     max_slices = 10  # total wedges to show (including "Other")
#     if len(counts) > max_slices:
#         top = counts.head(max_slices - 1)
#         other = counts.iloc[max_slices - 1:].sum()
#         counts = pd.concat([top, pd.Series({"Other": other})])

#     plt.figure(figsize=(7, 7))
#     plt.pie(
#         counts.values,
#         labels=counts.index,
#         autopct="%1.1f%%",
#         startangle=90,
#         counterclock=False,
#     )
#     plt.title("Tickets per Site")
#     plt.tight_layout()
#     plt.show()

#     # Optional: save the figure
#     # plt.savefig(r"C:\temp\tickets_per_site_pie.png", dpi=150)
# else:
#     print("No 'site' column present after normalization.")

if "ticket_owner" in df.columns:
    # Clean up site values a bit
    site_series = (
        df["ticket_owner"]
        .astype("string")
        .fillna("Unknown")
        .str.strip()
        .replace("", "Unknown")
    )

    counts = site_series.value_counts().sort_values(ascending=False)

    # (Optional) keep chart readable by grouping smaller slices into "Other"
    max_slices = 5  # total wedges to show (including "Other")
    if len(counts) > max_slices:
        top = counts.head(max_slices - 1)
        other = counts.iloc[max_slices - 1:].sum()
        counts = pd.concat([top, pd.Series({"Other": other})])

    plt.figure(figsize=(7, 7))
    plt.pie(
        counts.values,
        labels=counts.index,
        autopct="%1.1f%%",
        startangle=90,
        counterclock=False,
    )
    plt.title("Tickets per Owner")
    plt.tight_layout()
    plt.show()

    # Optional: save the figure
    # plt.savefig(r"C:\temp\tickets_per_site_pie.png", dpi=150)
else:
    print("No 'site' column present after normalization.")

# --- New Code for Lost/Stolen/Vandalized Tickets ---

# Check if the 'summary_description' column exists before proceeding
if "summary_description" in df.columns:
    # Define keywords to search for
    include_keywords = ["lost", "stolen", "vandalized", "broken", "damage", "damaged"]
    exclude_keywords = "charger"
    # Create a regular expression pattern for case-insensitive search
    include_pattern = '|'.join(include_keywords)

    # Filter the DataFrame for rows where the summary_description contains any of the keywords
    # Use .str.contains() with the case=False parameter for a case-insensitive search
    # and na=False to handle any missing values in the column
    mask_include = df["summary_description"].str.contains(include_pattern, case=False, na=False)
    mask_exclude = df["summary_description"].str.contains(exclude_keywords, case=False, na=False)
    
    # Count the number of tickets that match the criteria
    final_mask = mask_include & ~mask_exclude
    total_lost_stolen = int(final_mask.sum())
    print(f"Total Lost Stolen is: {total_lost_stolen}")


    # Create a new visual for this total
    fig_lost_stolen, ax_lost_stolen = plt.subplots(figsize=(6, 3.2))
    ax_lost_stolen.axis("off")
    ax_lost_stolen.text(0.02, 0.70, "Lost/Stolen/Vandalized", fontsize=16, fontweight="bold", va="center")
    ax_lost_stolen.text(0.02, 0.22, f"{total_lost_stolen:,}", fontsize=42, fontweight="bold", va="center")
    plt.tight_layout()
    plt.show()
else:
    print("Warning: 'summary_description' column not found in the CSV file. Skipping 'Lost/Stolen/Vandalized' count.")
