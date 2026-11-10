"""
dash_app_export.py — Excel exports for dash_app.py (same workbook design for every exam).

Summary export : Records (+ Ignored Assessors)
Detailed export:
  Overview        KPIs, scoring method per checklist, section maxima/weights, GR scales, colour legend, sheet guide
  Records         one row per form: identity, status, GR, section %, total, overall, CC, overrides, comments
  Follow-up       forms needing action, with reasons (CC, incomplete, missing section, in progress, low GR, below cut)
  Students        per student: forms, mean/min %, GR, CC, below-cut count, review flag
  Scores …        per checklist: MC grid (points, colour by fraction) + section score/% + summary + comments
  Std Setting …   per checklist: BLR + BGM cut scores, viability tests, grade means, per-section cuts, charts
  Sections …      per checklist: section descriptives, α, r with GR/overall, mean % by GR, intercorrelations
  Items …         per checklist: difficulty, discrimination, α-if-deleted, D27, 2PL-lite, importance, response mix
  Assessors       leniency Δ, GR-adjusted Δ, GR mix, fail-level rate, CC rate, completion; chart
  Roster          present / missing / off-roster / duplicates vs studentEmailList.csv
  Ignored Assessors  forms excluded from every analysis (from <exam>_overrides.json)
"""
import math, re, csv, tempfile
from collections import OrderedDict, defaultdict
from datetime import datetime

import numpy as np
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.comments import Comment as XlComment
from openpyxl.chart import ScatterChart, BarChart, Reference, Series
from openpyxl.chart.trendline import Trendline
from openpyxl.chart.marker import Marker, DataPoint
from openpyxl.chart.label import DataLabelList
from openpyxl.worksheet.table import Table as XlTable, TableStyleInfo

import dash_app_config as cfg
import dash_app_core as core

try:                                                   # optional: exact t-distribution p-values / CIs
    from scipy import stats as spStats
except Exception:
    spStats = None

# ══ Style helpers ═══════════════════════════════════════════════════════════
THIN, THICK = Side(style="thin", color="E2E8F0"), Side(style="medium", color="94A3B8")
FRAC_FILLS = [(0.99, "BBFFD9"), (0.70, "BFDBFE"), (0.45, "A5F3FC"), (1e-9, "FEF08A"), (-1, "FECACA")]
GR_FILL = {5: "BBFFD9", 4: "D1FAE5", 3: "FEF9C3", 2: "FED7AA", 1: "FECACA"}
FLAG_FILL = {"PASS": "BBFFD9", "WARN": "FEF08A", "FAIL": "FECACA", "Good": "D1FAE5", "Review": "FEF9C3",
             "Poor": "FECACA", "Too easy": "FED7AA", "Too hard": "FED7AA", "No variance": "E2E8F0",
             "Lenient": "FED7AA", "Harsh": "FECACA", "Typical": "D1FAE5", "Yes": "FECACA"}


def xFill(h):  return PatternFill(fill_type="solid", fgColor=h)
def xFont(bold=False, color="1E293B", size=9): return Font(bold=bold, color=color, name="Calibri", size=size)
def xAlign(h="left", v="center", wrap=False): return Alignment(horizontal=h, vertical=v, wrap_text=wrap)
def xBorder(l=False, r=False): return Border(left=THICK if l else THIN, right=THICK if r else THIN, top=THIN, bottom=THIN)


def fracFill(v, m):
    if v is None or v == "" or not m:
        return None
    f = v / m
    return next(h for t, h in FRAC_FILLS if f >= t)


def rhoColour(rho):
    """Bar colour for an item-vs-GR correlation: green ≥ .30, amber .20–.30, red < .20 / NaN."""
    return "1D9E75" if rho == rho and rho >= 0.30 else ("EF9F27" if rho == rho and rho >= 0.20 else "E24B4A")


def rhoFill(rho):
    """Light cell fill for ρ with GR (None when NaN)."""
    if rho != rho:
        return None
    return "C6EFCE" if rho >= 0.30 else ("FFEB9C" if rho >= 0.20 else "FFC7CE")


def pctFill(p):
    return fracFill(p, 100) if isinstance(p, (int, float)) and p >= 0 else None


def rnd(v, d=1):
    return None if v is None or (isinstance(v, float) and v != v) else round(float(v), d)


def sheetName(wb, base: str) -> str:
    """Excel-safe unique sheet name (≤31 chars)."""
    s = re.sub(r"[\[\]:*?/\\]", "-", base)[:31]
    n, out = 1, s
    while out in wb.sheetnames:
        n += 1; out = f"{s[:28]}~{n}"
    return out


class SheetWriter:
    """Row cursor + common blocks (title, section bar, header row, key/value, table)."""

    def __init__(self, ws, width=6):
        self.ws, self.r, self.width = ws, 1, width

    def title(self, text, sub=""):
        c = self.ws.cell(self.r, 1, text); c.font = xFont(True, "FFFFFF", 14)
        for cc in range(1, self.width + 1):
            self.ws.cell(self.r, cc).fill = xFill("010D44")
        self.ws.row_dimensions[self.r].height = 26; self.r += 1
        if sub:
            self.ws.cell(self.r, 1, sub).font = xFont(size=9, color="64748B"); self.r += 1
        self.r += 1

    def bar(self, text, color="4F5FB2"):
        c = self.ws.cell(self.r, 1, text); c.font = xFont(True, "FFFFFF", 11)
        for cc in range(1, self.width + 1):
            self.ws.cell(self.r, cc).fill = xFill(color)
        self.r += 1

    def para(self, text, size=9, color="334155"):
        c = self.ws.cell(self.r, 1, text); c.font = xFont(size=size, color=color); c.alignment = xAlign(v="top", wrap=True)
        self.ws.merge_cells(start_row=self.r, start_column=1, end_row=self.r, end_column=self.width)
        self.ws.row_dimensions[self.r].height = 14 * max(1, math.ceil(len(text) / 140)); self.r += 1

    def header(self, labels, start=1, fill="E0E7FF", color="1E293B"):
        for i, h in enumerate(labels, start):
            c = self.ws.cell(self.r, i, h); c.font = xFont(True, color); c.fill = xFill(fill); c.border = xBorder()
            c.alignment = xAlign("center", wrap=True)
        self.r += 1

    def row(self, vals, start=1, bold0=False, fills=None, wrap=False):
        for i, v in enumerate(vals):
            c = self.ws.cell(self.r, start + i, v); c.font = xFont(bold0 and i == 0); c.border = xBorder()
            c.alignment = xAlign("left" if isinstance(v, str) else "center", "top" if wrap else "center", wrap)
            if fills and i < len(fills) and fills[i]:
                c.fill = xFill(fills[i])
        self.r += 1

    def gap(self, n=1):
        self.r += n

    def widths(self, ws_):
        for i, w in enumerate(ws_, 1):
            self.ws.column_dimensions[get_column_letter(i)].width = w


def finishSheet(ws, landscape=True):
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0


# ══ Statistics ══════════════════════════════════════════════════════════════
def tCrit(df, alpha=0.05):
    return float(spStats.t.ppf(1 - alpha / 2, df)) if spStats and df > 0 else 1.96


def tPvalue(t, df):
    if t != t or df <= 0:
        return float("nan")
    return float(2 * spStats.t.sf(abs(t), df)) if spStats else math.erfc(abs(t) / math.sqrt(2))


def rankData(v):
    order = sorted(range(len(v)), key=lambda i: v[i]); ranks = [0.0] * len(v); i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def pearsonR(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else float("nan")


def spearman(xs, ys):
    """(rho, p)."""
    n = len(xs)
    if n < 3:
        return float("nan"), float("nan")
    rho = pearsonR(rankData(xs), rankData(ys))
    if rho != rho:
        return rho, float("nan")
    t = rho * math.sqrt((n - 2) / (1 - rho ** 2)) if abs(rho) < 1 else float("inf")
    return rho, (tPvalue(t, n - 2) if t != float("inf") else 0.0)


def computeBlr(xs, ys, borderline):
    """Borderline regression: score on GR, cut = prediction at the borderline GR (95% CI)."""
    n = len(xs); out = {"n": n, "ok": False}
    if n < 3 or len(set(xs)) < 2:
        return out
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx; a = my - b * mx
    ssRes = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    see = math.sqrt(ssRes / (n - 2)) if n > 2 else 0.0
    seSlope = see / math.sqrt(sxx) if sxx else float("nan")
    cut = a + b * borderline
    seCut = see * math.sqrt(1 / n + (borderline - mx) ** 2 / sxx)
    tc = tCrit(n - 2)
    out.update(ok=True, slope=b, intercept=a, r2=1 - ssRes / syy if syy else 0.0, r=pearsonR(xs, ys), see=see,
               pSlope=tPvalue(b / seSlope if seSlope else float("nan"), n - 2), cut=cut,
               cutLo=cut - tc * seCut, cutHi=cut + tc * seCut, mean=my, sd=math.sqrt(syy / (n - 1)) if n > 1 else 0.0,
               nPass=sum(1 for y in ys if y >= cut), minGr=min(xs), maxGr=max(xs), nLevels=len(set(xs)))
    return out


def computeBgm(xs, ys, borderline):
    """Borderline group: cut = mean score of candidates rated borderline (95% CI)."""
    grp = [y for x, y in zip(xs, ys) if x == borderline]; nb = len(grp)
    out = {"nB": nb, "ok": nb >= 1}
    if not nb:
        return out
    m = sum(grp) / nb
    sd = math.sqrt(sum((y - m) ** 2 for y in grp) / (nb - 1)) if nb > 1 else float("nan")
    se = sd / math.sqrt(nb) if nb > 1 else float("nan")
    tc = tCrit(nb - 1) if nb > 1 else float("nan")
    srt = sorted(grp)
    out.update(cut=m, median=srt[nb // 2] if nb % 2 else (srt[nb // 2 - 1] + srt[nb // 2]) / 2, sd=sd,
               cutLo=m - tc * se if nb > 1 else float("nan"), cutHi=m + tc * se if nb > 1 else float("nan"),
               minB=min(grp), maxB=max(grp), nPass=sum(1 for y in ys if y >= m))
    return out


def gradeMeans(xs, ys, levels=5):
    res = {}
    for g in range(1, levels + 1):
        v = [y for x, y in zip(xs, ys) if x == g]
        if v:
            m = sum(v) / len(v)
            res[g] = (len(v), m, math.sqrt(sum((y - m) ** 2 for y in v) / (len(v) - 1)) if len(v) > 1 else 0.0)
    return res


def viabilityChecks(xs, ys, blr, bgm, bl):
    """[(method, test, value, criterion, PASS/WARN/FAIL, note)] — AMEE Guide 49 style checks."""
    chk, n = [], len(xs)
    add = lambda *a: chk.append(a)
    add("BLR", "Sample size (n)", n, f"≥ {cfg.SS_MIN_N}", "PASS" if n >= cfg.SS_MIN_N else ("WARN" if n >= 5 else "FAIL"),
        "Small n makes the regression unstable.")
    if blr.get("ok"):
        add("BLR", "GR levels used", blr["nLevels"], "≥ 3 distinct", "PASS" if blr["nLevels"] >= 3 else "WARN",
            "Few levels = line fixed by few points.")
        add("BLR", f"GR={bl} inside observed range", f"{blr['minGr']}–{blr['maxGr']}", "inside",
            "PASS" if blr["minGr"] <= bl <= blr["maxGr"] else "WARN", "Outside = extrapolated cut.")
        add("BLR", "R² (score vs GR)", round(blr["r2"], 3), f"≥ {cfg.R2_MIN}", "PASS" if blr["r2"] >= cfg.R2_MIN else "FAIL",
            "Checklist and global judgement agree.")
        add("BLR", "Slope positive & significant", f"{blr['slope']:.2f} (p={blr['pSlope']:.3g})", "> 0, p < 0.05",
            "PASS" if blr["slope"] > 0 and blr["pSlope"] < 0.05 else "FAIL", "Higher GR must mean higher score.")
        add("BLR", "Inter-grade discrimination (%-pts/GR)", round(blr["slope"], 2),
            f"≈ {cfg.DISCRIM_GUIDE:g} ({cfg.DISCRIM_LOW:g}–{cfg.DISCRIM_HIGH:.1f})",
            "PASS" if cfg.DISCRIM_LOW <= blr["slope"] <= cfg.DISCRIM_HIGH else "WARN",
            "Low = barely separates grades; high = outlier-driven.")
        w = blr["cutHi"] - blr["cutLo"]
        add("BLR", "Cut 95% CI width", f"{w:.1f}", "≤ 10 %-pts", "PASS" if w <= 10 else "WARN", "Wide = imprecise cut.")
    else:
        add("BLR", "Regression computable", "No", "≥ 3 points, ≥ 2 GR levels", "FAIL", "")
    nb = bgm.get("nB", 0)
    add("BGM", f"Borderline group size (GR={bl})", nb, f"≥ {cfg.BGM_MIN_BORDERLINE}",
        "PASS" if nb >= cfg.BGM_MIN_BORDERLINE else ("WARN" if nb >= 2 else "FAIL"), "BGM uses only borderline candidates.")
    if nb >= 2:
        add("BGM", "Borderline group SD", round(bgm["sd"], 2), "≤ 15 %-pts", "PASS" if bgm["sd"] <= 15 else "WARN",
            "Large spread = assessors disagree on 'borderline'.")
        w = bgm["cutHi"] - bgm["cutLo"]
        add("BGM", "Cut 95% CI width", f"{w:.1f}", "≤ 10 %-pts", "PASS" if w <= 10 else "WARN", "")
    means = [m for _, (_, m, _) in sorted(gradeMeans(xs, ys).items())]
    add("Both", "Mean score rises with GR", " < ".join(f"{m:.0f}" for m in means) or "—", "non-decreasing",
        "PASS" if len(means) >= 2 and all(b >= a for a, b in zip(means, means[1:])) else "WARN", "")
    if n >= 3:
        rho, p = spearman(xs, ys)
        add("Both", "Spearman ρ (GR vs score)", f"{rho:.3f} (p={p:.3g})", "ρ > 0, p < 0.05",
            "PASS" if rho > 0 and p < 0.05 else "WARN", "Rank agreement without assuming linearity.")
    if blr.get("ok") and nb:
        d = abs(blr["cut"] - bgm["cut"])
        add("Both", "BLR vs BGM agreement", f"{d:.1f} %-pts", f"≤ {cfg.METHOD_AGREE_TOL:g}",
            "PASS" if d <= cfg.METHOD_AGREE_TOL else "WARN", "Large gap = review before adopting either cut.")
    return chk


def cronbachAlpha(X):
    """α for an (n × k) matrix with NaN → column mean imputation; None if k < 2 or n < 3."""
    X = np.asarray(X, float)
    if X.ndim != 2 or X.shape[1] < 2 or X.shape[0] < 3:
        return None
    X = np.where(np.isnan(X), np.nanmean(X, axis=0), X)
    X = np.nan_to_num(X)
    k = X.shape[1]; itemVar = X.var(axis=0, ddof=1).sum(); totVar = X.sum(axis=1).var(ddof=1)
    return float(k / (k - 1) * (1 - itemVar / totVar)) if totVar > 0 else None


def irtLite(item, ability):
    """2PL-style logistic of item fraction on standardised rest-score (IRLS): (a = discrimination, b = difficulty)."""
    m = ~np.isnan(item) & ~np.isnan(ability); y, a = item[m], ability[m]
    if len(y) < 8 or len(np.unique(y)) < 2:
        return (np.nan, np.nan)
    Xd = np.column_stack([np.ones_like(a), a]); b = np.zeros(2)
    for _ in range(50):
        p = 1 / (1 + np.exp(-(Xd @ b))); W = np.clip(p * (1 - p), 1e-6, None)
        try:
            b = np.linalg.solve((Xd * W[:, None]).T @ Xd, (Xd * W[:, None]).T @ (Xd @ b + (y - p) / W))
        except np.linalg.LinAlgError:
            return (np.nan, np.nan)
    slope = float(np.clip(b[1], -5, 5))
    if abs(slope) < 0.2:
        return (slope, np.nan)
    diff = -b[0] / b[1]
    return (slope, float(diff) if np.isfinite(diff) and abs(diff) <= 6 else np.nan)


def importance(Xg, target):
    """Per-item importance for predicting the total: RandomForest if scikit-learn exists, else |item-rest r|."""
    k = Xg.shape[1]
    Xi = np.nan_to_num(np.where(np.isnan(Xg), np.nanmean(Xg, axis=0), Xg))
    try:
        from sklearn.ensemble import RandomForestRegressor
        rf = RandomForestRegressor(n_estimators=300, random_state=0, n_jobs=-1).fit(Xi, np.nan_to_num(target))
        imp, lbl = np.asarray(rf.feature_importances_, float), "RandomForest importance"
    except Exception:
        imp = np.zeros(k)
        for j in range(k):
            rest = np.nansum(np.delete(Xg, j, axis=1), axis=1); col = Xg[:, j]; v = ~np.isnan(col)
            imp[j] = abs(np.corrcoef(col[v], rest[v])[0, 1]) if v.sum() > 2 and np.nanstd(col[v]) > 0 and np.std(rest[v]) > 0 else 0
        lbl = "Importance = |item-rest r| (install scikit-learn for RandomForest)"
    s = imp.sum()
    return (imp / s if s else imp), lbl


# ══ Shared row helpers ══════════════════════════════════════════════════════
def basePct(r):
    """Overall % before administrative penalties, unrounded (used for all analysis)."""
    if r.get("_pctExact") is not None:
        return r["_pctExact"]
    p = r.get("_pctBase", r["Pct"])
    return p if p is not None and p >= 0 else None


def ssPoints(rows):
    """(GR, base %, row) for submitted forms with both."""
    return [(r["GR_int"], basePct(r), r) for r in rows if r["Submitted"] == "Yes" and r["GR_int"] > 0 and basePct(r) is not None]


def borderlineOf(examKey):
    return cfg.EXAMS[examKey].get("borderline", 2)


def grLabels(rows):
    """{level: label} from the forms' own scale (latest wins)."""
    m = {}
    for r in sorted(rows, key=lambda x: x["_ts"]):
        if r["_gr"]:
            m.update({int(k): v for k, v in r["_gr"]["fields"].items() if str(k).isdigit()})
    return m


def tplTag(tpl, many):
    """Short sheet suffix for a template."""
    if not many or not tpl:
        return ""
    return " " + re.sub(r"\s*\(\d+ parts\)", "", tpl["label"])


def itemColumns(rows, tpl):
    """Ordered (ck, mc, secKey, sub, question) over the template's forms."""
    cols = OrderedDict()
    for r in sorted(rows, key=lambda x: -x["_ts"]):
        for it in r["_items"]:
            cols.setdefault((it["ck"], it["mc"]), (it["secKey"], it["sub"], it["question"]))
    secOrder = [sk for sk, _, _ in tpl["sections"]]
    keyOrder = {k: i for i, k in enumerate(tpl["keys"])}
    return sorted(((ck, mc, *v) for (ck, mc), v in cols.items()),
                  key=lambda c: (keyOrder.get(c[0], 99), secOrder.index(c[2]) if c[2] in secOrder else 99, core.natKey(c[1])))


def itemLookup(r):
    return {(it["ck"], it["mc"]): it for it in r["_items"]}


def itemFrac(r, c):
    """points ÷ max for item column c (NaN when unanswered/unscored; unansweredAsZero profiles count blanks as 0)."""
    it = itemLookup(r).get((c[0], c[1]))
    if not it or not it["max"]:
        return np.nan
    if it["points"] is None:
        return 0.0 if cfg.PROFILES[r["_profile"]]["unansweredAsZero"] else np.nan
    return it["points"] / it["max"]


def weightedPoints(it):
    """weight × points for an item cell (None when blank)."""
    if not it or it.get("points") is None:
        return None
    v = it["points"] * it.get("weight", 1)
    return int(v) if float(v).is_integer() else round(v, 2)


def autoWidth(ws, minW=6, maxW=40):
    for col in ws.columns:
        L = max((len(str(c.value)) for c in col if c.value is not None), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = max(minW, min(maxW, L + 2))


# ══ Records (summary) sheet ═════════════════════════════════════════════════
def recordColumns(rows, templates):
    """(header, valueFn, fillFn) list; section % columns when one template is in view."""
    tids = {r["_tid"] for r in rows}
    tpl = templates.get(next(iter(tids))) if len(tids) == 1 else None
    extraScaleNames = list(OrderedDict.fromkeys(s["name"] for r in rows for s in r["_extraScales"]))
    groups = list(OrderedDict.fromkeys(g for r in rows for g in r["_groupPct"]))
    cols = [("ID", lambda r: r["_id"], None), ("Date", lambda r: r["Date"], None), ("Student", lambda r: r["Student"], None),
            ("Assessor", lambda r: r["Assessor"], None), ("Examiner 2", lambda r: r["Examiner"], None),
            ("Cohort", lambda r: r["Cohort"], None), ("Subject", lambda r: r["Subject"], None),
            ("Checklist", lambda r: r["Checklist"], None),
            ("Status", lambda r: r["Status"], lambda v, r: {"Submitted": "BBFFD9", "In progress": "FEF08A"}.get(v, "FECACA")),
            ("Items scored", lambda r: f'{r["_scored"]}/{r["_nItems"]}' if r["_nItems"] else "", None),
            ("GR", lambda r: r["GR_int"] if r["GR_int"] > 0 else None, lambda v, r: GR_FILL.get(v)),
            ("GR label", lambda r: r["GR_label"] if r["GR_int"] > 0 else "", None)]
    cols += [(nm, (lambda r, nm=nm: next((s["value"] for s in r["_extraScales"] if s["name"] == nm), None)),
              lambda v, r: GR_FILL.get(v)) for nm in extraScaleNames]
    if tpl:
        for sk, nm, short in tpl["sections"]:
            cols.append((f"{short} %", (lambda r, sk=sk: rnd((r["_sec"].get(sk) or {}).get("pct"))),
                         (lambda v, r, sk=sk: "FEF3C7" if sk in r["_sec"] and not r["_sec"][sk]["present"] else pctFill(v))))
    cols += [(f"{g} total %", (lambda r, g=g: rnd(r["_groupPct"].get(g))), lambda v, r: pctFill(v)) for g in groups]
    if any(r.get("_outcome") for r in rows):
        cols.append(("Outcome", lambda r: r.get("_outcome", ""),
                     lambda v, r: "FECACA" if r.get("_unsafe") or (v and v.startswith("Fail")) or "— Fail" in (v or "") else None))
    cols += [("Total", lambda r: r["Total"], None), ("Max", lambda r: r["Max"], None),
             ("Overall %", lambda r: r["Pct"] if r["Pct"] >= 0 else None, lambda v, r: pctFill(v)),
             ("Overall % before override", lambda r: basePct(r), None),
             ("Override", lambda r: r.get("_overrideNote") or "", lambda v, r: "FECACA" if v else None),
             ("Critical concerns", lambda r: r["CC"], lambda v, r: "FECACA" if r["CC_int"] else None),
             ("Not in form", lambda r: r["Missing"] if r["_missing"] else "", lambda v, r: "FEF3C7" if v else None),
             ("Submitted incomplete", lambda r: "; ".join(r["_incomplete"]), lambda v, r: "FED7AA" if v else None),
             ("Comments", lambda r: r["Comments"] if r["Comments"] != "—" else "", None)]
    return cols


def writeRecords(wb, title, rows, templates):
    ws = wb.create_sheet(sheetName(wb, title))
    cols = pairedRecordColumns(rows, templates) if rows and all(r.get("_paired") for r in rows) else recordColumns(rows, templates)
    for i, (h, _, _) in enumerate(cols, 1):
        c = ws.cell(1, i, h); c.font = xFont(True, "FFFFFF"); c.fill = xFill("010D44")
        c.alignment = xAlign("center", wrap=True); c.border = xBorder()
    for ri, r in enumerate(rows, 2):
        bg = "FFFFFF" if ri % 2 else "F8FAFC"
        for ci, (h, vf, ff) in enumerate(cols, 1):
            v = vf(r)
            c = ws.cell(ri, ci, v); c.font = xFont(); c.border = xBorder(); c.alignment = xAlign(wrap=False)
            c.fill = xFill((ff(v, r) if ff else None) or bg)
            if h in ("Total", "Overall %") and r.get("_overrideNote"):
                cm = XlComment(r["_overrideNote"], "DASH dashboard"); cm.width, cm.height = 320, 110; c.comment = cm
    ws.row_dimensions[1].height = 30
    autoWidth(ws)
    for ci, (h, _, _) in enumerate(cols, 1):
        if h in ("Comments", "Override", "Submitted incomplete", "Comments E1", "Comments E2", "Pairing issues"):
            ws.column_dimensions[get_column_letter(ci)].width = 50
    ws.freeze_panes = "D2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"
    return ws


# ══ Per-checklist score sheet (MC grid) ═════════════════════════════════════
def writeScoreSheet(wb, title, rows, tpl):
    ws = wb.create_sheet(sheetName(wb, title))
    icols = itemColumns(rows, tpl)
    secName = {sk: (nm, short) for sk, nm, short in tpl["sections"]}
    blocks = []                                                  # (label, color, [(header, valueFn, fillFn)])
    paired = bool(rows) and all(r.get("_paired") for r in rows)  # BOH viva: one row per student, E1 + E2
    statusFill = lambda v, r: {"Submitted": "BBFFD9", "In progress": "FEF08A"}.get(v, "FECACA")
    if paired:
        blocks.append(("Student", ("010D44", "C7D2FE"), [
            ("Date", lambda r: r["Date"], None), ("Student", lambda r: r["Student"], None),
            ("Assessor 1 (E1)", lambda r: r["Assessor1"], None), ("Assessor 2 (E2, scorer)", lambda r: r["Assessor2"], None),
            ("Cohort", lambda r: r["Cohort"], None),
            ("Status E2", lambda r: r["_e2"]["Status"] if r["_e2"] else "—", statusFill),
            ("Status E1", lambda r: r["_e1"]["Status"] if r["_e1"] else "—", statusFill),
            ("Pairing issues", lambda r: "; ".join(r["_pairIssues"]), lambda v, r: "FED7AA" if v else None)]))
    else:
        blocks.append(("Form", ("010D44", "C7D2FE"), [
            ("Date", lambda r: r["Date"], None), ("Student", lambda r: r["Student"], None),
            ("Assessor", lambda r: r["Assessor"], None), ("Examiner 2", lambda r: r["Examiner"], None),
            ("Cohort", lambda r: r["Cohort"], None), ("Status", lambda r: r["Status"], statusFill)]))
    palette = [("4338CA", "E0E7FF"), ("6D28D9", "EDE9FE"), ("0E7490", "CFFAFE"), ("065F46", "D1FAE5"),
               ("92400E", "FEF3C7"), ("9D174D", "FCE7F3"), ("1D4ED8", "DBEAFE"), ("7C2D12", "FFEDD5")]
    bySec = OrderedDict()
    for c in icols:
        bySec.setdefault(c[2], []).append(c)
    for si, (sk, its) in enumerate(bySec.items()):
        nm, short = secName.get(sk, (sk, sk))
        col = palette[si % len(palette)]
        subs = OrderedDict()
        for c in its:
            subs.setdefault(c[3], []).append(c)
        for sub, scs in subs.items():
            label = f"{short} · {nm}" + (f" | {sub}" if sub else "")
            cs = []
            for ck, mc, _, _, q in scs:
                mxs = [itemLookup(r).get((ck, mc), {}).get("max") for r in rows]
                mx = next((m for m in mxs if m), "?")
                wt = next((itemLookup(r)[(ck, mc)].get("weight", 1) for r in rows if (ck, mc) in itemLookup(r)), 1)
                if isinstance(mx, (int, float)):                               # weighted items show weight × points
                    hdr = f"{mc} (/{mx:g})" if wt == 1 else f"{mc} (×{wt:g}, /{mx * wt:g})"
                else:
                    hdr = mc
                cs.append((hdr, (lambda r, k=(ck, mc): weightedPoints(itemLookup(r).get(k))),
                           (lambda v, r, k=(ck, mc): fracFill((itemLookup(r).get(k) or {}).get("points"),
                                                              (itemLookup(r).get(k) or {}).get("max"))), q))
            blocks.append((label, col, cs))
        mxS = next((r["_sec"][sk]["max"] for r in rows if sk in r["_sec"] and r["_sec"][sk]["max"]), None)
        blocks.append((f"{short} total", col, [
            (f"Score /{mxS:g}" if mxS else "Score", lambda r, sk=sk: rnd((r["_sec"].get(sk) or {}).get("score"), 2),
             lambda v, r, sk=sk: "FEF3C7" if sk in r["_sec"] and not r["_sec"][sk]["present"] else None),
            ("%", lambda r, sk=sk: rnd((r["_sec"].get(sk) or {}).get("pct")), lambda v, r: pctFill(v))]))
    groups = list(OrderedDict.fromkeys(g for r in rows for g in r["_groupPct"]))
    extra = list(OrderedDict.fromkeys(s["name"] for r in rows for s in r["_extraScales"]))
    if paired:                                                   # each scale: E1, E2, Δ
        rkeys = list(OrderedDict.fromkeys(k for r in rows for k in r["_ratings"]))
        sinfo = {}
        for r in rows:
            sinfo.update({k: v for k, v in r["_scaleInfo"].items() if k not in sinfo})
        ratingCols = []
        for k in rkeys:
            sh = sinfo[k]["short"]
            ratingCols += [(f"{sh} E1", (lambda r, k=k: ratingPair(r, k)[0]), lambda v, r: GR_FILL.get(v)),
                           (f"{sh} E2", (lambda r, k=k: ratingPair(r, k)[1]), lambda v, r: GR_FILL.get(v)),
                           (f"{sh} Δ", (lambda r, k=k: (ratingPair(r, k)[1] - ratingPair(r, k)[0]) if None not in ratingPair(r, k) else None),
                            lambda v, r: "FED7AA" if v is not None and abs(v) >= 2 else None)]
    else:
        ratingCols = ([("GR", lambda r: r["GR_int"] if r["GR_int"] > 0 else None, lambda v, r: GR_FILL.get(v))]
                      + [(nm, (lambda r, nm=nm: next((s["value"] for s in r["_extraScales"] if s["name"] == nm), None)),
                          lambda v, r: GR_FILL.get(v)) for nm in extra])
    blocks.append(("Summary", ("1E293B", "F1F5F9"),
                   ratingCols
                   + [(f"{g} total %", (lambda r, g=g: rnd(r["_groupPct"].get(g))), lambda v, r: pctFill(v)) for g in groups]
                   + [("Total", lambda r: r["Total"], None), ("Max", lambda r: r["Max"], None),
                      ("Overall %", lambda r: r["Pct"] if r["Pct"] >= 0 else None, lambda v, r: pctFill(v)),
                      ("CC", lambda r: r["CC"], lambda v, r: "FECACA" if r["CC_int"] else None),
                      ("Not in form", lambda r: r["Missing"] if r["_missing"] else "", lambda v, r: "FEF3C7" if v else None),
                      ("Override", lambda r: r.get("_overrideNote") or "", lambda v, r: "FECACA" if v else None)]))
    ckCom = [ck for ck in tpl["keys"] if any((r["_ad"].get(f"{ck}_comments") or "").strip() for r in rows)] if tpl["multi"] else []
    shortOf = {sk: s for sk, _, s in tpl["sections"]}
    if paired:                                                   # both examiners' general comments + critical errors
        adE = lambda r, e: ((r.get(e) or {}).get("_ad") or {})
        comCols = [("Comments E1", lambda r: (adE(r, "_e1").get("comments") or "").strip(), None),
                   ("Comments E2", lambda r: (adE(r, "_e2").get("comments") or "").strip(), None)]
        for fld, lbl in (("critical_error", "Critical error"), ("clinical_incident", "Clinical incident"),
                         ("critical_concerns_comments", "Critical concerns")):
            for e, el in (("_e1", "E1"), ("_e2", "E2")):
                if any(core.meaningful(adE(r, e).get(fld)) for r in rows):
                    comCols.append((f"{lbl} {el}", (lambda r, f=fld, e=e: str(adE(r, e).get(f) or "").strip()), None))
    else:
        comCols = [("General", lambda r: (r["_ad"].get("comments") or "").strip(), None)]
    comCols += [(f"{shortOf.get(ck, ck)} comments", (lambda r, ck=ck: (r["_ad"].get(f"{ck}_comments") or "").strip()), None) for ck in ckCom]
    for fld, lbl in (("critical_concerns_comments", "Critical concerns comments"), ("critical_error", "Critical error"),
                     ("clinical_incident", "Clinical incident")):
        if not paired and any(core.meaningful(r["_ad"].get(fld)) for r in rows):
            comCols.append((lbl, (lambda r, f=fld: str(r["_ad"].get(f) or "").strip()), None))
    blocks.append(("Comments", ("374151", "F3F4F6"), comCols))

    ci = 1
    for label, (hh, sh), cs in blocks:
        start = ci
        for c in cs:
            h = ws.cell(2, ci, c[0]); h.fill = xFill(sh); h.font = xFont(True, size=8)
            h.alignment = xAlign("center", wrap=True); h.border = xBorder(l=ci == start, r=ci == start + len(cs) - 1)
            if len(c) > 3 and c[3]:
                cm = XlComment(c[3][:400], "Question"); cm.width, cm.height = 300, 90; h.comment = cm
            for ri, r in enumerate(rows, 3):
                v = c[1](r)
                cell = ws.cell(ri, ci, v); cell.font = xFont(size=8 if c[0].startswith("MC") else 9)
                cell.border = xBorder(l=ci == start, r=ci == start + len(cs) - 1)
                cell.alignment = xAlign("center" if not isinstance(v, str) or len(str(v)) < 12 else "left")
                f = c[2](v, r) if c[2] else None
                cell.fill = xFill(f or ("FFFFFF" if ri % 2 else "F8FAFC"))
                if c[0] in ("Total", "Overall %") and r.get("_overrideNote"):
                    cm = XlComment(r["_overrideNote"], "DASH dashboard"); cm.width, cm.height = 320, 110; cell.comment = cm
            w = 7 if c[0].startswith("MC") else 34 if label == "Comments" else \
                18 if c[0] in ("Student", "Assessor", "Examiner 2", "Assessor 1 (E1)", "Assessor 2 (E2, scorer)", "Pairing issues") else 10
            ws.column_dimensions[get_column_letter(ci)].width = w
            ci += 1
        for cc in range(start, ci):
            x = ws.cell(1, cc); x.fill = xFill(hh); x.font = xFont(True, "FFFFFF", 9); x.alignment = xAlign("center", wrap=True)
            x.border = xBorder(l=cc == start, r=cc == ci - 1)
        ws.cell(1, start, label)
        if ci - 1 > start:
            ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=ci - 1)
    ws.row_dimensions[1].height, ws.row_dimensions[2].height = 30, 30
    ws.freeze_panes = ws.cell(3, 3)
    return ws


# ══ Standard setting sheet ══════════════════════════════════════════════════
def writeStandardSetting(wb, title, rows, tpl, examKey):
    """BLR + BGM on Overall % (pre-penalty) and per section; viability; grade means; charts. Returns summary dict."""
    bl = borderlineOf(examKey)
    pts = ssPoints(rows)
    if not pts and not any(r["GR_int"] > 0 for r in rows):              # checklist has no global rating at all
        return {"blr": {}, "bgm": {}, "checks": [], "n": 0, "sections": [], "skipped": "no GR on these forms"}
    ws = wb.create_sheet(sheetName(wb, title)); w = SheetWriter(ws, 5)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    blr, bgm = computeBlr(xs, ys, bl), computeBgm(xs, ys, bl)
    checks = viabilityChecks(xs, ys, blr, bgm, bl) if pts else []
    grl = grLabels(rows)
    levels = max([5] + list(grl))
    w.title(f"Standard Setting — {tpl['label'] if tpl else 'All'} (borderline = GR {bl}: {grl.get(bl, '')})",
            f"{len(pts)} submitted forms with GR + Overall % (pre-penalty). BLR and BGM side by side — no recommended cut.")
    w.bar("Cut scores by method")
    w.header(["Statistic", "BLR (regression)", "BGM (borderline group)"])
    ok, nb = blr.get("ok"), bgm.get("nB", 0)
    f = lambda v, d=1: "—" if v is None or v != v else round(v, d)
    for row in [("Cut score (Overall %)", f(blr.get("cut")) if ok else "—", f(bgm.get("cut")) if nb else "—"),
                ("95% CI", f"{blr['cutLo']:.1f} – {blr['cutHi']:.1f}" if ok else "—",
                 f"{bgm['cutLo']:.1f} – {bgm['cutHi']:.1f}" if nb > 1 else "—"),
                ("Candidates used", blr.get("n", 0), nb),
                ("Pass at this cut", f"{blr['nPass']}/{len(ys)}" if ok else "—", f"{bgm['nPass']}/{len(ys)}" if nb else "—"),
                ("Slope (%-pts per GR)", f(blr.get("slope"), 2) if ok else "—", "n/a"),
                ("Intercept", f(blr.get("intercept"), 2) if ok else "—", "n/a"),
                ("R² / Pearson r", f"{blr['r2']:.3f} / {blr['r']:.3f}" if ok else "—", "n/a"),
                ("Std error of estimate", f(blr.get("see"), 2) if ok else "—", "n/a"),
                ("Borderline mean / median", "n/a", f"{bgm['cut']:.1f} / {bgm['median']:.1f}" if nb else "—"),
                ("Borderline SD / range", "n/a", f"{f(bgm.get('sd'))} / {bgm['minB']:.1f}–{bgm['maxB']:.1f}" if nb else "—")]:
        w.row(list(row), bold0=True)
    w.gap()
    w.bar("Viability tests")
    w.header(["Test", "Value", "Criterion", "Result", "Why it matters"])
    for m, t, v, crit, st, note in checks:
        w.row([f"[{m}] {t}", v, crit, st, note], fills=[None, None, None, FLAG_FILL[st]], wrap=True)
    if not checks:
        w.para("No submitted forms with GR + Overall % — nothing to test.", color="DC2626")
    w.para("PASS = criterion met · WARN = usable but review · FAIL = method not supported by the data. "
           "Thresholds in dash_app_config.py.", color="64748B")
    w.gap()
    w.bar("Overall % by Global Rating")
    w.header(["GR", "Label", "n", "Mean %", "SD"])
    gm = gradeMeans(xs, ys, levels); gmStart = w.r
    for g in range(1, levels + 1):
        n_, m_, sd_ = gm.get(g, (0, None, None))
        w.row([g, grl.get(g, ""), n_, rnd(m_), rnd(sd_)], fills=["FED7AA" if g == bl else None] * 5)
    gmEnd = w.r - 1
    w.gap()
    secRows = []
    if tpl:
        w.bar("Per-section cut scores (section % vs GR)")
        w.header(["Section", "BLR cut % (R²)", "BGM cut % (n borderline)", "Mean %", "Note"])
        for sk, nm, short in tpl["sections"]:
            dx, dy = [], []
            for g, _, r in pts:
                s = r["_sec"].get(sk)
                if s and s["pct"] is not None:
                    dx.append(g); dy.append(s["pct"])
            db, dg = computeBlr(dx, dy, bl), computeBgm(dx, dy, bl)
            note = "No data" if not db.get("ok") else ("" if db["r2"] >= cfg.R2_MIN else "R² < threshold — indicative only")
            w.row([f"{short} · {nm}", f"{db['cut']:.1f} (R² {db['r2']:.2f})" if db.get("ok") else "—",
                   f"{dg['cut']:.1f} (n={dg['nB']})" if dg.get("nB") else "—", rnd(sum(dy) / len(dy)) if dy else "—", note], bold0=True)
            secRows.append((short, db, dg))
    w.widths([44, 22, 24, 14, 52])

    dc = 30                                                           # chart data (visible; charts skip hidden cells)
    ws.cell(1, dc - 1, "Chart data →").font = xFont(True, size=8, color="94A3B8")
    for i, h in enumerate(["GR", "Overall %", "Student", "", "Marker", "GR", "%"]):
        ws.cell(1, dc + i, h).font = xFont(size=8, color="94A3B8")
    for i, (g, p, r) in enumerate(pts, 2):
        for j, v in enumerate([g, p, r["Student"]]):
            ws.cell(i, dc + j, v).font = xFont(size=8, color="94A3B8")
    mk = ([("BLR cut", bl, round(blr["cut"], 1))] if ok else []) + ([("BGM cut", bl, round(bgm["cut"], 1))] if nb else [])
    for i, (lbl, g, v) in enumerate(mk, 2):
        for j, x in enumerate([lbl, g, v]):
            ws.cell(i, dc + 4 + j, x).font = xFont(size=8, color="94A3B8")
    if len(pts) >= 2:
        sc = ScatterChart(); sc.style = 13
        sc.title = f"BLR — Overall % vs GR" + (f" (R² {blr['r2']:.2f})" if ok else "")
        sc.x_axis.title, sc.y_axis.title = "Global rating", "Overall %"
        sc.x_axis.scaling.min, sc.x_axis.scaling.max, sc.x_axis.majorUnit = 1, levels, 1
        sc.y_axis.scaling.min, sc.y_axis.scaling.max = 0, 100
        sc.x_axis.delete = sc.y_axis.delete = False; sc.height, sc.width = 9, 15
        s1 = Series(Reference(ws, min_col=dc + 1, min_row=2, max_row=len(pts) + 1),
                    Reference(ws, min_col=dc, min_row=2, max_row=len(pts) + 1), title="Candidates")
        s1.marker = Marker(symbol="circle", size=6); s1.marker.graphicalProperties.solidFill = "094183"
        s1.graphicalProperties.line.noFill = True
        if ok:
            s1.trendline = Trendline(trendlineType="linear")
        sc.series.append(s1)
        for i, (lbl, g, v) in enumerate(mk, 2):
            s = Series(Reference(ws, min_col=dc + 6, min_row=i, max_row=i), Reference(ws, min_col=dc + 5, min_row=i, max_row=i),
                       title=f"{lbl} {v}%")
            s.marker = Marker(symbol="diamond" if lbl.startswith("BLR") else "triangle", size=11)
            s.marker.graphicalProperties.solidFill = "DC2626" if lbl.startswith("BLR") else "E87722"
            s.graphicalProperties.line.noFill = True; sc.series.append(s)
        ws.add_chart(sc, "G3")
        bc = BarChart(); bc.type = "col"; bc.title = "BGM — mean Overall % by GR"; bc.legend = None
        bc.y_axis.scaling.min, bc.y_axis.scaling.max = 0, 100; bc.x_axis.delete = bc.y_axis.delete = False
        bc.add_data(Reference(ws, min_col=4, min_row=gmStart - 1, max_row=gmEnd), titles_from_data=True)
        bc.set_categories(Reference(ws, min_col=1, min_row=gmStart, max_row=gmEnd))
        bc.dataLabels = DataLabelList(); bc.dataLabels.showVal = True
        bc.series[0].graphicalProperties.solidFill = "094183"
        dp = DataPoint(idx=bl - 1); dp.graphicalProperties.solidFill = "E87722"; bc.series[0].dPt.append(dp)
        bc.height, bc.width = 9, 15
        ws.add_chart(bc, "G23")
    finishSheet(ws)
    ws.print_area = f"A1:Q{max(w.r, 44)}"                              # chart data columns stay out of print
    return {"blr": blr, "bgm": bgm, "checks": checks, "n": len(pts), "sections": secRows}


# ══ Section analysis ════════════════════════════════════════════════════════
def writeSections(wb, title, rows, tpl, examKey, ss):
    bl = borderlineOf(examKey)
    sub = [r for r in rows if r["Submitted"] == "Yes" and basePct(r) is not None]
    if len(sub) < 3 or not tpl:
        return None
    ws = wb.create_sheet(sheetName(wb, title)); w = SheetWriter(ws, 12)
    secs = tpl["sections"]
    w.title(f"Section Analysis — {tpl['label']}", f"{len(sub)} submitted, scored forms · % = section percentage per form")
    w.bar("Section descriptives")
    w.header(["Section", "Name", "Items", "n", "Mean %", "SD", "Min", "Median", "Max", "% full marks",
              "α (items)", "ρ with GR", "r with overall"])
    icols = itemColumns(sub, tpl)
    chartStart = w.r
    for sk, nm, short in secs:
        vals = [r["_sec"][sk]["pct"] for r in sub if sk in r["_sec"] and r["_sec"][sk]["pct"] is not None]
        if not vals:
            w.row([short, nm, "", 0]); continue
        a = np.array(vals)
        ks = [c for c in icols if c[2] == sk]
        X = np.array([[itemFrac(r, c) for c in ks] for r in sub], float)
        alpha = cronbachAlpha(X)
        gx = [(r["GR_int"], r["_sec"][sk]["pct"]) for r in sub if r["GR_int"] > 0 and sk in r["_sec"] and r["_sec"][sk]["pct"] is not None]
        rho = spearman([g for g, _ in gx], [p for _, p in gx])[0] if len(gx) >= 3 else None
        ov = [(r["_sec"][sk]["pct"], basePct(r)) for r in sub if sk in r["_sec"] and r["_sec"][sk]["pct"] is not None]
        rOv = pearsonR([x for x, _ in ov], [y for _, y in ov])
        w.row([short, nm, len(ks), len(vals), rnd(a.mean()), rnd(a.std(ddof=1) if len(a) > 1 else 0), rnd(a.min()),
               rnd(float(np.median(a))), rnd(a.max()), rnd(100 * np.mean(a >= 99.95)),
               rnd(alpha, 3), rnd(rho, 3), rnd(rOv, 3)],
              bold0=True, fills=[None, None, None, None, pctFill(a.mean())] + [None] * 5 +
              ["BBFFD9" if alpha and alpha >= cfg.ALPHA_GOOD else ("FEF08A" if alpha else None)])
    chartEnd = w.r - 1
    Xall = np.array([[itemFrac(r, c) for c in icols] for r in sub], float)
    aAll = cronbachAlpha(Xall)
    w.para(f"Whole checklist: {len(icols)} items, Cronbach α = {rnd(aAll, 3) if aAll is not None else '—'} "
           f"(≥ {cfg.ALPHA_GOOD} acceptable). ρ = Spearman with GR; r = Pearson with Overall %.", color="475569")
    w.gap()
    grl = grLabels(rows); levels = max([5] + list(grl))
    w.bar("Mean section % by Global Rating")
    w.header(["Section"] + [f"GR {g}" + (f" {grl[g][:14]}" if g in grl else "") for g in range(1, levels + 1)] + ["All"])
    for sk, nm, short in secs:
        cells, fills = [short], [None]
        for g in range(1, levels + 1):
            v = [r["_sec"][sk]["pct"] for r in sub if r["GR_int"] == g and sk in r["_sec"] and r["_sec"][sk]["pct"] is not None]
            m = sum(v) / len(v) if v else None
            cells.append(f"{m:.1f} (n={len(v)})" if v else "—"); fills.append(pctFill(m) if v else None)
        allv = [r["_sec"][sk]["pct"] for r in sub if sk in r["_sec"] and r["_sec"][sk]["pct"] is not None]
        cells.append(rnd(sum(allv) / len(allv)) if allv else "—")
        w.row(cells, bold0=True, fills=fills)
    w.gap()
    if len(secs) > 1:
        w.bar("Section intercorrelations (Pearson r of section %)")
        w.header([""] + [s for _, _, s in secs])
        for sk, _, short in secs:
            cells, fills = [short], [None]
            for sk2, _, _ in secs:
                pr = [(r["_sec"][sk]["pct"], r["_sec"][sk2]["pct"]) for r in sub
                      if sk in r["_sec"] and sk2 in r["_sec"] and r["_sec"][sk]["pct"] is not None and r["_sec"][sk2]["pct"] is not None]
                rv = pearsonR([a for a, _ in pr], [b for _, b in pr]) if len(pr) >= 3 else float("nan")
                cells.append(rnd(rv, 2))
                fills.append(None if rv != rv else ("BBFFD9" if rv >= .7 else "D1FAE5" if rv >= .4 else "FEF9C3" if rv >= .2 else "FECACA"))
            w.row(cells, bold0=True, fills=fills)
    w.widths([10, 40, 7, 6, 9, 8, 8, 9, 8, 11, 10, 10, 12])
    if chartEnd >= chartStart:
        bc = BarChart(); bc.type = "bar"; bc.title = "Mean % by section"; bc.legend = None
        bc.add_data(Reference(ws, min_col=5, min_row=chartStart - 1, max_row=chartEnd), titles_from_data=True)
        bc.set_categories(Reference(ws, min_col=1, min_row=chartStart, max_row=chartEnd))
        bc.x_axis.delete = bc.y_axis.delete = False; bc.y_axis.scaling.min, bc.y_axis.scaling.max = 0, 100
        bc.series[0].graphicalProperties.solidFill = "094183"; bc.height, bc.width = 8, 14
        ws.add_chart(bc, "O3")
    finishSheet(ws)
    return aAll


# ══ Item analysis ═══════════════════════════════════════════════════════════
def writeItems(wb, title, rows, tpl):
    sub = [r for r in rows if r["Submitted"] == "Yes" and basePct(r) is not None]
    icols = itemColumns(sub, tpl) if tpl else []
    if len(sub) < 5 or len(icols) < 2:
        return
    X = np.array([[itemFrac(r, c) for c in icols] for r in sub], float)
    tot = np.nansum(X, axis=1)
    imp, impLbl = importance(X, tot)
    order = np.argsort(tot); cut = max(1, int(round(0.27 * len(order))))
    lo, hi = set(order[:cut].tolist()), set(order[-cut:].tolist())
    aAll = cronbachAlpha(X)
    secName = {sk: s for sk, _, s in tpl["sections"]}
    ws = wb.create_sheet(sheetName(wb, title)); w = SheetWriter(ws, 19)
    w.title(f"Item Analysis — {tpl['label']}",
            f"n={len(sub)} submitted forms · {len(icols)} items · α = {rnd(aAll, 3)} · {impLbl} · "
            f"difficulty p = mean item fraction · r = corrected item-rest · ρ GR = Spearman item vs Global Rating · "
            f"D = top − bottom 27% · 2PL-lite on standardised rest score")
    hdrs = ["Section", "Item", "Question", "n answered", "Blank", "Difficulty p", "SD", "Item-rest r", "ρ with GR", "α if deleted",
            "D (27%)", "IRT a", "IRT b", "Importance", "Rank", "% full", "% partial", "% zero", "Flag"]
    w.header(hdrs, fill="010D44", color="FFFFFF")
    start = w.r
    ranks = (-imp).argsort().argsort() + 1
    grArr = np.array([r["GR_int"] for r in sub], float)                # GR per form (≤ 0 = no GR)
    grRhos = []                                                         # ρ per item, for the chart colours
    for j, c in enumerate(icols):
        col = X[:, j]; v = ~np.isnan(col); n = int(v.sum())
        p = float(np.nanmean(col)) if n else np.nan
        sd = float(np.nanstd(col)) if n else np.nan
        rest = np.nansum(np.delete(X, j, axis=1), axis=1)
        rIt = float(np.corrcoef(col[v], rest[v])[0, 1]) if n > 2 and np.std(col[v]) > 0 and np.std(rest[v]) > 0 else np.nan
        gv = v & (grArr > 0)                                            # pairwise: item marked AND GR given
        rhoGr = spearman(grArr[gv].tolist(), col[gv].tolist())[0] if gv.sum() >= 3 else np.nan
        grRhos.append(rhoGr)
        aDel = cronbachAlpha(np.delete(X, j, axis=1))
        hiV = [col[i] for i in hi if not np.isnan(col[i])]; loV = [col[i] for i in lo if not np.isnan(col[i])]
        D = (np.mean(hiV) - np.mean(loV)) if hiV and loV else np.nan
        ab = (rest - np.mean(rest)) / (np.std(rest) or 1)
        a, b = irtLite(col, ab)
        full = float(np.mean(col[v] >= 0.999)) if n else np.nan
        zero = float(np.mean(col[v] <= 0.001)) if n else np.nan
        novar = n > 0 and np.nanstd(col[v]) == 0
        flag = ("No variance" if novar else "Poor" if not (rIt == rIt) or rIt < 0.10 else "Too easy" if p > 0.95
                else "Too hard" if p < 0.10 else "Good" if rIt >= 0.20 and 0.20 <= p <= 0.90 else "Review")
        if aDel is not None and aAll is not None and aDel > aAll + 0.01 and flag == "Good":
            flag = "Review"
        blank = sum(1 for r in sub if (itemLookup(r).get((c[0], c[1])) or {}).get("points") is None)
        w.row([secName.get(c[2], c[2]), c[1], (c[4] or "")[:90], n, blank, rnd(p, 3), rnd(sd, 3), rnd(rIt, 3), rnd(rhoGr, 3), rnd(aDel, 3),
               rnd(D, 3), rnd(a, 2), rnd(b, 2), rnd(imp[j], 3), int(ranks[j]), rnd(100 * full), rnd(100 * (1 - full - zero)),
               rnd(100 * zero), flag],
              fills=[None] * 5 + [fracFill(p, 1) if p == p else None] + [None] * 2 + [rhoFill(rhoGr)] + [None] * 9
                    + [FLAG_FILL.get(flag)])
    end = w.r - 1
    w.gap()
    w.para("ρ with GR: Spearman rank correlation of the item with the Global Rating (forms with both) — "
           "green ≥ .30, amber .20–.30, red < .20 (item barely tracks the examiner's overall judgement).", color="64748B")
    w.para("Flags: Good = r ≥ .20 and .20 ≤ p ≤ .90 · Review = borderline p/r or α rises when deleted · Poor = r < .10 · "
           "Too easy/hard = p > .95 / < .10 · No variance = every candidate scored the same. Small samples: interpret with care.",
           color="64748B")
    w.widths([8, 7, 48, 9, 6, 10, 7, 10, 10, 10, 9, 7, 7, 10, 6, 7, 8, 7, 11])
    ws.freeze_panes = ws.cell(start, 3)
    ws.auto_filter.ref = f"A{start - 1}:{get_column_letter(len(hdrs))}{end}"
    sc = ScatterChart(); sc.title = "Difficulty vs discrimination"; sc.style = 13
    sc.x_axis.title, sc.y_axis.title = "Difficulty p", "Item-rest r"; sc.x_axis.delete = sc.y_axis.delete = False
    s = Series(Reference(ws, min_col=8, min_row=start, max_row=end), Reference(ws, min_col=6, min_row=start, max_row=end), title="items")
    s.marker = Marker(symbol="circle", size=6); s.marker.graphicalProperties.solidFill = "094183"
    s.graphicalProperties.line.noFill = True; sc.series.append(s); sc.height, sc.width = 9, 14
    ws.add_chart(sc, "U3")
    bc = BarChart(); bc.title = "Item-rest r"; bc.legend = None; bc.height, bc.width = 9, 18
    bc.add_data(Reference(ws, min_col=8, min_row=start - 1, max_row=end), titles_from_data=True)
    bc.set_categories(Reference(ws, min_col=2, min_row=start, max_row=end))
    bc.series[0].graphicalProperties.solidFill = "E87722"; bc.x_axis.delete = bc.y_axis.delete = False
    ws.add_chart(bc, "U22")
    if any(x == x for x in grRhos):                                     # item vs GR correlation chart
        gc = BarChart(); gc.title = "Item vs Global Rating (Spearman ρ)"; gc.legend = None; gc.height, gc.width = 9, 18
        gc.add_data(Reference(ws, min_col=9, min_row=start - 1, max_row=end), titles_from_data=True)
        gc.set_categories(Reference(ws, min_col=2, min_row=start, max_row=end))
        gc.y_axis.title = "ρ with GR"; gc.x_axis.delete = gc.y_axis.delete = False
        gc.y_axis.scaling.max = 1.0; gc.y_axis.scaling.min = min(-0.2, min((x for x in grRhos if x == x), default=0) - 0.1)
        gc.series[0].graphicalProperties.solidFill = "1D9E75"
        for k, x in enumerate(grRhos):                                  # per-bar colour: good / acceptable / weak
            dp = DataPoint(idx=k); dp.graphicalProperties.solidFill = rhoColour(x)
            gc.series[0].dPt.append(dp)
        gc.dataLabels = DataLabelList(showVal=True, showSerName=False, showCatName=False,   # value only
                                      showLegendKey=False, showPercent=False, numFmt="0.00")
        gc.dataLabels.position = "outEnd"
        ws.add_chart(gc, "U41")
    finishSheet(ws)


# ══ Assessors ═══════════════════════════════════════════════════════════════
def writeAssessors(wb, rows, templates, ssByTpl, examKey):
    bl = borderlineOf(examKey)
    if not rows:
        return
    ws = wb.create_sheet(sheetName(wb, "Assessors")); w = SheetWriter(ws, 18)
    sub = [r for r in rows if r["Submitted"] == "Yes"]
    allP = [basePct(r) for r in sub if basePct(r) is not None]
    grand = float(np.mean(allP)) if allP else 0.0
    # residual vs each template's BLR line = how far the assessor's % sits from what their own GR predicts
    def resid(r):
        blr = (ssByTpl.get(r["_tid"]) or {}).get("blr") or {}
        if not blr.get("ok") or r["GR_int"] < 1 or basePct(r) is None:
            return None
        return basePct(r) - (blr["intercept"] + blr["slope"] * r["GR_int"])
    grl = grLabels(rows); levels = max([5] + list(grl))
    by = defaultdict(list)
    for r in rows:
        by[r["Assessor"]].append(r)
    data = []
    for asr, rs in by.items():
        sr = [r for r in rs if r["Submitted"] == "Yes"]
        ps = [basePct(r) for r in sr if basePct(r) is not None]
        grs = [r["GR_int"] for r in sr if r["GR_int"] > 0]
        res = [x for x in (resid(r) for r in sr) if x is not None]
        data.append({"asr": asr, "forms": len(rs), "sub": len(sr), "stu": len({r["Student"] for r in rs}),
                     "mean": float(np.mean(ps)) if ps else None, "sd": float(np.std(ps, ddof=1)) if len(ps) > 1 else None,
                     "gr": float(np.mean(grs)) if grs else None, "grDist": [grs.count(g) for g in range(1, levels + 1)],
                     "low": 100 * sum(1 for g in grs if g <= bl) / len(grs) if grs else None,
                     "cc": sum(r["CC_int"] for r in rs), "open": sum(1 for r in rs if r["Status"] != "Submitted"),
                     "delta": (float(np.mean(ps)) - grand) if ps else None,
                     "adj": float(np.mean(res)) if res else None, "tpl": ", ".join(sorted({r["Checklist"] for r in rs}))})
    means = [d["mean"] for d in data if d["mean"] is not None]
    cutL = max(cfg.LENIENCY_MIN_CUT, 0.67 * float(np.std(means))) if len(means) > 1 else cfg.LENIENCY_MIN_CUT
    for d in data:
        d["flag"] = "" if d["delta"] is None or d["sub"] < 3 else ("Lenient" if d["delta"] > cutL else "Harsh" if d["delta"] < -cutL else "Typical")
        d["flagAdj"] = "" if d["adj"] is None or d["sub"] < 3 else ("Lenient" if d["adj"] > cutL else "Harsh" if d["adj"] < -cutL else "Typical")
    data.sort(key=lambda d: (d["mean"] is None, -(d["mean"] or 0)))
    w.title("Assessor Analysis",
            f"Cohort mean Overall % = {grand:.1f} · Δ = assessor mean − cohort mean · GR-adjusted Δ = mean of (score − score "
            f"predicted from the GR they gave, BLR line) · flags at ±{cutL:.1f} %-pts, assessors with ≥ 3 submitted forms")
    hdr = (["Assessor", "Forms", "Submitted", "Students", "Mean %", "SD", "Mean GR"] + [f"GR {g}" for g in range(1, levels + 1)]
           + [f"% GR ≤ {bl}", "CC", "Open forms", "Δ vs cohort", "Flag", "GR-adjusted Δ", "Flag (adj.)", "Checklists"])
    w.header(hdr, fill="010D44", color="FFFFFF"); start = w.r
    for d in data:
        vals = ([d["asr"], d["forms"], d["sub"], d["stu"], rnd(d["mean"]), rnd(d["sd"]), rnd(d["gr"], 2)] + d["grDist"]
                + [rnd(d["low"]), d["cc"], d["open"], rnd(d["delta"]), d["flag"], rnd(d["adj"]), d["flagAdj"], d["tpl"]])
        fills = [None] * len(vals)
        fills[4] = pctFill(d["mean"]); fills[-4] = FLAG_FILL.get(d["flag"]); fills[-2] = FLAG_FILL.get(d["flagAdj"])
        fills[7 + levels + 1] = "FECACA" if d["cc"] else None
        w.row(vals, bold0=True, fills=fills)
    end = w.r - 1
    w.widths([24, 7, 9, 8, 8, 7, 8] + [6] * levels + [9, 5, 8, 10, 9, 12, 10, 30])
    ws.freeze_panes = ws.cell(start, 2)
    if end >= start:
        bc = BarChart(); bc.type = "bar"; bc.title = "Mean Overall % by assessor"; bc.legend = None
        bc.add_data(Reference(ws, min_col=5, min_row=start - 1, max_row=end), titles_from_data=True)
        bc.set_categories(Reference(ws, min_col=1, min_row=start, max_row=end))
        bc.series[0].graphicalProperties.solidFill = "094183"; bc.x_axis.delete = bc.y_axis.delete = False
        bc.height, bc.width = max(8, 0.5 * len(data)), 16
        ws.add_chart(bc, f"{get_column_letter(len(hdr) + 2)}3")
    writeRaterProfiles(ws, w, rows, examKey)                             # paired exams only (no-op otherwise)
    finishSheet(ws)


# ══ Students + follow-up ════════════════════════════════════════════════════
def cutOf(r, ssByTpl):
    blr = (ssByTpl.get(r["_tid"]) or {}).get("blr") or {}
    return blr.get("cut") if blr.get("ok") else None


def writeStudents(wb, rows, ssByTpl, examKey):
    bl = borderlineOf(examKey)
    by = defaultdict(list)
    for r in rows:
        by[(r["Student"], r["Cohort"])].append(r)
    if not by:
        return
    ws = wb.create_sheet(sheetName(wb, "Students")); w = SheetWriter(ws, 14)
    anyPaired = any(r.get("_paired") for r in rows)
    w.title("Students", "One row per student · Review = any GR ≤ borderline, critical concern, or Overall % below that checklist's BLR cut"
            + (" · paired (E1 + E2) rows: Mean / Lowest GR use BOTH examiners' primary ratings, Assessors lists both" if anyPaired else ""))
    w.header(["Student", "Cohort", "Forms", "Submitted", "Checklists", "Mean %", "Min %", "Max %", "Mean GR", "Lowest GR",
              "CC", "Below BLR cut", "Review", "Assessors"], fill="010D44", color="FFFFFF")
    out = []
    for (stu, coh), rs in by.items():
        sr = [r for r in rs if r["Submitted"] == "Yes"]
        ps = [r["Pct"] for r in sr if r["Pct"] >= 0]
        grs = [g for r in sr for g in ratingValues(r)]                     # paired: E1 + E2 ratings
        below = sum(1 for r in sr if cutOf(r, ssByTpl) is not None and basePct(r) is not None and basePct(r) < cutOf(r, ssByTpl))
        cc = sum(r["CC_int"] for r in rs)
        review = bool(cc or below or (grs and min(grs) <= bl))
        out.append([stu, coh, len(rs), len(sr), ", ".join(sorted({r["Checklist"] for r in rs})),
                    rnd(np.mean(ps)) if ps else None, rnd(min(ps)) if ps else None, rnd(max(ps)) if ps else None,
                    rnd(np.mean(grs), 2) if grs else None, min(grs) if grs else None, cc, below, "Yes" if review else "",
                    ", ".join(sorted({a for r in rs for a in ((r["Assessor1"], r["Assessor2"]) if r.get("_paired") else (r["Assessor"],))
                                      if a and a != "—"}))])
    out.sort(key=lambda v: (v[12] != "Yes", v[5] if v[5] is not None else 999))
    start = w.r
    for v in out:
        w.row(v, bold0=True, fills=[None] * 5 + [pctFill(v[5]), pctFill(v[6]), None, None, GR_FILL.get(v[9]),
                                                 "FECACA" if v[10] else None, "FED7AA" if v[11] else None, "FECACA" if v[12] else None])
    w.widths([24, 8, 7, 9, 26, 8, 8, 8, 9, 9, 5, 12, 8, 40])
    ws.freeze_panes = ws.cell(start, 2)
    ws.auto_filter.ref = f"A{start - 1}:N{w.r - 1}"
    finishSheet(ws)


def writeFollowUp(wb, rows, ssByTpl, examKey):
    bl = borderlineOf(examKey)
    items = []
    for r in rows:
        why = []
        if r["CC_int"]:
            why.append("Critical concern")
        if r["_incomplete"]:
            why.append("Submitted incomplete: " + "; ".join(r["_incomplete"]))
        elif r["_missing"]:
            why.append("Not in form: " + r["Missing"])
        if r["Status"] != "Submitted":
            why.append(r["Status"])
        low = min(ratingValues(r)) if ratingValues(r) else None              # paired: lower of E1 / E2
        if r["Submitted"] == "Yes" and low is not None and low <= bl:
            why.append(f"GR {low} ≤ borderline" + (" (lower of E1/E2)" if r.get("_paired") else ""))
        if r.get("_paired"):
            why += r["_pairIssues"]
            a, b = ratingPair(r)
            if a is not None and b is not None and abs(b - a) >= 2:
                why.append(f"Examiners differ by {abs(b - a)} levels (E1 {a}, E2 {b})")
        c = cutOf(r, ssByTpl)
        if r["Submitted"] == "Yes" and c is not None and basePct(r) is not None and basePct(r) < c:
            why.append(f"Below BLR cut ({basePct(r):.1f} < {c:.1f})")
        if r.get("_unsafe"):
            why.append("UNSAFE — auto fail")
        elif r.get("_outcome") and 0 <= r["Pct"] < (cfg.PROFILES[r["_profile"]].get("matrix") or {}).get("passMark", 50):
            why.append(f"Below pass mark ({r['_outcome']})")
        if r.get("_overrideNote"):
            why.append("Override applied")
        if why:
            items.append((r, why))
    ws = wb.create_sheet(sheetName(wb, "Follow-up")); w = SheetWriter(ws, 11)
    w.title("Follow-up", f"{len(items)} forms need attention (critical concerns first)")
    w.header(["Date", "Student", "Assessor", "Cohort", "Checklist", "Status", "GR", "Overall %", "Reasons", "Critical / general comments", "Form ID"],
             fill="010D44", color="FFFFFF")
    items.sort(key=lambda x: (-x[0]["CC_int"], x[0]["_stateRank"], -x[0]["_ts"]))
    for r, why in items:
        crit = " | ".join(f"{lbl + ': ' if lbl else ''}{str(e['_ad'].get(k) or '').strip()}" for lbl, e in formsOf(r)
                          for k in ("critical_concerns_comments", "critical_error", "clinical_incident") if core.meaningful(e["_ad"].get(k))) \
            or " | ".join(f"{lbl + ': ' if lbl else ''}{(e['_ad'].get('comments') or '').strip()}" for lbl, e in formsOf(r)
                          if (e["_ad"].get("comments") or "").strip())
        gShow = (min(ratingValues(r)) if ratingValues(r) else None) if r.get("_paired") else (r["GR_int"] if r["GR_int"] > 0 else None)
        asr = f"E1 {r['Assessor1']} · E2 {r['Assessor2']}" if r.get("_paired") else r["Assessor"]
        w.row([r["Date"], r["Student"], asr, r["Cohort"], r["Checklist"], r["Status"],
               gShow, r["Pct"] if r["Pct"] >= 0 else None, " · ".join(why), crit, r["_id"]],
              fills=[None] * 6 + [GR_FILL.get(gShow), pctFill(r["Pct"]), "FECACA" if r["CC_int"] else "FEF3C7"])
    w.widths([12, 22, 20, 8, 16, 11, 5, 9, 60, 60, 8])
    ws.freeze_panes = "C5"
    finishSheet(ws)


# ══ Double marking ══════════════════════════════════════════════════════════
def linearKappa(a, b):
    """Linearly weighted Cohen's κ for two raters' integer levels (None if undefined)."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    cats = sorted({v for p in pairs for v in p})
    if len(cats) < 2:
        return None
    k, n = len(cats), len(pairs); idx = {c: i for i, c in enumerate(cats)}
    obs = np.zeros((k, k))
    for x, y in pairs:
        obs[idx[x], idx[y]] += 1
    obs /= n
    exp = np.outer(obs.sum(axis=1), obs.sum(axis=0))
    wgt = np.array([[abs(i - j) / (k - 1) for j in range(k)] for i in range(k)])
    de = (wgt * exp).sum()
    return float(1 - (wgt * obs).sum() / de) if de else None


def writeDoubleMarking(wb, rows, templates):
    """Students with ≥ 2 submitted forms on the same checklist: E1 vs E2 (by form id = submission order)."""
    groups = defaultdict(list)
    for r in rows:
        if r["Submitted"] == "Yes" and basePct(r) is not None and r["_tid"]:
            groups[(r["_tid"], r["Student"], r["Cohort"])].append(r)
    pairs = {k: sorted(v, key=lambda r: r["_id"] or 0) for k, v in groups.items() if len(v) >= 2}
    if len(pairs) < 3:
        return
    gap = cfg.DOUBLE_MARK_GAP
    ws = wb.create_sheet(sheetName(wb, "Double Marking")); w = SheetWriter(ws, 12)
    w.title("Double marking — examiner agreement",
            f"{len(pairs)} student × checklist pairs · E1 / E2 = form id order (submission order) · flag when |gap| ≥ {gap:g} %-points · "
            f"Final % = mean of all that student's forms")
    for tid in templates:
        tp = {k: v for k, v in pairs.items() if k[0] == tid}
        if not tp:
            continue
        tpl = templates[tid]
        e1 = [basePct(v[0]) for v in tp.values()]; e2 = [basePct(v[1]) for v in tp.values()]
        diffs = [b - a for a, b in zip(e1, e2)]
        w.bar(f"{tpl['label']} — {len(tp)} double-marked students")
        nFlag = sum(1 for d in diffs if abs(d) >= gap)
        w.row(["Pairs", len(tp), "Mean |gap|", rnd(np.mean(np.abs(diffs))), f"Gap ≥ {gap:g}", f"{nFlag} ({100 * nFlag / len(tp):.0f}%)",
               "Mean E2 − E1", rnd(np.mean(diffs)), "r (E1, E2)", rnd(pearsonR(e1, e2), 3)],
              fills=["F1F5F9", None, "F1F5F9", None, "F1F5F9", "FED7AA" if nFlag else None, "F1F5F9", None, "F1F5F9", None])
        icols = itemColumns([r for v in tp.values() for r in v], tpl)
        if icols:
            w.header(["Item", "Question", "Exact agreement %", "Linear weighted κ", "Mean |level gap|"])
            for c in icols:
                a = [(itemLookup(v[0]).get((c[0], c[1])) or {}).get("points") for v in tp.values()]
                b = [(itemLookup(v[1]).get((c[0], c[1])) or {}).get("points") for v in tp.values()]
                both = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
                ag = 100 * sum(1 for x, y in both if x == y) / len(both) if both else None
                kap = linearKappa(a, b)
                w.row([c[1], (c[4] or "")[:70], rnd(ag), rnd(kap, 3), rnd(np.mean([abs(x - y) for x, y in both]), 2) if both else None],
                      fills=[None, None, pctFill(ag), None if kap is None else ("BBFFD9" if kap >= .6 else "FEF08A" if kap >= .4 else "FECACA")])
        w.header(["Student", "Cohort", "E1 assessor", "E1 %", "E2 assessor", "E2 %", "Gap (E2 − E1)", "|Gap| flag",
                  "Final %", "Forms", "E1 outcome", "E2 outcome"])
        for (tid_, stu, coh), v in sorted(tp.items(), key=lambda kv: -abs(basePct(kv[1][1]) - basePct(kv[1][0]))):
            a, b = basePct(v[0]), basePct(v[1]); d = b - a
            fin = float(np.mean([basePct(x) for x in v]))
            w.row([stu, coh, v[0]["Assessor"], rnd(a), v[1]["Assessor"], rnd(b), rnd(d), "Yes" if abs(d) >= gap else "",
                   rnd(fin), len(v), v[0].get("_outcome", ""), v[1].get("_outcome", "")],
                  bold0=True, fills=[None, None, None, pctFill(a), None, pctFill(b), None, "FED7AA" if abs(d) >= gap else None, pctFill(fin)])
        w.gap()
    w.widths([24, 30, 20, 8, 20, 8, 12, 10, 9, 7, 30, 30])
    finishSheet(ws)


# ══ Paired examiners (BOH viva: Examiner 1 + Examiner 2 forms → one row per student) ═══════════════
SCALE_SHORT = {"scale-global-rating": "GR", "scale-practice-readiness": "RTP",
               "scale-global-rating-om": "GR OM", "scale-global-rating-os": "GR OS"}


def scaleShort(key: str, name: str = "") -> str:
    """Column label for a scale: GR / RTP, else its name."""
    return SCALE_SHORT.get(key, name or key)


def scaleMap(r) -> dict:
    """{scale key: scale dict} for one form (primary GR + extra scales)."""
    return {s["key"]: s for s in ([r["_gr"]] if r.get("_gr") else []) + list(r.get("_extraScales") or [])}


def pickForm(forms: list):
    """One form per examiner role: submitted first, then latest date, then highest id."""
    return max(forms, key=lambda r: (r["Submitted"] == "Yes", r["_ts"], r["_id"] or 0)) if forms else None


def makeSitting(e1, e2, nForms: int, examKey: str) -> dict:
    """Merge one student's Examiner 1 and Examiner 2 forms. Score, sections, items come from E2 (the scorer)."""
    base = e2 or e1
    s = dict(base)
    pref = cfg.EXAMS[examKey].get("grScales", [])
    maps = {1: scaleMap(e1) if e1 else {}, 2: scaleMap(e2) if e2 else {}}
    keys = [k for k in pref if k in maps[1] or k in maps[2]]
    keys += [k for k in list(maps[2]) + list(maps[1]) if k not in keys]
    ratings, info = OrderedDict(), {}
    for k in keys:
        ratings[k] = ((maps[1].get(k) or {}).get("value"), (maps[2].get(k) or {}).get("value"))
        sc = maps[2].get(k) or maps[1].get(k)
        info[k] = {"name": sc["name"], "fields": sc["fields"], "short": scaleShort(k, sc["name"])}
    ratingKey = next((k for k in keys if any(v is not None for v in ratings[k])), keys[0] if keys else None)
    issues = []
    for lbl, e in (("Examiner 1", e1), ("Examiner 2", e2)):
        if e is None:
            issues.append(f"{lbl} form missing")
        elif e["Submitted"] != "Yes":
            issues.append(f"{lbl} not submitted")
    extra = nForms - (e1 is not None) - (e2 is not None)
    if extra > 0:
        issues.append(f"{extra} extra form(s) ignored")
    present = [(lbl, e) for lbl, e in (("E1", e1), ("E2", e2)) if e]
    ccFlag = any(e["CC_int"] for _, e in present)
    com = []
    for lbl, e in present:
        for line in (e["Comments"] or "").split("\n"):
            if line.strip() and line.strip() != "—":
                com.append(f"[{lbl} {line[1:]}" if line.startswith("[") else f"[{lbl}] {line}")
    s.update(_paired=True, _e1=e1, _e2=e2, _nForms=nForms, _ratings=ratings, _scaleInfo=info, _ratingKey=ratingKey,
             _pairIssues=issues, Assessor1=e1["Assessor"] if e1 else "—", Assessor2=e2["Assessor"] if e2 else "—",
             Assessor=(e2 or e1)["Assessor"], Examiner=e1["Assessor"] if e1 else "—",
             CC_int=1 if ccFlag else 0,
             CC=" · ".join(f"{lbl}: {e['CC']}" for lbl, e in present if e["CC"] != "—") or "—",
             Comments="\n".join(com) or "—")
    return s


def pairSittings(examKey: str, rows: list) -> list:
    """Exams with 'pairing': forms with an examiner role → one row per student (at the first form's position)."""
    pc = cfg.EXAMS[examKey].get("pairing")
    if not pc:
        return rows
    scorer, other = pc.get("scorerRole", 2), pc.get("otherRole", 1)
    out, groups = [], OrderedDict()
    for r in rows:
        if r.get("_role") in (scorer, other):
            k = tuple(r[f] for f in pc.get("matchOn", ["Student", "Cohort"]))
            if k not in groups:
                groups[k] = {}
                out.append(("__pair__", k))
            groups[k].setdefault(r["_role"], []).append(r)
        else:
            out.append(r)                                                   # no role (e.g. DDS4 viva): unchanged
    res = []
    for x in out:
        if isinstance(x, tuple) and x[0] == "__pair__":
            g = groups[x[1]]
            res.append(makeSitting(pickForm(g.get(other, [])), pickForm(g.get(scorer, [])),
                                   sum(len(v) for v in g.values()), examKey))
        else:
            res.append(x)
    return res


def ratingPair(r, key=None):
    """(E1, E2) value of one scale (default: the primary rating) for a paired row."""
    key = key or r.get("_ratingKey")
    return (r.get("_ratings") or {}).get(key, (None, None))


def ratingValues(r) -> list:
    """All primary ratings on a row: both examiners when paired, else the form's GR."""
    if r.get("_paired"):
        return [v for v in ratingPair(r) if v is not None]
    return [r["GR_int"]] if r["GR_int"] > 0 else []


def formsOf(r) -> list:
    """[(label, form row)] behind a row: E1 + E2 when paired, else the row itself."""
    if r.get("_paired"):
        return [(lbl, e) for lbl, e in (("E1", r["_e1"]), ("E2", r["_e2"])) if e]
    return [("", r)]


def pairedRecordColumns(rows, templates):
    """Records / summary columns for paired rows: one row per student, E1 and E2 side by side."""
    tids = {r["_tid"] for r in rows}
    tpl = templates.get(next(iter(tids))) if len(tids) == 1 else None
    keys = list(OrderedDict.fromkeys(k for r in rows for k in r["_ratings"]))
    info = {}
    for r in rows:
        info.update({k: v for k, v in r["_scaleInfo"].items() if k not in info})
    cols = [("E2 form ID", lambda r: r["_e2"]["_id"] if r["_e2"] else None, None),
            ("E1 form ID", lambda r: r["_e1"]["_id"] if r["_e1"] else None, None),
            ("Date", lambda r: r["Date"], None), ("Student", lambda r: r["Student"], None),
            ("Assessor 1 (E1)", lambda r: r["Assessor1"], None), ("Assessor 2 (E2, scorer)", lambda r: r["Assessor2"], None),
            ("Cohort", lambda r: r["Cohort"], None), ("Subject", lambda r: r["Subject"], None),
            ("Checklist", lambda r: r["Checklist"], None),
            ("Status (E2)", lambda r: r["_e2"]["Status"] if r["_e2"] else "—",
             lambda v, r: {"Submitted": "BBFFD9", "In progress": "FEF08A"}.get(v, "FECACA")),
            ("Status (E1)", lambda r: r["_e1"]["Status"] if r["_e1"] else "—",
             lambda v, r: {"Submitted": "BBFFD9", "In progress": "FEF08A"}.get(v, "FECACA")),
            ("Pairing issues", lambda r: "; ".join(r["_pairIssues"]), lambda v, r: "FED7AA" if v else None),
            ("Items scored", lambda r: f'{r["_scored"]}/{r["_nItems"]}' if r["_nItems"] else "", None)]
    for k in keys:
        sh = info[k]["short"]
        cols += [(f"{sh} E1", (lambda r, k=k: ratingPair(r, k)[0]), lambda v, r: GR_FILL.get(v)),
                 (f"{sh} E2", (lambda r, k=k: ratingPair(r, k)[1]), lambda v, r: GR_FILL.get(v)),
                 (f"{sh} Δ (E2 − E1)", (lambda r, k=k: (ratingPair(r, k)[1] - ratingPair(r, k)[0])
                                        if None not in ratingPair(r, k) else None),
                  lambda v, r: "FED7AA" if v is not None and abs(v) >= 2 else None)]
    if tpl:
        for sk, nm, short in tpl["sections"]:
            cols.append((f"{short} %", (lambda r, sk=sk: rnd((r["_sec"].get(sk) or {}).get("pct"))),
                         (lambda v, r, sk=sk: "FEF3C7" if sk in r["_sec"] and not r["_sec"][sk]["present"] else pctFill(v))))
    cols += [("Total", lambda r: r["Total"], None), ("Max", lambda r: r["Max"], None),
             ("Overall %", lambda r: r["Pct"] if r["Pct"] >= 0 else None, lambda v, r: pctFill(v)),
             ("Overall % before override", lambda r: basePct(r), None),
             ("Override", lambda r: r.get("_overrideNote") or "", lambda v, r: "FECACA" if v else None),
             ("Critical (E1 · E2)", lambda r: r["CC"], lambda v, r: "FECACA" if r["CC_int"] else None),
             ("Submitted incomplete (E2)", lambda r: "; ".join(r["_incomplete"]), lambda v, r: "FED7AA" if v else None),
             ("Comments E1", lambda r: (r["_e1"]["Comments"] if r["_e1"] and r["_e1"]["Comments"] != "—" else ""), None),
             ("Comments E2", lambda r: (r["_e2"]["Comments"] if r["_e2"] and r["_e2"]["Comments"] != "—" else ""), None)]
    return cols


def writeStandardSettingPaired(wb, title, rows, tpl, examKey):
    """Paired rows: BLR + BGM on Overall % against E2's rating, E1's rating and their mean, side by side."""
    bl = borderlineOf(examKey)
    sub = [r for r in rows if r["Submitted"] == "Yes" and basePct(r) is not None]
    key = next((r["_ratingKey"] for r in sub if r.get("_ratingKey")), None)
    if not sub or key is None:
        return {"blr": {}, "bgm": {}, "checks": [], "n": 0, "sections": [], "skipped": "no ratings"}
    info = next(r["_scaleInfo"][key] for r in sub if key in r["_scaleInfo"])
    levels = max([len(info["fields"]) or 5] + [v for r in sub for v in ratingPair(r, key) if v])
    mean2 = lambda r: (sum(ratingPair(r, key)) / 2) if None not in ratingPair(r, key) else None
    sources = [("E2 (scorer)", lambda r: ratingPair(r, key)[1]), ("E1 (independent)", lambda r: ratingPair(r, key)[0]),
               ("Mean E1+E2", mean2)]
    res = []
    for lbl, fn in sources:
        pts = [(fn(r), basePct(r), r) for r in sub if fn(r) is not None]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        blr, bgm = computeBlr(xs, ys, bl), computeBgm(xs, ys, bl)
        res.append({"label": lbl, "pts": pts, "xs": xs, "ys": ys, "blr": blr, "bgm": bgm,
                    "checks": viabilityChecks(xs, ys, blr, bgm, bl) if pts else []})
    ws = wb.create_sheet(sheetName(wb, title)); w = SheetWriter(ws, 7)
    blName = info["fields"].get(str(bl), "")
    w.title(f"Standard Setting — {tpl['label']} · {info['short']} by examiner (borderline = {bl}: {blName})",
            f"{len(sub)} students (E1 + E2 merged). Overall % (pre-penalty) from Examiner 2's checklist, regressed on E2's "
            f"rating, E1's independent rating and their mean. Mean: BGM borderline group = mean exactly {bl} "
            f"(e.g. {bl}+{bl} or {bl - 1}+{bl + 1}). No recommended cut.")
    f = lambda v, d=1: "—" if v is None or v != v else round(v, d)
    w.bar("Cut scores by rating source")
    w.header(["Statistic"] + [f"{x['label']} · {m}" for x in res for m in ("BLR", "BGM")])
    def both(fnB, fnG):                                                 # BLR, BGM value per source
        return [v for x in res for v in ((fnB(x["blr"]) if x["blr"].get("ok") else "—"),
                                         (fnG(x["bgm"]) if x["bgm"].get("nB") else "—"))]
    rowsT = [("Cut score (Overall %)", lambda b: f(b["cut"]), lambda g: f(g["cut"])),
             ("95% CI", lambda b: f"{b['cutLo']:.1f} – {b['cutHi']:.1f}",
              lambda g: f"{g['cutLo']:.1f} – {g['cutHi']:.1f}" if g["nB"] > 1 else "—"),
             ("Candidates used", lambda b: b["n"], lambda g: g["nB"]),
             ("Pass at this cut", lambda b: f"{b['nPass']}/{b['n']}", lambda g: f"{g['nPass']}/{len(sub)}"),
             ("Slope (%-pts per level) / borderline SD", lambda b: f(b["slope"], 2), lambda g: f(g["sd"])),
             ("R² / borderline median", lambda b: f(b["r2"], 3), lambda g: f(g["median"]))]
    for name, fb, fg in rowsT:
        w.row([name] + both(fb, fg), bold0=True,
              fills=[None] + ["E0E7FF" if i % 2 == 0 else None for i in range(6)])
    w.gap()
    w.bar("Viability tests (PASS / WARN / FAIL per source)")
    w.header(["Test"] + [f"{x['label']} value" if j == 0 else "Result" for x in res for j in (0, 1)])
    tests = list(OrderedDict.fromkeys(f"[{c[0]}] {c[1]}" for x in res for c in x["checks"]))
    for t in tests:
        vals, fills = [t], [None]
        for x in res:
            c = next((c for c in x["checks"] if f"[{c[0]}] {c[1]}" == t), None)
            vals += [c[2] if c else "—", c[4] if c else "—"]; fills += [None, FLAG_FILL.get(c[4]) if c else None]
        w.row(vals, fills=fills, wrap=True)
    w.gap()
    w.bar("Overall % by rating level")
    steps = [x / 2 for x in range(2, 2 * levels + 1)]
    w.header(["Rating", "Label"] + [x["label"] for x in res])
    gmStart = w.r
    for st in steps:
        lab = info["fields"].get(str(int(st)), "") if float(st).is_integer() else "(mean only)"
        cells, fills = [st if not float(st).is_integer() else int(st), lab[:40]], [None, None]
        for x in res:
            v = [y for xx, y in zip(x["xs"], x["ys"]) if xx == st]
            cells.append(f"{sum(v) / len(v):.1f} (n={len(v)})" if v else "—"); fills.append(pctFill(sum(v) / len(v)) if v else None)
        if any(c != "—" for c in cells[2:]):
            w.row(cells, fills=[("FED7AA" if st == bl else None)] + fills[1:])
    w.gap()
    w.bar("Per-section BLR cut (section % vs rating)")
    w.header(["Section"] + [x["label"] for x in res])
    for sk, nm, short in tpl["sections"]:
        cells = [f"{short} · {nm}"[:60]]
        for (lbl, fn), x in zip(sources, res):
            dx, dy = [], []
            for r in sub:
                sct = r["_sec"].get(sk)
                if fn(r) is not None and sct and sct["pct"] is not None:
                    dx.append(fn(r)); dy.append(sct["pct"])
            db = computeBlr(dx, dy, bl)
            cells.append(f"{db['cut']:.1f} (R² {db['r2']:.2f})" if db.get("ok") else "—")
        w.row(cells, bold0=True)
    w.widths([40, 20, 20, 20, 20, 20, 20])
    dc = 30                                                               # chart data (visible; charts skip hidden cells)
    ws.cell(1, dc - 1, "Chart data →").font = xFont(True, size=8, color="94A3B8")
    colours = ["094183", "E87722", "10B981"]
    sc = ScatterChart(); sc.style = 13; sc.title = f"Overall % vs {info['short']} — E2, E1, mean"
    sc.x_axis.title, sc.y_axis.title = info["short"], "Overall %"
    sc.x_axis.scaling.min, sc.x_axis.scaling.max, sc.x_axis.majorUnit = 1, levels, 1
    sc.y_axis.scaling.min, sc.y_axis.scaling.max = 0, 100
    sc.x_axis.delete = sc.y_axis.delete = False; sc.height, sc.width = 10, 16
    for j, x in enumerate(res):
        c0 = dc + 3 * j
        ws.cell(1, c0, f"{x['label']} rating").font = xFont(size=8, color="94A3B8")
        ws.cell(1, c0 + 1, "Overall %").font = xFont(size=8, color="94A3B8")
        for i, (g, pc_, _) in enumerate(x["pts"], 2):
            ws.cell(i, c0, g).font = xFont(size=8, color="94A3B8"); ws.cell(i, c0 + 1, pc_).font = xFont(size=8, color="94A3B8")
        if len(x["pts"]) >= 2:
            se = Series(Reference(ws, min_col=c0 + 1, min_row=2, max_row=len(x["pts"]) + 1),
                        Reference(ws, min_col=c0, min_row=2, max_row=len(x["pts"]) + 1),
                        title=f"{x['label']}" + (f" (cut {x['blr']['cut']:.1f})" if x["blr"].get("ok") else ""))
            se.marker = Marker(symbol=["circle", "triangle", "diamond"][j], size=6)
            se.marker.graphicalProperties.solidFill = colours[j]; se.graphicalProperties.line.noFill = True
            if x["blr"].get("ok"):
                se.trendline = Trendline(trendlineType="linear")
            sc.series.append(se)
    if sc.series:
        ws.add_chart(sc, "I3")
    finishSheet(ws)
    ws.print_area = f"A1:Q{max(w.r, 44)}"
    ref = next((x for x in (res[2], res[0], res[1]) if x["blr"].get("ok")), res[0])   # flags: mean, else E2, else E1
    return {"blr": ref["blr"], "bgm": ref["bgm"], "checks": ref["checks"], "n": len(sub), "sections": [],
            "refLabel": ref["label"], "variants": {x["label"]: (x["blr"], x["bgm"]) for x in res}}


def writeExaminerAgreement(wb, rows):
    """Paired rows: E1 vs E2 agreement on every rating scale, by examiner pair, and the ≥ 2-level disagreements."""
    pr = [r for r in rows if r.get("_paired") and r["_e1"] and r["_e2"]]
    keys = list(OrderedDict.fromkeys(k for r in pr for k in r["_ratings"]))
    if not pr or not any(sum(1 for r in pr if None not in ratingPair(r, k)) >= 3 for k in keys):
        return
    info = {}
    for r in pr:
        info.update({k: v for k, v in r["_scaleInfo"].items() if k not in info})
    ws = wb.create_sheet(sheetName(wb, "Examiner Agreement")); w = SheetWriter(ws, 10)
    w.title("Examiner agreement — Examiner 1 vs Examiner 2",
            f"{len(pr)} students with both forms · κ = linear weighted Cohen's kappa · adjacent = within one level")
    for k in keys:
        both = [ratingPair(r, k) for r in pr if None not in ratingPair(r, k)]
        if len(both) < 3:
            continue
        a, b = [x for x, _ in both], [y for _, y in both]
        nLev = max([len(info[k]["fields"]) or 5] + a + b)
        diffs = [y - x for x, y in both]
        kap = linearKappa(a, b); rho = spearman(a, b)[0]
        w.bar(f"{info[k]['short']} — {info[k]['name']} ({len(both)} pairs)")
        w.row(["Exact agreement", f"{100 * sum(1 for d in diffs if d == 0) / len(diffs):.0f}%",
               "Adjacent (±1)", f"{100 * sum(1 for d in diffs if abs(d) <= 1) / len(diffs):.0f}%",
               "Mean E2 − E1", rnd(float(np.mean(diffs)), 2), "Linear κ", rnd(kap, 3), "Spearman ρ", rnd(rho, 3)],
              fills=["F1F5F9", None, "F1F5F9", None, "F1F5F9", None, "F1F5F9",
                     None if kap is None else ("BBFFD9" if kap >= .6 else "FEF08A" if kap >= .4 else "FECACA"), "F1F5F9", None])
        w.header(["E1 ↓ / E2 →"] + [str(g) for g in range(1, nLev + 1)] + ["Total"])
        for g1 in range(1, nLev + 1):
            cnt = [sum(1 for x, y in both if x == g1 and y == g2) for g2 in range(1, nLev + 1)]
            w.row([f"{g1} {info[k]['fields'].get(str(g1), '')[:30]}"] + cnt + [sum(cnt)], bold0=True,
                  fills=[None] + [("BBFFD9" if g1 == g2 and c else "FED7AA" if abs(g1 - g2) >= 2 and c else None)
                                  for g2, c in zip(range(1, nLev + 1), cnt)])
        w.gap()
    pk = next((k for k in keys if sum(1 for r in pr if None not in ratingPair(r, k)) >= 1), None)
    if pk:
        w.bar(f"By examiner pair ({info[pk]['short']})")
        w.header(["Examiner 1", "Examiner 2", "Students", "Exact %", "Mean E2 − E1", "Pairs ≥ 2 apart"])
        byPair = defaultdict(list)
        for r in pr:
            if None not in ratingPair(r, pk):
                byPair[(r["Assessor1"], r["Assessor2"])].append(ratingPair(r, pk))
        for (x1, x2), v in sorted(byPair.items(), key=lambda kv: -len(kv[1])):
            d = [b - a for a, b in v]
            w.row([x1, x2, len(v), rnd(100 * sum(1 for z in d if z == 0) / len(d)), rnd(float(np.mean(d)), 2),
                   sum(1 for z in d if abs(z) >= 2)], fills=[None] * 5 + ["FED7AA" if any(abs(z) >= 2 for z in d) else None])
        w.gap()
    w.bar("Students where the examiners differ by 2 or more levels")
    w.header(["Student", "Scale", "E1", "E2", "Examiner 1", "Examiner 2", "Overall %", "Comments E1", "Comments E2"])
    nBig = sum(1 for r in pr for k in keys if None not in ratingPair(r, k) and abs(ratingPair(r, k)[1] - ratingPair(r, k)[0]) >= 2)
    if not nBig:
        w.para("None — every pair of ratings is within one level.", color="15803D")
    for r in pr:
        for k in keys:
            a, b = ratingPair(r, k)
            if a is not None and b is not None and abs(b - a) >= 2:
                w.row([r["Student"], info[k]["short"], a, b, r["Assessor1"], r["Assessor2"], r["Pct"] if r["Pct"] >= 0 else None,
                       r["_e1"]["Comments"] if r["_e1"]["Comments"] != "—" else "",
                       r["_e2"]["Comments"] if r["_e2"]["Comments"] != "—" else ""],
                      bold0=True, fills=[None, None, GR_FILL.get(a), GR_FILL.get(b)], wrap=True)
    w.widths([26, 22, 9, 9, 20, 20, 10, 50, 50, 10])
    finishSheet(ws)


def writeRaterProfiles(ws, w, rows, examKey):
    """Assessors sheet, paired exams: ratings each examiner gave as E1 and as E2, and vs their partner."""
    bl = borderlineOf(examKey)
    pr = [r for r in rows if r.get("_paired")]
    if not pr:
        return
    stats = defaultdict(lambda: {"E1": [], "E2": [], "diff": []})
    for r in pr:
        a, b = ratingPair(r)
        if r["_e1"] and a is not None:
            stats[r["Assessor1"]]["E1"].append(a)
            if b is not None:
                stats[r["Assessor1"]]["diff"].append(a - b)
        if r["_e2"] and b is not None:
            stats[r["Assessor2"]]["E2"].append(b)
            if a is not None:
                stats[r["Assessor2"]]["diff"].append(b - a)
    key = next((r["_ratingKey"] for r in pr if r.get("_ratingKey")), "")
    sh = next((r["_scaleInfo"][key]["short"] for r in pr if key in r.get("_scaleInfo", {})), "rating")
    w.gap()
    w.bar(f"Global ratings by examiner role ({sh}) — own rating minus partner's rating for the same student")
    w.header(["Assessor", "Rated as E1", f"Mean {sh} as E1", "Rated as E2", f"Mean {sh} as E2", f"% ≤ {bl}",
              "Mean (own − partner)", "Tendency"], fill="010D44", color="FFFFFF")
    for asr, s in sorted(stats.items(), key=lambda kv: -(len(kv[1]["E1"]) + len(kv[1]["E2"]))):
        allR = s["E1"] + s["E2"]
        d = float(np.mean(s["diff"])) if s["diff"] else None
        tend = "" if d is None or len(s["diff"]) < 3 else ("Higher than partner" if d >= 0.5 else "Lower than partner" if d <= -0.5 else "In line")
        w.row([asr, len(s["E1"]), rnd(np.mean(s["E1"]), 2) if s["E1"] else None, len(s["E2"]),
               rnd(np.mean(s["E2"]), 2) if s["E2"] else None, rnd(100 * sum(1 for v in allR if v <= bl) / len(allR)) if allR else None,
               rnd(d, 2), tend], bold0=True,
              fills=[None] * 7 + [{"Higher than partner": "FED7AA", "Lower than partner": "FECACA", "In line": "D1FAE5"}.get(tend)])


# ══ Roster ══════════════════════════════════════════════════════════════════
def loadRoster():
    roster = {}
    try:
        with open(core.APP_DIR / cfg.ROSTER_CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                ch, nm = (r.get("cohort") or "").strip().upper(), (r.get("student_name") or "").strip()
                if ch and nm:
                    roster.setdefault(ch, {})[core.normName(nm)] = nm
    except FileNotFoundError:
        return None
    return roster


def writeRoster(wb, rows):
    roster = loadRoster()
    if roster is None:
        return
    ws = wb.create_sheet(sheetName(wb, "Roster")); w = SheetWriter(ws, 6)
    w.title("Roster check", f"Forms vs {cfg.ROSTER_CSV} (names matched case/space-insensitive, nicknames in brackets ignored)")
    seen, disp, perCk = defaultdict(set), {}, defaultdict(lambda: defaultdict(int))
    for r in rows:
        ch, n = r["Cohort"].upper(), core.normName(r["Student"])
        seen[ch].add(n); disp[n] = r["Student"]; perCk[ch][(n, r["Checklist"])] += 1
    for ch in sorted(seen):
        rost = roster.get(ch, {})
        missing = sorted(rost[n] for n in rost if n not in seen[ch])
        extra = sorted(disp[n] for n in seen[ch] if n not in rost)
        dups = sorted(f"{disp[n]} — {ck} (x{c})" for (n, ck), c in perCk[ch].items() if c > 1)
        w.bar(f"{ch} · enrolled {len(rost)} · present {len(seen[ch] & set(rost))} · missing {len(missing)} · "
              f"off-roster {len(extra)} · same checklist twice {len(dups)}", "010D44")
        w.header(["Missing (no form)", "Off-roster (form, not enrolled)", "Same checklist more than once"])
        for i in range(max(len(missing), len(extra), len(dups), 1)):
            w.row([missing[i] if i < len(missing) else "", extra[i] if i < len(extra) else "", dups[i] if i < len(dups) else ""],
                  fills=["FECACA" if i < len(missing) else None, "FED7AA" if i < len(extra) else None, "FEF9C3" if i < len(dups) else None])
        w.gap()
    w.widths([32, 32, 40])
    finishSheet(ws, False)


# ══ Overview ════════════════════════════════════════════════════════════════
def writeOverview(wb, examKey, rows, ign, templates, ssByTpl, alphaByTpl, filterDesc, sheetsMade):
    ws = wb.create_sheet("Overview", 0); w = SheetWriter(ws, 8)
    exam = cfg.EXAMS[examKey]; bl = borderlineOf(examKey)
    w.title(f"DASH · {exam['title']} — detailed export",
            f"Exported {datetime.now():%d %b %Y %H:%M} · {cfg.APP_BUILD} · {filterDesc}")
    sub = [r for r in rows if r["Submitted"] == "Yes"]
    ps = [basePct(r) for r in sub if basePct(r) is not None]; grs = [r["GR_int"] for r in sub if r["GR_int"] > 0]
    w.bar("Key figures")
    kpis = [("Forms", len(rows)), ("Submitted", len(sub)), ("In progress", sum(r["Status"] == "In progress" for r in rows)),
            ("Not started", sum(r["Status"] == "Not started" for r in rows)),
            ("Submitted but incomplete", sum(1 for r in rows if r["_incomplete"])),
            ("Critical concerns", sum(r["CC_int"] for r in rows)), ("Students", len({r["Student"] for r in rows})),
            ("Assessors", len({r["Assessor"] for r in rows})), ("Mean Overall % (submitted)", rnd(np.mean(ps)) if ps else "—"),
            ("Mean GR (submitted)", rnd(np.mean(grs), 2) if grs else "—"),
            ("Forms by ignored assessors (excluded)", len(ign))]
    pairedRows = [r for r in rows if r.get("_paired")]
    if pairedRows:                                                        # BOH viva: E1 + E2 merged per student
        kpis += [("Students with E1 + E2 merged (one row each)", len(pairedRows)),
                 ("Both examiner forms submitted", sum(1 for r in pairedRows if not r["_pairIssues"])),
                 ("Missing / unsubmitted partner form", sum(1 for r in pairedRows if any("Examiner" in i for i in r["_pairIssues"]))),
                 ("Examiners ≥ 2 levels apart", sum(1 for r in pairedRows if None not in ratingPair(r) and abs(ratingPair(r)[1] - ratingPair(r)[0]) >= 2))]
    for i in range(0, len(kpis), 2):
        vals = []
        for k, v in kpis[i:i + 2]:
            vals += [k, v]
        w.row(vals, fills=["F1F5F9", None, "F1F5F9", None])
    w.gap()
    w.bar("Checklists in this export")
    w.header(["Checklist", "Scoring profile", "Forms", "Submitted", "Mean %", "α", "BLR cut (R²)", "BGM cut (n)"])
    for tid, tpl in templates.items():
        rs = [r for r in rows if r["_tid"] == tid]
        if not rs:
            continue
        ss = ssByTpl.get(tid) or {}; blr, bgm = ss.get("blr") or {}, ss.get("bgm") or {}
        p = [basePct(r) for r in rs if r["Submitted"] == "Yes" and basePct(r) is not None]
        w.row([tpl["label"], cfg.PROFILES[tpl["profile"]]["title"], len(rs), sum(r["Submitted"] == "Yes" for r in rs),
               rnd(np.mean(p)) if p else "—", rnd(alphaByTpl.get(tid), 3) if alphaByTpl.get(tid) is not None else "—",
               " · ".join(f"{lb.split(' ')[0]} {vb['cut']:.1f} ({vb['r2']:.2f})" for lb, (vb, _) in ss["variants"].items() if vb.get("ok")) or "—"
               if ss.get("variants") else (f"{blr['cut']:.1f} ({blr['r2']:.2f})" if blr.get("ok") else "—"),
               " · ".join(f"{lb.split(' ')[0]} {vg['cut']:.1f} ({vg['nB']})" for lb, (_, vg) in ss["variants"].items() if vg.get("nB")) or "—"
               if ss.get("variants") else (f"{bgm['cut']:.1f} ({bgm['nB']})" if bgm.get("nB") else "—")], bold0=True)
    w.gap()
    for tid, tpl in templates.items():
        rs = [r for r in rows if r["_tid"] == tid]
        if not rs:
            continue
        prof = cfg.PROFILES[tpl["profile"]]
        w.bar(f"How {tpl['label']} is scored — {prof['title']}")
        w.para(prof["guide"] + " Every form is scored against its OWN rubric, so form versions with different maxima are handled.")
        w.header(["Section", "Name", "Items", "Max points", "Weight"])
        weights = prof.get("weights")
        itemW = (prof.get("itemWeights") or {})
        for sk, nm, short in tpl["sections"]:
            its = {(it["ck"], it["mc"]) for r in rs for it in r["_items"] if it["secKey"] == sk}
            mx = next((r["_sec"][sk]["max"] for r in sorted(rs, key=lambda x: -x["_ts"]) if sk in r["_sec"] and r["_sec"][sk]["max"]), None)
            if weights:
                wt = f"{weights.get(short, 0):.0%}"
            elif prof.get("sectionsByItem") and itemW:
                wt = f"×{(itemW.get(tpl['keys'][0]) or {}).get(sk, 1):g}"
            else:
                wt = "equal" if prof["overall"] == "sections" else "—"
            w.row([short, nm, len(its), rnd(mx, 2), wt], bold0=True)
        if prof.get("matrix"):                                            # ECCA combined performance matrix
            mxc = prof["matrix"]; codes = list(mxc["rowLabels"])
            w.gap()
            w.header(["Presentation ↓ / Questioning →"] + [f"{c} — {mxc['colLabels'][c]}" for c in codes])
            for rc in codes:
                cells, fills = [f"{rc} — {mxc['rowLabels'][rc]}"], [None]
                for cc in codes:
                    pct, outc, _ = mxc["table"][(rc, cc)]
                    cells.append(f"{pct}% — {outc}"); fills.append(pctFill(pct))
                w.row(cells, bold0=True, fills=fills, wrap=True)
            w.para(f"Pass mark {mxc.get('passMark', 50)}%. Patient Safety = Unsafe → automatic fail: Overall % = "
                   f"min(matrix %, {mxc.get('unsafeCap', 45)}%). Full descriptors are in the form view and Records 'Outcome'.",
                   color="B91C1C")
            rsu = [r for r in rs if r["Submitted"] == "Yes" and r.get("_outcome")]
            if rsu:
                w.header(["Presentation ↓ / Questioning → (forms)"] + codes)
                codeOf = lambda r, rx: next((it["code"] for it in r["_items"] if re.search(rx, it["question"], re.I)), "")
                for rc in codes:
                    w.row([rc] + [sum(1 for r in rsu if codeOf(r, mxc["rowItem"]) == rc and codeOf(r, mxc["colItem"]) == cc)
                                  for cc in codes], bold0=True)
                w.para(f"Unsafe forms: {sum(1 for r in rsu if r.get('_unsafe'))} of {len(rsu)}.", color="475569")
        w.gap()
    grl = grLabels(rows)
    w.bar("Global rating scale (from the forms) and colour legend")
    w.header(["GR", "Label", "", "Cell colour", "Meaning"])
    leg = [("BBFFD9", "Full marks / ≥ 99%"), ("BFDBFE", "≥ 70%"), ("A5F3FC", "45–69%"), ("FEF08A", "> 0 and < 45%"),
           ("FECACA", "0 / critical concern / not submitted"), ("FEF3C7", "Section not in this form"),
           ("FED7AA", "Submitted but incomplete / borderline GR")]
    for i in range(max(len(grl), len(leg))):
        g = sorted(grl, reverse=True)[i] if i < len(grl) else None
        w.row([g, (grl[g] + (" ← borderline" if g == bl else "")) if g else "", "", "", leg[i][1] if i < len(leg) else ""],
              fills=[GR_FILL.get(g), None, None, leg[i][0] if i < len(leg) else None])
    w.gap()
    if pairedRows:
        w.bar("Paired examiners (BOH viva)")
        w.para("Each student has an Examiner 1 form (ratings + comments) and an Examiner 2 form (checklist + ratings + comments). "
               "They are merged into ONE row per student (matched on student + cohort; per examiner the submitted, latest form). "
               "Score, sections and items come from Examiner 2. Ratings and comments are shown for both (E1 / E2 / Δ). "
               "Std Setting shows BLR + BGM against E2's rating, E1's independent rating and their mean; Follow-up, Students and "
               "below-cut flags use the LOWER of the two ratings and the mean-rating BLR cut. Forms without an examiner role "
               "(e.g. DDS4 viva) are unchanged.")
        w.gap()
    w.bar("Sheets")
    guide = {"Records": "Every form: identity, status, GR, section %, total, overall, CC, overrides, comments (filterable)",
             "Follow-up": "Forms needing action, with reasons", "Students": "Per-student summary and review flag",
             "Scores": "MC-level grid per checklist (hover a header for the question)",
             "Std Setting": "BLR + BGM cut scores, viability tests, charts", "Sections": "Section descriptives, α, correlations",
             "Items": "Item difficulty, discrimination, ρ with GR (+ chart), α-if-deleted, IRT-lite, importance",
             "Assessors": "Leniency / harshness, GR mix, completion", "Roster": f"Coverage vs {cfg.ROSTER_CSV}",
             "Double Marking": "Students marked by two examiners: E1 vs E2 %, gap, flags, agreement per item",
             "Examiner Agreement": "BOH viva: Examiner 1 vs Examiner 2 ratings — exact/adjacent %, κ, cross-tab, by pair, ≥ 2-level list",
             "Ignored Assessors": "Forms excluded from all analysis (overrides file)"}
    for s in sheetsMade:
        key = next((k for k in guide if s.startswith(k)), None)
        w.row([s, guide.get(key, "")], bold0=True)
    w.widths([34, 40, 12, 14, 30, 10, 14, 14])
    finishSheet(ws, False)


# ══ Entry points ════════════════════════════════════════════════════════════
def splitIgnored(rows):
    return [r for r in rows if not r.get("_ignored")], [r for r in rows if r.get("_ignored")]


def writeRecordsSplit(wb, title, rows, templates):
    """Records sheet(s): paired (E1 + E2) rows get their own column layout, other rows the standard one."""
    plain, paired = [r for r in rows if not r.get("_paired")], [r for r in rows if r.get("_paired")]
    first = None
    if plain or not paired:
        first = writeRecords(wb, title, plain, templates)
    if paired:
        ws = writeRecords(wb, f"{title} (E1+E2)" if plain else title, paired, templates)
        first = first or ws
    return first


def summaryExport(examKey, rows, templates, filterDesc) -> str:
    main, ign = splitIgnored(pairSittings(examKey, rows))                # BOH viva: one row per student
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    writeRecordsSplit(wb, "Records", main, templates)
    if ign:
        writeRecordsSplit(wb, "Ignored Assessors", ign, templates).sheet_properties.tabColor = "94A3B8"
    ws = wb.create_sheet("About"); ws["A1"] = f"DASH · {cfg.EXAMS[examKey]['title']} — summary"; ws["A1"].font = xFont(True, size=12)
    ws["A2"] = f"Exported {datetime.now():%d %b %Y %H:%M} · {filterDesc}"; ws["A2"].font = xFont(size=9, color="64748B")
    tmp = tempfile.NamedTemporaryFile(suffix=f"_{examKey}_Summary.xlsx", delete=False); tmp.close()
    wb.save(tmp.name)
    return tmp.name


def detailedExport(examKey, rows, templates, filterDesc) -> str:
    main, ign = splitIgnored(pairSittings(examKey, rows))                # BOH viva: one row per student
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    tids = [t for t in templates if any(r["_tid"] == t for r in main)]
    many = len(tids) > 1
    writeRecordsSplit(wb, "Records", main, templates)
    ssByTpl, alphaByTpl = {}, {}
    for tid in tids:
        tpl, rs = templates[tid], [r for r in main if r["_tid"] == tid]
        tag = tplTag(tpl, many)
        writeScoreSheet(wb, f"Scores{tag}", rs, tpl)
        ssFn = writeStandardSettingPaired if rs and all(r.get("_paired") for r in rs) else writeStandardSetting
        ssByTpl[tid] = ssFn(wb, f"Std Setting{tag}", rs, tpl, examKey)
        alphaByTpl[tid] = writeSections(wb, f"Sections{tag}", rs, tpl, examKey, ssByTpl[tid])
        writeItems(wb, f"Items{tag}", rs, tpl)
    writeAssessors(wb, main, templates, ssByTpl, examKey)
    writeStudents(wb, main, ssByTpl, examKey)
    writeFollowUp(wb, main, ssByTpl, examKey)
    writeExaminerAgreement(wb, main)                                    # paired exams only
    writeDoubleMarking(wb, main, templates)
    writeRoster(wb, main)
    if ign:
        writeRecordsSplit(wb, "Ignored Assessors", ign, templates).sheet_properties.tabColor = "94A3B8"
    order = ["Records", "Records (E1+E2)", "Follow-up", "Students"]   # put the action sheets up front
    for name in reversed(order):
        if name in wb.sheetnames:
            wb.move_sheet(name, offset=-wb.sheetnames.index(name))
    writeOverview(wb, examKey, main, ign, templates, ssByTpl, alphaByTpl, filterDesc, list(wb.sheetnames))
    wb.active = 0
    tmp = tempfile.NamedTemporaryFile(suffix=f"_{examKey}_Detailed.xlsx", delete=False); tmp.close()
    wb.save(tmp.name)
    return tmp.name
