"""
risk_report.report
──────────────────
Importable module for generating multi-sheet Excel student performance risk reports.

Notebook usage (one-liner)
───────────────────────────
    from risk_report import generate
    generate("my_cohort.xlsx", "output_report.xlsx", cohort="DDS3")

Notebook usage (interactive / tweak thresholds mid-analysis)
─────────────────────────────────────────────────────────────
    from risk_report import load, RiskReport

    rr = load("my_cohort.xlsx", cohort="DDS3")

    # inspect the analytics dataframe before writing
    rr.df[rr.df.risk_label == "High Risk"]

    # override a threshold and recompute
    rr.cfg["lowScoreThreshold"] = 0.60
    rr.recompute()
    rr.df.head()

    # write the report
    rr.save("output_report.xlsx")

Default thresholds (all overridable via cfg dict or keyword args)
────────────────────────────────────────────────────────────────
    sdBelowMeanScore    = 1.0     # flag if avg score > 1 SD below cohort mean
    decliningSlope      = -0.001  # OLS slope/week below which trend is "declining"
    improvementWindow   = 5       # weeks at each end for early-vs-late comparison
    improvementMinGain  = 0.02    # gain < 2pp → no improvement flag
    sdBelowMeanRating   = 1.0
    sdBelowMeanPr       = 1.0
    lowScoreThreshold   = 0.65    # absolute per-week floor
    lowScoreWeekCount   = 3       # flag if ≥ N weeks below floor
    missingThreshold    = 2       # flag if ≥ N weeks missing
    lateStallWindow     = 3       # final weeks used for stall check
    lateStallDrop       = 0.05    # stall if last N wks > 5pp below mid avg
    highRiskFlags       = 4
    moderateRiskFlags   = 2
    watchFlags          = 1
    minWeeksForSlope    = 4
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# ══════════════════════════════════════════════════════════════════════════════
# DEFAULTS
# ══════════════════════════════════════════════════════════════════════════════

DEFAULTS = dict(
    # Sheet names
    sheetScores    = "scores",
    sheetRatings   = "global_ratings",
    sheetPr        = "practice_readiness",
    sheetMissing   = "scores_missing",
    sheetRepeated  = "repeated_attempts",
    weekColKeyword = "Week",
    # Thresholds
    sdBelowMeanScore   = 1.0,
    decliningSlope     = -0.001,
    improvementWindow  = 5,
    improvementMinGain = 0.02,
    sdBelowMeanRating  = 1.0,
    sdBelowMeanPr      = 1.0,
    lowScoreThreshold  = 0.65,
    lowScoreWeekCount  = 3,
    missingThreshold   = 2,
    lateStallWindow    = 3,
    lateStallDrop      = 0.05,
    highRiskFlags      = 4,
    moderateRiskFlags  = 2,
    watchFlags         = 1,
    minWeeksForSlope   = 4,
    # Flag 9: rating trajectory across three equal phases (first/mid/last third)
    # Triggered when the last-phase avg rating is below the first-phase avg by this margin
    ratingPhaseDropMin = 0.3,   # 0.3 points on 1–5 scale
)

FLAG_LABELS = {
    "flag_low_avg_score"    : "Low avg score",
    "flag_declining_score"  : "Declining trend",
    "flag_no_improvement"   : "No improvement",
    "flag_low_rating"       : "Low global rating",
    "flag_low_pr"           : "Low practice readiness",
    "flag_many_low_weeks"   : "Many low-score weeks",
    "flag_missing"          : "Excessive missing",
    "flag_late_stall"       : "Late-stage stall",
    "flag_rating_phase_drop": "Rating declined across thirds",
}

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    navy      = "1A2B4A", darkSlate = "2C3E50",
    redH      = "C0392B", orangeM   = "E67E22",
    yellowW   = "F39C12", greenOk   = "27AE60",
    bgRed     = "FDECEA", bgOrange  = "FEF5EC",
    bgYellow  = "FEFAE8", bgGreen   = "EAF8F0",
    lightGrey = "F5F5F5", white     = "FFFFFF",
    tabHdr    = "34495E", subHdr    = "7F8C8D",
)

RISK_COLORS = {
    "High Risk"    : (C["redH"],    C["bgRed"],    "FFFFFF"),
    "Moderate Risk": (C["orangeM"], C["bgOrange"], "FFFFFF"),
    "Watch"        : (C["yellowW"], C["bgYellow"], "2C3E50"),
    "OK"           : (C["greenOk"], C["bgGreen"],  "FFFFFF"),
}


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def load(
    inputPath: str,
    cohort: str = "Cohort",
    **cfgOverrides,
) -> "RiskReport":
    """
    Load a workbook and return a RiskReport ready for inspection or saving.

    Parameters
    ----------
    inputPath : str
        Path to the input .xlsx file.
    cohort : str
        Label used in report headings (e.g. "DDS3", "BOH2").
    **cfgOverrides
        Any key from DEFAULTS can be overridden here, e.g.
        lowScoreThreshold=0.60, highRiskFlags=3
    """
    return RiskReport(inputPath, cohort=cohort, **cfgOverrides)


def generate(
    inputPath: str,
    outputPath: str,
    cohort: str = "Cohort",
    **cfgOverrides,
) -> "RiskReport":
    """
    Load, compute, and save the report in one call.

    Returns the RiskReport so you can still inspect .df afterwards.
    """
    rr = load(inputPath, cohort=cohort, **cfgOverrides)
    rr.save(outputPath)
    return rr


# ══════════════════════════════════════════════════════════════════════════════
# RiskReport CLASS
# ══════════════════════════════════════════════════════════════════════════════

class RiskReport:
    """
    Holds the raw dataframes, config, computed analytics, and writes the report.

    Attributes (all public, inspect freely)
    ────────────────────────────────────────
    df          – per-student analytics + risk flags + risk_label, sorted by risk
    scores      – raw scores sheet
    ratings     – raw global_ratings sheet
    pr          – raw practice_readiness sheet
    missing     – raw scores_missing sheet
    repeated    – raw repeated_attempts sheet
    weekCols    – list of detected week column names
    stats       – dict of cohort-level summary stats
    cfg         – active config dict (edit & call recompute() to update df)
    """

    def __init__(self, inputPath: str, cohort: str = "Cohort", **cfgOverrides):
        self.cohort = cohort
        self.cfg    = {**DEFAULTS, **cfgOverrides}

        self.scores, self.ratings, self.pr, self.missing, self.repeated = \
            _loadSheets(inputPath, self.cfg)

        self.weekCols = [
            c for c in self.scores.columns
            if self.cfg["weekColKeyword"] in str(c)
        ]
        if not self.weekCols:
            raise ValueError(
                f"No columns containing '{self.cfg['weekColKeyword']}' found in "
                f"sheet '{self.cfg['sheetScores']}'."
            )

        self.df, self.stats = _buildAnalytics(
            self.scores, self.ratings, self.pr,
            self.missing, self.repeated,
            self.weekCols, self.cfg,
        )
        print(
            f"Loaded: {self.cohort}  |  {len(self.df)} students  |  "
            f"{len(self.weekCols)} weeks  |  "
            f"High: {(self.df.risk_label=='High Risk').sum()}  "
            f"Mod: {(self.df.risk_label=='Moderate Risk').sum()}  "
            f"Watch: {(self.df.risk_label=='Watch').sum()}  "
            f"OK: {(self.df.risk_label=='OK').sum()}"
        )

    def recompute(self):
        """Rerun analytics with current self.cfg (useful after editing thresholds)."""
        self.df, self.stats = _buildAnalytics(
            self.scores, self.ratings, self.pr,
            self.missing, self.repeated,
            self.weekCols, self.cfg,
        )
        return self

    def save(self, outputPath: str) -> str:
        """Write the Excel report and return the resolved output path."""
        out = Path(outputPath)
        out.parent.mkdir(parents=True, exist_ok=True)
        wb = _buildWorkbook(self)
        wb.save(str(out))
        print(f"Saved → {out}")
        return str(out)

    # ── Convenience query shortcuts ──────────────────────────────────────────

    @property
    def highRisk(self) -> pd.DataFrame:
        """Students with risk_label == 'High Risk'."""
        return self.df[self.df.risk_label == "High Risk"]

    @property
    def moderateRisk(self) -> pd.DataFrame:
        return self.df[self.df.risk_label == "Moderate Risk"]

    @property
    def declining(self) -> pd.DataFrame:
        """Students with a negative OLS score slope."""
        return self.df[self.df.score_slope < 0].sort_values("score_slope")

    @property
    def noImprovement(self) -> pd.DataFrame:
        """Students who did not improve by the configured minimum gain."""
        return self.df[
            self.df.score_improvement < self.cfg["improvementMinGain"]
        ].sort_values("score_improvement")

    def summary(self) -> pd.DataFrame:
        """Compact cohort summary: one row per risk tier."""
        rows = []
        for label in ["High Risk", "Moderate Risk", "Watch", "OK"]:
            sub = self.df[self.df.risk_label == label]
            rows.append({
                "risk_tier"     : label,
                "n_students"    : len(sub),
                "avg_score_mean": sub.avg_score.mean(),
                "avg_score_min" : sub.avg_score.min(),
                "avg_score_max" : sub.avg_score.max(),
            })
        return pd.DataFrame(rows).set_index("risk_tier")

    def __repr__(self):
        return (
            f"RiskReport(cohort='{self.cohort}', students={len(self.df)}, "
            f"weeks={len(self.weekCols)}, "
            f"high={( self.df.risk_label=='High Risk').sum()}, "
            f"moderate={(self.df.risk_label=='Moderate Risk').sum()})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL – DATA LOADING & ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

# Combined workbooks written from 2026-08-18 carry Title Case headers (the source of truth
# is general_utils.COMBINED_SHEET_COLUMN_LABELS). This module is deliberately standalone —
# it reads a workbook off disk and imports nothing from the reporting stack — so the
# reverse map is duplicated here rather than imported. KEEP THE TWO IN STEP: a label added
# there and missed here shows up as a KeyError on the snake_case name.
#
# Item-code columns are NOT in this map and must never be: `weekCols` finds them by
# substring, and renaming one would silently drop a week from every trend and slope.
_COMBINED_HEADER_ALIASES = {
    "Student Number":     "student_number",
    "Student Name":       "student_name",
    "Last Name":          "last_name",
    "First Name":         "first_name",
    "Item Code":          "item_code",
    "Date":               "date",
    "Subject":            "subject",
    "Assessor Name":      "assessor_name",
    "Low Count":          "low_count",
    "Attempts":           "n_attempts",
    "Dates":              "dates",
    "Scores":             "scores",
    "Missing Item Codes": "missing_item_codes",
    "Total Forms":        "n_forms",
    "Distinct Assessors": "n_assessors",
    "Most Seen Assessor": "most_seen_assessor",
    "Most Seen Count":    "most_seen_count",
    "Stream":             "stream",
    "Expected Subject":   "expected_subject",
}


def _normaliseHeaders(df: pd.DataFrame) -> pd.DataFrame:
    """Map a combined sheet's display headers back to the snake_case names used here.

    A workbook written before 2026-08-18 has nothing to map, so the same call handles both
    layouts and the two can sit side by side in one folder. "Avg Score" and "Pass/Fail"
    were always display-cased and are deliberately absent from the map.
    """
    return df.rename(columns=_COMBINED_HEADER_ALIASES)


def _loadSheets(path: str, cfg: dict):
    xf = pd.ExcelFile(path)
    required = {
        "sheetScores"  : cfg["sheetScores"],
        "sheetRatings" : cfg["sheetRatings"],
        "sheetPr"      : cfg["sheetPr"],
        "sheetMissing" : cfg["sheetMissing"],
        "sheetRepeated": cfg["sheetRepeated"],
    }
    missing_sheets = [v for v in required.values() if v not in xf.sheet_names]
    if missing_sheets:
        raise ValueError(
            f"Sheet(s) not found: {missing_sheets}\n"
            f"Available: {xf.sheet_names}"
        )
    return tuple(
        _normaliseHeaders(pd.read_excel(path, sheet_name=cfg[key]))
        for key in ("sheetScores", "sheetRatings", "sheetPr",
                    "sheetMissing", "sheetRepeated")
    )


def _olsSlope(row, cols, minWeeks: int) -> float:
    vals = row[cols].dropna()
    if len(vals) < minWeeks:
        return np.nan
    x = np.arange(len(vals), dtype=float)
    y = vals.values.astype(float)
    xm, ym = x.mean(), y.mean()
    ssx  = ((x - xm) ** 2).sum()
    ssxy = ((x - xm) * (y - ym)).sum()
    return ssxy / ssx if ssx != 0 else 0.0


def _buildAnalytics(scores, ratings, pr, missing, repeated, weekCols, cfg):
    minW = cfg["minWeeksForSlope"]
    impW = cfg["improvementWindow"]
    lstW = cfg["lateStallWindow"]

    # Cohort stats
    cAvgScore  = scores["Avg Score"].mean();  cSdScore  = scores["Avg Score"].std()
    cAvgRating = ratings["Avg Score"].mean(); cSdRating = ratings["Avg Score"].std()
    cAvgPr     = pr["Avg Score"].mean();      cSdPr     = pr["Avg Score"].std()

    # Ancillary counts
    missingCount = {}
    for _, row in missing.iterrows():
        try:   codes = eval(row["missing_item_codes"])
        except Exception: codes = []
        missingCount[row["student_number"]] = len(codes)
    repeatedCount = repeated.groupby("student_number").size().to_dict()

    # ── Phase split (equal thirds of week list) ───────────────────────────────
    n      = len(weekCols)
    seg    = n // 3
    # first seg weeks, next seg weeks, remainder goes to last (handles non-multiples of 3)
    phaseFirstCols = weekCols[:seg]
    phaseMidCols   = weekCols[seg : 2 * seg]
    phaseLastCols  = weekCols[2 * seg :]

    ratingPhaseFirst = ratings[phaseFirstCols].mean(axis=1)
    ratingPhaseMid   = ratings[phaseMidCols].mean(axis=1)
    ratingPhaseLast  = ratings[phaseLastCols].mean(axis=1)
    ratingPhaseDrop  = ratingPhaseLast - ratingPhaseFirst   # negative = dropped

    # Per-student metrics
    scoreSlope  = scores.apply(lambda r: _olsSlope(r, weekCols, minW), axis=1)
    ratingSlope = ratings.apply(lambda r: _olsSlope(r, weekCols, minW), axis=1)
    prSlope     = pr.apply(lambda r: _olsSlope(r, weekCols, minW), axis=1)

    lowScoreWeeks = scores[weekCols].apply(
        lambda r: int((r.dropna() < cfg["lowScoreThreshold"]).sum()), axis=1)

    first5Score  = scores[weekCols[:impW]].mean(axis=1)
    last5Score   = scores[weekCols[-impW:]].mean(axis=1)
    scoreImprove = last5Score - first5Score

    first5Rating = ratings[weekCols[:impW]].mean(axis=1)
    last5Rating  = ratings[weekCols[-impW:]].mean(axis=1)

    midCols   = weekCols[impW:-lstW] if len(weekCols) > impW + lstW else weekCols
    lateStall = scores[weekCols[-lstW:]].mean(axis=1) - scores[midCols].mean(axis=1)

    df = pd.DataFrame({
        "student_number"      : scores["student_number"].values,
        "student_name"        : scores["student_name"].values,
        "avg_score"           : scores["Avg Score"].values,
        "avg_rating"          : ratings["Avg Score"].values,
        "avg_pr"              : pr["Avg Score"].values,
        "score_slope"         : scoreSlope.values,
        "rating_slope"        : ratingSlope.values,
        "pr_slope"            : prSlope.values,
        "low_score_weeks"     : lowScoreWeeks.values,
        "first5_score"        : first5Score.values,
        "last5_score"         : last5Score.values,
        "score_improvement"   : scoreImprove.values,
        "first5_rating"       : first5Rating.values,
        "last5_rating"        : last5Rating.values,
        "volatility"          : scores[weekCols].std(axis=1).values,
        "late_stall"          : lateStall.values,
        # Phase rating columns (stored for sheet use)
        "rating_phase_first"  : ratingPhaseFirst.values,
        "rating_phase_mid"    : ratingPhaseMid.values,
        "rating_phase_last"   : ratingPhaseLast.values,
        "rating_phase_drop"   : ratingPhaseDrop.values,   # last − first
    })
    df["missing_count"]  = df["student_number"].map(missingCount).fillna(0).astype(int)
    df["repeated_count"] = df["student_number"].map(repeatedCount).fillna(0).astype(int)

    # Flags
    df["flag_low_avg_score"]     = df["avg_score"]  < (cAvgScore  - cfg["sdBelowMeanScore"]  * cSdScore)
    df["flag_declining_score"]   = df["score_slope"] < cfg["decliningSlope"]
    df["flag_no_improvement"]    = df["score_improvement"] < cfg["improvementMinGain"]
    df["flag_low_rating"]        = df["avg_rating"] < (cAvgRating - cfg["sdBelowMeanRating"] * cSdRating)
    df["flag_low_pr"]            = df["avg_pr"]     < (cAvgPr     - cfg["sdBelowMeanPr"]     * cSdPr)
    df["flag_many_low_weeks"]    = df["low_score_weeks"] >= cfg["lowScoreWeekCount"]
    df["flag_missing"]           = df["missing_count"]   >= cfg["missingThreshold"]
    df["flag_late_stall"]        = df["late_stall"] < -cfg["lateStallDrop"]
    # Flag 9: global rating declined from first to last phase by >= threshold
    df["flag_rating_phase_drop"] = df["rating_phase_drop"] < -cfg["ratingPhaseDropMin"]

    flagCols = [c for c in df.columns if c.startswith("flag_")]
    df["risk_score"] = df[flagCols].sum(axis=1)

    def _label(n):
        if n >= cfg["highRiskFlags"]:    return "High Risk"
        if n >= cfg["moderateRiskFlags"]:return "Moderate Risk"
        if n >= cfg["watchFlags"]:       return "Watch"
        return "OK"

    df["risk_label"] = df["risk_score"].apply(_label)
    df = df.sort_values(["risk_score", "avg_score"], ascending=[False, True]).reset_index(drop=True)

    stats = dict(
        cohortAvgScore=cAvgScore, cohortSdScore=cSdScore,
        cohortAvgRating=cAvgRating, cohortSdRating=cSdRating,
        cohortAvgPr=cAvgPr, cohortSdPr=cSdPr,
        flagCols=flagCols,
        # Phase metadata (used by the rating phase sheet)
        phaseFirstCols=phaseFirstCols,
        phaseMidCols=phaseMidCols,
        phaseLastCols=phaseLastCols,
        cohortRatingPhaseFirst=ratingPhaseFirst.mean(),
        cohortRatingPhaseMid=ratingPhaseMid.mean(),
        cohortRatingPhaseLast=ratingPhaseLast.mean(),
    )
    return df, stats


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL – STYLING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fill(hex_):
    return PatternFill("solid", fgColor=hex_)

def _thinBorder():
    s = Side(style="thin", color="D0D0D0")
    return Border(left=s, right=s, top=s, bottom=s)

def _hdr(ws, row, col, val, bg="2C3E50", fg="FFFFFF", sz=10, wrap=False, halign="center"):
    c = ws.cell(row=row, column=col, value=val)
    c.font      = Font(name="Arial", bold=True, color=fg, size=sz)
    c.fill      = _fill(bg)
    c.alignment = Alignment(horizontal=halign, vertical="center", wrap_text=wrap)
    c.border    = _thinBorder()
    return c

def _dat(ws, row, col, val, fmt=None, bold=False, color="2C3E50",
         bg=None, halign="center", wrap=False, sz=9):
    c = ws.cell(row=row, column=col, value=val)
    c.font      = Font(name="Arial", size=sz, bold=bold, color=color)
    c.alignment = Alignment(horizontal=halign, vertical="center", wrap_text=wrap)
    c.border    = _thinBorder()
    if fmt: c.number_format = fmt
    if bg:  c.fill = _fill(bg)
    return c

def _badge(ws, row, col, label):
    badgeBg, _, badgeFg = RISK_COLORS[label]
    c = ws.cell(row=row, column=col, value=label)
    c.font      = Font(name="Arial", size=9, bold=True, color=badgeFg)
    c.fill      = _fill(badgeBg)
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border    = _thinBorder()

def _titleRow(ws, row, c1, c2, text, bg, sz=13, fg="FFFFFF"):
    ws.merge_cells(start_row=row, start_column=c1, end_row=row, end_column=c2)
    c = ws.cell(row=row, column=c1, value=text)
    c.font      = Font(name="Arial", size=sz, bold=True, color=fg)
    c.fill      = _fill(bg)
    c.alignment = Alignment(horizontal="center", vertical="center")

def _sectionBar(ws, row, c1, c2, text, bg, fg="FFFFFF"):
    ws.merge_cells(start_row=row, start_column=c1, end_row=row, end_column=c2)
    c = ws.cell(row=row, column=c1, value=text)
    c.font      = Font(name="Arial", size=10, bold=True, color=fg)
    c.fill      = _fill(bg)
    c.alignment = Alignment(horizontal="left", vertical="center")

def _slopeCell(ws, row, col, slope, bg):
    arrow  = "▼ " if slope < -0.001 else ("▲ " if slope > 0.005 else "→ ")
    sColor = "C0392B" if slope < -0.001 else ("27AE60" if slope > 0.005 else "7F8C8D")
    c = ws.cell(row=row, column=col, value=f"{arrow}{slope:+.4f}")
    c.font      = Font(name="Arial", size=9, color=sColor)
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border    = _thinBorder()
    c.fill      = _fill(bg)

def _improvCell(ws, row, col, improv, bg):
    c = ws.cell(row=row, column=col, value=improv)
    c.number_format = "+0.0%;-0.0%;0.0%"
    c.font      = Font(name="Arial", size=9,
                       color="27AE60" if improv >= 0.02 else ("C0392B" if improv < 0 else "E67E22"))
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border    = _thinBorder()
    c.fill      = _fill(bg)

def _heatCell(ws, row, col, val, fallbackBg):
    if pd.isna(val):
        c = ws.cell(row=row, column=col, value="—")
        c.font      = Font(name="Arial", size=8, color="BBBBBB", italic=True)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = _thinBorder()
        c.fill      = _fill("EEEEEE")
    else:
        if   val < 0.60:  bg = "E74C3C"
        elif val < 0.65:  bg = "F5B7B1"
        elif val < 0.70:  bg = "FAD7A0"
        elif val >= 0.85: bg = "A9DFBF"
        else:             bg = fallbackBg
        c = ws.cell(row=row, column=col, value=val)
        c.number_format = "0%"
        c.font      = Font(name="Arial", size=8, color="FFFFFF" if val < 0.60 else "2C3E50")
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = _thinBorder()
        c.fill      = _fill(bg)


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL – SHEET WRITERS
# ══════════════════════════════════════════════════════════════════════════════

def _sheetMethodology(wb, rr: RiskReport):
    ws = wb.active
    ws.title = "0_Methodology"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 60
    ws.column_dimensions["D"].width = 22

    def mCell(r, c, v, bold=False, sz=10, color="2C3E50", bg=None, italic=False):
        cel = ws.cell(row=r, column=c, value=v)
        cel.font      = Font(name="Arial", size=sz, bold=bold, color=color, italic=italic)
        cel.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        if bg: cel.fill = _fill(bg)
        return cel

    ws.merge_cells("B1:D1")
    ws.cell(row=1, column=2, value=f"{rr.cohort} Student Performance Risk Report").font = \
        Font(name="Arial", size=16, bold=True, color="FFFFFF")
    ws.cell(row=1, column=2).fill      = _fill(C["navy"])
    ws.cell(row=1, column=2).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36
    ws.merge_cells("B2:D2")
    ws.cell(row=2, column=2, value="Methodology & Indicator Guide").font = \
        Font(name="Arial", size=11, color="FFFFFF", italic=True)
    ws.cell(row=2, column=2).fill      = _fill(C["darkSlate"])
    ws.cell(row=2, column=2).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 22

    cfg = rr.cfg; s = rr.stats
    r = 4
    mCell(r, 2, "WHY NOT PERCENTILE ALONE?", bold=True, sz=11, color=C["redH"]); r += 1
    for col, hd in zip([2, 3], ["Rationale", "Detail"]):
        mCell(r, col, hd, bold=True, bg=C["lightGrey"])
    r += 1
    for title, detail in [
        ("Percentile is relative, not absolute",
         "A student in the bottom 25th percentile of a high-performing cohort may still be clinically safe. "
         "Percentile flags shift as the cohort moves, masking genuine improvement."),
        ("No trajectory information",
         "Percentile cannot distinguish a stagnating student from one who is consistently improving."),
        ("Does not capture multi-modal risk",
         "Assessor global ratings and practice readiness are independent evidence streams not reflected by score percentile."),
        ("Sensitive to cohort size and composition",
         "A fixed percentile cut flags a constant fraction of students regardless of absolute performance."),
    ]:
        mCell(r, 2, title, bold=True); mCell(r, 3, detail); r += 1

    r += 1
    mCell(r, 2, "RISK INDICATORS", bold=True, sz=11, color=C["navy"]); r += 1
    for col, hd in zip([2, 3, 4], ["Indicator", "Threshold", "Why it matters"]):
        mCell(r, col, hd, bold=True, bg=C["lightGrey"])
    r += 1
    for name, thresh, why in [
        ("Low Average Score",
         f"Avg Score < {cfg['sdBelowMeanScore']:.0f} SD below mean "
         f"(< {s['cohortAvgScore'] - cfg['sdBelowMeanScore']*s['cohortSdScore']:.1%})",
         "Most direct signal of persistent underperformance."),
        ("Declining Trend",
         f"OLS slope < {cfg['decliningSlope']:+.4f}/week",
         "Competency should consolidate late in year; a falling slope is a concern."),
        (f"No Improvement (first vs last {cfg['improvementWindow']} weeks)",
         f"Last-{cfg['improvementWindow']}-wk avg − first-{cfg['improvementWindow']}-wk avg < +{cfg['improvementMinGain']:.0%}",
         "Clinical training should yield measurable skill acquisition over the semester."),
        ("Low Global Rating",
         f"Avg rating < {cfg['sdBelowMeanRating']:.0f} SD below mean (< {s['cohortAvgRating'] - cfg['sdBelowMeanRating']*s['cohortSdRating']:.2f}/5)",
         "Holistic assessor judgement captures dimensions item checklists miss."),
        ("Low Practice Readiness",
         f"Avg PR < {cfg['sdBelowMeanPr']:.0f} SD below mean (< {s['cohortAvgPr'] - cfg['sdBelowMeanPr']*s['cohortSdPr']:.2f})",
         "Direct assessor view on readiness for independent practice."),
        ("Many Low-Score Weeks",
         f"≥ {cfg['lowScoreWeekCount']} weeks below {cfg['lowScoreThreshold']:.0%}",
         "Frequent poor episodes signal procedural gaps even if the average looks acceptable."),
        ("Excessive Missing",
         f"≥ {cfg['missingThreshold']} weeks absent",
         "Reduces confidence in aggregate score; may signal disengagement."),
        ("Late-Stage Stall",
         f"Last {cfg['lateStallWindow']} weeks > {cfg['lateStallDrop']:.0%} below mid-semester avg",
         "Decline as complexity increases late in semester warrants attention."),
    ]:
        mCell(r, 2, name, bold=True); mCell(r, 3, thresh); mCell(r, 4, why)
        ws.row_dimensions[r].height = 46; r += 1

    r += 1
    mCell(r, 2, "RISK TIER DEFINITIONS", bold=True, sz=11, color=C["navy"]); r += 1
    for label, thresh, bg, desc in [
        ("High Risk",     f"≥ {cfg['highRiskFlags']} flags",     C["bgRed"],    "Immediate academic support referral recommended."),
        ("Moderate Risk", f"≥ {cfg['moderateRiskFlags']} flags", C["bgOrange"], "Monitoring and early outreach warranted."),
        ("Watch",         f"≥ {cfg['watchFlags']} flag",         C["bgYellow"], "Track week-on-week; no action unless it persists."),
        ("OK",            "0 flags",                             C["bgGreen"],  "No elevated concerns."),
    ]:
        c1 = ws.cell(row=r, column=2, value=label)
        c1.font = Font(name="Arial", size=9, bold=True, color="2C3E50")
        c1.fill = _fill(bg); c1.alignment = Alignment(horizontal="center", vertical="center")
        c1.border = _thinBorder()
        mCell(r, 3, thresh, bg=bg); mCell(r, 4, desc, bg=bg)
        ws.row_dimensions[r].height = 30; r += 1


def _sheetDashboard(wb, rr: RiskReport):
    ws = wb.create_sheet("1_Risk_Dashboard")
    ws.sheet_view.showGridLines = False
    for col, w in {"A":2,"B":6,"C":28,"D":12,"E":9,"F":10,"G":10,
                   "H":10,"I":11,"J":12,"K":10,"L":10,"M":30}.items():
        ws.column_dimensions[col].width = w

    _titleRow(ws, 1, 2, 13, f"{rr.cohort} – Student Performance Risk Dashboard", C["navy"], sz=14)
    ws.row_dimensions[1].height = 32

    ws.merge_cells("B2:M2")
    s = rr.stats; df = rr.df
    statsStr = (
        f"Students: {len(df)}  |  Avg Score: {s['cohortAvgScore']:.1%}  |  "
        f"Avg Rating: {s['cohortAvgRating']:.2f}/5  |  "
        f"High: {(df.risk_label=='High Risk').sum()}  "
        f"Mod: {(df.risk_label=='Moderate Risk').sum()}  "
        f"Watch: {(df.risk_label=='Watch').sum()}  "
        f"OK: {(df.risk_label=='OK').sum()}"
    )
    sc = ws.cell(row=2, column=2, value=statsStr)
    sc.font = Font(name="Arial", size=8, color="FFFFFF", italic=True)
    sc.fill = _fill(C["tabHdr"])
    sc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18

    for ci, h in enumerate(["#","Student Name","Risk Tier","Flags\nActive","Avg\nScore",
                             "Avg\nRating","Avg\nReadiness","Score\nTrend","Early→Late\nChange",
                             "Low\nWeeks","Missing\nWeeks","Flags Triggered"], start=2):
        _hdr(ws, 3, ci, h, bg=C["darkSlate"], wrap=True)
    ws.row_dimensions[3].height = 30
    ws.freeze_panes = "C4"

    flagCols = s["flagCols"]
    for i, (_, row) in enumerate(df.iterrows()):
        r = 4 + i
        alt = "F5F5F5" if i % 2 == 0 else C["white"]
        _dat(ws, r, 2, i+1, halign="center", bg=alt)
        _dat(ws, r, 3, row["student_name"], halign="left", bg=alt, bold=(row["risk_label"]=="High Risk"))
        _badge(ws, r, 4, row["risk_label"])
        _dat(ws, r, 5, row["risk_score"], fmt="0", bg=alt, bold=(row["risk_score"] >= 4))
        _dat(ws, r, 6, row["avg_score"],  fmt="0.0%", bg=alt)
        _dat(ws, r, 7, row["avg_rating"], fmt="0.00", bg=alt)
        _dat(ws, r, 8, row["avg_pr"],     fmt="0.00", bg=alt)
        _slopeCell(ws, r, 9, row["score_slope"], alt)
        _improvCell(ws, r, 10, row["score_improvement"], alt)
        _dat(ws, r, 11, row["low_score_weeks"], fmt="0", bg=alt,
             color="C0392B" if row["low_score_weeks"] >= 5 else "2C3E50")
        _dat(ws, r, 12, row["missing_count"], fmt="0", bg=alt,
             color="C0392B" if row["missing_count"] >= 2 else "2C3E50")
        triggered = [FLAG_LABELS[f] for f in flagCols if row[f]]
        fl = ws.cell(row=r, column=13, value="; ".join(triggered) if triggered else "—")
        fl.font = Font(name="Arial", size=8, color="2C3E50")
        fl.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        fl.border = _thinBorder(); fl.fill = _fill(alt)
        ws.row_dimensions[r].height = 16


def _sheetDetail(wb, rr: RiskReport):
    ws = wb.create_sheet("2_High_Risk_Detail")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 26
    for col, w in {"C":9,"D":9,"E":9,"F":10,"G":10}.items():
        ws.column_dimensions[col].width = w
    for i in range(len(rr.weekCols)):
        ws.column_dimensions[get_column_letter(8+i)].width = 7
    eoc = 8 + len(rr.weekCols)
    ws.column_dimensions[get_column_letter(eoc)].width   = 8
    ws.column_dimensions[get_column_letter(eoc+1)].width = 8
    ws.column_dimensions[get_column_letter(eoc+2)].width = 32

    _titleRow(ws, 1, 2, eoc+2, f"{rr.cohort} – High & Moderate Risk Detail", C["navy"])
    ws.row_dimensions[1].height = 28

    weekScoresDf = rr.scores[["student_number"] + rr.weekCols].copy()
    flagCols     = rr.stats["flagCols"]
    s            = rr.stats

    def writeBlock(students, sectionTitle, bgTitle, startRow):
        _sectionBar(ws, startRow, 2, eoc+2, sectionTitle, bgTitle)
        ws.row_dimensions[startRow].height = 20
        startRow += 1

        hdrs = (["Student Name","Avg Score","Avg Rating","Avg PR","Score Trend","Early→Late"] +
                [f"Wk{i+1}" for i in range(len(rr.weekCols))] + ["Low\nWks","Missing","Flags Triggered"])
        for ci, h in enumerate(hdrs, start=2):
            _hdr(ws, startRow, ci, h, bg=C["tabHdr"], wrap=True)
        ws.row_dimensions[startRow].height = 28
        startRow += 1

        # Cohort reference row
        ws.cell(row=startRow, column=2, value="─── Cohort Average ───").font = \
            Font(name="Arial", size=8, italic=True, color="7F8C8D")
        ws.cell(row=startRow, column=2).alignment = Alignment(horizontal="left")
        _dat(ws, startRow, 3, s["cohortAvgScore"],  fmt="0.0%", bg="F0F0F0", color="7F8C8D")
        _dat(ws, startRow, 4, s["cohortAvgRating"], fmt="0.00", bg="F0F0F0", color="7F8C8D")
        _dat(ws, startRow, 5, s["cohortAvgPr"],     fmt="0.00", bg="F0F0F0", color="7F8C8D")
        wkAvgs = rr.scores[rr.weekCols].mean()
        for ci, wk in enumerate(rr.weekCols):
            _dat(ws, startRow, 8+ci, wkAvgs[wk], fmt="0%", bg="F0F0F0", color="7F8C8D")
        startRow += 1

        altA = "FDF3F2" if bgTitle == C["redH"] else "FEF5EC"
        for si, (_, srow) in enumerate(students.iterrows()):
            r = startRow + si
            rowBg = altA if si % 2 == 0 else C["white"]
            _dat(ws, r, 2, srow["student_name"], halign="left", bold=True, bg=rowBg)
            _dat(ws, r, 3, srow["avg_score"],   fmt="0.0%", bg=rowBg)
            _dat(ws, r, 4, srow["avg_rating"],  fmt="0.00", bg=rowBg)
            _dat(ws, r, 5, srow["avg_pr"],      fmt="0.00", bg=rowBg)
            _slopeCell(ws, r, 6, srow["score_slope"], rowBg)
            _improvCell(ws, r, 7, srow["score_improvement"], rowBg)

            rs = weekScoresDf[weekScoresDf["student_number"] == srow["student_number"]].iloc[0]
            for ci, wk in enumerate(rr.weekCols):
                val = rs[wk]
                if pd.isna(val):
                    c = ws.cell(row=r, column=8+ci, value="—")
                    c.font = Font(name="Arial", size=8, color="BBBBBB", italic=True)
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    c.border = _thinBorder(); c.fill = _fill("F5F5F5")
                else:
                    if val < 0.60:   bg = "F5B7B1"
                    elif val < 0.65: bg = "FAD7A0"
                    elif val < 0.70: bg = "FDEBD0"
                    elif val >= 0.85:bg = "A9DFBF"
                    else:            bg = rowBg
                    _dat(ws, r, 8+ci, val, fmt="0%", bg=bg)

            _dat(ws, r, eoc,   srow["low_score_weeks"], fmt="0", bg=rowBg,
                 color="C0392B" if srow["low_score_weeks"] >= 5 else "2C3E50")
            _dat(ws, r, eoc+1, srow["missing_count"],   fmt="0", bg=rowBg,
                 color="C0392B" if srow["missing_count"] >= 2 else "2C3E50")
            triggered = [FLAG_LABELS[f] for f in flagCols if srow[f]]
            fl = ws.cell(row=r, column=eoc+2, value="; ".join(triggered))
            fl.font = Font(name="Arial", size=8,
                           color="C0392B" if bgTitle == C["redH"] else "E67E22")
            fl.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            fl.border = _thinBorder(); fl.fill = _fill(rowBg)
            ws.row_dimensions[r].height = 16

        return startRow + len(students) + 2

    df = rr.df
    r  = 3
    r  = writeBlock(df[df.risk_label == "High Risk"],
                    f"HIGH RISK  ({(df.risk_label=='High Risk').sum()} students)", C["redH"], r)
    r  = writeBlock(df[df.risk_label == "Moderate Risk"],
                    f"MODERATE RISK  ({(df.risk_label=='Moderate Risk').sum()} students)", C["orangeM"], r)
    ws.freeze_panes = "C4"


def _sheetNoImprovement(wb, rr: RiskReport):
    ws = wb.create_sheet("3_No_Improvement")
    ws.sheet_view.showGridLines = False
    for col, w in {"A":2,"B":5,"C":28,"D":11,"E":11,"F":11,"G":11,"H":11,"I":16}.items():
        ws.column_dimensions[col].width = w

    _titleRow(ws, 1, 2, 9, f"{rr.cohort} – Students Showing No Meaningful Improvement", C["navy"])
    ws.row_dimensions[1].height = 28

    cfg = rr.cfg
    ws.merge_cells("B2:I2")
    note = ws.cell(row=2, column=2,
        value=f"Criterion: last-{cfg['improvementWindow']}-wk avg − first-{cfg['improvementWindow']}-wk avg "
              f"< +{cfg['improvementMinGain']:.0%}. Negative = lower late semester than early.")
    note.font = Font(name="Arial", size=8, color="7F8C8D", italic=True)
    note.fill = _fill(C["lightGrey"])
    note.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 26

    for ci, h in enumerate(["#","Student Name",f"First {cfg['improvementWindow']} Wk\nAvg",
                             f"Last {cfg['improvementWindow']} Wk\nAvg",
                             "Change","Score\nSlope","Overall\nAvg","Risk Tier"], start=2):
        _hdr(ws, 3, ci, h, bg=C["darkSlate"], wrap=True)
    ws.row_dimensions[3].height = 28
    ws.freeze_panes = "C4"

    subset = rr.df[rr.df.score_improvement < cfg["improvementMinGain"]].sort_values("score_improvement")
    for i, (_, row) in enumerate(subset.iterrows()):
        r = 4 + i
        alt   = "FEF9F4" if i % 2 == 0 else C["white"]
        improv = row["score_improvement"]
        impBg  = "FDECEA" if improv < 0 else "FEF5EC" if improv < 0.01 else alt
        _dat(ws, r, 2, i+1, halign="center", bg=alt)
        _dat(ws, r, 3, row["student_name"], halign="left", bg=alt)
        _dat(ws, r, 4, row["first5_score"], fmt="0.0%", bg=alt)
        _dat(ws, r, 5, row["last5_score"],  fmt="0.0%", bg=alt)
        _improvCell(ws, r, 6, improv, impBg)
        _dat(ws, r, 7, row["score_slope"], fmt="0.0000", bg=alt)
        _dat(ws, r, 8, row["avg_score"],   fmt="0.0%",   bg=alt)
        _badge(ws, r, 9, row["risk_label"])
        ws.row_dimensions[r].height = 15


def _sheetDeclining(wb, rr: RiskReport):
    ws = wb.create_sheet("4_Declining_Trend")
    ws.sheet_view.showGridLines = False
    for col, w in {"A":2,"B":5,"C":28,"D":11,"E":11,"F":11,"G":11,"H":14}.items():
        ws.column_dimensions[col].width = w

    _titleRow(ws, 1, 2, 8, f"{rr.cohort} – Declining or Stalling Trajectory", C["navy"])
    ws.row_dimensions[1].height = 28

    declining = rr.df[rr.df.score_slope < 0].sort_values("score_slope")
    _sectionBar(ws, 2, 2, 8,
                f"NEGATIVE TREND (OLS slope < 0) — {len(declining)} students", C["redH"])
    ws.row_dimensions[2].height = 20
    for ci, h in enumerate(["#","Student Name","Score Slope\n(per week)",
                             "First 5 Wk","Last 5 Wk","Change","Risk Tier"], start=2):
        _hdr(ws, 3, ci, h, bg=C["tabHdr"], wrap=True)
    ws.row_dimensions[3].height = 26
    ws.freeze_panes = "C4"

    for i, (_, row) in enumerate(declining.iterrows()):
        r = 4 + i; alt = "FDF3F2" if i % 2 == 0 else C["white"]
        _dat(ws, r, 2, i+1, halign="center", bg=alt)
        _dat(ws, r, 3, row["student_name"], halign="left", bg=alt)
        c = ws.cell(row=r, column=4, value=row["score_slope"])
        c.number_format = "0.0000"
        c.font = Font(name="Arial", size=9, bold=True, color="C0392B")
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = _thinBorder(); c.fill = _fill(alt)
        _dat(ws, r, 5, row["first5_score"],  fmt="0.0%", bg=alt)
        _dat(ws, r, 6, row["last5_score"],   fmt="0.0%", bg=alt)
        _improvCell(ws, r, 7, row["score_improvement"], alt)
        _badge(ws, r, 8, row["risk_label"])
        ws.row_dimensions[r].height = 15

    cfg     = rr.cfg
    stalled = rr.df[rr.df.flag_late_stall].sort_values("late_stall")
    stStart = 4 + len(declining) + 2
    _sectionBar(ws, stStart, 2, 8,
                f"LATE-STAGE STALL (last {cfg['lateStallWindow']} wks > {cfg['lateStallDrop']:.0%} "
                f"below mid-sem) — {len(stalled)} students", C["orangeM"])
    ws.row_dimensions[stStart].height = 20
    for ci, h in enumerate(["#","Student Name","Mid-Sem Avg","Last 3 Wk Avg",
                             "Drop","Avg Score","Risk Tier"], start=2):
        _hdr(ws, stStart+1, ci, h, bg=C["tabHdr"], wrap=True)
    ws.row_dimensions[stStart+1].height = 26

    impW = cfg["improvementWindow"]; lstW = cfg["lateStallWindow"]
    midCols = rr.weekCols[impW:-lstW] if len(rr.weekCols) > impW + lstW else rr.weekCols
    for i, (_, row) in enumerate(stalled.iterrows()):
        r2 = stStart + 2 + i; alt = "FEF5EC" if i % 2 == 0 else C["white"]
        midAvg   = rr.scores.loc[rr.scores.student_number == row.student_number, midCols].mean(axis=1).values[0]
        last3Avg = rr.scores.loc[rr.scores.student_number == row.student_number, rr.weekCols[-lstW:]].mean(axis=1).values[0]
        drop     = last3Avg - midAvg
        _dat(ws, r2, 2, i+1, halign="center", bg=alt)
        _dat(ws, r2, 3, row["student_name"], halign="left", bg=alt)
        _dat(ws, r2, 4, midAvg,   fmt="0.0%", bg=alt)
        _dat(ws, r2, 5, last3Avg, fmt="0.0%", bg=alt)
        c = ws.cell(row=r2, column=6, value=drop)
        c.number_format = "+0.0%;-0.0%;0.0%"
        c.font = Font(name="Arial", size=9, bold=True, color="C0392B")
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = _thinBorder(); c.fill = _fill(alt)
        _dat(ws, r2, 7, row["avg_score"], fmt="0.0%", bg=alt)
        _badge(ws, r2, 8, row["risk_label"])
        ws.row_dimensions[r2].height = 15


def _sheetHeatmap(wb, rr: RiskReport):
    ws = wb.create_sheet("5_Score_Heatmap")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 10
    for i in range(len(rr.weekCols)):
        ws.column_dimensions[get_column_letter(4+i)].width = 7
    eoc = 4 + len(rr.weekCols)
    ws.column_dimensions[get_column_letter(eoc)].width   = 10
    ws.column_dimensions[get_column_letter(eoc+1)].width = 11

    _titleRow(ws, 1, 2, eoc+1,
              f"{rr.cohort} – Full Cohort Score Heatmap ({len(rr.weekCols)} Weeks)", C["navy"])
    ws.row_dimensions[1].height = 28

    ws.merge_cells(f"B2:{get_column_letter(eoc+1)}2")
    leg = ws.cell(row=2, column=2,
        value="■ <60% (red)  ■ 60–65% (light red)  ■ 65–70% (orange)  "
              "■ 70–85% (neutral)  ■ ≥85% (green)  |  Sorted by Risk Tier then Avg Score")
    leg.font = Font(name="Arial", size=8, color="2C3E50", italic=True)
    leg.fill = _fill(C["lightGrey"])
    leg.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 16

    for ci, h in enumerate(["Student Name","Risk Tier"] +
                            [f"Wk{i+1}" for i in range(len(rr.weekCols))] +
                            ["Avg\nScore","Flags\nActive"], start=2):
        _hdr(ws, 3, ci, h, bg=C["darkSlate"], wrap=True)
    ws.row_dimensions[3].height = 26
    ws.freeze_panes = "C4"

    weekScoresDf = rr.scores[["student_number"] + rr.weekCols].copy()
    for i, (_, row) in enumerate(rr.df.iterrows()):
        r = 4 + i; alt = "F5F5F5" if i % 2 == 0 else C["white"]
        _dat(ws, r, 2, row["student_name"], halign="left", bg=alt)
        _badge(ws, r, 3, row["risk_label"])
        rs = weekScoresDf[weekScoresDf.student_number == row.student_number].iloc[0]
        for ci, wk in enumerate(rr.weekCols):
            _heatCell(ws, r, 4+ci, rs[wk], alt)
        _dat(ws, r, eoc,   row["avg_score"],  fmt="0.0%", bg=alt, bold=True)
        _dat(ws, r, eoc+1, row["risk_score"], fmt="0",    bg=alt,
             color="C0392B" if row["risk_score"] >= 4 else "E67E22" if row["risk_score"] >= 2 else "2C3E50")
        ws.row_dimensions[r].height = 14


def _sheetRatingPhase(wb, rr: RiskReport):
    """
    Sheet 6 – Global Rating Trajectory by Phase.

    Splits the semester into three equal thirds (first / mid / last 5 weeks for a
    15-week cohort, or n//3 weeks each for any other length).  For every student
    shows the phase-average rating, the change between phases, a visual
    trend indicator, and the flag status.  Cohort averages per phase are shown
    as a reference row.  Students are sorted by last-phase rating ascending so
    the most concerning cases appear at the top.
    """
    ws  = wb.create_sheet("6_Rating_Phase_Trajectory")
    ws.sheet_view.showGridLines = False

    s   = rr.stats
    cfg = rr.cfg
    df  = rr.df.copy()

    # Label the phase column ranges for the header
    pF  = s["phaseFirstCols"]
    pM  = s["phaseMidCols"]
    pL  = s["phaseLastCols"]

    def phaseLabel(cols):
        # Try to extract a compact range like "Wk1–5" from the column names
        idxFirst = rr.weekCols.index(cols[0])  + 1
        idxLast  = rr.weekCols.index(cols[-1]) + 1
        return f"Wks {idxFirst}–{idxLast}"

    labelF = phaseLabel(pF)
    labelM = phaseLabel(pM)
    labelL = phaseLabel(pL)

    # Week-level rating columns for the per-week detail sub-section
    weekRatingsDf = rr.ratings[["student_number"] + rr.weekCols].copy()

    # Column layout
    # B: name  C: risk  D: phase1  E: phase2  F: phase3
    # G: Δ(mid−first)  H: Δ(last−mid)  I: Δ(last−first)  J: trend arrow
    # K: flagged?  L…: per-week ratings
    COL_NAME   = 2
    COL_RISK   = 3
    COL_PF     = 4
    COL_PM     = 5
    COL_PL     = 6
    COL_D1     = 7   # mid − first
    COL_D2     = 8   # last − mid
    COL_DTOTAL = 9   # last − first
    COL_TREND  = 10
    COL_FLAG   = 11
    COL_WK0    = 12  # weekly rating columns start here

    totalCols = COL_WK0 + len(rr.weekCols) - 1

    ws.column_dimensions["A"].width = 2
    ws.column_dimensions[get_column_letter(COL_NAME)].width  = 26
    ws.column_dimensions[get_column_letter(COL_RISK)].width  = 12
    ws.column_dimensions[get_column_letter(COL_PF)].width    = 10
    ws.column_dimensions[get_column_letter(COL_PM)].width    = 10
    ws.column_dimensions[get_column_letter(COL_PL)].width    = 10
    ws.column_dimensions[get_column_letter(COL_D1)].width    = 10
    ws.column_dimensions[get_column_letter(COL_D2)].width    = 10
    ws.column_dimensions[get_column_letter(COL_DTOTAL)].width= 10
    ws.column_dimensions[get_column_letter(COL_TREND)].width = 9
    ws.column_dimensions[get_column_letter(COL_FLAG)].width  = 8
    for i in range(len(rr.weekCols)):
        ws.column_dimensions[get_column_letter(COL_WK0 + i)].width = 6

    # ── Title ────────────────────────────────────────────────────────────────
    _titleRow(ws, 1, COL_NAME, totalCols,
              f"{rr.cohort} – Global Rating Trajectory by Semester Phase", C["navy"])
    ws.row_dimensions[1].height = 28

    # ── Subtitle / legend ────────────────────────────────────────────────────
    ws.merge_cells(start_row=2, start_column=COL_NAME,
                   end_row=2,   end_column=totalCols)
    leg = ws.cell(row=2, column=COL_NAME,
        value=(
            f"Semester split into three equal phases: "
            f"First ({labelF}), Mid ({labelM}), Last ({labelL}).  "
            f"Ratings on 1–5 scale.  "
            f"Flag triggered when Last-phase avg drops ≥ {cfg['ratingPhaseDropMin']:.1f} pts below First-phase avg.  "
            f"▼ = declining  ▶ = flat  ▲ = improving  "
            f"■ Wk cells: ≤2 (red)  3 (amber)  ≥4 (green)."
        ))
    leg.font = Font(name="Arial", size=8, color="2C3E50", italic=True)
    leg.fill = _fill(C["lightGrey"])
    leg.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 24

    # ── Phase divider labels (row 3) ─────────────────────────────────────────
    # Spans over the weekly columns to show which weeks belong to which phase
    ws.merge_cells(start_row=3, start_column=COL_NAME,
                   end_row=3,   end_column=COL_FLAG)
    ws.cell(row=3, column=COL_NAME)  # blank spacer

    def phaseSpan(cols, label, bg):
        startC = COL_WK0 + rr.weekCols.index(cols[0])
        endC   = COL_WK0 + rr.weekCols.index(cols[-1])
        ws.merge_cells(start_row=3, start_column=startC, end_row=3, end_column=endC)
        c = ws.cell(row=3, column=startC, value=label)
        c.font      = Font(name="Arial", size=9, bold=True, color="FFFFFF")
        c.fill      = _fill(bg)
        c.alignment = Alignment(horizontal="center", vertical="center")

    phaseSpan(pF, f"◀ First Phase ({labelF}) ▶", C["tabHdr"])
    phaseSpan(pM, f"◀ Mid Phase ({labelM}) ▶",   "546E7A")
    phaseSpan(pL, f"◀ Last Phase ({labelL}) ▶",  C["darkSlate"])
    ws.row_dimensions[3].height = 18

    # ── Column headers (row 4) ───────────────────────────────────────────────
    hdrs = [
        ("Student Name",      COL_NAME,   C["darkSlate"]),
        ("Risk Tier",         COL_RISK,   C["darkSlate"]),
        (f"First\n{labelF}",  COL_PF,     C["tabHdr"]),
        (f"Mid\n{labelM}",    COL_PM,     "546E7A"),
        (f"Last\n{labelL}",   COL_PL,     C["darkSlate"]),
        ("Mid−First\nΔ",      COL_D1,     "37474F"),
        ("Last−Mid\nΔ",       COL_D2,     "37474F"),
        ("Total\nChange",     COL_DTOTAL, "37474F"),
        ("Trend",             COL_TREND,  "37474F"),
        ("Flagged?",          COL_FLAG,   C["redH"]),
    ]
    for text, col, bg in hdrs:
        _hdr(ws, 4, col, text, bg=bg, wrap=True)
    # Per-week headers
    for i, wk in enumerate(rr.weekCols):
        phase_bg = (C["tabHdr"] if wk in pF else "546E7A" if wk in pM else C["darkSlate"])
        _hdr(ws, 4, COL_WK0 + i, f"W{i+1}", bg=phase_bg, sz=8)
    ws.row_dimensions[4].height = 30
    ws.freeze_panes = "C5"

    # ── Cohort reference row ─────────────────────────────────────────────────
    REF_ROW = 5
    ws.cell(row=REF_ROW, column=COL_NAME, value="─── Cohort Average ───").font = \
        Font(name="Arial", size=8, italic=True, color="7F8C8D")
    ws.cell(row=REF_ROW, column=COL_NAME).alignment = Alignment(horizontal="left")
    _dat(ws, REF_ROW, COL_PF, s["cohortRatingPhaseFirst"], fmt="0.00", bg="F0F0F0", color="7F8C8D")
    _dat(ws, REF_ROW, COL_PM, s["cohortRatingPhaseMid"],   fmt="0.00", bg="F0F0F0", color="7F8C8D")
    _dat(ws, REF_ROW, COL_PL, s["cohortRatingPhaseLast"],  fmt="0.00", bg="F0F0F0", color="7F8C8D")
    cohortD1     = s["cohortRatingPhaseMid"]   - s["cohortRatingPhaseFirst"]
    cohortD2     = s["cohortRatingPhaseLast"]  - s["cohortRatingPhaseMid"]
    cohortDtotal = s["cohortRatingPhaseLast"]  - s["cohortRatingPhaseFirst"]
    _dat(ws, REF_ROW, COL_D1,     cohortD1,     fmt="+0.00;-0.00;0.00", bg="F0F0F0", color="7F8C8D")
    _dat(ws, REF_ROW, COL_D2,     cohortD2,     fmt="+0.00;-0.00;0.00", bg="F0F0F0", color="7F8C8D")
    _dat(ws, REF_ROW, COL_DTOTAL, cohortDtotal, fmt="+0.00;-0.00;0.00", bg="F0F0F0", color="7F8C8D")
    # Cohort weekly averages
    wkAvgs = rr.ratings[rr.weekCols].mean()
    for i, wk in enumerate(rr.weekCols):
        _dat(ws, REF_ROW, COL_WK0 + i, wkAvgs[wk], fmt="0.0", bg="F0F0F0", color="7F8C8D", sz=8)
    ws.row_dimensions[REF_ROW].height = 15

    # ── Student rows – sorted by last-phase rating ascending ─────────────────
    dfSorted = df.sort_values("rating_phase_last", ascending=True).reset_index(drop=True)

    for i, (_, row) in enumerate(dfSorted.iterrows()):
        r      = 6 + i
        alt    = "F9F9F9" if i % 2 == 0 else C["white"]
        flagged = row["flag_rating_phase_drop"]

        # Highlight the whole row subtly if flagged
        rowHighlight = "FEF0EE" if flagged else alt

        _dat(ws, r, COL_NAME, row["student_name"], halign="left",
             bg=rowHighlight, bold=flagged)
        _badge(ws, r, COL_RISK, row["risk_label"])

        # Phase averages — colour-coded by absolute rating level (1–5 scale)
        def ratingBg(val):
            if pd.isna(val): return "EEEEEE"
            if val <= 2.0:   return "F5B7B1"   # red — consistently low
            if val <= 2.9:   return "FAD7A0"   # amber
            if val >= 4.0:   return "A9DFBF"   # green
            return alt

        for col, key in [(COL_PF, "rating_phase_first"),
                         (COL_PM, "rating_phase_mid"),
                         (COL_PL, "rating_phase_last")]:
            val = row[key]
            c   = ws.cell(row=r, column=col, value=round(val, 2) if not pd.isna(val) else None)
            c.number_format = "0.00"
            c.font      = Font(name="Arial", size=9, bold=(col == COL_PL),
                               color="C0392B" if (not pd.isna(val) and val <= 2.0) else "2C3E50")
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border    = _thinBorder()
            c.fill      = _fill(ratingBg(val))

        # Delta cells
        d1     = row["rating_phase_mid"]   - row["rating_phase_first"]
        d2     = row["rating_phase_last"]  - row["rating_phase_mid"]
        dtotal = row["rating_phase_drop"]  # last − first (precomputed)

        for col, val in [(COL_D1, d1), (COL_D2, d2), (COL_DTOTAL, dtotal)]:
            if pd.isna(val):
                _dat(ws, r, col, None, bg=alt)
                continue
            c = ws.cell(row=r, column=col, value=round(val, 2))
            c.number_format = "+0.00;-0.00;0.00"
            dColor = "27AE60" if val > 0.1 else ("C0392B" if val < -0.1 else "7F8C8D")
            c.font      = Font(name="Arial", size=9, bold=(col == COL_DTOTAL), color=dColor)
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border    = _thinBorder()
            c.fill      = _fill(rowHighlight)

        # Trend arrow — based on the shape first→mid→last
        rising   = d1 > 0.1 and d2 > 0.1
        falling  = d1 < -0.1 and d2 < -0.1
        recovery = d1 < -0.1 and d2 > 0.2
        dip      = d1 > 0.1  and d2 < -0.2
        if   rising:  trendStr = "▲ Rising";   tColor = "27AE60"
        elif falling: trendStr = "▼ Falling";  tColor = "C0392B"
        elif recovery:trendStr = "↗ Recovery"; tColor = "2980B9"
        elif dip:     trendStr = "↘ Late dip"; tColor = "E67E22"
        else:         trendStr = "▶ Stable";   tColor = "7F8C8D"

        tc = ws.cell(row=r, column=COL_TREND, value=trendStr)
        tc.font      = Font(name="Arial", size=8, bold=True, color=tColor)
        tc.alignment = Alignment(horizontal="center", vertical="center")
        tc.border    = _thinBorder()
        tc.fill      = _fill(rowHighlight)

        # Flagged indicator
        fc = ws.cell(row=r, column=COL_FLAG, value="⚑ Yes" if flagged else "—")
        fc.font      = Font(name="Arial", size=9, bold=flagged,
                            color="C0392B" if flagged else "AAAAAA")
        fc.alignment = Alignment(horizontal="center", vertical="center")
        fc.border    = _thinBorder()
        fc.fill      = _fill("FDECEA" if flagged else rowHighlight)

        # Per-week rating cells (colour-coded 1–5)
        rs = weekRatingsDf[weekRatingsDf.student_number == row.student_number].iloc[0]
        for ci, wk in enumerate(rr.weekCols):
            val  = rs[wk]
            col  = COL_WK0 + ci
            if pd.isna(val):
                c = ws.cell(row=r, column=col, value="—")
                c.font      = Font(name="Arial", size=8, color="BBBBBB", italic=True)
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border    = _thinBorder()
                c.fill      = _fill("EEEEEE")
            else:
                if   val <= 2:  wkBg = "F5B7B1"; fColor = "2C3E50"
                elif val <= 2.9:wkBg = "FAD7A0"; fColor = "2C3E50"
                elif val >= 4:  wkBg = "A9DFBF"; fColor = "2C3E50"
                else:           wkBg = rowHighlight; fColor = "2C3E50"
                c = ws.cell(row=r, column=col, value=val)
                c.number_format = "0.0"
                c.font      = Font(name="Arial", size=8, color=fColor)
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border    = _thinBorder()
                c.fill      = _fill(wkBg)

        ws.row_dimensions[r].height = 15


# ══════════════════════════════════════════════════════════════════════════════
# WORKBOOK BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _buildWorkbook(rr: RiskReport) -> Workbook:
    wb = Workbook()
    _sheetMethodology(wb, rr)
    _sheetDashboard(wb, rr)
    _sheetDetail(wb, rr)
    _sheetNoImprovement(wb, rr)
    _sheetDeclining(wb, rr)
    _sheetHeatmap(wb, rr)
    _sheetRatingPhase(wb, rr)
    return wb
