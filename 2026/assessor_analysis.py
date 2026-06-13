"""
boh1_assessor_analysis.py
─────────────────────────
Loads BOH1 form data, scores checklists via scoreMap, then analyses
assessor-level harshness and consistency across checklist scores,
global rating, and practice readiness.

Usage (from PostGresProcess.ipynb or standalone):
    from boh1_assessor_analysis import run_assessor_analysis
    run_assessor_analysis(engine)
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import scipy.stats as stats
from sqlalchemy import create_engine   # only needed if running standalone
from Utils import readDf               # existing helper

# ─── Config ──────────────────────────────────────────────────────────────────

SCORE_MAP = {
    "O1": 1.00,
    "O2": 0.80,
    "O3": 0.60,
    "O4": 0.40,
    "O5": 0.00,
    "Yes": 1.00,
    "No":  0.00,
}

# Minimum number of assessments an assessor must have to appear in analysis
MIN_ASSESSMENTS = 2

UNI_COLOR = "#010d44"

# ─── Data loading ─────────────────────────────────────────────────────────────

FETCH_SQL = """
SELECT
    assessmentid,
    form_code,
    assessor_name,
    student_number,
    student_name,
    datetimeutc::date                                               AS date,
    type,
    clinic,
    NULLIF(assessor_data->'scale-global-rating'->>'scale',  '')::int AS global_rating,
    NULLIF(assessor_data->'scale-practice-readiness'->>'scale', '')::int AS practice_readiness,
    assessor_data
FROM public.rawform_forms
WHERE cohort = 'BOH1'
  AND submitted_by_assessor
  AND datetimeutc >= '2026-01-01'
ORDER BY assessmentid ASC, form_code ASC
"""
 

def load_data(engine) -> pd.DataFrame:
    df = readDf(engine, FETCH_SQL)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ─── Scoring ──────────────────────────────────────────────────────────────────

def calc_score(assessor_data: dict, score_map: dict = SCORE_MAP) -> dict:
    """
    Score all checklist items in assessor_data.

    Returns
    -------
    dict  keyed by item-code (e.g. "221", "BOH-DD"), each value:
        {
            "score":   float,          # mean across all MC items (0-1)
            "n_items": int,            # number of scoreable MC items
            "items":   {               # per-MC-item score
                "MC1": float, ...
            }
        }
    Returns {} if assessor_data is None or not a dict.
    """
    if not isinstance(assessor_data, dict):
        return {}

    result = {}
    for item_code, item_data in assessor_data.items():
        if "scale" in item_code:
            continue
        if not isinstance(item_data, dict):
            continue

        per_item = {}
        for mc_key, mc_val in item_data.items():
            if mc_val in score_map:
                per_item[mc_key] = score_map[mc_val]

        if not per_item:
            continue

        mean_score = round(np.mean(list(per_item.values())), 4)
        # Strip compound codes (e.g. "022/024" → "022")
        clean_code = item_code.split("/")[0]
        result[clean_code] = {
            "score":   mean_score,
            "n_items": len(per_item),
            "items":   per_item,
        }

    return result


def add_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Add a 'scores' column (dict) and a flat 'checklist_mean' column."""
    df = df.copy()
    df["scores"] = df["assessor_data"].apply(calc_score)
    # Flat mean across all item codes in a form
    df["checklist_mean"] = df["scores"].apply(
        lambda s: round(np.mean([v["score"] for v in s.values()]), 4) if s else np.nan
    )
    return df


# ─── Assessor-level aggregation ───────────────────────────────────────────────

def build_assessor_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate per assessor:
      - n_assessments
      - checklist_mean / std
      - global_rating mean / std
      - practice_readiness mean / std
      - composite_harshness  (inverted, so higher = harsher)
    """
    grp = df.groupby("assessor_name")

    agg = pd.DataFrame({
        "n_assessments":      grp["assessmentid"].count(),
        "checklist_mean":     grp["checklist_mean"].mean().round(4),
        "checklist_std":      grp["checklist_mean"].std().round(4),
        "global_rating_mean": grp["global_rating"].mean().round(4),
        "global_rating_std":  grp["global_rating"].std().round(4),
        "pr_mean":            grp["practice_readiness"].mean().round(4),
        "pr_std":             grp["practice_readiness"].std().round(4),
    })

    agg = agg[agg["n_assessments"] >= MIN_ASSESSMENTS].copy()

    # Z-score normalise each metric then invert (low score = harsher)
    for col in ["checklist_mean", "global_rating_mean", "pr_mean"]:
        z = (agg[col] - agg[col].mean()) / agg[col].std(ddof=0)
        agg[f"{col}_z"] = z.round(3)

    # Composite harshness = average of the three inverted z-scores
    # (more negative → harsher assessor)
    agg["harshness_z"] = (
        agg[["checklist_mean_z", "global_rating_mean_z", "pr_mean_z"]].mean(axis=1).round(3)
    )

    return agg.sort_values("harshness_z")


# ─── Inter-rater statistics ───────────────────────────────────────────────────

def anova_test(df: pd.DataFrame, metric: str) -> dict:
    """One-way ANOVA: does metric differ significantly across assessors?"""
    groups = [g[metric].dropna().values for _, g in df.groupby("assessor_name") if g[metric].count() >= MIN_ASSESSMENTS]
    if len(groups) < 2:
        return {"F": np.nan, "p": np.nan}
    F, p = stats.f_oneway(*groups)
    return {"F": round(F, 3), "p": round(p, 4)}


def icc_oneway(df: pd.DataFrame, metric: str) -> float:
    """
    ICC(1,1) — one-way random effects.
    Treats each (student, date) case as the unit and assessor as rater.
    Only meaningful when multiple assessors rate the same student.
    Returns NaN if insufficient variance.
    """
    sub = df[["assessor_name", "student_number", metric]].dropna()
    if sub.empty:
        return np.nan
    # Build ratings matrix: rows = students, cols = assessors
    pivot = sub.pivot_table(index="student_number", columns="assessor_name", values=metric, aggfunc="mean")
    pivot = pivot.dropna(how="all")
    n, k = pivot.shape
    if n < 2 or k < 2:
        return np.nan

    grand_mean = pivot.stack().mean()
    SS_between = k * ((pivot.mean(axis=1) - grand_mean) ** 2).sum()
    SS_within  = ((pivot.sub(pivot.mean(axis=1), axis=0)) ** 2).stack().sum()
    MS_between = SS_between / (n - 1)
    MS_within  = SS_within  / (n * (k - 1))
    icc = (MS_between - MS_within) / (MS_between + (k - 1) * MS_within)
    return round(float(icc), 4)


# ─── Plots ────────────────────────────────────────────────────────────────────

def _bar_with_error(ax, series_mean, series_std, title, ylabel, color=UNI_COLOR):
    names = series_mean.index.tolist()
    x = np.arange(len(names))
    # sort by mean score (harsher → more lenient)
    order = np.argsort(series_mean.values)
    ax.bar(x, series_mean.values[order], yerr=series_std.values[order],
           color=color, alpha=0.75, capsize=4, error_kw={"elinewidth": 1.2})
    ax.set_xticks(x)
    ax.set_xticklabels(np.array(names)[order], rotation=40, ha="right", fontsize=8)
    ax.set_title(title, fontsize=10, color=UNI_COLOR)
    ax.set_ylabel(ylabel, fontsize=9)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)


def plot_assessor_overview(assessor_stats: pd.DataFrame, df: pd.DataFrame):
    """
    4-panel figure:
      1. Checklist mean ± std per assessor
      2. Global rating mean ± std per assessor
      3. Practice readiness mean ± std per assessor
      4. Composite harshness z-score (diverging bar)
    """
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("Assessor Harshness & Consistency – BOH1", fontsize=13,
                 color=UNI_COLOR, fontweight="bold", y=1.01)

    ordered = assessor_stats.sort_values("harshness_z")

    # ── Panel 1: Checklist mean ───
    _bar_with_error(axes[0, 0],
                    ordered["checklist_mean"], ordered["checklist_std"].fillna(0),
                    "Checklist Score (0–1)", "Mean score ± SD")

    # ── Panel 2: Global rating ───
    _bar_with_error(axes[0, 1],
                    ordered["global_rating_mean"], ordered["global_rating_std"].fillna(0),
                    "Global Rating (1–5)", "Mean ± SD", color="#4f5fb2")

    # ── Panel 3: Practice readiness ───
    _bar_with_error(axes[1, 0],
                    ordered["pr_mean"], ordered["pr_std"].fillna(0),
                    "Practice Readiness (1–4)", "Mean ± SD", color="#2e7d4f")

    # ── Panel 4: Composite harshness z ───
    ax = axes[1, 1]
    names = ordered.index.tolist()
    z_vals = ordered["harshness_z"].values
    colors = [("#c0392b" if z < 0 else "#27ae60") for z in z_vals]
    x = np.arange(len(names))
    ax.barh(x, z_vals, color=colors, alpha=0.8)
    ax.set_yticks(x)
    ax.set_yticklabels(names, fontsize=8)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title("Composite Harshness Z-score\n(red = harsher, green = more lenient)",
                 fontsize=10, color=UNI_COLOR)
    ax.set_xlabel("Z-score", fontsize=9)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    plt.tight_layout()
    return fig


def plot_score_distributions(df: pd.DataFrame):
    """
    KDE / box-plot of checklist_mean per assessor — shows spread, not just average.
    """
    assessors = (
        df.groupby("assessor_name")["checklist_mean"]
        .count()
        .loc[lambda s: s >= MIN_ASSESSMENTS]
        .index.tolist()
    )
    sub = df[df["assessor_name"].isin(assessors)].copy()

    fig, ax = plt.subplots(figsize=(12, 5))
    order = (sub.groupby("assessor_name")["checklist_mean"]
                .median()
                .sort_values()
                .index.tolist())

    data_by_assessor = [sub[sub["assessor_name"] == a]["checklist_mean"].dropna().values
                        for a in order]
    bp = ax.boxplot(data_by_assessor, patch_artist=True, vert=True,
                    medianprops={"color": "white", "linewidth": 2})
    colors = plt.cm.Blues(np.linspace(0.3, 0.85, len(order)))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)

    ax.set_xticks(range(1, len(order) + 1))
    ax.set_xticklabels(order, rotation=40, ha="right", fontsize=9)
    ax.set_title("Checklist Score Distribution per Assessor\n(sorted by median, left = harsher)",
                 fontsize=11, color=UNI_COLOR)
    ax.set_ylabel("Checklist Mean Score (0–1)")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    plt.tight_layout()
    return fig


def plot_scatter_gr_vs_checklist(df: pd.DataFrame):
    """
    Scatter: global_rating vs checklist_mean, coloured by assessor.
    Helps spot assessors whose rubric scores don't match their holistic rating.
    """
    sub = df.dropna(subset=["global_rating", "checklist_mean"])
    assessors = sub["assessor_name"].unique()
    palette = dict(zip(assessors, plt.cm.tab20(np.linspace(0, 1, len(assessors)))))

    fig, ax = plt.subplots(figsize=(9, 6))
    for assessor, grp in sub.groupby("assessor_name"):
        if len(grp) < MIN_ASSESSMENTS:
            continue
        ax.scatter(grp["checklist_mean"], grp["global_rating"],
                   label=assessor, color=palette[assessor], alpha=0.7, s=50)

    # Overall trend line
    x = sub["checklist_mean"].values
    y = sub["global_rating"].values
    if len(x) > 1:
        m, b = np.polyfit(x, y, 1)
        xs = np.linspace(x.min(), x.max(), 100)
        ax.plot(xs, m * xs + b, color="black", linewidth=1.2, linestyle="--", label="_trend")

    ax.set_xlabel("Checklist Mean Score (0–1)", fontsize=10)
    ax.set_ylabel("Global Rating (1–5)", fontsize=10)
    ax.set_title("Global Rating vs Checklist Score by Assessor", fontsize=11, color=UNI_COLOR)
    ax.legend(fontsize=7, bbox_to_anchor=(1.01, 1), loc="upper left")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    plt.tight_layout()
    return fig


# ─── Summary table ────────────────────────────────────────────────────────────

def print_summary(assessor_stats: pd.DataFrame, df: pd.DataFrame):
    print("\n" + "=" * 70)
    print("ASSESSOR HARSHNESS SUMMARY  (sorted: harshest → most lenient)")
    print("=" * 70)
    display_cols = [
        "n_assessments",
        "checklist_mean", "checklist_std",
        "global_rating_mean", "global_rating_std",
        "pr_mean", "pr_std",
        "harshness_z",
    ]
    print(assessor_stats[display_cols].to_string())

    print("\n── ANOVA tests (significant p < 0.05 → assessors differ) ──")
    for metric, label in [
        ("checklist_mean", "Checklist score"),
        ("global_rating",  "Global rating"),
        ("practice_readiness", "Practice readiness"),
    ]:
        res = anova_test(df, metric)
        sig = "**" if res["p"] < 0.05 else "  "
        print(f"  {label:25s}  F={res['F']:7.3f}  p={res['p']:.4f} {sig}")

    print("\n── ICC(1,1) — agreement when rating same student ──")
    for metric, label in [
        ("checklist_mean", "Checklist score"),
        ("global_rating",  "Global rating"),
        ("practice_readiness", "Practice readiness"),
    ]:
        icc = icc_oneway(df, metric)
        interp = ("poor" if icc < 0.4
                  else "moderate" if icc < 0.6
                  else "good" if icc < 0.75
                  else "excellent")
        print(f"  {label:25s}  ICC={icc:6.4f}  ({interp})")


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def run_assessor_analysis(engine, show_plots: bool = True):
    """
    Main entry point.  Pass your SQLAlchemy engine.

    Returns
    -------
    df              : raw form-level DataFrame with 'scores' and 'checklist_mean' columns
    assessor_stats  : aggregated assessor-level stats DataFrame
    """
    print("Loading BOH1 data …")
    df = load_data(engine)
    print(f"  {len(df)} assessor-submitted forms, "
          f"{df['assessor_name'].nunique()} unique assessors.")

    df = add_scores(df)

    assessor_stats = build_assessor_stats(df)

    print_summary(assessor_stats, df)

    if show_plots:
        fig1 = plot_assessor_overview(assessor_stats, df)
        fig2 = plot_score_distributions(df)
        fig3 = plot_scatter_gr_vs_checklist(df)
        plt.show()

    return df, assessor_stats


# ─── Standalone run ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Replace with your actual connection string
    _engine = create_engine("postgresql://user:pass@localhost/dental_db")
    df, stats_df = run_assessor_analysis(_engine)