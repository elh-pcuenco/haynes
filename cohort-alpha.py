# --- Cohorting MVP (grade-locked KMeans) -------------------------------------
# pip install pandas scikit-learn numpy

import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

# === CONFIG ==================================================================
INPUT_CSV = r"C:\temp\student_performance_sample.csv"   # replace with your export path
OUTPUT_DIR = Path(r"C:\data")                 # where outputs will be written
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Choose what to run:
SUBJECTS_TO_RUN = ["Math", "ELA"]   # e.g., ["Math","ELA"] or ["Math"] or [None] for "All Subjects"

GRADE_COL = "grade"
ID_COL = "student_id"
NAME_COL = "student_name"

# Numeric features used for clustering (tune this list!)
FEATURES = [
    "benchmark_score",
    "growth_percentile",
    "current_grade_pct",
    "missing_work_pct",
    "attendance_30d"
]

# Try these values for k and pick the best by silhouette
K_CANDIDATES = [3, 4, 5, 6, 7]
RANDOM_STATE = 42

# === LOAD ONCE ===============================================================
df_all = pd.read_csv(INPUT_CSV)

def best_k_for_grade(gdf: pd.DataFrame) -> int:
    X = gdf[FEATURES].to_numpy()
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    best_k, best_score = None, -1
    max_k = min(max(K_CANDIDATES), len(gdf) - 1)
    candidates = [k for k in K_CANDIDATES if 2 <= k <= max_k]
    if not candidates:
        return 1  # fallback if too few students

    for k in candidates:
        km = KMeans(n_clusters=k, n_init="auto", random_state=RANDOM_STATE)
        labels = km.fit_predict(Xs)
        score = silhouette_score(Xs, labels) if len(set(labels)) > 1 else -1
        if score > best_score:
            best_k, best_score = k, score
    return best_k if best_k is not None else 1

def cluster_grade(gdf: pd.DataFrame, subject_tag: str):
    # Choose k
    k = best_k_for_grade(gdf)
    if k == 1:
        labels = np.zeros(len(gdf), dtype=int)
        centers = {0: gdf[FEATURES].mean().to_dict()}
    else:
        X = gdf[FEATURES].to_numpy()
        scaler = StandardScaler().fit(X)
        Xs = scaler.transform(X)
        km = KMeans(n_clusters=k, n_init="auto", random_state=RANDOM_STATE)
        labels = km.fit_predict(Xs)
        centers = {i: dict(zip(FEATURES, km.cluster_centers_[i])) for i in range(k)}

    out = gdf[[ID_COL, NAME_COL, GRADE_COL] + FEATURES].copy()
    out["cohort_label"] = labels
    prefix = subject_tag[:3].upper() if subject_tag != "All" else "GEN"
    out["cohort_name"] = out[GRADE_COL].astype(str) + f"-{prefix}-" + out["cohort_label"].astype(str)
    return out, centers

# ---------- Cohort categorizer (adds category + blurb) ----------
HI, LO, VHI, VLO = 0.50, -0.50, 1.00, -1.00  # z-score thresholds

def categorize_and_blurb(row):
    b   = row.get("center_benchmark_score", 0.0)
    g   = row.get("center_growth_percentile", 0.0)
    cg  = row.get("center_current_grade_pct", 0.0)
    mw  = row.get("center_missing_work_pct", 0.0)   # higher = worse
    att = row.get("center_attendance_30d", 0.0)

    # Category precedence
    if att <= -0.70:
        category = "Attendance risk"
    elif mw >= 0.70:
        category = "Work completion risk"
    elif (b >= HI and cg >= HI) or (b >= VHI) or (cg >= VHI):
        category = "Enrichment"
    elif (b <= LO or cg <= LO):
        category = "Growth" if g >= HI else "Support"
    elif g >= HI and (b <= 0 or cg <= 0):
        category = "Growth"
    else:
        category = "Core"

    # Build blurb from key signals
    notes = []
    if b >= HI:   notes.append("above-avg benchmark")
    if b <= LO:   notes.append("below-avg benchmark")
    if g >= HI:   notes.append("strong growth")
    if g <= LO:   notes.append("slower growth")
    if cg >= HI:  notes.append("strong course grades")
    if cg <= LO:  notes.append("lower course grades")
    if mw >= HI:  notes.append("high missing work")
    if mw <= LO:  notes.append("low missing work")
    if att >= HI: notes.append("high attendance")
    if att <= LO: notes.append("lower attendance")

    pos = [n for n in notes if n in ("above-avg benchmark","strong growth",
                                     "strong course grades","high attendance","low missing work")]
    neg = [n for n in notes if n not in pos]
    pieces = (pos[:2] + neg[:2]) or ["balanced profile"]
    blurb = f"{category}: " + ", ".join(pieces)

    return pd.Series({"category": category, "blurb": blurb})


def run_for_subject(SUBJECT):
    """
    SUBJECT may be "Math", "ELA", etc. or None / "" to disable filtering (run all subjects together).
    Produces:
      - student_cohorts_<subject_tag>.csv
      - student_cohorts_<subject_tag>_profiles.csv
    """
    subject_tag = SUBJECT if SUBJECT else "All"
    df = df_all.copy()

    # Filter if a subject column exists and SUBJECT is set
    if "subject" in df.columns and SUBJECT:
        df = df[df["subject"].str.casefold() == SUBJECT.casefold()].copy()

    # Keep only rows with complete numeric data
    df_feat = df.dropna(subset=FEATURES + [GRADE_COL, ID_COL])
    if df_feat.empty:
        print(f"[{subject_tag}] No rows to process (after filtering/NA drop). Skipping.")
        return

    results = []
    centroid_cards = []

    for grade, gdf in df_feat.groupby(GRADE_COL, sort=True):
        clustered_df, centers = cluster_grade(gdf, subject_tag)
        results.append(clustered_df)

        for label, center in centers.items():
            centroid_cards.append({
                "grade": grade,
                "subject": subject_tag,
                "cohort_label": label,
                **{f"center_{k}": v for k, v in center.items()}
            })

    # ---------- write outputs ----------
    cohorts = pd.concat(results, ignore_index=True)
    out_cohorts = OUTPUT_DIR / f"student_cohorts_{subject_tag}.csv"
    out_profiles = OUTPUT_DIR / f"student_cohorts_{subject_tag}_profiles.csv"

    # Build profiles from centroids and add labels
    profiles = pd.DataFrame(centroid_cards)
    profiles[["category", "blurb"]] = profiles.apply(categorize_and_blurb, axis=1)

    # Save files
    cohorts.to_csv(out_cohorts, index=False)
    profiles.to_csv(out_profiles, index=False)

    # Print a quick size table
    size_table = (
        cohorts.groupby(["grade", "cohort_name"])
               .size()
               .reset_index(name="students")
               .sort_values(["grade", "cohort_name"])
    )
    print(f"\n[{subject_tag}] Cohort sizes")
    print(size_table.to_string(index=False))
    print(f"\nSaved cohort assignments → {out_cohorts}")
    print(f"Saved cohort profiles     → {out_profiles}")

# === RUN =====================================================================
for SUBJECT in SUBJECTS_TO_RUN:
    run_for_subject(SUBJECT)

# Bonus: to also run “All Subjects together” in the same pass:
# run_for_subject(None)
