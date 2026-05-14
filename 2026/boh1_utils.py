"""
boh1_utils.py
Query, processing, and report-building functions for the BOH1 cohort.

BOH1 uses option keys (O1–O6) in student_data/assessor_data, with item codes
as top-level JSONB keys (e.g., "221", "114 H/S", "531").  Scales are stored as
{"scale": "N"} values under keys like "scale-practice-readiness".

Usage in notebook:
    from boh1_utils import *
"""

import re
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils.dataframe import dataframe_to_rows

from Utils import readDf
import variableUtils

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

BOH1_TABLE   = "rawform_forms"   # override per environment if needed
BOH1_COHORT  = "BOH1"

# Scoring weights — O6 (N/A) is excluded from score AND from denominator
SCORE_MAP = {
    "O1": 1.00,  # Done well
    "O2": 0.80,  # Done
    "O3": 0.60,  # Mostly done
    "O4": 0.40,  # Sometimes done
    "O5": 0.00,  # Not done
}

OPTION_LABELS = {
    "O1": "Done well",
    "O2": "Done",
    "O3": "Mostly done",
    "O4": "Sometimes done",
    "O5": "Not done",
    "O6": "N/A",
}

# Global Rating labels (1–5)
GLOBAL_RATING_LABELS = {1: "Unsatisfactory", 2: "Borderline", 3: "Satisfactory",
                         4: "Good", 5: "Excellent"}

# Practice Readiness labels (1–4)
PRACTICE_READINESS_LABELS = {
    1: "L1 – Not ready",
    2: "L2 – Ready with continuous supervision",
    3: "L3 – Ready with periodic supervision",
    4: "L4 – Ready with indirect supervision",
}

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sanitizeSheet(name: str) -> str:
    safe = re.sub(r'[\[\]\:\*\?\/\\]', '', str(name or '')).strip()
    return (safe[:31] or "Sheet")


def _autoFit(ws, minW=10, maxW=60):
    for col in ws.columns:
        best = max((len(str(c.value)) for c in col if c.value is not None), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = max(minW, min(maxW, best + 2))


def _headerRow(ws, row: int, cols: list, fillHex="1F4E79"):
    fill = PatternFill("solid", fgColor=fillHex)
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for j, col in enumerate(cols, 1):
        c = ws.cell(row=row, column=j, value=col)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
        c.alignment = Alignment(wrap_text=True, vertical="top", horizontal="center")
        c.border = border
    return row + 1


def _dataRow(ws, row: int, values: list, shade=False):
    fill = PatternFill("solid", fgColor="D9E1F2") if shade else None
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for j, v in enumerate(values, 1):
        c = ws.cell(row=row, column=j, value=v)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.border = border
        if fill:
            c.fill = fill
    return row + 1


def _sectionTitle(ws, row: int, title: str, ncols: int = 1, fillHex="2E75B6"):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=title)
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=fillHex)
    c.alignment = Alignment(vertical="center")
    return row + 1

# ─────────────────────────────────────────────────────────────────────────────
# WHERE clause builder
# ─────────────────────────────────────────────────────────────────────────────

def _where(cohort: str, dateFrom=None, dateTo=None, filters: dict = None):
    """
    Build WHERE clause + params for BOH1 queries.

    Parameters
    ----------
    cohort   : str  — cohort value (e.g. "BOH1")
    dateFrom : str  — inclusive lower date bound (YYYY-MM-DD), or None
    dateTo   : str  — inclusive upper date bound (YYYY-MM-DD), or None
    filters  : dict — additional column=value filters; lists become ANY()
    """
    clauses = ["cohort = :cohort", "submitted_by_assessor = true"]
    params  = {"cohort": cohort}

    if dateFrom:
        clauses.append("DATE(datetimeutc AT TIME ZONE 'Australia/Melbourne') >= :dateFrom")
        params["dateFrom"] = dateFrom
    if dateTo:
        clauses.append("DATE(datetimeutc AT TIME ZONE 'Australia/Melbourne') <= :dateTo")
        params["dateTo"] = dateTo

    if filters:
        for key, val in filters.items():
            if isinstance(val, list):
                clauses.append(f"{key} = ANY(:{key})")
            else:
                clauses.append(f"{key} = :{key}")
            params[key] = val

    return " AND ".join(clauses), params


# ─────────────────────────────────────────────────────────────────────────────
# Core query: per-(assessment, item_code) scores from assessor_data
# ─────────────────────────────────────────────────────────────────────────────

def getChecklistScores(
    engine,
    itemCodes: list,
    cohort: str        = BOH1_COHORT,
    dateFrom: str      = None,
    dateTo: str        = None,
    formsTable: str    = BOH1_TABLE,
    filters: dict      = None,
) -> pd.DataFrame:
    """
    Return one row per (assessmentid, item_code) with score, %score and
    all scale values.

    Parameters
    ----------
    engine     : SQLAlchemy engine
    itemCodes  : list of item code strings, e.g. ["221", "114 H/S", "531"]
    cohort     : cohort filter (default "BOH1")
    dateFrom   : YYYY-MM-DD lower bound (inclusive), or None
    dateTo     : YYYY-MM-DD upper bound (inclusive), or None
    formsTable : table name (default BOH1_TABLE)
    filters    : extra WHERE filters (dict)

    Returns
    -------
    pd.DataFrame with columns:
        Assessment ID, Student ID, Student Name, Assessor, Date,
        Item Code, Item Name,
        Practice Readiness, Global Rating, Time Management,
        Communication, Professionalism, Position & Ergonomics,
        Score, Max Score, % Score,
        Assessor Comments, Student Reflection
    """
    whereClause, params = _where(cohort, dateFrom, dateTo, filters)
    params["item_codes"] = itemCodes

    sql = f"""
    WITH base AS (
        SELECT
            f.assessmentid,
            f.student_number,
            f.student_name,
            f.assessor_name,
            DATE(f.datetimeutc AT TIME ZONE 'Australia/Melbourne') AS session_date,
            NULLIF(f.assessor_data->'scale-practice-readiness'->>'scale', '')::int  AS practice_readiness,
            NULLIF(f.assessor_data->'scale-global-rating'->>'scale',       '')::int  AS global_rating,
            NULLIF(f.assessor_data->'scale-time-mgmt'->>'scale',           '')::int  AS time_mgmt,
            NULLIF(f.assessor_data->'scale-communication'->>'scale',       '')::int  AS communication,
            NULLIF(f.assessor_data->'scale-professionalism'->>'scale',     '')::int  AS professionalism,
            NULLIF(f.assessor_data->'scale-position-ergonomics'->>'scale', '')::int  AS position_ergonomics,
            f.assessor_reflection,
            f.student_reflection,
            f.assessor_data,
            f.checklists
        FROM {formsTable} f
        WHERE {whereClause}
    ),
    item_scores AS (
        SELECT
            b.assessmentid,
            b.student_number,
            b.student_name,
            b.assessor_name,
            b.session_date,
            b.practice_readiness,
            b.global_rating,
            b.time_mgmt,
            b.communication,
            b.professionalism,
            b.position_ergonomics,
            b.assessor_reflection,
            b.student_reflection,
            item_expand.item_code,
            b.checklists->item_expand.item_code->>'name' AS item_name,
            ROUND(SUM(
                CASE mc_expand.mc_val
                    WHEN 'O1' THEN 1.00
                    WHEN 'O2' THEN 0.80
                    WHEN 'O3' THEN 0.60
                    WHEN 'O4' THEN 0.40
                    WHEN 'O5' THEN 0.00
                    ELSE NULL
                END
            )::numeric, 2) AS raw_score,
            SUM(CASE WHEN mc_expand.mc_val IN ('O1','O2','O3','O4','O5') THEN 1 ELSE 0 END) AS max_items
        FROM base b
        CROSS JOIN LATERAL jsonb_each(b.assessor_data)         AS item_expand(item_code, item_data)
        CROSS JOIN LATERAL jsonb_each_text(item_expand.item_data) AS mc_expand(mc_key, mc_val)
        WHERE item_expand.item_code = ANY(:item_codes)
          AND mc_expand.mc_key LIKE 'MC%%'
        GROUP BY
            b.assessmentid, b.student_number, b.student_name, b.assessor_name,
            b.session_date, b.practice_readiness, b.global_rating, b.time_mgmt,
            b.communication, b.professionalism, b.position_ergonomics,
            b.assessor_reflection, b.student_reflection,
            item_expand.item_code, b.checklists
    )
    SELECT
        assessmentid                                                       AS "Assessment ID",
        student_number                                                     AS "Student ID",
        student_name                                                       AS "Student Name",
        assessor_name                                                      AS "Assessor",
        session_date                                                       AS "Date",
        item_code                                                          AS "Item Code",
        COALESCE(item_name, item_code)                                     AS "Item Name",
        practice_readiness                                                 AS "Practice Readiness",
        global_rating                                                      AS "Global Rating",
        time_mgmt                                                          AS "Time Mgmt",
        communication                                                      AS "Communication",
        professionalism                                                    AS "Professionalism",
        position_ergonomics                                                AS "Position & Ergonomics",
        raw_score                                                          AS "Score",
        max_items                                                          AS "Max Score",
        ROUND(raw_score / NULLIF(max_items, 0) * 100, 1)                  AS "% Score",
        COALESCE(NULLIF(TRIM(assessor_reflection), ''), '—')              AS "Assessor Comments",
        COALESCE(NULLIF(TRIM(student_reflection),  ''), '—')              AS "Student Reflection"
    FROM item_scores
    ORDER BY student_name, session_date, item_code;
    """
    return readDf(engine, sql, params)


# ─────────────────────────────────────────────────────────────────────────────
# Per-item MC breakdown query (assessor vs student option key comparison)
# ─────────────────────────────────────────────────────────────────────────────

def getMcBreakdown(
    engine,
    itemCodes: list,
    cohort: str      = BOH1_COHORT,
    dateFrom: str    = None,
    dateTo: str      = None,
    formsTable: str  = BOH1_TABLE,
    filters: dict    = None,
) -> pd.DataFrame:
    """
    Return one row per (assessmentid, item_code, MC key) with assessor and
    student option selections and the resolved option label.
    Useful for drilling into which individual checklist items are weak.
    """
    whereClause, params = _where(cohort, dateFrom, dateTo, filters)
    params["item_codes"] = itemCodes

    sql = f"""
    SELECT
        f.assessmentid                                                     AS "Assessment ID",
        f.student_name                                                     AS "Student Name",
        f.assessor_name                                                    AS "Assessor",
        DATE(f.datetimeutc AT TIME ZONE 'Australia/Melbourne')             AS "Date",
        item_expand.item_code                                              AS "Item Code",
        f.checklists->item_expand.item_code->>'name'                      AS "Item Name",
        mc_a.mc_key                                                        AS "MC",
        f.checklists->item_expand.item_code->'fields'->>mc_a.mc_key       AS "MC Description",
        mc_a.mc_val                                                        AS "Assessor Option",
        mc_s.mc_val                                                        AS "Student Option"
    FROM {formsTable} f
    CROSS JOIN LATERAL jsonb_each(f.assessor_data)            AS item_expand(item_code, item_data)
    CROSS JOIN LATERAL jsonb_each_text(item_expand.item_data) AS mc_a(mc_key, mc_val)
    LEFT JOIN LATERAL (
        SELECT val->mc_a.mc_key AS mc_val_raw,
               val->>mc_a.mc_key AS mc_val
        FROM   jsonb_each(f.student_data) sd(k, val)
        WHERE  sd.k = item_expand.item_code
        LIMIT 1
    ) mc_s ON true
    WHERE {whereClause}
      AND item_expand.item_code = ANY(:item_codes)
      AND mc_a.mc_key LIKE 'MC%%'
    ORDER BY "Student Name", "Date", "Item Code", "MC";
    """
    return readDf(engine, sql, params)


# ─────────────────────────────────────────────────────────────────────────────
# Excel report builders
# ─────────────────────────────────────────────────────────────────────────────

_TIMED_COLS = [
    "Student Name", "Assessor", "Date", "Item Code", "Item Name",
    "Score", "Max Score", "% Score",
    "Practice Readiness", "Global Rating",
    "Time Mgmt", "Communication", "Professionalism", "Position & Ergonomics",
    "Assessor Comments", "Student Reflection",
]

_HIST_COLS = [
    "Student Name", "Date", "Item Code", "Item Name", "Session Type",
    "Score", "Max Score", "% Score",
    "Practice Readiness", "Global Rating",
    "Assessor Comments",
]


def buildTimedSessionReport(
    engine,
    outputPath: str,
    timedDate: str,           # "YYYY-MM-DD"
    timedItems: list,         # e.g. ["161", "114 H/S", "221", "222"]
    cohort: str     = BOH1_COHORT,
    formsTable: str = BOH1_TABLE,
    sessionLabel: str = None, # e.g. "Timed Session 1" — auto-derived from date if None
    dateFrom: str   = None,   # earliest date for historical comparison (default: all)
):
    """
    Build an Excel workbook for a timed clinical session.

    Sheets
    ------
    "Timed Session"      : scores for timedDate only (all students × items)
    "Historical Comparison": all sessions (timed + prior) for same students × items
    "MC Breakdown"       : per-MC option selections for the timed date

    Parameters
    ----------
    engine      : SQLAlchemy engine
    outputPath  : file path for the output .xlsx
    timedDate   : date of the timed session (YYYY-MM-DD)
    timedItems  : list of item codes assessed in the timed session
    cohort      : cohort filter
    formsTable  : source table
    sessionLabel: short label shown in sheet/title (default: "Timed Session DD Mon YYYY")
    dateFrom    : lower bound for historical comparison query
    """
    label = sessionLabel or f"Timed {pd.to_datetime(timedDate).strftime('%d %b %Y')}"

    # ── 1. Timed session data ──────────────────────────────────────────────
    timedDf = getChecklistScores(
        engine, itemCodes=timedItems, cohort=cohort,
        dateFrom=timedDate, dateTo=timedDate, formsTable=formsTable,
    )

    # ── 2. Historical data (all prior dates) for the same students+items ───
    timedStudents = timedDf["Student Name"].unique().tolist() if not timedDf.empty else []
    histFilters = {"student_name": timedStudents} if timedStudents else None
    histDf = getChecklistScores(
        engine, itemCodes=timedItems, cohort=cohort,
        dateFrom=dateFrom, dateTo=timedDate,
        formsTable=formsTable, filters=histFilters,
    )
    # Tag session type
    histDf["Session Type"] = histDf["Date"].apply(
        lambda d: "Timed" if str(d) == timedDate else "Regular"
    )

    # ── 3. MC breakdown for timed date ─────────────────────────────────────
    mcDf = getMcBreakdown(
        engine, itemCodes=timedItems, cohort=cohort,
        dateFrom=timedDate, dateTo=timedDate, formsTable=formsTable,
    )

    # ── 4. Write workbook ──────────────────────────────────────────────────
    wb = Workbook()
    wb.remove(wb.active)  # remove default sheet

    # Sheet 1: Timed Session
    _writeScoreSheet(wb, _sanitizeSheet(label), timedDf, _TIMED_COLS, label)

    # Sheet 2: Historical Comparison
    histCols = [c for c in _HIST_COLS if c in histDf.columns]
    _writeScoreSheet(wb, "Historical Comparison", histDf, histCols,
                     f"Historical — {', '.join(timedItems)}")

    # Sheet 3: MC Breakdown (timed date)
    _writeMcBreakdownSheet(wb, "MC Breakdown", mcDf)

    for ws in wb.worksheets:
        _autoFit(ws)

    wb.save(outputPath)
    print(f"✓ Timed session report saved → {outputPath}")
    return timedDf, histDf


def buildItemReport(
    engine,
    outputPath: str,
    itemCode: str,
    cohort: str     = BOH1_COHORT,
    dateFrom: str   = None,
    dateTo: str     = None,
    formsTable: str = BOH1_TABLE,
):
    """
    Build an Excel report for a single item code across all dates.
    Includes an Assessor column per the coordinator's request.

    Sheets
    ------
    "Summary"      : one row per (student, session) — scores + all scales + assessor
    "MC Breakdown" : per-MC option for every session
    "By Assessor"  : pivot of % Score by assessor (mean across students)

    Parameters
    ----------
    engine     : SQLAlchemy engine
    outputPath : file path for the output .xlsx
    itemCode   : item code string (e.g. "531")
    cohort     : cohort filter
    dateFrom   : lower date bound (YYYY-MM-DD), or None
    dateTo     : upper date bound (YYYY-MM-DD), or None
    formsTable : source table
    """
    scoreDf = getChecklistScores(
        engine, itemCodes=[itemCode], cohort=cohort,
        dateFrom=dateFrom, dateTo=dateTo, formsTable=formsTable,
    )
    mcDf = getMcBreakdown(
        engine, itemCodes=[itemCode], cohort=cohort,
        dateFrom=dateFrom, dateTo=dateTo, formsTable=formsTable,
    )

    wb = Workbook()
    wb.remove(wb.active)

    # Sheet 1: Summary
    summaryCols = [
        "Student Name", "Student ID", "Assessor", "Date",
        "Item Code", "Item Name",
        "Score", "Max Score", "% Score",
        "Practice Readiness", "Global Rating",
        "Time Mgmt", "Communication", "Professionalism", "Position & Ergonomics",
        "Assessor Comments", "Student Reflection",
    ]
    _writeScoreSheet(wb, f"Item {itemCode} — Summary", scoreDf, summaryCols,
                     f"Item {itemCode} — All Sessions")

    # Sheet 2: MC Breakdown
    _writeMcBreakdownSheet(wb, "MC Breakdown", mcDf)

    # Sheet 3: By Assessor pivot
    if not scoreDf.empty and "Assessor" in scoreDf.columns:
        assessorPivot = (
            scoreDf.groupby("Assessor")
            .agg(
                Sessions=("Assessment ID", "count"),
                Avg_Pct_Score=("% Score", "mean"),
                Avg_Global_Rating=("Global Rating", "mean"),
                Avg_Practice_Readiness=("Practice Readiness", "mean"),
            )
            .round(2)
            .reset_index()
            .rename(columns={
                "Avg_Pct_Score": "Avg % Score",
                "Avg_Global_Rating": "Avg Global Rating",
                "Avg_Practice_Readiness": "Avg Practice Readiness",
            })
            .sort_values("Avg % Score", ascending=False)
        )
        _writeScoreSheet(wb, "By Assessor", assessorPivot,
                         list(assessorPivot.columns), f"Item {itemCode} — By Assessor")

    for ws in wb.worksheets:
        _autoFit(ws)

    wb.save(outputPath)
    print(f"✓ Item {itemCode} report saved → {outputPath}")
    return scoreDf


# ─────────────────────────────────────────────────────────────────────────────
# Internal sheet writers
# ─────────────────────────────────────────────────────────────────────────────

def _writeScoreSheet(wb, sheetName: str, df: pd.DataFrame, cols: list, title: str):
    ws = wb.create_sheet(_sanitizeSheet(sheetName))
    ws.row_dimensions[1].height = 20

    # Title row
    ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(cols), 1))

    if df.empty:
        ws.cell(row=3, column=1, value="No data found for the selected filters.")
        return

    # Only keep columns that exist in df
    validCols = [c for c in cols if c in df.columns]
    sub = df[validCols].copy()

    # Header
    row = _headerRow(ws, 3, validCols)

    # Data rows
    for i, (_, r) in enumerate(sub.iterrows()):
        vals = []
        for c in validCols:
            v = r[c]
            if isinstance(v, float) and np.isnan(v):
                v = None
            elif hasattr(v, 'item'):   # numpy scalar
                v = v.item()
            vals.append(v)
        row = _dataRow(ws, row, vals, shade=(i % 2 == 1))

    # Freeze header rows
    ws.freeze_panes = f"A4"


def _writeMcBreakdownSheet(wb, sheetName: str, df: pd.DataFrame):
    ws = wb.create_sheet(_sanitizeSheet(sheetName))
    ws.cell(row=1, column=1, value="Per-MC Checklist Breakdown — Assessor vs Student").font = Font(bold=True, size=13)

    if df.empty:
        ws.cell(row=3, column=1, value="No MC data found.")
        return

    cols = [c for c in df.columns]
    row = _headerRow(ws, 3, cols)

    for i, (_, r) in enumerate(df.iterrows()):
        vals = [r[c] if not (isinstance(r[c], float) and np.isnan(r[c])) else None for c in cols]
        # Highlight discrepancies between assessor and student options
        shade = (r.get("Assessor Option") != r.get("Student Option")) if "Assessor Option" in r else (i % 2 == 1)
        row = _dataRow(ws, row, vals, shade=shade)

    ws.freeze_panes = "A4"


# ─────────────────────────────────────────────────────────────────────────────
# Notebook convenience — process sample TSV data without DB (for preview)
# ─────────────────────────────────────────────────────────────────────────────

def scoreFromSampleData(rawDf: pd.DataFrame, itemCodes: list) -> pd.DataFrame:
    """
    Compute checklist scores from a DataFrame already loaded from the raw
    exported TSV (assessor_data and checklists columns as JSON strings).

    Use this when you have exported sample data but no live DB connection.

    Parameters
    ----------
    rawDf     : DataFrame with at least columns: assessmentid, student_name,
                assessor_name, datetimeutc, assessor_data (JSON str or dict),
                student_data (JSON str or dict), checklists (JSON str or dict),
                assessor_reflection, student_reflection,
                plus the scale columns embedded in assessor_data.
    itemCodes : list of item code strings to score

    Returns
    -------
    pd.DataFrame — same schema as getChecklistScores()
    """
    import json as _json

    def _parseJson(v):
        if isinstance(v, dict):
            return v
        try:
            return _json.loads(v) if v else {}
        except Exception:
            return {}

    rows = []
    for _, r in rawDf.iterrows():
        ad = _parseJson(r.get("assessor_data", "{}"))
        sd = _parseJson(r.get("student_data",  "{}"))
        cl = _parseJson(r.get("checklists",    "{}"))

        pr  = ad.get("scale-practice-readiness", {}).get("scale")
        gr  = ad.get("scale-global-rating", {}).get("scale")
        tm  = ad.get("scale-time-mgmt", {}).get("scale")
        com = ad.get("scale-communication", {}).get("scale")
        pro = ad.get("scale-professionalism", {}).get("scale")
        pos = ad.get("scale-position-ergonomics", {}).get("scale")

        def _toInt(v):
            try:
                return int(v) if v is not None else None
            except (ValueError, TypeError):
                return None

        for ic in itemCodes:
            if ic not in ad:
                continue
            mc_data = {k: v for k, v in ad[ic].items() if k.startswith("MC")}
            raw_score = sum(SCORE_MAP.get(v, 0) for v in mc_data.values() if v in SCORE_MAP)
            max_items = sum(1 for v in mc_data.values() if v in SCORE_MAP)  # excludes O6
            pct_score = round(raw_score / max_items * 100, 1) if max_items else None

            item_name = cl.get(ic, {}).get("name", ic)

            rows.append({
                "Assessment ID":        r.get("assessmentid"),
                "Student ID":           r.get("student_number"),
                "Student Name":         r.get("student_name"),
                "Assessor":             r.get("assessor_name"),
                "Date":                 pd.to_datetime(r.get("datetimeutc")).date() if r.get("datetimeutc") else None,
                "Item Code":            ic,
                "Item Name":            item_name,
                "Practice Readiness":   _toInt(pr),
                "Global Rating":        _toInt(gr),
                "Time Mgmt":            _toInt(tm),
                "Communication":        _toInt(com),
                "Professionalism":      _toInt(pro),
                "Position & Ergonomics":_toInt(pos),
                "Score":                round(raw_score, 2),
                "Max Score":            max_items,
                "% Score":              pct_score,
                "Assessor Comments":    r.get("assessor_reflection") or "—",
                "Student Reflection":   r.get("student_reflection")  or "—",
            })

    return pd.DataFrame(rows).sort_values(["Student Name", "Date", "Item Code"])


def buildReportFromDf(
    outputPath: str,
    scoreDf: pd.DataFrame,
    reportTitle: str = "BOH1 Session Report",
    timedDate: str   = None,
):
    """
    Write an Excel report from an already-computed score DataFrame
    (e.g., from scoreFromSampleData or getChecklistScores).

    If timedDate is provided, a 'Timed Session' sheet is written for that date
    and a 'Historical Comparison' sheet for all other dates (same students).
    Otherwise a single 'Summary' sheet is written.
    """
    wb = Workbook()
    wb.remove(wb.active)

    if timedDate and "Date" in scoreDf.columns:
        timedMask = scoreDf["Date"].astype(str) == str(timedDate)
        timedDf   = scoreDf[timedMask].copy()
        histDf    = scoreDf.copy()
        histDf["Session Type"] = histDf["Date"].apply(
            lambda d: "Timed" if str(d) == str(timedDate) else "Regular"
        )
        label = f"Timed {pd.to_datetime(timedDate).strftime('%d %b %Y')}"
        _writeScoreSheet(wb, _sanitizeSheet(label), timedDf, _TIMED_COLS, reportTitle)

        histCols = [c for c in _HIST_COLS if c in histDf.columns]
        _writeScoreSheet(wb, "Historical Comparison", histDf, histCols,
                         f"Historical Comparison — {reportTitle}")
    else:
        _writeScoreSheet(wb, "Summary", scoreDf, _TIMED_COLS, reportTitle)

    for ws in wb.worksheets:
        _autoFit(ws)

    wb.save(outputPath)
    print(f"✓ Report saved → {outputPath}")