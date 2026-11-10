"""
osce_metrics.py
===============
Rigorous OSCE quality metrics following AMEE Guide No. 49 (Pell, Fuller, Homer & Roberts,
Medical Teacher 2010; 32:802-811). Adds two analysis sheets that complement the BLR sheet.

  "Station Metrics (AMEE)" — per station, the AMEE Table-2 family:
     - Overall test Cronbach's alpha (stations as items) + N complete cases
     - Cronbach's alpha if STATION deleted (leave-one-station-out); if it exceeds the overall
       alpha, the station detracts from reliability
     - R^2 = Pearson(checklist score, global grade)^2  (good if > 0.5)
     - Inter-grade discrimination = regression slope in RAW checklist marks per grade
       (guideline ~ max mark / 10; very high => outlier / low-pass driven)
     - Number of failures (reality check)
     - Between-group (circuit) variation % via one-way ANOVA eta^2  (<30% good, >40% concern)
     - item Cronbach alpha + mean item-total r (station internal consistency)

  "Assessor Analysis (AMEE)" — hawks & doves via one-way ANOVA of checklist % by assessor,
     per station: F, p, eta^2 (between-assessor variance %), a verdict, and a per-assessor
     stringency table (mean %, deltas vs station, BLR residual, flag) + a diverging-bar figure.

Thresholds (from the guide): R^2 > 0.5 acceptable; discrimination ~ maxMark/10; between-group
variation < 30% good, 30-40% watch, > 40% concern (hawks & doves).
"""

import numpy as np
from scipy import stats
from collections import defaultdict, Counter

from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XlImage

import osce_utils as ou


# ─────────── computations ───────────
def studentStationMatrix(specs):
    """Return (colKeys, students, M) where M[student][ck] = checklist Score% at that station."""
    colKeys = [sp["ck"] for sp in specs]
    M = defaultdict(dict)
    for sp in specs:
        for r in sp["rows"]:
            if r["score"] is not None:
                M[r["student"]][sp["ck"]] = r["score"] * 100
    return colKeys, sorted(M), M


def nonEmptySpecs(specs, blr=None):
    """Drop stations with no scored rows (or no BLR entry) so every metric ignores them safely."""
    keep, skipped = [], []
    for sp in specs:
        hasData = any(r.get("score") is not None for r in sp.get("rows", []))
        if hasData and (blr is None or sp["ck"] in blr):
            keep.append(sp)
        else:
            skipped.append(sp.get("ck"))
    if skipped:
        print(f"osce_metrics: ignoring empty station(s): {skipped}")
    return keep


def testAlpha(colKeys, students, M, dropCk=None):
    """Cronbach's alpha treating each station as an item (complete cases). dropCk leaves one out."""
    keys = [k for k in colKeys if k != dropCk]
    rows = [[M[s][k] for k in keys] for s in students if all(k in M[s] for k in keys)]
    k = len(keys)
    if k < 2 or len(rows) < 2:
        return float("nan"), len(rows)
    A = np.array(rows, float)
    itemVar = A.var(axis=0, ddof=1).sum()
    totalVar = A.sum(axis=1).var(ddof=1)
    a = (k / (k - 1)) * (1 - itemVar / totalVar) if totalVar > 0 else float("nan")
    return a, A.shape[0]


def interGradeDiscrimination(spec):
    """Regression slope of checklist marks on the global grade (1..5). For a uniform-level
    checklist the raw-mark scale is kept (maxMark = 10 x per-item max, as before); for a
    mixed-level checklist (per-item scales) the normalised percentage scale is used
    (maxMark = 100), so the metric stays defined and cohort-generic."""
    maxPer = spec.get("maxPerItem")
    maxMark = (10 * maxPer) if maxPer else 100.0
    xs, ys = [], []
    for r in spec["rows"]:
        if r["gr"] is None or r["score"] is None:
            continue
        xs.append(r["gr"]); ys.append(r["score"] * maxMark)
    if len(xs) < 2 or len(set(xs)) < 2:
        return dict(slope=float("nan"), maxMark=maxMark, guideline=maxMark / 10.0, ratio=float("nan"))
    slope, intercept, rv, pv, se = stats.linregress(xs, ys)
    return dict(slope=slope, maxMark=maxMark, guideline=maxMark / 10.0,
                ratio=(slope / maxMark) if maxMark else float("nan"))


def betweenGroupVariation(spec, groupField):
    """One-way ANOVA of checklist Score% by group ('circuit' or 'assessor'): eta^2 %, F, p, k."""
    groups = defaultdict(list)
    for r in spec["rows"]:
        if r["score"] is None:
            continue
        groups[r[groupField]].append(r["score"] * 100)
    arrs = [np.array(v) for v in groups.values() if len(v) > 0]
    if len(arrs) < 2:
        return dict(eta2=float("nan"), F=float("nan"), p=float("nan"), k=len(arrs))
    allv = np.concatenate(arrs); grand = allv.mean()
    ssb = sum(len(a) * (a.mean() - grand) ** 2 for a in arrs)
    sst = ((allv - grand) ** 2).sum()
    eta2 = ssb / sst * 100 if sst > 0 else float("nan")
    try:
        F, p = stats.f_oneway(*arrs)
    except Exception:
        F, p = float("nan"), float("nan")
    return dict(eta2=eta2, F=F, p=p, k=len(arrs))


def betweenGroupVerdict(eta2, p):
    if eta2 != eta2:
        return "-"
    if eta2 > 40 or (p == p and p < 0.05 and eta2 > 30):
        return "Hawks & doves (concern)"
    if eta2 > 30:
        return "Watch"
    return "Consistent"


# ─────────── shared styles ───────────
def _styles():
    hFont = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    bFont = Font(name="Arial", size=10)
    hFill = PatternFill("solid", fgColor=ou.HEAD)
    thin = Side(style="thin", color="C5D5E8")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    ctrW = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ctr = Alignment(horizontal="center", vertical="center")
    return hFont, bFont, hFill, box, ctrW, ctr


# ─────────── sheet builders ───────────
def buildStationMetricsSheet(awb, specs, blr, position=None):
    specs = nonEmptySpecs(specs, blr)
    hFont, bFont, hFill, box, ctrW, ctr = _styles()
    ws = awb.create_sheet("Station Metrics (AMEE)") if position is None else awb.create_sheet("Station Metrics (AMEE)", position)
    ws.sheet_view.showGridLines = False
    colKeys, students, M = studentStationMatrix(specs)
    overallA, nComplete = testAlpha(colKeys, students, M)
    ws.cell(1, 1, f"AMEE Guide 49 station metrics — overall test Cronbach's a = {overallA:.3f} "
                  f"(stations as items, K={len(colKeys)}, N={nComplete} complete cases)").font = Font(name="Arial", size=12, bold=True, color=ou.HEAD)
    hdr = ["Station", "Sheet", "Checklist", "Levels", "N", "BLR cut %", "Mean-2SD %", "R^2",
           "Inter-grade discrim (pts/grade)", "Max mark", "Discrim guide (max/10)", "Failures",
           "Circuit var % (eta^2)", "Assessor var % (eta^2)", "a if stn deleted", "Item a",
           "Mean item-total r", "Excellent", "Very good", "Pass", "Borderline", "Fail", "Flags"]
    for c, h in enumerate(hdr, 1):
        cc = ws.cell(3, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
    R2C = hdr.index("R^2") + 1; CIRC = hdr.index("Circuit var % (eta^2)") + 1
    firstRow = 4; r = 4
    for sp in specs:
        b = blr[sp["ck"]]; scs = b["scs"]
        disc = interGradeDiscrimination(sp)
        bgC = betweenGroupVariation(sp, "circuit"); bgA = betweenGroupVariation(sp, "assessor")
        aDel, _ = testAlpha(colKeys, students, M, dropCk=sp["ck"])
        itemA = ou.cronbachAlpha(sp["rows"], sp["items"])
        itr = [x for x in ou.itemTotalCorrs(sp["rows"], sp["items"]) if x == x]
        nfail = ou.countBelow(scs, b["cut"])
        grc = Counter(ou.GR_LABELS[r["gr"]] for r in sp["rows"] if r["gr"] is not None)
        flags = []
        if b["r2"] < 0.5: flags.append("R2<0.5")
        if disc["slope"] > disc["maxMark"] / 6: flags.append("high discrim")
        if bgC["eta2"] == bgC["eta2"] and bgC["eta2"] > 40: flags.append("circuit var>40%")
        elif bgC["eta2"] == bgC["eta2"] and bgC["eta2"] > 30: flags.append("circuit var>30%")
        if aDel == aDel and overallA == overallA and aDel > overallA + 1e-9: flags.append("detracts")
        row = [sp["st"], ou.stationTitle(sp["st"], sp["ck"]), sp["cfg"]["name"].split(".")[0][:34], sp["levels"], len(scs),
               b["cutPct"], b["mean2sdPct"], round(b["r2"], 3), round(disc["slope"], 2), disc["maxMark"], round(disc["guideline"], 1),
               nfail, round(bgC["eta2"], 1), round(bgA["eta2"], 1), round(aDel, 3), round(itemA, 3),
               round(float(np.mean(itr)), 3) if itr else "-",
               grc["Excellent"], grc["Very good"], grc["Pass"], grc["Borderline"], grc["Fail"], ", ".join(flags)]
        for c, v in enumerate(row, 1):
            cc = ws.cell(r, c, v); cc.font = bFont; cc.border = box
            cc.alignment = Alignment(horizontal="left") if c in (3, len(hdr)) else ctr
        if b["r2"] < 0.5:
            ws.cell(r, R2C).fill = PatternFill("solid", fgColor="FFC7CE")
        if bgC["eta2"] == bgC["eta2"] and bgC["eta2"] > 40:
            ws.cell(r, CIRC).fill = PatternFill("solid", fgColor="FFC7CE")
        elif bgC["eta2"] == bgC["eta2"] and bgC["eta2"] > 30:
            ws.cell(r, CIRC).fill = PatternFill("solid", fgColor="FFEB9C")
        r += 1
    lastRow = r - 1
    # column averages row
    avgCols = [5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
    ac = ws.cell(r, 1, "Average"); ac.font = Font(name="Arial", size=10, bold=True, color=ou.HEAD); ac.border = box
    for c in range(2, len(hdr) + 1):
        cc = ws.cell(r, c); cc.border = box; cc.alignment = ctr
        if c in avgCols:
            vals = [ws.cell(rr, c).value for rr in range(firstRow, lastRow + 1) if isinstance(ws.cell(rr, c).value, (int, float))]
            if vals:
                cc.value = round(sum(vals) / len(vals), 2); cc.font = Font(name="Arial", size=10, bold=True)
    r += 1
    for c, w in zip(range(1, len(hdr) + 1), [8, 12, 26, 7, 6, 9, 10, 8, 15, 9, 12, 9, 13, 13, 13, 8, 13, 9, 9, 9, 9, 9, 26]):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A4"
    notes = [
        "Overall test a: each station's Score% treated as an item; >=0.7 acceptable for this kind of high-stakes OSCE.",
        "BLR cut % and Mean-2SD % are two candidate pass marks (both rounded to 1 dp). Failures = students below the BLR cut.",
        "a if stn deleted: overall alpha with this station removed; if it EXCEEDS the overall a, the station detracts from reliability.",
        "R^2 = Pearson(checklist score, global grade)^2; > 0.5 = reasonable grade/checklist relationship.",
        "Inter-grade discrimination = regression slope in raw marks per grade; guideline ~ max mark / 10.",
        "Circuit / Assessor var % = one-way ANOVA eta^2 of Score% by circuit / by assessor: <30% good, 30-40% watch, >40% concern.",
        "Last row = column averages across stations.",
    ]
    for i, t in enumerate(notes):
        ws.cell(r + 1 + i, 1, t).font = Font(name="Arial", size=9, italic=True, color="555555")
    return ws


def buildCircuitCutSheet(awb, specs, blr, borderlineGr=2, position=None):
    """Matrix of BLR cut scores computed WITHIN each circuit, per station, vs the overall cut."""
    specs = nonEmptySpecs(specs, blr)
    hFont, bFont, hFill, box, ctrW, ctr = _styles()
    ws = awb.create_sheet("BLR Cut per Circuit") if position is None else awb.create_sheet("BLR Cut per Circuit", position)
    ws.sheet_view.showGridLines = False
    circuits = sorted({r["circuit"] for sp in specs for r in sp["rows"]})
    ws.cell(1, 1, "BLR cut score (%) computed within each circuit (per station) vs the overall cut").font = Font(name="Arial", size=12, bold=True, color=ou.HEAD)
    hdr = ["Station", "Checklist"] + [f"Circuit {c}" for c in circuits] + ["All"]
    for c, h in enumerate(hdr, 1):
        cc = ws.cell(3, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
    r = 4
    for sp in specs:
        line = [ou.stationTitle(sp["st"], sp["ck"]), sp["cfg"]["name"].split(".")[0][:34]]
        for c in circuits:
            sub = [rr for rr in sp["rows"] if rr["circuit"] == c and rr["score"] is not None and rr["gr"] is not None]
            val = "-"
            if len(sub) >= 3 and len({rr["gr"] for rr in sub}) >= 2:
                try:
                    bb = ou.computeBlr(sub, borderlineGr)
                    val = round(bb["cut"] * 100, 1) if np.isfinite(bb["cut"]) else "-"
                except Exception:
                    val = "-"
            line.append(val)
        line.append(blr[sp["ck"]]["cutPct"])
        for c, v in enumerate(line, 1):
            cc = ws.cell(r, c, v); cc.font = bFont; cc.border = box
            cc.alignment = Alignment(horizontal="left") if c == 2 else ctr
        r += 1
    ws.column_dimensions["A"].width = 12; ws.column_dimensions["B"].width = 26
    for c in range(3, len(hdr) + 1):
        ws.column_dimensions[get_column_letter(c)].width = 10
    ws.freeze_panes = "C4"
    ws.cell(r + 1, 1, "Each circuit has one assessor; a circuit-specific BLR regresses only that assessor's ~18 students, so small-n cuts are unstable — compare to 'All'.").font = Font(name="Arial", size=9, italic=True, color="555555")
    return ws


def buildAssessorAnalysisSheet(awb, specs, blr, imgDir, position=None):
    specs = nonEmptySpecs(specs, blr)
    hFont, bFont, hFill, box, ctrW, ctr = _styles()
    ws = awb.create_sheet("Assessor Analysis (AMEE)") if position is None else awb.create_sheet("Assessor Analysis (AMEE)", position)
    ws.sheet_view.showGridLines = False
    ws.cell(1, 1, "Assessor stringency (hawks & doves) — one-way ANOVA of checklist % by assessor, per station").font = Font(name="Arial", size=12, bold=True, color=ou.HEAD)
    rp = 3
    for sp in specs:
        st, ck, cfg = sp["st"], sp["ck"], sp["cfg"]
        harsh, stMeanPct, stMeanGr = ou.computeAssessorHarshness(sp, blr[ck])
        bg = betweenGroupVariation(sp, "assessor")
        img = ou.buildHarshnessFigure(sp, harsh, stMeanPct, imgDir)
        top = rp
        ws.cell(rp, 1, f"{ou.stationTitle(st, ck)} — {cfg['name'].split('.')[0]}   "
                       f"(station mean {stMeanPct:.1f}%, mean GR {stMeanGr:.2f})").font = Font(name="Arial", size=11, bold=True, color=ou.HEAD)
        rp += 1
        for c, (lab, val) in enumerate([("Assessors (k)", bg["k"]),
                                        ("ANOVA F", round(bg["F"], 2) if bg["F"] == bg["F"] else "-"),
                                        ("p-value", ("%.2e" % bg["p"]) if bg["p"] == bg["p"] else "-"),
                                        ("Between-assessor var % (eta^2)", round(bg["eta2"], 1) if bg["eta2"] == bg["eta2"] else "-"),
                                        ("Verdict", betweenGroupVerdict(bg["eta2"], bg["p"]))], 1):
            lc = ws.cell(rp, 2 * c - 1, lab); lc.font = Font(name="Arial", size=9, bold=True); lc.border = box; lc.alignment = ctr
            vc = ws.cell(rp, 2 * c, val); vc.font = bFont; vc.border = box; vc.alignment = ctr
            if lab == "Verdict" and str(val).startswith("Hawks"):
                vc.fill = PatternFill("solid", fgColor="FFC7CE"); vc.font = Font(name="Arial", size=10, bold=True, color="9C0006")
            elif lab == "Verdict" and val == "Watch":
                vc.fill = PatternFill("solid", fgColor="FFEB9C")
        rp += 2
        hdr = ["Assessor", "n", "Mean %", "Δ% vs stn", "Mean GR", "ΔGR vs stn", "Mean BLR resid %", "Flag"]
        for c, h in enumerate(hdr, 1):
            cc = ws.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
        rp += 1
        for h in harsh:
            vals = [h["assessor"], h["n"], round(h["meanPct"], 1), round(h["dPct"], 1),
                    round(h["meanGr"], 2), round(h["dGr"], 2), round(h["residPct"], 1), h["flag"]]
            for c, v in enumerate(vals, 1):
                cc = ws.cell(rp, c, v); cc.font = bFont; cc.border = box
                cc.alignment = Alignment(horizontal="left") if c == 1 else ctr
            fc = ws.cell(rp, 8)
            if h["flag"] == "Harsh":
                fc.fill = PatternFill("solid", fgColor="FFC7CE"); fc.font = Font(name="Arial", size=10, bold=True, color="9C0006")
            elif h["flag"] == "Lenient":
                fc.fill = PatternFill("solid", fgColor="C6EFCE"); fc.font = Font(name="Arial", size=10, bold=True, color="375623")
            rp += 1
        if img:
            xi = XlImage(img); xi.width = 560; xi.height = int(560 * (max(2.4, 0.42 * len(harsh) + 1.1) / 8)); ws.add_image(xi, f"J{top+1}")
        rp = max(rp, top + max(6, len(harsh) + 5)) + 2
    ws.column_dimensions["A"].width = 24
    for c in "BCDEFGH":
        ws.column_dimensions[c].width = 13
    for i, t in enumerate([
        "Δ% / ΔGR vs stn: assessor mean minus station mean (negative = harsher). Assumes ~random student allocation.",
        "Mean BLR resid %: mean of (checklist % - the % their grades predict); negative = marks checklist below cohort trend for the grades given.",
        "Between-assessor var % (eta^2): share of checklist-score variance explained by assessor; >40% (or p<.05 & >30%) = hawks & doves.",
        "Flag: Harsh if Δ%<=-5 or ΔGR<=-0.4; Lenient if >=+5 or +0.4; else Typical."]):
        ws.cell(rp + i, 1, t).font = Font(name="Arial", size=9, italic=True, color="555555")
    return ws


# ═══════════════════════════════════════════════════════════════════════════════
# Station review Word table  (added 2026-11-09)
# Reads an existing "<cohort> BLR & Validity*.xlsx" analysis workbook (no recompute) and writes a
# landscape .docx with one row per station:
#   Station | Key Station Metrics | Recommendation | Reasons for recommendation | Notes about the station
# Metrics come from 'Station Metrics (AMEE)' (+ full names from 'BLR Analysis', assessor flags from
# 'Assessor Analysis (AMEE)', applied cut from 'Standard Setting'). Recommendation/Reasons are a
# rule-based DRAFT (REVIEW_THRESHOLDS) for the panel to edit in Word; Notes start blank unless given.
# ═══════════════════════════════════════════════════════════════════════════════
import os
import re
import datetime as _dt

REVIEW_THRESHOLDS = {
    "alphaMajor": 0.5,         # station (item) Cronbach's alpha below this -> major
    "alphaMinor": 0.7,         # ... below this -> minor
    "r2Major": 0.3,            # R^2 checklist vs global rating below this -> major
    "r2Minor": 0.5,            # ... below this -> minor (AMEE: > 0.5 reasonable)
    "failMajor": 30.0,         # % of cohort below the BLR cut above this -> major
    "failMinor": 20.0,         # ... above this -> minor
    "discrimFactor": 0.5,      # inter-grade discrimination < factor x guide (max/10) -> minor
    "alphaDeletedGain": 0.005, # overall alpha rises by >= this when the station is dropped -> minor
    "assessorModerate": 10.0,  # assessor eta^2 %: < this Low, else Moderate
    "assessorHigh": 30.0,      # >= this High (AMEE 'watch') -> minor
    "assessorConcern": 40.0,   # >= this (or ANOVA verdict hawks & doves) -> major
}
REVIEW_LABELS = {0: "Keep Station", 1: "Keep Station (minor review)", 2: "Review Station before reuse"}
REVIEW_COLOURS = {0: "094183", 1: "9C5700", 2: "C55A11"}   # UniMelb blue / amber / orange
REVIEW_HEAD = "000F46"                                     # UniMelb navy header


def reviewNum(v):
    """Cell value -> float or None."""
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def reviewSheetRows(wb, name):
    return [list(r) for r in wb[name].iter_rows(values_only=True)] if name in wb.sheetnames else []


def reviewStationKey(v):
    """1 / 1.0 / '1' / '1+5' -> '1' / '1+5'."""
    f = reviewNum(v)
    return str(int(f)) if f is not None and f == int(f) else str(v).strip()


def readStationMetricsRows(rows):
    """'Station Metrics (AMEE)' -> (list of row dicts, overall {alpha, k, n})."""
    overall = {"alpha": None, "k": None, "n": None}
    if rows and rows[0] and rows[0][0]:
        t = str(rows[0][0])
        m = re.search(r"=\s*(-?\d+(?:\.\d+)?)", t); overall["alpha"] = float(m.group(1)) if m else None
        m = re.search(r"K\s*=\s*(\d+)", t); overall["k"] = int(m.group(1)) if m else None
        m = re.search(r"N\s*=\s*(\d+)", t); overall["n"] = int(m.group(1)) if m else None
    hi = next((i for i, r in enumerate(rows) if r and r[0] == "Station" and "Sheet" in r), None)
    if hi is None:
        return [], overall
    hdr = [str(h).strip() if h is not None else "" for h in rows[hi]]
    out = []
    for r in rows[hi + 1:]:
        if not r or r[0] in (None, "", "Average") or (isinstance(r[0], str) and len(r[0]) > 12):
            break
        out.append(dict(zip(hdr, r)))
    return out, overall


def readBlrTitles(rows):
    """'BLR Analysis' title rows -> list of (stationKey, fullName)."""
    out = []
    for r in rows:
        a = r[0] if r else None
        if isinstance(a, str):
            m = re.match(r"^Station\s+(\S+)\s+—\s+(.*?)\s*\(n=\d+", a)
            if m:
                out.append((m.group(1), m.group(2).strip()))
    return out


def readAssessorBlocks(rows):
    """'Assessor Analysis (AMEE)' -> {sheetName: {k, eta2, p, verdict, assessors:[{name, dPct, dGr, flag}]}}."""
    out, cur, inTbl = {}, None, False
    for r in rows:
        a = r[0] if r else None
        if isinstance(a, str) and " — " in a and "(station mean" in a:
            cur = {"k": None, "eta2": None, "p": None, "verdict": "", "assessors": []}
            out[a.split(" — ")[0].strip()] = cur; inTbl = False
            continue
        if cur is None:
            continue
        if a == "Assessors (k)":
            pairs = {r[i]: r[i + 1] for i in range(0, len(r) - 1, 2) if isinstance(r[i], str)}
            cur["k"] = reviewNum(pairs.get("Assessors (k)"))
            cur["eta2"] = reviewNum(pairs.get("Between-assessor var % (eta^2)"))
            cur["p"] = reviewNum(pairs.get("p-value"))
            cur["verdict"] = str(pairs.get("Verdict") or "")
        elif a == "Assessor" and len(r) > 1 and r[1] == "n":
            inTbl = True
        elif inTbl:
            if not a or len(r) < 8 or r[7] not in ("Harsh", "Lenient", "Typical"):
                inTbl = False; continue
            cur["assessors"].append({"name": a, "dPct": reviewNum(r[3]), "dGr": reviewNum(r[5]), "flag": r[7]})
    return out


def readStandardSetting(rows):
    """'Standard Setting' -> list of {st, checklist, appliedCut, appliedFails}."""
    out, mode, byKey = [], None, {}
    for r in rows:
        if not r or r[0] is None:
            mode = None; continue
        if r[0] == "Station" and "APPLIED cut %" in r:
            mode = ("cut", r.index("APPLIED cut %")); continue
        if r[0] == "Station" and "Fails APPLIED" in r:
            mode = ("fails", r.index("Fails APPLIED")); continue
        if mode and reviewNum(r[0]) is not None or (mode and isinstance(r[0], str) and len(r[0]) <= 8):
            key = (reviewStationKey(r[0]), str(r[1] or "").strip())
            d = byKey.setdefault(key, {"st": key[0], "checklist": key[1], "appliedCut": None, "appliedFails": None})
            if mode[0] == "cut":
                d["appliedCut"] = reviewNum(r[mode[1]])
            else:
                d["appliedFails"] = reviewNum(r[mode[1]])
        else:
            mode = None
    return list(byKey.values())


def matchByName(stKey, shortName, candidates, nameField):
    """Pick the candidate with the same station key whose name starts with shortName (names are truncated)."""
    short = (shortName or "").strip().lower()
    same = [c for c in candidates if c[0] == stKey]
    for c in same:
        nm = (c[1] if nameField is None else c[1].get(nameField) or "").strip().lower()
        if short and (nm.startswith(short) or short.startswith(nm)):
            return c
    return same[0] if len(same) == 1 else None


def cleanStationName(name):
    """'Station 01 - Polypharmacy' -> 'Polypharmacy'."""
    s = re.sub(r"^\s*station\s*\d+\s*[-–—:.]?\s*", "", str(name or ""), flags=re.I).strip()
    return s or str(name or "").strip()


def lookupByStation(mapping, sheet, st, checklist):
    """Optional per-station dict lookup by sheet name, station number (str/int) or checklist name."""
    if not mapping:
        return None
    for k in (sheet, st, checklist):
        if k in mapping:
            return mapping[k]
    stInt = reviewNum(st)
    if stInt is not None and int(stInt) in mapping:
        return mapping[int(stInt)]
    return None


def assessorInfluence(blk, t, showNames=False):
    """-> (severity 0/1/2, text) e.g. 'Assessor influence – Moderate (η² 18.0%) – 1 of 2 assessors recorded as harsh'."""
    if not blk or blk.get("eta2") is None:
        return 0, None
    eta, verdict = blk["eta2"], blk.get("verdict") or ""
    if eta >= t["assessorConcern"] or verdict.lower().startswith("hawks"):
        level, sev = "High", 2
    elif eta >= t["assessorHigh"]:
        level, sev = "High", 1
    elif eta >= t["assessorModerate"]:
        level, sev = "Moderate", 0
    else:
        level, sev = "Low", 0
    txt = f"Assessor influence – {level} (between-assessor variance η² = {eta:.1f}%"
    vClean = re.sub(r"\s*\(.*?\)", "", verdict).strip().lower()
    txt += f", {vClean})" if vClean and vClean != "-" else ")"
    nA = len(blk.get("assessors") or [])
    parts = []
    for flag in ("Harsh", "Lenient"):
        who = [a["name"] for a in blk.get("assessors") or [] if a["flag"] == flag]
        if who:
            parts.append(f"{len(who)} {flag.lower()}" + (f" ({', '.join(who)})" if showNames else ""))
    if parts:
        nFlag = sum(a["flag"] in ("Harsh", "Lenient") for a in blk.get("assessors") or [])
        txt += f" – {' and '.join(parts)} assessor{'s' if nFlag > 1 and len(parts) == 1 else ''} (of {nA})"
    return sev, txt


def draftStationRecommendation(m, overallAlpha=None, thresholds=None, showAssessorNames=False):
    """
    Rule-based draft for one station dict (from collectStationReview). Returns (label, reasons, level).
    level 0 = Keep, 1 = Keep (minor review), 2 = Review before reuse. Thresholds: REVIEW_THRESHOLDS.
    """
    t = {**REVIEW_THRESHOLDS, **(thresholds or {})}
    major, minor, info = [], [], []
    a, r2 = m.get("itemAlpha"), m.get("r2")
    if a is not None:
        if a < t["alphaMajor"]:
            major.append(f"Low internal consistency of checklist items (Cronbach's α = {a:.3f} < {t['alphaMajor']})")
        elif a < t["alphaMinor"]:
            minor.append(f"Modest internal consistency of checklist items (Cronbach's α = {a:.3f} < {t['alphaMinor']})")
    if r2 is not None:
        if r2 < t["r2Major"]:
            major.append(f"Weak agreement between checklist score and global rating (R² = {r2:.3f} < {t['r2Major']})")
        elif r2 < t["r2Minor"]:
            minor.append(f"Moderate agreement between checklist score and global rating (R² = {r2:.3f} < {t['r2Minor']})")
    n, fails = m.get("n"), m.get("blrFails")
    if n and fails is not None:
        fr = 100.0 * fails / n
        if fr > t["failMajor"]:
            major.append(f"High BLR failure rate ({int(fails)} of {int(n)}, {fr:.0f}% > {t['failMajor']:.0f}%) – check station difficulty / checklist")
        elif fr > t["failMinor"]:
            minor.append(f"Elevated BLR failure rate ({int(fails)} of {int(n)}, {fr:.0f}% > {t['failMinor']:.0f}%)")
    d, g = m.get("discrim"), m.get("discrimGuide")
    if d is not None and g:
        if d < t["discrimFactor"] * g:
            minor.append(f"Low inter-grade discrimination ({d:.2f} marks per grade vs guide ≈ {g:g})")
    aDel = m.get("alphaIfDeleted")
    if overallAlpha is not None and aDel is not None and aDel - overallAlpha >= t["alphaDeletedGain"]:
        minor.append(f"Removing this station would raise overall OSCE α ({overallAlpha:.3f} → {aDel:.3f})")
    sev, aTxt = assessorInfluence(m.get("assessorBlock"), t, showAssessorNames)
    if aTxt:
        (major if sev == 2 else minor if sev == 1 else info).append(aTxt)
    level = 2 if major else (1 if minor else 0)
    reasons = major + minor + info
    if level == 0:
        reasons = ["Station metrics within acceptable ranges"] + reasons
    return REVIEW_LABELS[level], reasons, level


def collectStationReview(analysisPath, stationTypes=None, notes=None, metaPath=None, cohortLabel="",
                         thresholds=None, showAssessorNames=False):
    """
    Analysis workbook -> (stations, overall). One dict per 'Station Metrics (AMEE)' row:
      st, sheet, name, type, n, blrCut, appliedCut, r2, itemAlpha, alphaIfDeleted, discrim, discrimGuide,
      blrFails, blrPassed, grBorderline, grFail, assessorEta2, assessorVerdict, nHarsh, nLenient,
      recommendation, reasons (list), level, notes
    stationTypes / notes : optional {sheet | station number | checklist name: text}
    metaPath             : optional 'OSCE Station Metadata.xlsx' (Station Type by Sheet Name, filtered to cohortLabel)
    """
    import openpyxl
    wb = openpyxl.load_workbook(analysisPath, data_only=True, read_only=True)
    try:
        metricRows, overall = readStationMetricsRows(reviewSheetRows(wb, "Station Metrics (AMEE)"))
        titles = readBlrTitles(reviewSheetRows(wb, "BLR Analysis"))
        assessors = readAssessorBlocks(reviewSheetRows(wb, "Assessor Analysis (AMEE)"))
        stdSet = readStandardSetting(reviewSheetRows(wb, "Standard Setting"))
    finally:
        wb.close()
    if not metricRows:
        raise ValueError(f"No 'Station Metrics (AMEE)' table found in {analysisPath}")
    types = dict(stationTypes or {})
    if metaPath and os.path.exists(metaPath):
        try:
            meta, _ = ou.loadStationMeta(metaPath, cohort=cohortLabel or "DDS4")
            for sh, mm in meta.items():
                if mm.get("type") and sh not in types:
                    types[sh] = mm["type"]
        except Exception as e:  # metadata is optional
            print(f"[station review] metadata not used ({e})")
    out = []
    for r in metricRows:
        st, sheet = reviewStationKey(r.get("Station")), str(r.get("Sheet") or "").strip()
        shortNm = str(r.get("Checklist") or "").strip()
        tm = matchByName(st, shortNm, titles, None)
        fullNm = tm[1] if tm else shortNm
        ss = matchByName(st, shortNm, [(d["st"], d) for d in stdSet], "checklist")
        ss = ss[1] if ss else {}
        n, fails = reviewNum(r.get("N")), reviewNum(r.get("Failures"))
        blk = assessors.get(sheet)
        m = {"st": st, "sheet": sheet, "name": cleanStationName(fullNm), "fullName": fullNm,
             "type": lookupByStation(types, sheet, st, fullNm) or "",
             "n": n, "blrCut": reviewNum(r.get("BLR cut %")), "appliedCut": ss.get("appliedCut"),
             "appliedFails": ss.get("appliedFails"),
             "r2": reviewNum(r.get("R^2")), "itemAlpha": reviewNum(r.get("Item a")),
             "alphaIfDeleted": reviewNum(r.get("a if stn deleted")),
             "discrim": reviewNum(r.get("Inter-grade discrim (pts/grade)")),
             "discrimGuide": reviewNum(r.get("Discrim guide (max/10)")),
             "blrFails": fails, "blrPassed": (n - fails) if n is not None and fails is not None else None,
             "grBorderline": reviewNum(r.get("Borderline")), "grFail": reviewNum(r.get("Fail")),
             "assessorBlock": blk,
             "assessorEta2": blk.get("eta2") if blk else None,
             "assessorVerdict": blk.get("verdict") if blk else "",
             "nHarsh": sum(a["flag"] == "Harsh" for a in blk["assessors"]) if blk else 0,
             "nLenient": sum(a["flag"] == "Lenient" for a in blk["assessors"]) if blk else 0,
             "metricFlags": r.get("Flags") or ""}
        m["recommendation"], m["reasons"], m["level"] = draftStationRecommendation(
            m, overall.get("alpha"), thresholds, showAssessorNames)
        m["notes"] = lookupByStation(notes, sheet, st, fullNm) or ""
        out.append(m)
    return out, overall


def stationMetricLines(m):
    """Key Station Metrics cell text, one line each (mirrors the panel's template)."""
    def fi(v):
        return "–" if v is None else str(int(round(v)))
    lines = []
    if m.get("type"):
        lines.append(m["type"])
    lines.append(f"BLR Cut-off – {m['blrCut']:.1f}%" if m.get("blrCut") is not None else "BLR Cut-off – n/a")
    ac = m.get("appliedCut")
    if ac is not None and m.get("blrCut") is not None and abs(ac - m["blrCut"]) >= 0.05:
        lines.append(f"Applied cut-off – {ac:.1f}% (override)")
    lines.append(f"Cronbach's α – {m['itemAlpha']:.3f}" if m.get("itemAlpha") is not None else "Cronbach's α – n/a")
    lines.append(f"R-square value – {m['r2']:.3f}" if m.get("r2") is not None else "R-square value – n/a")
    lines.append(f"Number passed (BLR) – {fi(m.get('blrPassed'))}")
    lines.append(f"Number failed (BLR) – {fi(m.get('blrFails'))}")
    lines.append(f"Number of borderline (Global Rating Score) – {fi(m.get('grBorderline'))}")
    lines.append(f"Number of fail (Global Rating Score) – {fi(m.get('grFail'))}")
    return lines


def buildStationReviewDoc(analysisPath, outPath=None, cohortLabel="", title=None, stationTypes=None,
                          notes=None, metaPath=None, thresholds=None, showAssessorNames=False,
                          includeMethodNote=True):
    """
    Word (.docx) station-review table from a BLR & Validity analysis workbook.
      analysisPath      : e.g. "OSCE/BOH2/BOH2 BLR & Validity new.xlsx"
      outPath           : default "<same folder>/<cohort> OSCE Station Review.docx"
      stationTypes      : {1: "Simulated Patient Station", ...} -> first line of Key Station Metrics
      notes             : {1: "Lessons learned ...", ...} -> prefills 'Notes about the station'
      metaPath          : optional OSCE Station Metadata.xlsx (Station Type column) instead of stationTypes
      thresholds        : overrides for REVIEW_THRESHOLDS
      showAssessorNames : list harsh/lenient assessor names in Reasons (default off – doc may be circulated)
    Returns {"docPath", "stations", "overall"}. If the .docx is open in Word, saves "... (refreshed).docx".
    """
    try:
        import docx
        from docx.shared import Pt, Cm, RGBColor
        from docx.enum.section import WD_ORIENT
        from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
    except ImportError as e:
        raise ImportError("python-docx is required: pip install python-docx") from e

    stations, overall = collectStationReview(analysisPath, stationTypes, notes, metaPath, cohortLabel,
                                             thresholds, showAssessorNames)
    if outPath is None:
        outPath = os.path.join(os.path.dirname(analysisPath), f"{cohortLabel or 'OSCE'} OSCE Station Review.docx")

    doc = docx.Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(1.5))
    base = doc.styles["Normal"]; base.font.name = "Arial"; base.font.size = Pt(9)
    base.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")

    def shade(cell, hexFill):
        tcPr = cell._tc.get_or_add_tcPr(); sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hexFill); tcPr.append(sh)

    def cellLines(cell, lines, bold=False, colour=None, size=9, bulletAfter=0):
        cell.text = ""
        for i, ln in enumerate(lines):
            p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
            p.paragraph_format.space_after = Pt(2); p.paragraph_format.space_before = Pt(0)
            txt = ("• " + ln) if bulletAfter and i >= bulletAfter - 1 else ln
            run = p.add_run(txt); run.font.size = Pt(size); run.bold = bold
            if colour:
                run.font.color.rgb = RGBColor.from_string(colour)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP

    h = doc.add_paragraph(); r = h.add_run(title or f"{cohortLabel} OSCE — Station Review".strip())
    r.bold = True; r.font.size = Pt(15); r.font.color.rgb = RGBColor.from_string(REVIEW_HEAD)
    sub = f"Source: {os.path.basename(analysisPath)}   ·   Generated {_dt.date.today():%d %b %Y}"
    if overall.get("alpha") is not None:
        sub += (f"   ·   Overall OSCE Cronbach's α (stations as items) = {overall['alpha']:.3f}"
                + (f" (K={overall['k']}, N={overall['n']})" if overall.get("k") else ""))
    p = doc.add_paragraph(); rr = p.add_run(sub); rr.font.size = Pt(8.5); rr.italic = True
    rr.font.color.rgb = RGBColor.from_string("555555")

    hdr = ["Station", "Key Station Metrics", "Recommendation", "Reasons for recommendation", "Notes about the station"]
    widths = [Cm(3.2), Cm(7.3), Cm(3.2), Cm(8.0), Cm(5.0)]
    tbl = doc.add_table(rows=1, cols=len(hdr)); tbl.style = "Table Grid"; tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    trPr = tbl.rows[0]._tr.get_or_add_trPr(); th = OxmlElement("w:tblHeader"); th.set(qn("w:val"), "true"); trPr.append(th)
    for c, txt in enumerate(hdr):
        cell = tbl.rows[0].cells[c]; cellLines(cell, [txt], bold=True, colour="FFFFFF", size=9.5); shade(cell, REVIEW_HEAD)
    for m in stations:
        row = tbl.add_row()
        cs = OxmlElement("w:cantSplit"); row._tr.get_or_add_trPr().append(cs)
        c0, c1, c2, c3, c4 = row.cells
        cellLines(c0, [f"Station {m['st']}"], bold=True)
        pn = c0.add_paragraph(); rn = pn.add_run(m["name"]); rn.font.size = Pt(9)
        cellLines(c1, stationMetricLines(m))
        cellLines(c2, [m["recommendation"]], bold=True, colour=REVIEW_COLOURS[m["level"]])
        cellLines(c3, m["reasons"], bulletAfter=1)
        cellLines(c4, [m["notes"]] if m["notes"] else [""])
    for c, w in enumerate(widths):            # grid widths (LibreOffice/Word layout) + per-cell widths (Word)
        tbl.columns[c].width = w
    for row in tbl.rows:
        for c, w in enumerate(widths):
            row.cells[c].width = w

    if includeMethodNote:
        t = {**REVIEW_THRESHOLDS, **(thresholds or {})}
        doc.add_paragraph()
        for ln in [
            "How the draft recommendation is made (edit freely – it is a starting point for the panel):",
            f"Review Station before reuse = any MAJOR issue: item α < {t['alphaMajor']}, R² < {t['r2Major']}, "
            f"BLR failure rate > {t['failMajor']:.0f}%, or assessor variance η² ≥ {t['assessorConcern']:.0f}% / hawks & doves.",
            f"Keep Station (minor review) = MINOR issues only: item α < {t['alphaMinor']}, R² < {t['r2Minor']}, "
            f"failure rate > {t['failMinor']:.0f}%, inter-grade discrimination < {t['discrimFactor']} × guide (max mark/10), "
            f"overall α rises by ≥ {t['alphaDeletedGain']} without the station, or assessor η² ≥ {t['assessorHigh']:.0f}%.",
            "Keep Station = none of the above.",
            f"Assessor influence: Low < {t['assessorModerate']:.0f}% ≤ Moderate < {t['assessorHigh']:.0f}% ≤ High (one-way ANOVA η² of "
            "checklist % by assessor). Harsh / lenient = assessor mean ≥ 5 pp or ≥ 0.4 GR below / above the station mean.",
            "Number passed / failed (BLR) = students at or above / below the station BLR cut. Borderline / fail counts are examiner "
            "global ratings. Metrics from the 'Station Metrics (AMEE)', 'Assessor Analysis (AMEE)' and 'Standard Setting' sheets.",
        ]:
            q = doc.add_paragraph(); q.paragraph_format.space_after = Pt(1)
            rq = q.add_run(ln); rq.font.size = Pt(8); rq.italic = True; rq.font.color.rgb = RGBColor.from_string("555555")

    os.makedirs(os.path.dirname(outPath) or ".", exist_ok=True)
    try:
        doc.save(outPath)
    except PermissionError:
        root, ext = os.path.splitext(outPath)
        outPath = f"{root} (refreshed){ext}"
        doc.save(outPath)
        print(f"[station review] target open in Word – saved to {outPath}")
    for m in stations:
        m.pop("assessorBlock", None)
    return {"docPath": outPath, "stations": stations, "overall": overall}
