"""
student_report_html_utils.py
Interactive HTML version of the "Till Date performance report" (per-student).

WHY THIS MODULE EXISTS
----------------------
The PDF report (buildStudentReportV2 in boh2_dds2_dds3_utils.py) is static.
Students asked for something they can explore: hover for detail, toggle
Sim/Clinic, filter reflections, zoom the timeline. This module produces ONE
self-contained .html per student (Apache ECharts + all data + styles inlined)
that opens in any browser offline and can be emailed as a single file.

DESIGN RULES (match the PDF + Kunal's conventions)
--------------------------------------------------
* ADDITIVE ONLY. Nothing in boh2_dds2_dds3_utils.py is changed; we only *call*
  its (already correct) data functions so the HTML numbers can never drift from
  the PDF.
* ONE FUNCTION PER ELEMENT. Every visible block has its own `render*` function
  returning an HTML fragment, and its own `_ec*` ECharts option builder in the
  embedded JS (see renderScripts). Edit a block in one place.
* SAME COLOUR GRADING. The V2_* palette is imported from boh2_dds2_dds3_utils,
  so the page and the PDF share one source of truth for colour.
* camelCase throughout (Kunal's standing preference).

TWO LAYERS
----------
1. DATA layer  -> prepareReportData(engine, cohort, studentNumber, ...) : dict
   Needs pandas + the DB engine. Runs on the machine that runs the notebook.
   Reuses the V2 pipeline (getDataDf, _computeSummaryMetrics, explode/section,
   getCohortItemCodeAverages, ...). Returns a plain JSON-serialisable dict.
2. RENDER layer -> render* + buildStudentReportHtml(data, outPath, ...)
   Pure Python string building from the dict above. No pandas / DB needed, so
   it is trivially testable and editable.

ENTRY POINTS
------------
    import student_report_html_utils as sh
    # one student:
    data = sh.prepareReportData(engine, "BOH2", "1775573",
                                classAvgItemCounts=avgDict)   # avgDict optional
    sh.buildStudentReportHtml(data, "BOH2/Individual Student Reports HTML/1775573.html")
    # whole cohort:
    sh.buildEntireCohortStudentReportsHtml(engine, "BOH2")

The cohort driver mirrors buildEntireCohortStudentReportsV2 (same gating, same
class-average computation, same removed-student skips) and writes to
    {cohort}/Individual Student Reports HTML/{studentNumber}.html
leaving the PDF folders untouched.
"""

import os
import re
import json
import html as _html

import numpy as np
import pandas as pd

import boh2_dds2_dds3_utils as bu
import variableUtils

# ── Palette: single source of truth, imported from the PDF module ────────────
PALETTE = {
    "sim":        bu.V2_SIM_COLOR,
    "clinic":     bu.V2_CLINIC_COLOR,
    "ink":        bu.V2_INK,
    "muted":      bu.V2_MUTED,
    "line":       bu.V2_LINE,
    "page":       bu.V2_PAGE,
    "track":      bu.V2_TRACK,
    "up":         bu.V2_UP,
    "down":       bu.V2_DOWN,
    "eq":         bu.V2_EQ,
    "chipBg":     bu.V2_CHIP_BG,
    "chipAmberBg":   bu.V2_CHIP_AMBER_BG,
    "chipAmberText": bu.V2_CHIP_AMBER_TEXT,
    "navy":       variableUtils.uniColor,      # '#010d44'
    "zebra":      "#dfe6f0",                    # summary alt-row (matches PDF)
    "grColors":   {int(k): v for k, v in bu.V2_GR_COLORS.items()},
    "entColors":  {int(k): v for k, v in bu.V2_ENT_COLORS.items()},
}

DEFAULT_OUT_SUBFOLDER = "Individual Student Reports HTML"
DEFAULT_ASSETS_DIR = "_assets"          # where echarts.min.js lives (project root)
ECHARTS_FILENAME = "echarts.min.js"


# ═════════════════════════════════════════════════════════════════════════════
# DATA LAYER — reuse the V2 pipeline, emit a JSON-serialisable dict
# ═════════════════════════════════════════════════════════════════════════════
def _num(x):
    """None/NaN -> None, else python float/int for JSON."""
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    return x


def _streamGating(cohort, hasSim, hasClinic):
    """Mirror buildStudentReportV2's cohort gating exactly."""
    if cohort == "DDS3":
        hasSim = False
    if cohort in ("BOH1", "DDS1"):
        hasClinic = False
    return hasSim, hasClinic


def _summaryBlock(simMetrics, clinicMetrics, hasSim, hasClinic):
    """Ordered metric keys + per-stream display values. Multi-pair rows (age
    distribution, role counts, patient outcomes) are split into label/number
    pairs exactly like _v2SummaryTable so the HTML table reads the same."""
    from collections import OrderedDict
    allKeys = list(OrderedDict.fromkeys(list(simMetrics.keys()) + list(clinicMetrics.keys())))
    rows = []
    for k in allKeys:
        simRaw = str(simMetrics.get(k, ""))
        clinRaw = str(clinicMetrics.get(k, ""))
        isPairs = ("<br/>" in simRaw) or ("<br/>" in clinRaw)
        if isPairs:
            simPairs = bu._v2SplitPairs(simRaw) if "<br/>" in simRaw else []
            clinPairs = bu._v2SplitPairs(clinRaw) if "<br/>" in clinRaw else []
            template = simPairs or clinPairs
            subLabels = [re.sub(r"<[^>]+>", "", bu._v2ShortLabel(lbl)) for lbl, _ in template]
            rows.append({
                "key": k,
                "label": bu._V2_METRIC_DISPLAY.get(k, k),
                "subLabels": subLabels,
                "sim": [n for _, n in simPairs] if simPairs else None,
                "clinic": [n for _, n in clinPairs] if clinPairs else None,
                "pairs": True,
            })
        else:
            rows.append({
                "key": k,
                "label": bu._V2_METRIC_DISPLAY.get(k, k),
                "sim": (None if simRaw in ("", "None") else simRaw),
                "clinic": (None if clinRaw in ("", "None") else clinRaw),
                "pairs": False,
            })
    return {"rows": rows, "hasSim": hasSim, "hasClinic": hasClinic}


def _ratingsBlock(simDf, clinicDf, hasSim, hasClinic):
    """Entrustment + Global-Rating counts per stream (assessor-submitted only),
    same source as _makeRatingBarsFigureV2."""
    def counts(df):
        if df is None or df.empty:
            return {"entrust": {}, "gr": {}}
        a = df[df["submitted_by_assessor"]]
        return {
            "entrust": {int(k): int(v) for k, v in bu._v2EntCounts(a).items()},
            "gr": {int(k): int(v) for k, v in bu._v2GrCounts(a).items()},
        }
    return {
        "sim": counts(simDf) if hasSim else {"entrust": {}, "gr": {}},
        "clinic": counts(clinicDf) if hasClinic else {"entrust": {}, "gr": {}},
    }


def _proceduresBlock(simAdf, clinicAdf, classAvgItemCounts, cohort, hasSim, hasClinic):
    """Item-code counts vs class average, per stream. Same gating as
    buildStudentReportV2's procPanels."""
    out = {}
    panels = []
    if classAvgItemCounts and classAvgItemCounts.get("Simulation") and hasSim \
            and simAdf is not None and not simAdf.empty and cohort not in ("DDS3", "DDS2"):
        panels.append(("Simulation", simAdf, classAvgItemCounts["Simulation"]))
    if classAvgItemCounts and classAvgItemCounts.get("Clinic") and hasClinic \
            and clinicAdf is not None and not clinicAdf.empty and cohort not in ("BOH1",):
        panels.append(("Clinic", clinicAdf, classAvgItemCounts["Clinic"]))
    for title, adf, cavg in panels:
        cnt = adf["item_codes"].dropna().explode().value_counts().to_dict()
        codesSorted = sorted(cnt, key=lambda c: (-cnt[c], str(c)))
        multi = [c for c in codesSorted if cnt[c] >= 2]
        singles = [c for c in codesSorted if cnt[c] == 1]
        out[title] = {
            "codes": [{"code": str(c), "count": int(cnt[c]),
                       "classAvg": round(float(cavg.get(c, 0.0)), 2)} for c in multi],
            "singles": [{"code": str(c),
                         "classAvg": round(float(cavg.get(c, 0.0)), 2)} for c in singles],
        }
    return out


def _sectionsBlock(longDf, typePages):
    """Per-section aggregates (mean score / GR / ES) per stream — reuse
    _v2SectionAggs so the radar matches the PDF spider."""
    out = {}
    aggs = bu._v2SectionAggs(longDf, typePages)
    for typeLabel, a in aggs.items():
        rows = []
        for sec in a.index.tolist():
            rows.append({
                "section": str(sec),
                "label": bu._sectionLabel(sec),
                "count": int(a.loc[sec, "count"]),
                "meanScore": _num(a.loc[sec, "mean_score"]),
                "meanGr": _num(a.loc[sec, "mean_gr"]),
                "meanEs": _num(a.loc[sec, "mean_es"]),
            })
        if rows:
            out[typeLabel] = {"rows": rows}
    return out


def _timeseriesBlock(typeDf, cohort):
    """Per-assessed-item scatter points + per-date rolling mean + rubric series.
    Mirrors _addTimeSeriesPageV2's inputs (assessor-submitted, scored)."""
    if typeDf is None or typeDf.empty:
        return None
    df = typeDf.sort_values("datetimeutc")
    points = []
    rubric = []
    for _, r in df.iterrows():
        dateStr = r["datetimeutc"].strftime("%Y-%m-%d")
        ent = _num(pd.to_numeric(r.get("entrustment"), errors="coerce"))
        gr = _num(pd.to_numeric(r.get("global_rating"), errors="coerce"))
        clinic = r.get("clinic") if "clinic" in df.columns else None
        assessor = r.get("assessor_name")
        rubric.append({"date": dateStr, "entrust": ent, "gr": gr})
        sc = r.get("scores")
        if isinstance(sc, dict):
            for code, sd in sc.items():
                if isinstance(sd, dict) and sd.get("score") is not None and not pd.isna(sd.get("score")):
                    points.append({
                        "date": dateStr,
                        "code": str(code),
                        "score": round(float(sd["score"]) * 100.0, 1),
                        "entrust": ent, "gr": gr,
                        "clinic": (None if clinic is None or (isinstance(clinic, float) and pd.isna(clinic)) else str(clinic)),
                        "assessor": (None if assessor is None or (isinstance(assessor, float) and pd.isna(assessor)) else str(assessor)),
                    })
    dates = sorted({p["date"] for p in points} | {r["date"] for r in rubric})
    perDate = bu._v2SessionMeanByDate(df)
    roll = []
    if perDate is not None:
        perDate = perDate.reindex(dates)
        rolled = perDate.rolling(3, min_periods=1).mean()
        for d in dates:
            v = rolled.get(d)
            roll.append({"date": d, "mean": (None if v is None or pd.isna(v) else round(float(v), 1))})
    return {"points": points, "rubric": rubric, "roll": roll, "dates": dates}


def _reflectionsBlock(typeDf, minorMaxChars=25):
    """GR-keyed cards + collapsed assist/DA/FTA log — same card/log decision as
    _addReflectionCardsV2."""
    if typeDf is None or typeDf.empty:
        return {"cards": [], "log": []}
    df = typeDf.sort_values("datetimeutc")
    studentCol = "student_reflection_full" if "student_reflection_full" in df.columns else "student_reflection"
    assessorCol = "assessor_reflection_full" if "assessor_reflection_full" in df.columns else "assessor_reflection"
    cards, log = [], []
    for _, row in df.iterrows():
        dateStr = row["datetimeutc"].strftime("%Y-%m-%d")
        codesVal = row.get("item_codes")
        codeStr = ", ".join(map(str, codesVal)) if isinstance(codesVal, (list, tuple)) and len(codesVal) else ""
        studentFull = row.get(studentCol)
        assessorFull = row.get(assessorCol)
        sVis = bu._v2VisibleReflection(studentFull)
        aVis = bu._v2VisibleReflection(assessorFull)
        grRaw = pd.to_numeric(row.get("global_rating"), errors="coerce")
        gr = None if pd.isna(grRaw) else int(round(float(grRaw)))
        if len(sVis) <= minorMaxChars and len(aVis) <= minorMaxChars:
            note = aVis or sVis or "—"
            log.append({"date": dateStr, "type": bu._v2LogTag(sVis, aVis),
                        "note": bu.truncateText(note, 110)})
            continue
        cards.append({
            "date": dateStr, "codes": codeStr, "gr": gr,
            "student": bu.truncateText(studentFull) if studentFull else "",
            "assessor": bu.truncateText(assessorFull) if assessorFull else "",
        })
    return {"cards": cards, "log": log}


def prepareReportData(engine, cohort, studentNumber, formsTable="rawform_forms_v3",
                      patientInfo=True, classAvgItemCounts=None, studentName=None,
                      scoreMap=None):
    """Build the full JSON-serialisable data dict for one student by reusing the
    V2 data pipeline. `classAvgItemCounts` is {"Simulation": {...}, "Clinic": {...}}
    as produced by getCohortItemCodeAverages; if omitted the procedures block is
    empty (charts simply omit the class-average tick)."""
    if scoreMap is None:
        scoreMap = bu.SCORE_MAP

    df = bu.getDataDf(engine, cohort, formsTable, {"student_number": studentNumber})
    df = df.copy()
    df["datetimeutc"] = pd.to_datetime(df["datetimeutc"], utc=True).dt.tz_convert("Australia/Melbourne")

    simDf = df[df["type"] == "Simulation"]
    clinicDf = df[df["type"] == "Clinic"]
    simMetrics = bu._computeSummaryMetrics(simDf, patientInfo=patientInfo, isSimulation=True)
    clinicMetrics = bu._computeSummaryMetrics(clinicDf, patientInfo=patientInfo)
    if patientInfo and clinicMetrics:
        opMetrics = bu._computeSummaryMetrics(bu._v2OperatorClinicDf(clinicDf), patientInfo=patientInfo)
        for k in ("Patient Age Dist.", "Patient Details"):
            if k in clinicMetrics:
                clinicMetrics[k] = opMetrics.get(k, clinicMetrics[k])

    hasSim, hasClinic = _streamGating(cohort, bool(simMetrics), bool(clinicMetrics))

    # analytic (assessor-submitted, scored) frame — same as V2
    adf = df[df["submitted_by_assessor"]].copy()
    typePages, longDf = [], pd.DataFrame()
    simAdf = clinicAdf = None
    if not adf.empty:
        adf["scores"] = adf.apply(lambda r: bu.calcScore(r, scoreMap), axis=1)
        adf.sort_values("datetimeutc", inplace=True)
        longDf = bu.explodeScoresToLong(adf)
        longDf = bu._mergeSection(longDf)
        longDf = bu._v2RemapUnmappedSections(longDf)
        longDf["Section"] = longDf["Section"].replace("Unmapped", "Miscellaneous")
        simAdf = adf[adf["type"] == "Simulation"]
        clinicAdf = adf[adf["type"] == "Clinic"]
        if hasSim and not simAdf.empty:
            typePages.append(("Simulation", simAdf))
        if hasClinic and not clinicAdf.empty:
            typePages.append(("Clinic", clinicAdf))

    if studentName is None:
        try:
            info = bu.getStudentsInCohort(engine, cohort, formsTable).set_index("student_number")
            studentName = info.loc[studentNumber, "student_name"]
        except Exception:
            studentName = str(studentNumber)

    data = {
        "meta": {
            "cohort": cohort,
            "studentNumber": str(studentNumber),
            "studentName": str(studentName),
            "title": "Till Date performance report",
            "generated": pd.Timestamp.now(tz="Australia/Melbourne").strftime("%d %b %Y"),
        },
        "streams": [s for s, ok in (("Simulation", hasSim), ("Clinic", hasClinic)) if ok],
        "summary": _summaryBlock(simMetrics, clinicMetrics, hasSim, hasClinic),
        "ratings": _ratingsBlock(simDf, clinicDf, hasSim, hasClinic),
        "procedures": _proceduresBlock(simAdf, clinicAdf, classAvgItemCounts, cohort, hasSim, hasClinic),
        "sections": _sectionsBlock(longDf, typePages) if typePages else {},
        "timeseries": {t: _timeseriesBlock(d, cohort) for t, d in typePages},
        "reflections": {t: _reflectionsBlock(d) for t, d in typePages},
        "palette": PALETTE,
    }
    return data


# ═════════════════════════════════════════════════════════════════════════════
# RENDER LAYER — one function per element (pure Python, no pandas/DB needed)
# ═════════════════════════════════════════════════════════════════════════════
def esc(s):
    return _html.escape("" if s is None else str(s))


def renderBanner(data):
    """Navy header band: title + student name/number (mirrors the PDF banner)."""
    m = data["meta"]
    return f"""
<header class="banner">
  <div class="bannerInner">
    <div class="bannerTitle">{esc(m['title'])}</div>
    <div class="bannerSub">{esc(m['studentName'])} <span class="dim">({esc(m['studentNumber'])})</span>
      &nbsp;·&nbsp; {esc(m['cohort'])}</div>
  </div>
</header>"""


def renderIntro(data):
    """Intro paragraph (same copy as the PDF, minus the 'we are working on…' line
    since this IS that interactive dashboard)."""
    return """
<p class="intro">This is an interactive summary of your activity so far in 2026.
Hover any chart for detail, use the <b>Simulation / Clinic</b> switch to focus a
stream, and filter your reflections below. For the full record, review your
completed forms in the DASH program.</p>"""


def renderFilterBar(data):
    """Global stream switch (Both / Simulation / Clinic). Drives every element."""
    streams = data["streams"]
    if len(streams) < 2:
        return ""  # single-stream cohort: nothing to switch
    return """
<div class="filterBar" id="streamFilter">
  <span class="filterLabel">View</span>
  <button class="segBtn active" data-stream="both">Both</button>
  <button class="segBtn" data-stream="Simulation">Simulation</button>
  <button class="segBtn" data-stream="Clinic">Clinic</button>
</div>"""


def renderSummary(data):
    """Summary table (Metric / Simulation / Clinic). Zebra rows, navy header —
    same look as _v2SummaryTable. Columns hide with the stream switch."""
    return """
<section class="card" data-block="summary">
  <h2>Summary</h2>
  <div class="tableWrap"><table class="summary" id="summaryTable"></table></div>
</section>"""


def renderRatingDistribution(data):
    """100% stacked horizontal bars: Entrustment + Global Rating, Sim over Clinic
    (replaces the four pies, same as the PDF)."""
    return """
<section class="card" data-block="ratings">
  <h2>Rating Distribution</h2>
  <div class="chartRow">
    <div class="chartHalf"><div class="chartTitle">Entrustment</div><div id="chartEntrust" class="ec ecShort"></div></div>
    <div class="chartHalf"><div class="chartTitle">Global Rating</div><div id="chartGr" class="ec ecShort"></div></div>
  </div>
</section>"""


def renderProcedures(data):
    """Procedures performed: horizontal count bars with a class-average marker;
    single-occurrence codes as chips. One panel per present stream."""
    if not data.get("procedures"):
        return ""
    panels = "".join(
        f'<div class="procPanel" data-stream="{esc(t)}">'
        f'<div class="chartTitle">{esc(t)}</div>'
        f'<div id="chartProc_{esc(t)}" class="ec"></div>'
        f'<div id="chips_{esc(t)}" class="chips"></div></div>'
        for t in data["procedures"].keys()
    )
    return f"""
<section class="card" data-block="procedures">
  <h2>Procedures Performed</h2>
  <p class="hint">Bar = your count · white tick = class average (rounded) ·
    <span style="color:{PALETTE['up']}">▲</span> above /
    <span style="color:{PALETTE['down']}">▽</span> below the cohort.</p>
  <div class="procGrid">{panels}</div>
</section>"""


def renderSectionPerformance(data):
    """Radar per stream: Mean Score, plus GR(/5) & Entrustment(/4) overlay,
    with a section summary table (mirrors the PDF spider + table)."""
    if not data.get("sections"):
        return ""
    panels = "".join(
        f'<div class="secPanel" data-stream="{esc(t)}">'
        f'<div class="chartTitle">{esc(t)} — Section Performance</div>'
        f'<div class="chartRow">'
        f'<div class="chartHalf"><div id="radarScore_{esc(t)}" class="ec ecTall"></div></div>'
        f'<div class="chartHalf"><div id="radarGr_{esc(t)}" class="ec ecTall"></div></div>'
        f'</div>'
        f'<div class="tableWrap"><table class="secTable" id="secTable_{esc(t)}"></table></div>'
        f'</div>'
        for t in data["sections"].keys()
    )
    return f"""
<section class="card" data-block="sections">
  <h2>Performance by Section</h2>
  <div class="secGrid">{panels}</div>
</section>"""


def renderTimeSeries(data):
    """Performance over time: per-item score scatter + rolling-avg line, and a
    rubric panel (Entrustment / Global Rating) sharing the date axis. One block
    per present stream, with a date-range slider."""
    if not data.get("timeseries"):
        return ""
    panels = "".join(
        f'<div class="tsPanel" data-stream="{esc(t)}">'
        f'<div class="chartTitle">{esc(t)} — Performance Over Time</div>'
        f'<div class="tsFilter">'
        f'<input type="search" class="codeFilter" data-stream="{esc(t)}" '
        f'placeholder="Filter item codes — e.g. 311, 5xx, 4*">'
        f'<button class="clearCode" data-stream="{esc(t)}">Clear</button>'
        f'<span class="codeCount" id="codeCount_{esc(t)}"></span></div>'
        f'<div id="tsScatter_{esc(t)}" class="ec ecTall"></div>'
        f'<div id="tsRubric_{esc(t)}" class="ec"></div></div>'
        for t in data["timeseries"].keys() if data["timeseries"][t]
    )
    return f"""
<section class="card" data-block="timeseries">
  <h2>Performance Over Time</h2>
  <p class="hint">Each dot is one assessed item. Hover for the item, score,
    assessor and clinic. Drag the slider to zoom a date range; click a legend
    entry to hide a series. Type item codes to filter — commas for a list, and
    <code>x</code>/<code>*</code> as wildcards (<code>5xx</code> = any 5-series,
    <code>4*</code> = starts with 4). The rolling average recomputes on the filtered set.</p>
  <div class="tsGrid">{panels}</div>
</section>"""


def renderReflections(data):
    """Reflection cards (GR-coloured left band: your reflection + assessor
    feedback) with a GR filter, free-text search and a collapsed assist/FTA log.
    One block per present stream."""
    if not data.get("reflections"):
        return ""
    blocks = ""
    for t, rb in data["reflections"].items():
        if not rb["cards"] and not rb["log"]:
            continue
        blocks += f"""
<div class="reflPanel" data-stream="{esc(t)}">
  <div class="chartTitle">{esc(t)} — Reflections</div>
  <div class="reflControls">
    <input type="search" class="reflSearch" placeholder="Search reflections…"
           data-stream="{esc(t)}">
    <span class="grChips" data-stream="{esc(t)}">
      <button class="grChip active" data-gr="all">All GR</button>
      <button class="grChip" data-gr="1">1</button><button class="grChip" data-gr="2">2</button>
      <button class="grChip" data-gr="3">3</button><button class="grChip" data-gr="4">4</button>
      <button class="grChip" data-gr="5">5</button>
    </span>
  </div>
  <div class="reflCards" id="reflCards_{esc(t)}"></div>
  <div class="reflLog" id="reflLog_{esc(t)}"></div>
</div>"""
    if not blocks:
        return ""
    return f'<section class="card" data-block="reflections"><h2>Reflections</h2>{blocks}</section>'


def _css():
    P = PALETTE
    return f"""
:root{{
  --sim:{P['sim']}; --clinic:{P['clinic']}; --ink:{P['ink']}; --muted:{P['muted']};
  --line:{P['line']}; --page:{P['page']}; --navy:{P['navy']}; --zebra:{P['zebra']};
  --up:{P['up']}; --down:{P['down']}; --chipBg:{P['chipBg']};
  --chipAmberBg:{P['chipAmberBg']}; --chipAmberText:{P['chipAmberText']};
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--page);color:var(--ink);
  font-family:'Segoe UI',Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45}}
.wrap{{max-width:1100px;margin:0 auto;padding:0 20px 60px}}
.banner{{background:var(--navy);color:#fff;padding:26px 0}}
.bannerInner{{max-width:1100px;margin:0 auto;padding:0 20px}}
.bannerTitle{{font-size:26px;font-weight:700;letter-spacing:.2px}}
.bannerSub{{font-size:15px;margin-top:6px;opacity:.92}}
.bannerSub .dim{{opacity:.7}}
.intro{{color:var(--muted);margin:18px 0 6px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:10px;
  padding:18px 20px 22px;margin:18px 0;box-shadow:0 1px 2px rgba(20,30,60,.04)}}
.card h2{{margin:0 0 14px;font-size:19px;color:var(--navy)}}
.hint,.chartTitle{{color:var(--muted)}}
.hint{{font-size:12.5px;margin:-4px 0 12px}}
.chartTitle{{font-weight:700;color:var(--ink);font-size:13.5px;margin:6px 0 4px}}
.chartRow{{display:flex;gap:18px;flex-wrap:wrap}}
.chartHalf{{flex:1 1 340px;min-width:300px}}
.ec{{width:100%;height:320px}}
.ec.ecShort{{height:210px}}
.ec.ecTall{{height:380px}}
/* filter bar */
.filterBar{{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:8px;
  background:var(--page);padding:12px 0 6px;margin-top:6px}}
.filterLabel{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.5px;margin-right:4px}}
.segBtn,.grChip{{border:1px solid var(--line);background:#fff;color:var(--ink);
  padding:6px 14px;border-radius:20px;cursor:pointer;font-size:13px}}
.segBtn.active{{background:var(--navy);color:#fff;border-color:var(--navy)}}
.grChip{{padding:4px 11px}}
.grChip.active{{background:var(--navy);color:#fff;border-color:var(--navy)}}
/* summary + section tables */
table{{border-collapse:collapse;width:100%}}
.summary th,.summary td,.secTable th,.secTable td{{padding:8px 12px;border-bottom:1px solid var(--line);text-align:right}}
.summary th:first-child,.summary td:first-child,.secTable th:first-child,.secTable td:first-child{{text-align:left}}
.summary thead th,.secTable thead th{{background:var(--navy);color:#fff;border-bottom:none}}
.summary tbody tr:nth-child(even),.secTable tbody tr:nth-child(even){{background:var(--zebra)}}
.summary .sub{{display:block;color:var(--muted);font-size:11px;font-weight:400}}
.tableWrap{{overflow-x:auto}}
/* procedures */
.tsFilter{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:2px 0 8px}}
.codeFilter{{flex:1 1 260px;padding:7px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px}}
.clearCode{{border:1px solid var(--line);background:#fff;color:var(--ink);padding:6px 12px;border-radius:8px;cursor:pointer;font-size:13px}}
.codeCount{{color:var(--muted);font-size:12px}}
.procGrid,.secGrid,.tsGrid{{display:flex;flex-direction:column;gap:14px}}
.procGrid{{flex-direction:row;flex-wrap:wrap}}
.procPanel{{flex:1 1 380px;min-width:320px}}
.chips{{display:flex;flex-wrap:wrap;gap:7px;margin-top:8px}}
.chip{{background:var(--chipBg);color:var(--ink);border-radius:20px;padding:3px 11px;font-size:12px}}
.chip.amber{{background:var(--chipAmberBg);color:var(--chipAmberText)}}
/* reflections */
.reflControls{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:6px 0 14px}}
.reflSearch{{flex:1 1 240px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px}}
.reflCards{{display:flex;flex-direction:column;gap:12px}}
.reflCard{{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}}
.reflBar{{width:6px;flex:0 0 6px}}
.reflBody{{padding:10px 14px;flex:1;min-width:0}}
.reflHead{{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid var(--line);
  padding-bottom:6px;margin-bottom:8px}}
.reflHead .codes{{color:var(--muted);font-weight:400}}
.reflGr{{font-weight:700}}
.reflTwo{{display:flex;gap:22px;flex-wrap:wrap}}
.reflCol{{flex:1 1 260px;min-width:0}}
.reflCol .lab{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.4px;margin-bottom:3px}}
.reflLog{{margin-top:14px}}
.reflLog table td{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left}}
.reflLog .logHead{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.4px;margin:6px 0}}
.empty{{color:var(--muted);font-style:italic;padding:8px 0}}
[hidden]{{display:none!important}}
@media print{{.filterBar{{display:none}} .card{{break-inside:avoid}}}}
"""


def _reportJs():
    """All chart/option builders + filter wiring. One _ec* / render* per element,
    mirroring the Python render functions so each block stays editable."""
    # NB: kept as a raw JS string; data + palette are injected as JSON below it.
    return r"""
const P = REPORT.palette;
const GRC = P.grColors, ENTC = P.entColors;
const charts = {};   // id -> echarts instance (for resize/dispose)
function ec(id){ const el=document.getElementById(id); if(!el) return null;
  if(charts[id]) return charts[id]; const c=echarts.init(el,null,{renderer:'canvas'});
  charts[id]=c; return c; }
const baseTip = {backgroundColor:'#fff',borderColor:P.line,borderWidth:1,
  textStyle:{color:P.ink,fontSize:12},extraCssText:'box-shadow:0 2px 8px rgba(20,30,60,.12)'};
const axisText = {color:P.muted,fontSize:11};
const streamColor = s => s==='Simulation'?P.sim:P.clinic;

/* ── element: summary table ─────────────────────────────────────────────── */
function renderSummaryTable(state){
  const S=REPORT.summary, t=document.getElementById('summaryTable'); if(!t) return;
  const cols=[]; if(S.hasSim) cols.push('Simulation'); if(S.hasClinic) cols.push('Clinic');
  const show = c => state.stream==='both' || state.stream===c;
  let head='<thead><tr><th>Metric</th>'+cols.map(c=>`<th${show(c)?'':' hidden'}>${c}</th>`).join('')+'</tr></thead>';
  let body='<tbody>';
  for(const r of S.rows){
    body+='<tr><td>'+esc(r.label);
    if(r.pairs && r.subLabels && r.subLabels.length) body+='<span class="sub">'+r.subLabels.map(esc).join(' · ')+'</span>';
    body+='</td>';
    for(const c of cols){
      const key=c==='Simulation'?'sim':'clinic';
      let v=r[key];
      if(r.pairs) v = (v&&v.length)? v.join(' · ') : '—';
      else v = (v==null||v==='')? '—' : v;
      body+=`<td${show(c)?'':' hidden'}>${esc(v)}</td>`;
    }
    body+='</tr>';
  }
  t.innerHTML=head+body+'</tbody>';
}

/* ── element: rating distribution (100% stacked bars) ───────────────────── */
function _ecStacked(counts, colorMap, prefix, state){
  const rows=[]; // [label, countsObj, color]
  if(REPORT.summary.hasClinic && (state.stream==='both'||state.stream==='Clinic'))
    rows.push(['Clinic',counts.clinic,P.clinic]);
  if(REPORT.summary.hasSim && (state.stream==='both'||state.stream==='Simulation'))
    rows.push(['Simulation',counts.sim,P.sim]);
  const levels=new Set(); rows.forEach(r=>Object.keys(r[1]||{}).forEach(k=>levels.add(+k)));
  const lv=[...levels].sort((a,b)=>a-b);
  const totals=rows.map(r=>Object.values(r[1]||{}).reduce((a,b)=>a+b,0));
  const series=lv.map(l=>({name:prefix+' '+l,type:'bar',stack:'x',
    itemStyle:{color:colorMap[l]||'#999',borderColor:'#fff',borderWidth:1},
    label:{show:true,formatter:p=>{const pct=p.value; return pct>=9?pct.toFixed(0)+'%':(pct>=3?'':'')},
      color:'#fff',fontWeight:'bold',fontSize:10},
    data:rows.map((r,i)=>{const n=(r[1]||{})[l]||0; return totals[i]? +(n/totals[i]*100).toFixed(2):0;}),
    _raw:rows.map(r=>(r[1]||{})[l]||0)
  }));
  return {backgroundColor:'transparent',grid:{left:76,right:16,top:8,bottom:34},
    tooltip:{...baseTip,trigger:'item',formatter:p=>{
      const n=p.series._raw?p.series._raw[p.dataIndex]:'';
      return `<b>${rows[p.dataIndex][0]}</b><br/>${p.seriesName}: ${n} (${p.value.toFixed(0)}%)`;}},
    legend:{bottom:0,textStyle:axisText,itemWidth:12,itemHeight:12},
    xAxis:{type:'value',max:100,axisLabel:{...axisText,formatter:'{value}%'},splitLine:{lineStyle:{type:'dashed',opacity:.4}}},
    yAxis:{type:'category',data:rows.map(r=>r[0]),axisLabel:axisText,axisTick:{show:false}},
    series};
}
function renderRatings(state){
  const R=REPORT.ratings;
  const e=ec('chartEntrust'); if(e) e.setOption(_ecStacked(
    {sim:R.sim.entrust,clinic:R.clinic.entrust}, ENTC,'Lvl',state),true);
  const g=ec('chartGr'); if(g) g.setOption(_ecStacked(
    {sim:R.sim.gr,clinic:R.clinic.gr}, GRC,'GR',state),true);
}

/* ── element: procedures (count bars + class-average marker) ─────────────── */
function _ecProc(panel, stream){
  const codes=panel.codes.slice().reverse(); // top code at top
  const cats=codes.map(c=>c.code);
  const vals=codes.map(c=>c.count);
  const avg=codes.map(c=>({value:[Math.round(c.classAvg),c.code],code:c.code}));
  const col=streamColor(stream);
  return {backgroundColor:'transparent',grid:{left:64,right:26,top:10,bottom:28},
    tooltip:{...baseTip,trigger:'axis',axisPointer:{type:'shadow'},formatter:ps=>{
      const c=codes.find(x=>x.code===ps[0].name); if(!c) return '';
      const d=c.count-Math.round(c.classAvg);
      const sym=d>0?`<span style="color:${P.up}">▲ +${d}</span>`:(d<0?`<span style="color:${P.down}">▽ −${Math.abs(d)}</span>`:'= 0');
      return `<b>${c.code}</b><br/>You: ${c.count}<br/>Class avg: ${Math.round(c.classAvg)}<br/>${sym}`;}},
    xAxis:{type:'value',axisLabel:axisText,splitLine:{lineStyle:{type:'dashed',opacity:.25}}},
    yAxis:{type:'category',data:cats,axisLabel:{...axisText},axisTick:{show:false}},
    series:[
      {type:'bar',data:vals,barWidth:'62%',itemStyle:{color:col},
       label:{show:true,position:'right',color:P.ink,fontSize:10}},
      {type:'scatter',data:avg,symbol:'diamond',symbolSize:9,
       itemStyle:{color:P.ink},tooltip:{show:false},z:5}
    ]};
}
function renderProcedures(){
  if(!REPORT.procedures) return;
  for(const [t,panel] of Object.entries(REPORT.procedures)){
    const c=ec('chartProc_'+t); if(c){
      const el=document.getElementById('chartProc_'+t);
      if(el) el.style.height=Math.max(200, panel.codes.length*26+40)+'px';
      c.resize(); c.setOption(_ecProc(panel,t),true);
    }
    const chipEl=document.getElementById('chips_'+t);
    if(chipEl){ chipEl.innerHTML = panel.singles.length
      ? '<b style="color:'+P.muted+';font-size:12px;width:100%">Single occurrences (class avg in brackets · amber = fewer than the cohort typically does):</b>'
        + panel.singles.map(s=>{const a=Math.round(s.classAvg)>1;
            return `<span class="chip${a?' amber':''}">${esc(s.code)} (${Math.round(s.classAvg)})</span>`;}).join('')
      : ''; }
  }
}

/* ── element: section radar (score + GR/ES overlay) ─────────────────────── */
function _radarIndicators(rows,divisor){return rows.map(r=>({name:r.label+' (n='+r.count+')',max:1}));}
function _ecRadarScore(rows,stream){
  return {backgroundColor:'transparent',
    tooltip:{...baseTip,formatter:p=>rows.map((r,i)=>`${r.label}: ${(r.meanScore*100).toFixed(0)}%`).join('<br/>')},
    radar:{indicator:_radarIndicators(rows),radius:'62%',axisName:{color:P.muted,fontSize:10},
      splitLine:{lineStyle:{color:P.line}},splitArea:{areaStyle:{color:['#fff','#f5f7fb']}}},
    series:[{type:'radar',areaStyle:{opacity:.22,color:streamColor(stream)},
      lineStyle:{color:streamColor(stream),width:2},itemStyle:{color:streamColor(stream)},
      data:[{value:rows.map(r=>r.meanScore),name:'Mean Score'}]}],
    title:{text:'Mean Score',left:'center',top:4,textStyle:{color:P.ink,fontSize:12}}};
}
function _ecRadarGr(rows){
  const gr=rows.map(r=>r.meanGr==null?0:r.meanGr/5);
  const es=rows.map(r=>r.meanEs==null?0:r.meanEs/4);
  return {backgroundColor:'transparent',
    tooltip:{...baseTip,formatter:()=>rows.map(r=>`${r.label}: GR ${r.meanGr==null?'—':r.meanGr.toFixed(1)}/5 · ES ${r.meanEs==null?'—':r.meanEs.toFixed(1)}/4`).join('<br/>')},
    legend:{bottom:0,textStyle:axisText,data:['Global Rating (/5)','Entrustment (/4)']},
    radar:{indicator:_radarIndicators(rows),radius:'60%',axisName:{color:P.muted,fontSize:10},
      splitLine:{lineStyle:{color:P.line}},splitArea:{areaStyle:{color:['#fff','#f5f7fb']}}},
    series:[
      {type:'radar',name:'Global Rating (/5)',areaStyle:{opacity:.15,color:'#2ca02c'},
        lineStyle:{color:'#2ca02c',width:2},itemStyle:{color:'#2ca02c'},data:[{value:gr}]},
      {type:'radar',name:'Entrustment (/4)',lineStyle:{color:'#ff7f0e',width:2},
        itemStyle:{color:'#ff7f0e'},data:[{value:es}]}
    ],
    title:{text:'GR & Entrustment',left:'center',top:4,textStyle:{color:P.ink,fontSize:12}}};
}
function renderSections(){
  if(!REPORT.sections) return;
  for(const [t,blk] of Object.entries(REPORT.sections)){
    const rows=blk.rows;
    const s=ec('radarScore_'+t); if(s) s.setOption(_ecRadarScore(rows,t),true);
    const g=ec('radarGr_'+t); if(g) g.setOption(_ecRadarGr(rows),true);
    const tbl=document.getElementById('secTable_'+t);
    if(tbl){ tbl.innerHTML='<thead><tr><th>Section</th><th># Items</th><th>Mean Score</th><th>Mean GR</th><th>Mean ES</th></tr></thead><tbody>'
      + rows.map(r=>`<tr><td>${esc(r.label)}</td><td>${r.count}</td><td>${(r.meanScore*100).toFixed(0)}%</td>`
        +`<td>${r.meanGr==null?'N/A':r.meanGr.toFixed(1)+'/5'}</td>`
        +`<td>${r.meanEs==null?'N/A':r.meanEs.toFixed(1)+'/4'}</td></tr>`).join('')+'</tbody>'; }
  }
}

/* ── element: time series (scatter + rolling avg, and rubric) ───────────── */
/* code filter: "311, 5xx, 4*" -> list of regexes. x and * are wildcards       */
function _parseCodeQuery(str){
  return (str||'').split(',').map(s=>s.trim()).filter(Boolean).map(tok=>{
    let re=''; for(const ch of tok){
      if(ch==='x'||ch==='X'||ch==='*') re+= (ch==='*')?'.*':'.';
      else re+=ch.replace(/[.+?^${}()|[\]\\]/g,'\\$&');
    }
    return new RegExp('^'+re+'$','i');
  });
}
function _matchCode(code, regexes){
  if(!regexes.length) return true;
  return regexes.some(r=>r.test(String(code)));
}
/* recompute the 3-point rolling mean from the filtered points (pandas-style:   */
/* a value at each date that has data, averaging the last up-to-3 such dates)    */
function _rollFromPoints(points, dates){
  const byDate={}; points.forEach(p=>{(byDate[p.date]=byDate[p.date]||[]).push(p.score);});
  const means=dates.map(d=>byDate[d]? byDate[d].reduce((a,b)=>a+b,0)/byDate[d].length : null);
  const out=[];
  for(let i=0;i<dates.length;i++){
    if(means[i]==null) continue;
    const win=means.slice(Math.max(0,i-2),i+1).filter(v=>v!=null);
    out.push([i, +(win.reduce((a,b)=>a+b,0)/win.length).toFixed(1)]);
  }
  return out;
}
function _ecScatter(ts,stream,codeQuery){
  const dates=ts.dates;
  const regexes=_parseCodeQuery(codeQuery);
  const fpoints=ts.points.filter(p=>_matchCode(p.code,regexes));
  const pts=fpoints.map(p=>({value:[dates.indexOf(p.date),p.score],raw:p}));
  const roll=_rollFromPoints(fpoints, dates);
  const cc=document.getElementById('codeCount_'+stream);
  if(cc) cc.textContent = regexes.length? `${fpoints.length} of ${ts.points.length} items` : '';
  return {backgroundColor:'transparent',grid:{left:46,right:20,top:16,bottom:70},
    tooltip:{...baseTip,formatter:p=>{ if(p.seriesType==='line') return `Rolling avg (3): ${p.value[1].toFixed(0)}%`;
      const r=p.data.raw; return `<b>${r.date}</b> · ${esc(r.code)}<br/>Score: ${r.score.toFixed(0)}%`
        +(r.gr!=null?`<br/>GR ${r.gr} · ES ${r.entrust!=null?r.entrust:'—'}`:'')
        +(r.assessor?`<br/>Assessor: ${esc(r.assessor)}`:'')+(r.clinic?`<br/>Clinic: ${esc(r.clinic)}`:''); }},
    legend:{bottom:34,textStyle:axisText,data:['Item scores','Rolling avg (3)']},
    dataZoom:[{type:'slider',xAxisIndex:0,bottom:4,height:16,startValue:0}],
    xAxis:{type:'category',data:dates,axisLabel:{...axisText,rotate:45,fontSize:9},boundaryGap:true},
    yAxis:{type:'value',min:0,max:100,axisLabel:{...axisText,formatter:'{value}%'},splitLine:{lineStyle:{type:'dashed',opacity:.35}}},
    series:[
      {name:'Item scores',type:'scatter',symbolSize:8,itemStyle:{color:streamColor(stream),opacity:.75},data:pts},
      {name:'Rolling avg (3)',type:'line',smooth:true,symbol:'none',
        lineStyle:{color:P.navy,width:1.6,opacity:.6},data:roll}
    ]};
}
function _ecRubric(ts){
  const dates=ts.dates;
  const ent=ts.rubric.map(r=>[dates.indexOf(r.date),r.entrust]);
  const gr=ts.rubric.map(r=>[dates.indexOf(r.date),r.gr]);
  return {backgroundColor:'transparent',grid:{left:46,right:20,top:24,bottom:52},
    tooltip:{...baseTip,trigger:'axis'},
    legend:{top:0,textStyle:axisText,data:['Entrustment','Global Rating']},
    dataZoom:[{type:'slider',xAxisIndex:0,bottom:4,height:14}],
    xAxis:{type:'category',data:dates,axisLabel:{...axisText,rotate:45,fontSize:9}},
    yAxis:{type:'value',min:0,axisLabel:axisText,splitLine:{lineStyle:{type:'dashed',opacity:.35}}},
    series:[
      {name:'Entrustment',type:'line',connectNulls:true,symbolSize:6,lineStyle:{color:'#1f77b4'},itemStyle:{color:'#1f77b4'},data:ent},
      {name:'Global Rating',type:'line',connectNulls:true,symbolSize:6,lineStyle:{color:'#2ca02c'},itemStyle:{color:'#2ca02c'},data:gr}
    ]};
}
function renderTimeSeries(){
  if(!REPORT.timeseries) return;
  for(const [t,ts] of Object.entries(REPORT.timeseries)){
    if(!ts) continue;
    const s=ec('tsScatter_'+t); if(s) s.setOption(_ecScatter(ts,t,''),true);
    const r=ec('tsRubric_'+t); if(r) r.setOption(_ecRubric(ts),true);
  }
}
function applyTsFilter(stream){
  const ts=REPORT.timeseries&&REPORT.timeseries[stream]; if(!ts) return;
  const box=document.querySelector('.codeFilter[data-stream="'+CSS.escape(stream)+'"]');
  const s=ec('tsScatter_'+stream);
  if(s) s.setOption(_ecScatter(ts,stream,box?box.value:''),true);
}

/* ── element: reflection cards + log (client-side filtered) ─────────────── */
function _cardHtml(c){
  const bar=GRC[c.gr]||'#c9ced8'; const badge=c.gr!=null?('GR '+c.gr):'GR —';
  const bcol=GRC[c.gr]||P.muted;
  return `<div class="reflCard" data-gr="${c.gr==null?'':c.gr}" data-text="${esc((c.student+' '+c.assessor+' '+c.codes).toLowerCase())}">
    <div class="reflBar" style="background:${bar}"></div>
    <div class="reflBody">
      <div class="reflHead"><span><b>${esc(c.date)}</b> <span class="codes">${esc(c.codes)}</span></span>
        <span class="reflGr" style="color:${bcol}">${badge}</span></div>
      <div class="reflTwo">
        <div class="reflCol"><div class="lab">Your reflection</div><div>${c.student?esc(c.student):'<i>—</i>'}</div></div>
        <div class="reflCol"><div class="lab">Assessor feedback</div><div>${c.assessor?esc(c.assessor):'<i>—</i>'}</div></div>
      </div>
    </div></div>`;
}
function renderReflections(){
  if(!REPORT.reflections) return;
  for(const [t,rb] of Object.entries(REPORT.reflections)){
    const cardWrap=document.getElementById('reflCards_'+t);
    if(cardWrap) cardWrap.innerHTML = rb.cards.length? rb.cards.map(_cardHtml).join('')
      : '<div class="empty">No written reflections in this stream.</div>';
    const logWrap=document.getElementById('reflLog_'+t);
    if(logWrap) logWrap.innerHTML = rb.log.length
      ? '<div class="logHead">Assist / support / cancelled sessions</div><table><tbody>'
        + rb.log.map(l=>`<tr><td style="width:110px">${esc(l.date)}</td><td style="width:120px">${esc(l.type)}</td><td>${esc(l.note)}</td></tr>`).join('')
        + '</tbody></table>' : '';
  }
}
function filterReflections(stream){
  const wrap=document.getElementById('reflCards_'+stream); if(!wrap) return;
  const box=document.querySelector('.reflSearch[data-stream="'+CSS.escape(stream)+'"]');
  const q=(box?box.value:'').trim().toLowerCase();
  const grBtn=document.querySelector('.grChips[data-stream="'+CSS.escape(stream)+'"] .grChip.active');
  const gr=grBtn?grBtn.dataset.gr:'all';
  wrap.querySelectorAll('.reflCard').forEach(card=>{
    const okText=!q || card.dataset.text.includes(q);
    const okGr=gr==='all' || card.dataset.gr===gr;
    card.hidden=!(okText&&okGr);
  });
}

/* ── global helpers + filter wiring ─────────────────────────────────────── */
function esc(s){return (s==null?'':String(s)).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));}
function applyStream(stream){
  document.querySelectorAll('[data-stream]').forEach(el=>{
    if(el.classList.contains('segBtn')||el.classList.contains('grChip')||el.classList.contains('reflSearch')
       ||el.parentElement.classList.contains('grChips')) return;
    const s=el.getAttribute('data-stream');
    el.hidden = !(stream==='both'||stream===s);
  });
  renderSummaryTable({stream}); renderRatings({stream});
  Object.values(charts).forEach(c=>c.resize());
}
function initFilters(){
  const sf=document.getElementById('streamFilter');
  if(sf) sf.querySelectorAll('.segBtn').forEach(b=>b.addEventListener('click',()=>{
    sf.querySelectorAll('.segBtn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); applyStream(b.dataset.stream);
  }));
  document.querySelectorAll('.reflSearch').forEach(box=>box.addEventListener('input',()=>filterReflections(box.dataset.stream)));
  document.querySelectorAll('.codeFilter').forEach(box=>box.addEventListener('input',()=>applyTsFilter(box.dataset.stream)));
  document.querySelectorAll('.clearCode').forEach(btn=>btn.addEventListener('click',()=>{
    const box=document.querySelector('.codeFilter[data-stream="'+CSS.escape(btn.dataset.stream)+'"]');
    if(box){box.value='';} applyTsFilter(btn.dataset.stream);
  }));
  document.querySelectorAll('.grChips').forEach(grp=>grp.querySelectorAll('.grChip').forEach(chip=>chip.addEventListener('click',()=>{
    grp.querySelectorAll('.grChip').forEach(x=>x.classList.remove('active'));
    chip.classList.add('active'); filterReflections(grp.dataset.stream);
  })));
}
function boot(){
  renderSummaryTable({stream:'both'}); renderRatings({stream:'both'});
  renderProcedures(); renderSections(); renderTimeSeries(); renderReflections();
  initFilters();
  window.addEventListener('resize',()=>Object.values(charts).forEach(c=>c.resize()));
}
document.addEventListener('DOMContentLoaded',boot);
"""


def _loadEcharts(assetsDir):
    """Read the vendored echarts.min.js so it can be inlined (self-contained)."""
    path = os.path.join(assetsDir, ECHARTS_FILENAME)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"ECharts not found at {path}. Place echarts.min.js in '{assetsDir}/' "
            f"(vendored once; see the handover doc).")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def renderPage(data, echartsJs):
    """Assemble the full self-contained HTML document from the element fragments."""
    body = "\n".join([
        renderBanner(data),
        '<div class="wrap">',
        renderFilterBar(data),
        renderIntro(data),
        renderSummary(data),
        renderRatingDistribution(data),
        renderProcedures(data),
        renderSectionPerformance(data),
        renderTimeSeries(data),
        renderReflections(data),
        "</div>",
    ])
    dataJson = json.dumps(data, ensure_ascii=False, allow_nan=False)
    m = data["meta"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(m['studentName'])} — {esc(m['title'])}</title>
<style>{_css()}</style>
</head><body>
{body}
<script>{echartsJs}</script>
<script>const REPORT = {dataJson};</script>
<script>{_reportJs()}</script>
</body></html>"""


def buildStudentReportHtml(data, outPath, assetsDir=DEFAULT_ASSETS_DIR, echartsJs=None):
    """Render one student's data dict to a self-contained .html at outPath."""
    if echartsJs is None:
        echartsJs = _loadEcharts(assetsDir)
    os.makedirs(os.path.dirname(outPath) or ".", exist_ok=True)
    with open(outPath, "w", encoding="utf-8") as f:
        f.write(renderPage(data, echartsJs))
    return outPath


# ═════════════════════════════════════════════════════════════════════════════
# COHORT DRIVER — mirrors buildEntireCohortStudentReportsV2
# ═════════════════════════════════════════════════════════════════════════════
def buildEntireCohortStudentReportsHtml(engine, cohort, formsTable="rawform_forms_v3",
                                        patientInfo=True, outSubfolder=DEFAULT_OUT_SUBFOLDER,
                                        assetsDir=DEFAULT_ASSETS_DIR, onlyStudents=None,
                                        scoreMap=None):
    """Build interactive HTML reports for a whole cohort. Same data/gating as the
    PDF V2 driver; writes {cohort}/{outSubfolder}/{studentNumber}.html. The PDF
    folders are never touched."""
    echartsJs = _loadEcharts(assetsDir)   # read once, inline into every file
    studentInfoDf = bu.getStudentsInCohort(engine, cohort, formsTable).set_index("student_number")
    studentIds = studentInfoDf.index.tolist()
    if onlyStudents is not None:
        want = {str(x) for x in onlyStudents}
        studentIds = [i for i in studentIds if str(i) in want]

    classAvgSim = classAvgClinic = None
    if cohort not in ("DDS2", "DDS3"):
        classAvgSim = bu.getCohortItemCodeAverages(engine, cohort, formType="Simulation", formsTable=formsTable)
    if cohort not in ("BOH1",):
        classAvgClinic = bu.getCohortItemCodeAverages(engine, cohort, formType="Clinic", formsTable=formsTable)
    classAvgItemCounts = {"Simulation": classAvgSim, "Clinic": classAvgClinic}

    savefolder = f"{cohort}/{outSubfolder}"
    os.makedirs(savefolder, exist_ok=True)
    written = []
    for sid in studentIds:
        if cohort == "DDS2" and sid in bu.DDS2_REMOVED_STUDENTS:
            continue
        if cohort == "BOH2" and sid in bu.BOH2_REMOVED_STUDENTS:
            continue
        name = studentInfoDf.loc[sid, "student_name"]
        print(f"[HTML] Building report for student {sid} - {name}")
        try:
            data = prepareReportData(engine, cohort, sid, formsTable=formsTable,
                                     patientInfo=patientInfo, classAvgItemCounts=classAvgItemCounts,
                                     studentName=name, scoreMap=scoreMap)
            outPath = f"{savefolder}/{sid}.html"
            buildStudentReportHtml(data, outPath, echartsJs=echartsJs)
            written.append(outPath)
            print(f"[HTML] Report saved to {outPath}")
        except Exception as e:
            print(f"[HTML] FAILED for {sid}: {type(e).__name__}: {e}")
    print(f"[HTML] Done — {len(written)} reports in {savefolder}")
    return written
