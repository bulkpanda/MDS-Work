import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
import os
import re


# ── CONFIG ──
folderPath = r"2026/DDS2"
borderlineThreshold = 2  # global_rating value considered "borderline"
dateRegex = r"\d{4}-\d{2}-\d{2}"
filePattern = r"assessment_data\.xlsx$"


def loadWeeklyFiles(folderPath, dateRegex, filePattern):
    """Load all weekly assessment files, return list of (dateStr, df) tuples."""
    compiledFile = re.compile(filePattern, re.IGNORECASE)
    compiledDate = re.compile(dateRegex)
    files = []
    for filename in os.listdir(folderPath):
        if filename.startswith("~$"):
            continue
        if not compiledFile.search(filename):
            continue
        dateMatch = compiledDate.search(filename)
        if not dateMatch:
            continue
        dateStr = dateMatch.group(0)
        filePath = os.path.join(folderPath, filename)
        df = pd.read_excel(filePath, engine="openpyxl")
        files.append((dateStr, df))
    return sorted(files, key=lambda x: x[0])


def runBlrAnalysis(df, dateStr, borderlineGr, mcCols=None):
    """Run full BLR analysis for a single day's data. Returns dict of results."""
    if mcCols is None:
        mcCols = [c for c in df.columns if c.startswith("MC")]

    # ── 1. Borderline group method: mean score of borderline group ──
    borderlineScores = df.loc[df["global_rating"] == borderlineGr, "assessor_score"]
    borderlineMean = borderlineScores.mean()
    borderlineSd = borderlineScores.std()

    # ── 2. Linear regression: assessor_score ~ global_rating ──
    slope, intercept, rVal, pVal, stdErr = stats.linregress(
        df["global_rating"], df["assessor_score"]
    )
    regressionCutoff = slope * borderlineGr + intercept
    rSquared = rVal ** 2

    # ── 3. Per-rating group stats ──
    ratingGroups = df.groupby("global_rating")["assessor_score"]
    ratingStats = ratingGroups.agg(["mean", "std", "count"]).rename(
        columns={"mean": "meanScore", "std": "sdScore", "count": "n"}
    )

    # ── 4. Item analysis ──
    itemStats = []
    for mc in mcCols:
        if mc not in df.columns:
            continue
        itemMean = df[mc].mean()
        borderlineItemMean = df.loc[df["global_rating"] == borderlineGr, mc].mean()
        itemTotalCorr = df[mc].corr(df["assessor_score"])
        itemStats.append({
            "item": mc,
            "mean": round(itemMean, 3),
            "borderlineMean": round(borderlineItemMean, 3),
            "itemTotalCorr": round(itemTotalCorr, 3),
        })
    itemStatsDf = pd.DataFrame(itemStats)

    # ── 5. Cronbach's alpha ──
    validMcCols = [c for c in mcCols if c in df.columns]
    mcData = df[validMcCols].dropna()
    k = len(validMcCols)
    itemVars = mcData.var(axis=0, ddof=1)
    totalVar = mcData.sum(axis=1).var(ddof=1)
    cronbachAlpha = (k / (k - 1)) * (1 - itemVars.sum() / totalVar) if k > 1 else np.nan

    # ── 6. Flag students below cutoff ──
    belowCutoffDf = df.loc[
        df["assessor_score"] <= regressionCutoff,
        ["student_number", "student_name", "assessor_score", "global_rating", "assessor_name"],
    ].sort_values("assessor_score")

    return {
        "date": dateStr,
        "n": len(df),
        "borderlineMean": round(borderlineMean, 4),
        "borderlineSd": round(borderlineSd, 4),
        "regressionCutoff": round(regressionCutoff, 4),
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "rSquared": round(rSquared, 4),
        "pVal": pVal,
        "overallMean": round(df["assessor_score"].mean(), 4),
        "overallSd": round(df["assessor_score"].std(), 4),
        "cronbachAlpha": round(cronbachAlpha, 4),
        "ratingStats": ratingStats,
        "itemStatsDf": itemStatsDf,
        "belowCutoffDf": belowCutoffDf,
        "df": df,
    }


def plotBlrScatter(result, borderlineGr, ax=None):
    """Scatter of assessor_score vs global_rating with regression line + cutoff."""
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
    df = result["df"]
    colors = {1: "#E24B4A", 2: "#EF9F27", 3: "#3266ad", 4: "#1D9E75"}

    for gr in sorted(df["global_rating"].unique()):
        subset = df[df["global_rating"] == gr]
        jitter = np.random.uniform(-0.15, 0.15, len(subset))
        ax.scatter(
            subset["global_rating"] + jitter,
            subset["assessor_score"] * 100,
            c=colors.get(gr, "#888"),
            label=f"GR {gr} (n={len(subset)})",
            alpha=0.7,
            edgecolors="white",
            linewidth=0.5,
            s=40,
        )

    # regression line
    xLine = np.array([0.5, max(df["global_rating"]) + 0.5])
    yLine = (result["slope"] * xLine + result["intercept"]) * 100
    ax.plot(xLine, yLine, "k--", linewidth=1.5, label=f"Regression (R²={result['rSquared']:.3f})")

    # cutoff line
    cutoff = result["regressionCutoff"] * 100
    ax.axhline(cutoff, color="#E24B4A", linestyle=":", linewidth=1.5, label=f"BLR cutoff {cutoff:.1f}%")

    ax.set_xlabel("Global rating")
    ax.set_ylabel("Assessor score (%)")
    ax.set_title(f"BLR scatter — {result['date']}")
    ax.legend(fontsize=8, loc="lower right")
    ax.set_xlim(0.5, max(df["global_rating"]) + 0.5)
    ax.set_ylim(45, 105)
    return ax


def plotRatingBoxplot(result, ax=None):
    """Boxplot of assessor_score grouped by global_rating."""
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
    df = result["df"]
    ratings = sorted(df["global_rating"].unique())
    data = [df.loc[df["global_rating"] == gr, "assessor_score"].values * 100 for gr in ratings]
    colors = {1: "#E24B4A", 2: "#EF9F27", 3: "#3266ad", 4: "#1D9E75"}

    bp = ax.boxplot(data, labels=[f"GR {r}" for r in ratings], patch_artist=True, widths=0.5)
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(colors.get(ratings[i], "#8880") + "66")  # add transparency
        patch.set_edgecolor(colors.get(ratings[i], "#888"))

    cutoff = result["regressionCutoff"] * 100
    ax.axhline(cutoff, color="#E24B4A", linestyle=":", linewidth=1.5, label=f"BLR cutoff {cutoff:.1f}%")
    ax.set_ylabel("Assessor score (%)")
    ax.set_title(f"Score distribution by global rating — {result['date']}")
    ax.legend(fontsize=8)
    return ax


def plotItemAnalysis(result, ax=None):
    """Bar chart of item means + line of item-total correlations."""
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
    idf = result["itemStatsDf"]
    x = np.arange(len(idf))

    ax.bar(x, idf["mean"] * 100, color="#3266ad88", edgecolor="#3266ad", label="Item mean (%)")
    ax.set_ylabel("Mean (%)")
    ax.set_ylim(0, 110)

    ax2 = ax.twinx()
    ax2.plot(x, idf["itemTotalCorr"], "o-", color="#1D9E75", linewidth=2, markersize=6, label="Item-total r")
    ax2.set_ylabel("Correlation (r)")
    ax2.set_ylim(0, 1)

    ax.set_xticks(x)
    ax.set_xticklabels(idf["item"], rotation=45, ha="right")
    ax.set_title(f"Item analysis — {result['date']}")

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="lower left")
    return ax


def plotScoreHistogram(result, ax=None):
    """Histogram of assessor_score with cutoff line."""
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
    df = result["df"]
    ax.hist(df["assessor_score"] * 100, bins=15, color="#3266ad55", edgecolor="#3266ad", linewidth=0.8)
    cutoff = result["regressionCutoff"] * 100
    ax.axvline(cutoff, color="#E24B4A", linestyle=":", linewidth=2, label=f"BLR cutoff {cutoff:.1f}%")
    ax.axvline(result["overallMean"] * 100, color="#333", linestyle="--", linewidth=1, label=f"Mean {result['overallMean']*100:.1f}%")
    ax.set_xlabel("Assessor score (%)")
    ax.set_ylabel("Frequency")
    ax.set_title(f"Score distribution — {result['date']}")
    ax.legend(fontsize=8)
    return ax


def printSummary(result, borderlineGr):
    """Print key BLR stats to console."""
    print(f"\n{'='*60}")
    print(f"BLR ANALYSIS — {result['date']}  (n={result['n']})")
    print(f"{'='*60}")
    print(f"  Borderline GR threshold:   {borderlineGr}")
    print(f"  BLR cutoff (regression):   {result['regressionCutoff']*100:.2f}%")
    print(f"  Borderline group mean:     {result['borderlineMean']*100:.2f}% (SD={result['borderlineSd']*100:.2f}%)")
    print(f"  Regression: score = {result['slope']:.4f} × GR + {result['intercept']:.4f}")
    print(f"  R² = {result['rSquared']:.4f},  p = {result['pVal']:.2e}")
    print(f"  Overall mean: {result['overallMean']*100:.2f}%  SD: {result['overallSd']*100:.2f}%")
    print(f"  Cronbach's α: {result['cronbachAlpha']:.4f}")
    print(f"\n  Rating group stats:")
    print(result["ratingStats"].to_string())
    print(f"\n  Item analysis:")
    print(result["itemStatsDf"].to_string(index=False))
    print(f"\n  Students below cutoff ({len(result['belowCutoffDf'])}):")
    print(result["belowCutoffDf"].to_string(index=False))


# ── MAIN ──
if __name__ == "__main__":
    weeklyFiles = loadWeeklyFiles(folderPath, dateRegex, filePattern)

    if not weeklyFiles:
        print(f"No matching files found in {folderPath}")
        exit()

    allResults = []
    for dateStr, df in weeklyFiles:
        result = runBlrAnalysis(df, dateStr, borderlineThreshold)
        allResults.append(result)
        printSummary(result, borderlineThreshold)

        # ── Generate 4-panel figure per day ──
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(f"BLR Analysis — {dateStr}", fontsize=16, fontweight="bold")
        plotBlrScatter(result, borderlineThreshold, ax=axes[0, 0])
        plotRatingBoxplot(result, ax=axes[0, 1])
        plotItemAnalysis(result, ax=axes[1, 0])
        plotScoreHistogram(result, ax=axes[1, 1])
        plt.tight_layout()
        outFig = os.path.join(folderPath, f"blr_analysis_{dateStr}.png")
        fig.savefig(outFig, dpi=150, bbox_inches="tight")
        print(f"\n  Saved figure: {outFig}")
        plt.close(fig)

    # ── Longitudinal cutoff trend (if multiple days) ──
    if len(allResults) > 1:
        fig, ax = plt.subplots(figsize=(10, 5))
        dates = [r["date"] for r in allResults]
        cutoffs = [r["regressionCutoff"] * 100 for r in allResults]
        means = [r["overallMean"] * 100 for r in allResults]
        ax.plot(dates, cutoffs, "o-", color="#E24B4A", linewidth=2, label="BLR cutoff")
        ax.plot(dates, means, "s--", color="#3266ad", linewidth=1.5, label="Overall mean")
        ax.set_ylabel("Score (%)")
        ax.set_title("BLR cutoff trend across assessment days")
        ax.legend()
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        outTrend = os.path.join(folderPath, "blr_cutoff_trend.png")
        fig.savefig(outTrend, dpi=150, bbox_inches="tight")
        print(f"\nSaved trend figure: {outTrend}")
        plt.close(fig)
