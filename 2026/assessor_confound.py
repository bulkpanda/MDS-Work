"""
boh1_assessor_confound.py
─────────────────────────
Extends boh1_assessor_analysis with student-assessor confound diagnostics:

  1. Co-occurrence heatmaps  — who assessed whom, and their mean scores
  2. Student-adjusted residuals  — strips student ability before judging assessors
  3. Crossed variance decomposition  — splits total score variance into
     student, assessor, and residual components without statsmodels

Usage:
    from boh1_assessor_analysis  import load_data, add_scores
    from boh1_assessor_confound  import run_confound_analysis

    df = add_scores(load_data(engine))
    run_confound_analysis(df)
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.patches as mpatches
import seaborn as sns
import scipy.stats as stats
from typing import Tuple

UNI_COLOR   = "#010d44"
MIN_FORMS   = 2          # min forms for an entity to appear in analysis
METRICS     = {
    "checklist_mean":     "Checklist (0–1)",
    "global_rating":      "Global Rating (1–5)",
    "practice_readiness": "Practice Readiness (1–4)",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  Co-occurrence matrices
# ═══════════════════════════════════════════════════════════════════════════════

def build_cooccurrence(df: pd.DataFrame, metric: str = "checklist_mean") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns
    -------
    count_mx  : pivot  student × assessor  →  number of forms
    score_mx  : pivot  student × assessor  →  mean score on `metric`
    """
    sub = df.dropna(subset=[metric]).copy()

    count_mx = (sub
                .pivot_table(index="student_name", columns="assessor_name",
                             values="assessmentid", aggfunc="count")
                .fillna(0).astype(int))

    score_mx = (sub
                .pivot_table(index="student_name", columns="assessor_name",
                             values=metric, aggfunc="mean")
                .round(3))

    # Keep only assessors/students with enough data
    assessor_ok = count_mx.sum(axis=0) >= MIN_FORMS
    student_ok  = count_mx.sum(axis=1) >= MIN_FORMS
    count_mx = count_mx.loc[student_ok, assessor_ok]
    score_mx = score_mx.loc[student_ok, assessor_ok]

    return count_mx, score_mx


def plot_cooccurrence(count_mx: pd.DataFrame, score_mx: pd.DataFrame,
                      metric_label: str = "Checklist Score") -> plt.Figure:
    """
    Two side-by-side heatmaps:
      Left  — number of assessments (count)
      Right — mean score (colour) with count as annotation
    """
    nrows, ncols = count_mx.shape
    cell_w = max(0.6, 8 / max(ncols, 1))
    cell_h = max(0.4, 6 / max(nrows, 1))
    fig_w  = min(cell_w * ncols * 2 + 2, 24)
    fig_h  = min(cell_h * nrows     + 2, 18)

    fig, axes = plt.subplots(1, 2, figsize=(fig_w, fig_h))
    fig.suptitle(f"Student × Assessor  —  {metric_label}",
                 fontsize=12, color=UNI_COLOR, fontweight="bold")

    # ── Left: count ──
    sns.heatmap(count_mx, ax=axes[0],
                cmap="Blues", annot=True, fmt="d", linewidths=0.4,
                cbar_kws={"label": "# assessments"},
                annot_kws={"size": 7})
    axes[0].set_title("Assessment Count", fontsize=10, color=UNI_COLOR)
    axes[0].set_xlabel("Assessor", fontsize=8)
    axes[0].set_ylabel("Student", fontsize=8)
    axes[0].tick_params(axis="x", rotation=45, labelsize=7)
    axes[0].tick_params(axis="y", rotation=0,  labelsize=7)

    # ── Right: mean score (mask NaN cells) ──
    mask = score_mx.isna()
    # Annotation: show score where count > 0 else blank
    annot = score_mx.copy().round(2)
    annot_str = annot.applymap(lambda v: f"{v:.2f}" if pd.notna(v) else "")

    sns.heatmap(score_mx, ax=axes[1],
                cmap="RdYlGn", vmin=0, vmax=1,
                annot=annot_str, fmt="", mask=mask, linewidths=0.4,
                cbar_kws={"label": metric_label},
                annot_kws={"size": 7})
    axes[1].set_title(f"Mean {metric_label}\n(blank = no data)", fontsize=10, color=UNI_COLOR)
    axes[1].set_xlabel("Assessor", fontsize=8)
    axes[1].set_ylabel("")
    axes[1].tick_params(axis="x", rotation=45, labelsize=7)
    axes[1].tick_params(axis="y", rotation=0,  labelsize=7)

    plt.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  Student-adjusted assessor harshness
# ═══════════════════════════════════════════════════════════════════════════════

def student_adjusted_harshness(df: pd.DataFrame, metric: str = "checklist_mean") -> pd.DataFrame:
    """
    For each form, compute the residual:
        residual = score  -  that_student's_mean_score

    Then aggregate residuals by assessor.
    A negative mean residual → assessor scores below the student's typical level → harsher.

    Also adds:
      - n_students_unique : how many distinct students this assessor graded
      - coverage_ratio    : unique students / total assessments (1.0 = never repeated a student)
      - confound_risk     : HIGH if assessor graded few unique students relative to total forms
    """
    sub = df.dropna(subset=[metric]).copy()

    # Student mean on this metric (across all their assessors)
    student_means = sub.groupby("student_number")[metric].transform("mean")
    sub["residual"] = sub[metric] - student_means

    agg = sub.groupby("assessor_name").agg(
        n_forms          = ("assessmentid",   "count"),
        n_students_unique= ("student_number", "nunique"),
        raw_mean         = (metric,           "mean"),
        raw_std          = (metric,           "std"),
        adj_mean         = ("residual",       "mean"),   # KEY: student-adjusted
        adj_std          = ("residual",       "std"),
    ).round(4)

    agg = agg[agg["n_forms"] >= MIN_FORMS].copy()

    agg["coverage_ratio"] = (agg["n_students_unique"] / agg["n_forms"]).round(3)

    # Flag confound risk: assessor has repeated the same students a lot
    # threshold: if < 40 % of forms are unique students → HIGH risk
    agg["confound_risk"] = agg["coverage_ratio"].apply(
        lambda r: "HIGH" if r < 0.4 else ("MEDIUM" if r < 0.7 else "LOW")
    )

    return agg.sort_values("adj_mean")


def plot_adjusted_harshness(adj_df: pd.DataFrame, metric_label: str = "Checklist") -> plt.Figure:
    """
    Three-panel plot showing raw vs adjusted harshness and confound risk.
    """
    ordered = adj_df.sort_values("adj_mean")
    names   = ordered.index.tolist()
    x       = np.arange(len(names))

    risk_color = {"LOW": "#27ae60", "MEDIUM": "#e67e22", "HIGH": "#c0392b"}
    bar_colors = [risk_color[r] for r in ordered["confound_risk"]]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle(f"Student-Adjusted Assessor Harshness — {metric_label}",
                 fontsize=12, color=UNI_COLOR, fontweight="bold")

    # ── Panel 1: Raw mean ──
    axes[0].barh(x, ordered["raw_mean"], color=UNI_COLOR, alpha=0.7)
    axes[0].set_yticks(x); axes[0].set_yticklabels(names, fontsize=8)
    axes[0].set_title("Raw Mean Score\n(confounded by student ability)", fontsize=9)
    axes[0].set_xlabel(metric_label)
    for s in ["top", "right"]: axes[0].spines[s].set_visible(False)

    # ── Panel 2: Adjusted residual mean ──
    axes[1].barh(x, ordered["adj_mean"], color=bar_colors, alpha=0.85,
                 xerr=ordered["adj_std"].fillna(0),
                 error_kw={"elinewidth": 1, "ecolor": "grey"})
    axes[1].axvline(0, color="black", linewidth=0.9)
    axes[1].set_yticks(x); axes[1].set_yticklabels(names, fontsize=8)
    axes[1].set_title("Student-Adjusted Residual\n(negative = scores below student norm → harsher)",
                      fontsize=9)
    axes[1].set_xlabel("Residual")
    # Legend for confound risk
    legend_handles = [
        mpatches.Patch(facecolor=col, label=f"Confound risk: {label}")
        for label, col in risk_color.items()
    ]
    axes[1].legend(handles=legend_handles, fontsize=7, loc="lower right")
    for s in ["top", "right"]: axes[1].spines[s].set_visible(False)

    # ── Panel 3: Coverage ratio (unique students / total forms) ──
    axes[2].barh(x, ordered["coverage_ratio"], color=bar_colors, alpha=0.85)
    axes[2].axvline(0.4, color="#c0392b", linewidth=1, linestyle="--", label="HIGH risk threshold (0.4)")
    axes[2].axvline(0.7, color="#e67e22", linewidth=1, linestyle="--", label="MEDIUM threshold (0.7)")
    axes[2].set_yticks(x); axes[2].set_yticklabels(names, fontsize=8)
    axes[2].set_xlim(0, 1.05)
    axes[2].set_title("Coverage Ratio\n(unique students / total forms)", fontsize=9)
    axes[2].set_xlabel("Ratio (1.0 = never repeated a student)")
    axes[2].legend(fontsize=7)
    for s in ["top", "right"]: axes[2].spines[s].set_visible(False)

    plt.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  Crossed variance decomposition (no statsmodels)
# ═══════════════════════════════════════════════════════════════════════════════

def crossed_variance_decomposition(df: pd.DataFrame, metric: str = "checklist_mean") -> dict:
    """
    Decomposes total score variance into:
      - Student variance  (VS)  : how much students differ from each other
      - Assessor variance (VA)  : how much assessors differ from each other
      - Residual variance (VR)  : remaining unexplained

    Method: two-way ANOVA without interaction (Type I SS), balanced approximation.
    Only uses student-assessor pairs where both have MIN_FORMS assessments.

    Returns a dict with variance components and % of total.
    """
    sub = df.dropna(subset=[metric]).copy()

    # Filter to well-represented students and assessors
    keep_s = sub.groupby("student_number")[metric].count() >= MIN_FORMS
    keep_a = sub.groupby("assessor_name")[metric].count()  >= MIN_FORMS
    sub = sub[sub["student_number"].isin(keep_s[keep_s].index) &
              sub["assessor_name"].isin(keep_a[keep_a].index)]

    if sub.empty or sub["student_number"].nunique() < 2 or sub["assessor_name"].nunique() < 2:
        return {"error": "Insufficient crossed data for decomposition"}

    y          = sub[metric].values
    grand_mean = y.mean()
    SS_total   = ((y - grand_mean) ** 2).sum()

    # Student grand means
    s_means = sub.groupby("student_number")[metric].mean()
    SS_student = sum(
        (sub["student_number"] == sid).sum() * (smean - grand_mean) ** 2
        for sid, smean in s_means.items()
    )

    # Assessor grand means
    a_means = sub.groupby("assessor_name")[metric].mean()
    SS_assessor = sum(
        (sub["assessor_name"] == aname).sum() * (amean - grand_mean) ** 2
        for aname, amean in a_means.items()
    )

    SS_residual = max(SS_total - SS_student - SS_assessor, 0)

    n_s = sub["student_number"].nunique()
    n_a = sub["assessor_name"].nunique()
    n   = len(sub)

    df_student  = n_s - 1
    df_assessor = n_a - 1
    df_residual = max(n - n_s - n_a + 1, 1)

    MS_student  = SS_student  / df_student  if df_student  > 0 else np.nan
    MS_assessor = SS_assessor / df_assessor if df_assessor > 0 else np.nan
    MS_residual = SS_residual / df_residual if df_residual > 0 else np.nan

    # F-tests
    F_student  = MS_student  / MS_residual if MS_residual else np.nan
    F_assessor = MS_assessor / MS_residual if MS_residual else np.nan
    p_student  = 1 - stats.f.cdf(F_student,  df_student,  df_residual) if not np.isnan(F_student)  else np.nan
    p_assessor = 1 - stats.f.cdf(F_assessor, df_assessor, df_residual) if not np.isnan(F_assessor) else np.nan

    # Variance components (expected mean squares, balanced approximation)
    # E[MS_student]  = σ²_ε + k_a * σ²_s    → σ²_s  ≈ (MS_student  - MS_residual) / k_a
    # E[MS_assessor] = σ²_ε + k_s * σ²_a    → σ²_a  ≈ (MS_assessor - MS_residual) / k_s
    k_a = n / n_s   # avg assessments per student
    k_s = n / n_a   # avg assessments per assessor

    var_student  = max((MS_student  - MS_residual) / k_a, 0) if not np.isnan(MS_student)  else np.nan
    var_assessor = max((MS_assessor - MS_residual) / k_s, 0) if not np.isnan(MS_assessor) else np.nan
    var_residual = MS_residual if not np.isnan(MS_residual) else np.nan

    var_total = (var_student or 0) + (var_assessor or 0) + (var_residual or 0)

    def pct(v):
        return round(100 * v / var_total, 1) if var_total > 0 and not np.isnan(v) else np.nan

    return {
        "n_forms":      n,
        "n_students":   n_s,
        "n_assessors":  n_a,
        "var_student":  round(var_student,  6),
        "var_assessor": round(var_assessor, 6),
        "var_residual": round(var_residual, 6),
        "pct_student":  pct(var_student),
        "pct_assessor": pct(var_assessor),
        "pct_residual": pct(var_residual),
        "F_student":    round(F_student,  3),
        "F_assessor":   round(F_assessor, 3),
        "p_student":    round(p_student,  4),
        "p_assessor":   round(p_assessor, 4),
    }


def plot_variance_decomposition(decomp_results: dict) -> plt.Figure:
    """
    Stacked bar chart showing % variance from student / assessor / residual
    across all metrics.
    """
    rows = []
    for metric_key, label in METRICS.items():
        r = decomp_results.get(metric_key, {})
        if "error" in r:
            continue
        rows.append({
            "metric":        label,
            "Student":       r.get("pct_student",  0) or 0,
            "Assessor":      r.get("pct_assessor", 0) or 0,
            "Residual":      r.get("pct_residual", 0) or 0,
            "p_assessor":    r.get("p_assessor", np.nan),
        })

    if not rows:
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.text(0.5, 0.5, "Insufficient data for decomposition",
                ha="center", va="center", transform=ax.transAxes)
        return fig

    plot_df = pd.DataFrame(rows).set_index("metric")
    p_vals  = plot_df.pop("p_assessor")

    colors = ["#2980b9", "#c0392b", "#95a5a6"]
    fig, ax = plt.subplots(figsize=(9, 5))
    plot_df[["Student", "Assessor", "Residual"]].plot(
        kind="bar", stacked=True, ax=ax,
        color=colors, edgecolor="white", linewidth=0.5
    )
    ax.set_ylim(0, 115)
    ax.set_ylabel("% of total variance", fontsize=10)
    ax.set_title("Variance Decomposition: Student vs Assessor vs Residual",
                 fontsize=11, color=UNI_COLOR, fontweight="bold")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=25, ha="right", fontsize=9)
    ax.legend(loc="upper right", fontsize=9)

    # Annotate assessor p-value above each bar
    for i, (metric_label, p) in enumerate(p_vals.items()):
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else "ns"))
        ax.text(i, 103, f"assessor {sig}", ha="center", va="bottom", fontsize=7, color="#c0392b")

    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    plt.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  Entrypoint
# ═══════════════════════════════════════════════════════════════════════════════

def run_confound_analysis(df: pd.DataFrame, show_plots: bool = True) -> dict:
    """
    Parameters
    ----------
    df : output of add_scores(load_data(engine)) from boh1_assessor_analysis.py

    Returns
    -------
    results dict with keys:
        count_mx, score_mx          – co-occurrence DataFrames (per metric)
        adj_harshness               – student-adjusted harshness (per metric)
        decomp                      – variance decomposition (per metric)
    """
    results = {"adj_harshness": {}, "decomp": {}, "cooccurrence": {}}

    print("\n" + "=" * 70)
    print("STUDENT-ASSESSOR CONFOUND ANALYSIS")
    print("=" * 70)

    for metric, label in METRICS.items():
        print(f"\n── {label} ──")

        # Co-occurrence
        count_mx, score_mx = build_cooccurrence(df, metric)
        results["cooccurrence"][metric] = (count_mx, score_mx)
        print(f"  Students: {count_mx.shape[0]}  |  Assessors: {count_mx.shape[1]}")
        print(f"  Sparsity: {(count_mx == 0).values.sum() / count_mx.size:.1%} of cells have no data")

        if show_plots:
            fig = plot_cooccurrence(count_mx, score_mx, label)
            plt.show()

        # Student-adjusted harshness
        adj = student_adjusted_harshness(df, metric)
        results["adj_harshness"][metric] = adj
        print("\n  Student-adjusted harshness (adj_mean < 0 → harsher than student norm):")
        print(adj[["n_forms", "n_students_unique", "coverage_ratio",
                   "confound_risk", "raw_mean", "adj_mean", "adj_std"]].to_string())
        high_risk = adj[adj["confound_risk"] == "HIGH"]
        if not high_risk.empty:
            print(f"\n  ⚠ HIGH confound risk assessors (interpret their harshness score cautiously):")
            for name in high_risk.index:
                r = adj.loc[name]
                print(f"    {name}: {int(r.n_forms)} forms, {int(r.n_students_unique)} unique students "
                      f"({r.coverage_ratio:.0%} coverage)")

        if show_plots:
            fig = plot_adjusted_harshness(adj, label)
            plt.show()

        # Variance decomposition
        decomp = crossed_variance_decomposition(df, metric)
        results["decomp"][metric] = decomp
        if "error" not in decomp:
            print(f"\n  Variance decomposition:")
            print(f"    Student  variance: {decomp['pct_student']:5.1f}%  "
                  f"(F={decomp['F_student']:.2f}, p={decomp['p_student']:.4f})")
            print(f"    Assessor variance: {decomp['pct_assessor']:5.1f}%  "
                  f"(F={decomp['F_assessor']:.2f}, p={decomp['p_assessor']:.4f})")
            print(f"    Residual variance: {decomp['pct_residual']:5.1f}%")
        else:
            print(f"  Decomposition: {decomp['error']}")

    if show_plots:
        fig = plot_variance_decomposition(results["decomp"])
        plt.show()

    return results