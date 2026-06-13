"""
boh2_dds2_dds3_utils.py
Reusable query, processing, and report-building functions for the BOH2/DDS2/DDS3 cohorts.

Refactored from notebook inline code to follow the same flexible-filter pattern
as boh3_dds4_utils.py.

Usage in notebook:
    from boh2_dds2_dds3_utils import *
"""

import os
import re
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from collections import defaultdict, OrderedDict
from xml.sax.saxutils import escape
from sqlalchemy import text

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    KeepTogether, SimpleDocTemplate, PageBreak, Paragraph, Spacer,
)
from reportlab.lib.units import inch
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D

from Utils import createTable, addPlotImage, getBannerDrawer, getmodeArgs, readDf, runDdl, toInt, autoFitColumns
import variableUtils
from IPython.display import display

# Default score map used across BOH2/DDS2/DDS3
SCORE_MAP = {
    "O1": 1.00,
    "O2": 0.80,
    "O3": 0.60,
    "O4": 0.40,
    "O5": 0.00,
    "Yes": 1.00,
    "No": 0.00,
}

BOH2_REMOVED_STUDENTS = [1352051, 1606158, 1605793, 1617958, 1605538]
DDS2_REMOVED_STUDENTS = [1270152, 1155940, 914405]



# ═══════════════════════════════════════════════════════════════════════════
# 1. Flexible WHERE clause builder (matches boh3_dds4_utils pattern)
# ═══════════════════════════════════════════════════════════════════════════

def getWhereStatement(cohort, filters: dict = None, dateFrom="2026-01-01"):
    """
    Build a WHERE clause string + params dict from cohort and optional filters.

    Parameters
    ----------
    cohort : str
        Cohort name (e.g. "BOH2", "DDS2", "DDS3").
    filters : dict, optional
        Arbitrary column filters.  Supported value types:
        - str / int / float  →  ``column = :column``
        - list               →  ``column = ANY(:column)``
        Keys ending with ``_min`` or ``_max`` are skipped here (handled by
        callers that need range filtering, e.g. age ranges).
    dateFrom : str or None, optional
        Minimum datetimeutc value (inclusive).  Set to ``None`` to disable.
        Defaults to ``"2026-01-01"`` for backward compatibility.

    Returns
    -------
    (whereClause: str, params: dict)
    """
    whereClauses = ["cohort = :cohort"]
    params = {"cohort": cohort}

    if dateFrom is not None:
        whereClauses.append("datetimeutc >= :dateFrom")
        params["dateFrom"] = dateFrom

    if filters:
        for key, value in filters.items():
            if key.endswith("_min") or key.endswith("_max"):
                continue  # handled by specific callers
            if isinstance(value, list):
                whereClauses.append(f"{key} = ANY(:{key})")
            else:
                whereClauses.append(f"{key} = :{key}")
        params.update(filters)

    return " AND ".join(whereClauses), params


def _where(cohort, filters, dateFrom="2026-01-01"):
    """Shorthand: returns (whereClause, params)."""
    return getWhereStatement(cohort, filters, dateFrom=dateFrom)

def _loadSectionMapping(mappingFile=None):
    """
    Load the item-code → section mapping and return a DataFrame
    with columns ["Item Code", "Section", "Sub-section"].
    """
    if mappingFile is None:
        mappingFile = variableUtils.itemSectionMappingFile
    mappingDf = pd.read_excel(mappingFile)
    mappingDf["Item Code"] = mappingDf["Item Code"].astype(str).str.strip()
    return mappingDf


def _mergeSection(df, mappingDf = _loadSectionMapping(), codeCol="Item Code"):
    """
    Merge a DataFrame that has an item-code column with the section mapping.

    Handles compound codes like "022/024" by splitting on "/" and matching
    the first component.  Unmatched codes get Section/Sub-section = "Unmapped".

    Always adds both "Section" and "Sub-section" columns.
    """
    merged = df.copy()
    if len(merged) == 0:
        # If the input DataFrame is empty, just add the Section/Sub-section columns and return
        merged["Section"] = pd.NA
        merged["Sub-section"] = pd.NA
        return merged
    # SPLIT by - also only if first part is a number otherwise keep as it is (for codes like "BOH-DD" that should be matched as a whole)
    merged["_MappingCode"] = merged[codeCol].astype(str).str.split("/").str[0].str.strip()
    merged["_MappingCode"] = merged["_MappingCode"].apply(lambda code: code.split("-")[0] if code.split("-")[0].isdigit() else code)
    mergeCols = ["Item Code", "Section"]
    if "Sub-section" in mappingDf.columns:
        mergeCols.append("Sub-section")

    merged = merged.merge(
        mappingDf[mergeCols],
        left_on="_MappingCode", right_on="Item Code",
        how="left", suffixes=("", "_map"),
    )
    # Clean up helper columns
    if "Item Code_map" in merged.columns:
        merged.drop(columns=["Item Code_map"], inplace=True)
    merged.drop(columns=["_MappingCode"], inplace=True)
    merged["Section"] = merged["Section"].fillna("Unmapped")
    if "Sub-section" in merged.columns:
        merged["Sub-section"] = merged["Sub-section"].fillna("Unmapped")
    return merged

def _naturalKey(s: str) -> tuple:
    """Split into (str, int) parts for correct natural sort: '011-RPP' → ('', 11, '-rpp')."""
    return tuple(int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(s)))

def _mcNum(s: str) -> int:
    """Extract trailing number from MC key: 'MC10' → 10."""
    m = re.search(r'\d+$', str(s))
    return int(m.group()) if m else 0

def saveToExcel(filepath, sheets: dict, index=False, **writerKwargs):
    """
    Save multiple DataFrames to Excel with auto-fitted columns.

    Parameters
    ----------
    filepath : str or Path
    sheets : dict
        {sheetName: df} — written in insertion order.
    index : bool
    **writerKwargs : passed to pd.ExcelWriter (e.g. mode, if_sheet_exists)

    Usage
    -----
    >>> saveToExcel("report.xlsx", {
    ...     "Scales": scalesDf,
    ...     "Pivots": pivotDf,
    ...     "Incidents": incidentsDf,
    ... })
    """
    with pd.ExcelWriter(filepath, engine="openpyxl", **writerKwargs) as writer:
        for sheetName, df in sheets.items():
            df.to_excel(writer, sheet_name=sheetName, index=index)
        for ws in writer.sheets.values():
            autoFitColumns(ws)


def getChecklistMcTexts(
    engine,
    itemCodes: list,
    formsTable: str = "rawform_forms",
) -> pd.DataFrame:
    """
    Return the MC text descriptions for the given item codes.

    Pulls DISTINCT (item_code, item_name, MC, MC Text) from the checklists
    JSONB column — one row per MC per item code.

    Parameters
    ----------
    engine      : SQLAlchemy engine
    itemCodes   : list of item code strings, e.g. ["578", "579"]
    formsTable  : defaults to "rawform_forms"

    Returns
    -------
    DataFrame with columns: item_code, item_name, MC, MC Text
    """
    sql = f"""
    SELECT DISTINCT ON (item.item_code, mc.mc_key)
        item.item_code,
        item.item_data ->> 'name'                              AS item_name,
        mc.mc_key                                              AS "MC",
        mc.mc_text                                             AS "MC Text"
    FROM {formsTable} f
    CROSS JOIN LATERAL jsonb_each(f.checklists)
        AS item(item_code, item_data)
    CROSS JOIN LATERAL jsonb_each_text(
        COALESCE(item.item_data -> 'fields', '{{}}'::jsonb)
    ) AS mc(mc_key, mc_text)
    WHERE item.item_code = ANY(:itemCodes)
    AND f.datetimeutc >= '2026-01-01'
      AND mc.mc_key LIKE 'MC%'
      AND mc.mc_key ~ '^MC[0-9]+'
    ORDER BY item.item_code, mc.mc_key;
    """
    df = readDf(engine, sql, {"itemCodes": itemCodes})

    df["_item_sort"] = df["item_code"].apply(_naturalKey)
    df["_mc_sort"]   = df["MC"].apply(_mcNum)
    df = (df.sort_values(["_item_sort", "_mc_sort"])
            .drop(columns=["_item_sort", "_mc_sort"])
            .reset_index(drop=True))
    return df


def getChecklistItems(
    engine,
    cohort: str,
    formsTable: str = "rawform_forms",
    filters: dict = None,
) -> pd.DataFrame:
    """
    Return distinct checklist item codes and names for a cohort.

    Parameters
    ----------
    engine     : SQLAlchemy engine
    cohort     : e.g. "DDS2", "DDS3", "BOH1"
    formsTable : defaults to "rawform_forms"
    filters    : e.g. {"type": "Clinic"} or {"type": ["Clinic", "Simulation"]}

    Returns
    -------
    DataFrame with columns: item_code, item_name, mc_count
    """
    whereClause, params = _where(cohort, filters)

    sql = f"""
    SELECT DISTINCT ON (item.item_code)
        item.item_code,
        item.item_data ->> 'name'                          AS item_name,
        (SELECT COUNT(*)
         FROM jsonb_object_keys(
             COALESCE(item.item_data -> 'fields', '{{}}'::jsonb)
         ) k
         WHERE k ~ '^MC[0-9]+'
        )::int                                             AS mc_count
    FROM {formsTable} f
    CROSS JOIN LATERAL jsonb_each(f.checklists)
        AS item(item_code, item_data)
    WHERE {whereClause}
      AND NULLIF(item.item_data ->> 'name', '') IS NOT NULL
    ORDER BY item.item_code, LENGTH(item.item_data ->> 'name') DESC;
    """
    return readDf(engine, sql, params)
# ═══════════════════════════════════════════════════════════════════════════
# 2. Cohort-level query functions
# ═══════════════════════════════════════════════════════════════════════════

def getFullDf(engine, cohort, formsTable="rawform_forms", filters=None):
    whereClause, params = _where(cohort, filters)
    sql = f"SELECT * FROM {formsTable} WHERE {whereClause};"
    return readDf(engine, sql, params)


def getStudentScaleSummary(engine, cohort, formsTable="rawform_forms", filters=None):
    """
    Scale summary per student (entrustment, professionalism, communication,
    time management) with level counts and averages.

    Common filters: {"type": "Clinic"}, {"subject": "DENT90082"}, {"clinic": "RDH"}
    """
    whereClause, params = _where(cohort, filters)

    sql = f"""
    WITH base AS (
        SELECT
            student_number AS "Student ID",
            student_name AS "Student Name",
            type,

            COALESCE(
                NULLIF(assessor_data->'scale-practice-readiness'->>'scale', '')::int,
                NULLIF(assessor_data->'entrustment'->>'scale', '')::int,
                NULLIF(assessor_data->'practice-readiness'->>'scale', '')::int
            ) AS entrustment,

            COALESCE(
                NULLIF(assessor_data->'scale-professionalism'->>'scale', '')::int,
                NULLIF(assessor_data->'professionalism'->>'scale', '')::int
            ) AS professionalism,

            COALESCE(
                NULLIF(assessor_data->'scale-communication'->>'scale', '')::int,
                NULLIF(assessor_data->'communication'->>'scale', '')::int
            ) AS communication,

            COALESCE(
                NULLIF(assessor_data->'scale-time-mgmt'->>'scale', '')::int,
                NULLIF(assessor_data->'time_mgmt'->>'scale', '')::int
            ) AS timeManagement

        FROM {formsTable}
        WHERE {whereClause}
    )
    SELECT
        "Student ID",
        "Student Name",
        type AS "Type",

        COUNT(*) FILTER (WHERE entrustment = 1) AS "Entrustment Lvl 1",
        COUNT(*) FILTER (WHERE entrustment = 2) AS "Entrustment Lvl 2",
        COUNT(*) FILTER (WHERE entrustment = 3) AS "Entrustment Lvl 3",
        COUNT(*) FILTER (WHERE entrustment = 4) AS "Entrustment Lvl 4",
        ROUND(AVG(entrustment)::numeric, 2) AS "Entrustment Average",

        COUNT(*) FILTER (WHERE professionalism = 1) AS "Professionalism Lvl 1",
        COUNT(*) FILTER (WHERE professionalism = 2) AS "Professionalism Lvl 2",
        ROUND(AVG(professionalism)::numeric, 2) AS "Professionalism Average",

        COUNT(*) FILTER (WHERE communication = 1) AS "Communication Lvl 1",
        COUNT(*) FILTER (WHERE communication = 2) AS "Communication Lvl 2",
        ROUND(AVG(communication)::numeric, 2) AS "Communication Average",

        COUNT(*) FILTER (WHERE timeManagement = 1) AS "Time Management Lvl 1",
        COUNT(*) FILTER (WHERE timeManagement = 2) AS "Time Management Lvl 2",
        COUNT(*) FILTER (WHERE timeManagement = 3) AS "Time Management Lvl 3",
        COUNT(*) FILTER (WHERE timeManagement = 4) AS "Time Management Lvl 4",
        ROUND(AVG(timeManagement)::numeric, 2) AS "Time Management Average"

    FROM base
    GROUP BY "Student ID", "Student Name", type
    ORDER BY "Student Name", type;
    """
    return readDf(engine, sql, params)


def convertToMultiLevel(df):
    """Convert flat scale summary columns into a two-level MultiIndex."""
    columnMap = {
        "Student ID": ("", "Student ID"),
        "Student Name": ("", "Student Name"),
        "Type": ("", "Type"),

        "Entrustment Lvl 1": ("Entrustment", "Lvl 1"),
        "Entrustment Lvl 2": ("Entrustment", "Lvl 2"),
        "Entrustment Lvl 3": ("Entrustment", "Lvl 3"),
        "Entrustment Lvl 4": ("Entrustment", "Lvl 4"),
        "Entrustment Average": ("Entrustment", "Average"),

        "Professionalism Lvl 1": ("Professionalism", "Lvl 1"),
        "Professionalism Lvl 2": ("Professionalism", "Lvl 2"),
        "Professionalism Average": ("Professionalism", "Average"),

        "Communication Lvl 1": ("Communication", "Lvl 1"),
        "Communication Lvl 2": ("Communication", "Lvl 2"),
        "Communication Average": ("Communication", "Average"),

        "Time Management Lvl 1": ("Time Management", "Lvl 1"),
        "Time Management Lvl 2": ("Time Management", "Lvl 2"),
        "Time Management Lvl 3": ("Time Management", "Lvl 3"),
        "Time Management Lvl 4": ("Time Management", "Lvl 4"),
        "Time Management Average": ("Time Management", "Average"),
    }
    df.columns = pd.MultiIndex.from_tuples([columnMap[c] for c in df.columns])
    df.sort_values(by=[("Entrustment", "Average")], inplace=True, ascending=False)
    return df


def getCriticalIncidentDf(engine, cohort, formsTable="rawform_forms", filters=None):
    whereClause, params = _where(cohort, filters)

    sql = f"""
    SELECT
        student_number AS "Student ID",
        student_name AS "Student Name",
        datetimeutc::date AS "Date",
        clinical_incident AS "Critical Incident"
    FROM {formsTable}
    WHERE {whereClause}
      AND NULLIF(TRIM(clinical_incident), '') IS NOT NULL
    ORDER BY student_name, datetimeutc;
    """
    return readDf(engine, sql, params)


def getStudentFormCountDf(engine, cohort, formsTable="rawform_forms", filters=None):
    whereClause, params = _where(cohort, filters)

    sql = f"""
    SELECT
        student_number AS "Student ID",
        student_name AS "Student Name",
        COUNT(*)::int AS "# Forms"
    FROM {formsTable}
    WHERE {whereClause}
    GROUP BY student_number, student_name
    ORDER BY "# Forms" DESC, "Student Name";
    """
    return readDf(engine, sql, params)


def getStudentItemCodeDf(engine, cohort, formsTable="rawform_forms", filters=None):
    """
    Flat DataFrame of item codes per student with all scale values attached.

    Returns columns: Student ID, Student Name, Item Code, Description,
                     Global Rating, Entrustment, Professionalism,
                     Communication, Time Management
    """
    whereClause, params = _where(cohort, filters)

    sql = f"""
    SELECT
        f.student_number AS "Student ID",
        f.student_name   AS "Student Name",
        cl.key           AS "Item Code",
        cl.value->>'name' AS "Description",
        NULLIF(f.assessor_data->'scale-global-rating'->>'scale','')::int      AS "Global Rating",
        COALESCE(
            NULLIF(f.assessor_data->'scale-practice-readiness'->>'scale','')::int,
            NULLIF(f.assessor_data->'entrustment'->>'scale','')::int,
            NULLIF(f.assessor_data->'practice-readiness'->>'scale','')::int
        ) AS "Entrustment",
        COALESCE(
            NULLIF(f.assessor_data->'scale-professionalism'->>'scale','')::int,
            NULLIF(f.assessor_data->'professionalism'->>'scale','')::int
        ) AS "Professionalism",
        COALESCE(
            NULLIF(f.assessor_data->'scale-communication'->>'scale','')::int,
            NULLIF(f.assessor_data->'communication'->>'scale','')::int
        ) AS "Communication",
        COALESCE(
            NULLIF(f.assessor_data->'scale-time-mgmt'->>'scale','')::int,
            NULLIF(f.assessor_data->'time_mgmt'->>'scale','')::int
        ) AS "Time Management"
    FROM {formsTable} f
    CROSS JOIN LATERAL jsonb_each(COALESCE(f.checklists, '{{}}'::jsonb)) cl
    WHERE {whereClause}
    """
    return readDf(engine, sql, params)


def getCohortItemCodeAverages(engine, cohort, formType="Simulation",
                              formsTable="rawform_forms", filters=None):
    """
    Mean count of each item code performed per student in the given cohort/type.
 
    For each (student, item_code) the number of forms is counted, then averaged
    across all students that have at least one form in scope.  Useful as a
    class-average comparison baseline for individual student reports.
 
    Returns dict {item_code: avg_count}.
    """
    effectiveFilters = {"type": formType}
    if filters:
        effectiveFilters.update(filters)
 
    df = getStudentItemCodeDf(
        engine, cohort, formsTable=formsTable, filters=effectiveFilters,
    )
    if df.empty:
        return {}
 
    perStudent = (
        df.groupby(["Student ID", "Item Code"]).size().unstack(fill_value=0)
    )
    return perStudent.mean(axis=0).to_dict()


def getFlaggedFormDetails(engine, cohort, formsTable="rawform_forms", filters=None,
                          globalRatingThresholds=(1,), entrustmentThresholds=(1,),
                          includeEmptyComments=False):
    """
    Return forms flagged by low global-rating or low entrustment scores.

    The threshold values are inlined because they are small integer sets and
    never come from user input.
    """
    whereClause, params = _where(cohort, filters)

    globalRatingList = ",".join(str(int(x)) for x in globalRatingThresholds) if globalRatingThresholds else ""
    entrustmentList = ",".join(str(int(x)) for x in entrustmentThresholds) if entrustmentThresholds else ""

    triggerConditions = []
    triggerLabels = []

    if globalRatingList:
        triggerConditions.append(
            f"NULLIF(assessor_data->'scale-global-rating'->>'scale', '')::int IN ({globalRatingList})"
        )
        triggerLabels.append(
            f"""CASE
                    WHEN NULLIF(assessor_data->'scale-global-rating'->>'scale', '')::int IN ({globalRatingList})
                    THEN 'Global Rating'
                END"""
        )

    if entrustmentList:
        triggerConditions.append(
            f"NULLIF(assessor_data->'scale-practice-readiness'->>'scale', '')::int IN ({entrustmentList})"
        )
        triggerLabels.append(
            f"""CASE
                    WHEN NULLIF(assessor_data->'scale-practice-readiness'->>'scale', '')::int IN ({entrustmentList})
                    THEN 'Entrustment'
                END"""
        )

    if not triggerConditions:
        raise ValueError("At least one threshold list must be provided.")

    commentFilter = ""
    if not includeEmptyComments:
        commentFilter = """
        AND (
            NULLIF(TRIM(COALESCE(student_reflection, '')), '') IS NOT NULL
            OR NULLIF(TRIM(COALESCE(assessor_reflection, '')), '') IS NOT NULL
            OR NULLIF(TRIM(COALESCE(clinical_incident, '')), '') IS NOT NULL
        )
        """

    triggerExpr = " || '; ' || ".join(
        [f"COALESCE({label}, '')" for label in triggerLabels]
    )

    sql = f"""
    SELECT
        form_code AS "Form Code",
        assessmentid AS "Assessment ID",
        student_number AS "Student ID",
        student_name AS "Student Name",
        student_email AS "Student Email",
        datetimeutc::date AS "Date",
        type AS "Type",
        clinic AS "Clinic",
        assessor_name AS "Assessor Name",

        NULLIF(assessor_data->'scale-global-rating'->>'scale', '')::int AS "Global Rating",
        NULLIF(assessor_data->'scale-practice-readiness'->>'scale', '')::int AS "Entrustment",

        student_reflection AS "Student Reflection",
        assessor_reflection AS "Assessor Reflection",
        clinical_incident AS "Critical Incident",

        student_data AS "Student Checklist Responses",
        assessor_data AS "Assessor Checklist Responses",

        TRIM(BOTH '; ' FROM {triggerExpr}) AS "Triggered By"

    FROM {formsTable}
    WHERE {whereClause}
      AND (
          {" OR ".join(triggerConditions)}
      )
      {commentFilter}
    ORDER BY student_name, datetimeutc;
    """

    return readDf(engine, sql, params)


def getClinicList(engine, cohort, formsTable="rawform_forms", filters=None):
    whereClause, params = _where(cohort, filters)

    sql = f"""
    SELECT DISTINCT clinic
    FROM {formsTable}
    WHERE {whereClause}
      AND clinic IS NOT NULL
    ORDER BY clinic;
    """
    df = readDf(engine, sql, params)
    return df["clinic"].dropna().tolist()


def getSubmissionInfo(engine, cohort, formsTable="rawform_forms", filters=None):
    whereClause, params = _where(cohort, filters)

    sql = f"""
    SELECT
        student_number AS "Student ID",
        student_name AS "Student Name",
        assessor_name AS "Assessor Name",
        datetimeutc::date AS "Date",
        type AS "Type",
        clinic AS "Clinic",
        submitted_by_student AS "Submitted by Student",
        submitted_by_assessor AS "Submitted by Assessor"
    FROM {formsTable}
    WHERE {whereClause}
      AND (submitted_by_student = false OR submitted_by_assessor = false)
    ORDER BY student_name, datetimeutc;
    """
    return readDf(engine, sql, params)


def getStudentsInCohort(engine, cohort, formsTable="rawform_forms", dateFrom="2026-01-01"):
    """Return distinct student_number / student_name / student_email for a cohort."""
    whereClause, params = _where(cohort, filters=None, dateFrom=dateFrom)
    sql = f"""
    SELECT DISTINCT student_number, student_name, student_email
    FROM {formsTable}
    WHERE {whereClause}
      AND student_name IS NOT NULL AND student_name <> '' AND student_name <> 'Test Student'
    ORDER BY student_name;
    """
    return readDf(engine, sql, params)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Cohort report orchestrators
# ═══════════════════════════════════════════════════════════════════════════


def pivotItemCodes(df, groupBy="item_code", valueCol=None, aggfunc=None,
                   mappingFile=None):
    """
    Pivot a flat item-code DataFrame into a student × item/section matrix.

    Parameters
    ----------
    df : DataFrame
        From getStudentItemCodeDf.
    groupBy : str
        ``"item_code"`` | ``"section"`` | ``"sub_section"``
    valueCol : str or None
        Column to aggregate. ``None`` → counts.
        e.g. ``"Global Rating"``, ``"Entrustment"``, ``"Professionalism"``
    aggfunc : str or callable or None
        Pandas aggfunc. Defaults to ``"sum"`` for counts, ``"mean"`` for
        value columns.
    mappingFile : str or Path, optional

    Examples
    --------
    >>> df = getStudentItemCodeDf(engine, "DDS2", filters={"type": "Clinic"})
    >>> pivotItemCodes(df)                                          # counts by item code
    >>> pivotItemCodes(df, groupBy="section")                       # counts by section
    >>> pivotItemCodes(df, valueCol="Global Rating")                # mean GR by item code
    >>> pivotItemCodes(df, valueCol="Entrustment", groupBy="section")  # mean ES by section
    >>> pivotItemCodes(df, valueCol="Global Rating", aggfunc="median") # median GR
    """
    isCount = valueCol is None
    if isCount:
        df = df.assign(_count=1)
        valueCol = "_count"
        if aggfunc is None:
            aggfunc = "sum"
        fillValue = np.nan
    else:
        if aggfunc is None:
            aggfunc = "mean"
        fillValue = np.nan

    index = ["Student ID", "Student Name"]

    if groupBy in ("section", "sub_section"):
        mappingDf = _loadSectionMapping(mappingFile)
        df = _mergeSection(df, mappingDf, codeCol="Item Code")
        pivotCol = "Section" if groupBy == "section" else "Sub-section"
    else:
        pivotCol = "Item Code"

    pivotDf = (
        df.pivot_table(
            index=index,
            columns=pivotCol,
            values=valueCol,
            aggfunc=aggfunc,
            fill_value=fillValue,
        )
        .reset_index()
    )
    pivotDf.columns.name = None

    if isCount or groupBy in ("section", "sub_section"):
        pivotDf["Total"] = pivotDf.iloc[:, len(index):].sum(axis=1)

    if aggfunc == "mean":
        numCols = pivotDf.columns[len(index):]
        pivotDf[numCols] = pivotDf[numCols].round(2)

    pivotDf.sort_values("Student Name", inplace=True)
    return pivotDf, df


def getStudentItemCodePivot(engine, cohort, formsTable="rawform_forms", filters=None,
                            groupBy="item_code", mappingFile=None, valueCol=None, aggfunc=None):
    """Fetch item codes from checklists and pivot by item_code / section / sub_section."""
    df = getStudentItemCodeDf(engine, cohort, formsTable, filters)
    return pivotItemCodes(df, groupBy=groupBy, mappingFile=mappingFile, valueCol=valueCol, aggfunc=aggfunc)


def getCohortReports(engine, cohort, today, formsTable="rawform_forms",
                     subject=None, type_=("Simulation", "Clinic")):
    """
    Generate cohort-level Excel reports (scales, item-code pivots, submission info).

    Parameters
    ----------
    engine : SQLAlchemy engine
    cohort : str
    today : str   – formatted date string for filenames
    subject : str, optional – if set, filters to this subject
    type_ : tuple/list – which form types to include
    """
    suffix = f" {subject}" if subject else ""
    filepathScales = f"{cohort}/Scale Information {cohort}{suffix} ({today}).xlsx"
    filepathPivot = f"{cohort}/Item Code Pivot {cohort}{suffix} ({today}).xlsx"
    filepathSubmission = f"{cohort}/Submission Info {cohort}{suffix} ({today}).xlsx"

    # Build filters for each type
    def _filters(formType):
        f = {}
        if formType:
            f["type"] = formType
        if subject:
            f["subject"] = subject
        return f or None

    # Simulation and Clinic filters are built separately
    simFilters = _filters("Simulation")
    clinicFilters = _filters("Clinic")

    simScaleSummary = getStudentScaleSummary(engine, cohort, formsTable, filters=simFilters)
    simScaleSummary = convertToMultiLevel(simScaleSummary)
    clinicScaleSummary = getStudentScaleSummary(engine, cohort, formsTable, filters=clinicFilters)
    clinicScaleSummary = convertToMultiLevel(clinicScaleSummary)

    simCIDf = getCriticalIncidentDf(engine, cohort, formsTable, filters=simFilters)
    clinicCIDf = getCriticalIncidentDf(engine, cohort, formsTable, filters=clinicFilters)
    simFormCountDf = getStudentFormCountDf(engine, cohort, formsTable, filters=simFilters)
    clinicFormCountDf = getStudentFormCountDf(engine, cohort, formsTable, filters=clinicFilters)

    simPivot, _ = getStudentItemCodePivot(engine, cohort, formsTable, filters=_filters("Simulation"), groupBy="item_code")
    clinicPivot, mergedDf = getStudentItemCodePivot(engine, cohort, formsTable, filters=_filters("Clinic"), groupBy="section",
                                                     mappingFile=variableUtils.itemSectionMappingFile)
    simGlobalRatingPivot, _ = getStudentItemCodePivot(engine, cohort, formsTable, filters=_filters("Simulation"), 
                                                      valueCol="Global Rating", groupBy="item_code")
    simEntrustmentPivot, _ = getStudentItemCodePivot(engine, cohort, formsTable, filters=_filters("Simulation"),
                                                valueCol="Entrustment", groupBy="item_code")
    clinicGlobalRatingPivot, _ = getStudentItemCodePivot(engine, cohort, formsTable, filters=_filters("Clinic"), 
                                            valueCol="Global Rating", groupBy="section", mappingFile=variableUtils.itemSectionMappingFile)
    clinicEntrustmentPivot, _ = getStudentItemCodePivot(engine, cohort, formsTable, filters=_filters("Clinic"),
                                            valueCol="Entrustment", groupBy="section", mappingFile=variableUtils.itemSectionMappingFile)
    simSubmissionInfoDf = getSubmissionInfo(engine, cohort, formsTable, filters=simFilters)
    clinicSubmissionInfoDf = getSubmissionInfo(engine, cohort, formsTable, filters=clinicFilters)

    os.makedirs(cohort, exist_ok=True)
    sheetDataScales = {}
    if "Simulation" in type_:
        sheetDataScales.update({
            "Simulation Scale Summary": simScaleSummary,
            "Critical Incidents Sim": simCIDf,
            "Simulation Form Count": simFormCountDf,
        })
    if "Clinic" in type_:
        sheetDataScales.update({
            "Clinic Scale Summary": clinicScaleSummary,
            "Critical Incidents Clinic": clinicCIDf,
            "Clinic Form Count": clinicFormCountDf,
        })
    saveToExcel(filepathScales, sheetDataScales, index=True)

    sheetDataPivot = {}
    if "Simulation" in type_:
        sheetDataPivot.update({
            "Simulation Item Code Pivot": simPivot,
            "Simulation Global Rating Pivot": simGlobalRatingPivot,
            "Simulation Entrustment Pivot": simEntrustmentPivot,
        })
    if "Clinic" in type_:
        sheetDataPivot.update({
            "Clinic Item Code Pivot": clinicPivot,
            "Clinic Global Rating Pivot": clinicGlobalRatingPivot,
            "Clinic Entrustment Pivot": clinicEntrustmentPivot,
            "Clinic Item Code": mergedDf,
        })
    saveToExcel(filepathPivot, sheetDataPivot)

    sheetDataSubmission = {}
    if "Simulation" in type_:  
        sheetDataSubmission["Simulation Submission Info"] = simSubmissionInfoDf
    if "Clinic" in type_:
        sheetDataSubmission["Clinic Submission Info"] = clinicSubmissionInfoDf
    saveToExcel(filepathSubmission, sheetDataSubmission, index=False)

    flaggedSimDf = getFlaggedFormDetails(engine, cohort, formsTable, filters=simFilters)
    flaggedClinicDf = getFlaggedFormDetails(engine, cohort, formsTable, filters=clinicFilters)
    return flaggedSimDf, flaggedClinicDf


def getCohortReportsPerClinic(engine, cohort, today, formsTable="rawform_forms",
                              subject=None, type_=("Clinic",)):
    """Generate per-clinic breakdowns of scales, pivots, and submission info."""
    clinics = getClinicList(engine, cohort, formsTable,
                           filters={"subject": subject} if subject else None)
    suffix = f" {subject}" if subject else ""
    filepathScales = f"{cohort}/Scale Information by Clinic {cohort}{suffix} ({today}).xlsx"
    filepathPivot = f"{cohort}/Item Code Pivot by Clinic {cohort}{suffix} ({today}).xlsx"
    filepathSubmission = f"{cohort}/Submission Info by Clinic {cohort}{suffix} ({today}).xlsx"

    os.makedirs(cohort, exist_ok=True)

    for clinic in clinics:
        wargsScales = getmodeArgs(filepathScales)
        wargsPivot = getmodeArgs(filepathPivot)
        wargsSubmission = getmodeArgs(filepathSubmission)
        print(f"Generating report for clinic: {clinic}")

        clinicFilters = {"type": "Clinic", "clinic": clinic}
        if subject:
            clinicFilters["subject"] = subject

        clinicScaleSummary = getStudentScaleSummary(engine, cohort, formsTable, filters=clinicFilters)
        clinicScaleSummary = convertToMultiLevel(clinicScaleSummary)
        clinicCIDf = getCriticalIncidentDf(engine, cohort, formsTable, filters=clinicFilters)
        clinicFormCountDf = getStudentFormCountDf(engine, cohort, formsTable, filters=clinicFilters)

        # pivotFilters = {"type": "Clinic", "clinic": clinic}
        # clinicPivot, mergedDf = getStudentItemCodePivot(engine, cohort, formsTable, filters=pivotFilters, groupBy="section", mappingFile=variableUtils.itemSectionMappingFile)
        # clinicGlobalRatingPivot, _ = getStudentItemCodeGlobalRatingPivot(engine, cohort, formsTable, filters=pivotFilters, groupBy="section", mappingFile=variableUtils.itemSectionMappingFile)

        with pd.ExcelWriter(filepathScales, **wargsScales) as writer:
            clinicScaleSummary.to_excel(writer, sheet_name=f"{clinic} Scale Summary")
            clinicCIDf.to_excel(writer, sheet_name=f"{clinic} Critical Incidents", index=False)
            clinicFormCountDf.to_excel(writer, sheet_name=f"{clinic} Form Count", index=False)

        # with pd.ExcelWriter(filepathPivot, **wargsPivot) as writer:
        #     clinicPivot.to_excel(writer, sheet_name=f"{clinic} Clinic Item Code Pivot", index=False)
        #     mergedDf.to_excel(writer, sheet_name=f"{clinic} Clinic Item Code", index=False)
        #     clinicGlobalRatingPivot.to_excel(writer, sheet_name=f"{clinic} Clinic Global Rating Pivot", index=False)

        clinicSubmissionInfoDf = getSubmissionInfo(engine, cohort, formsTable, filters=clinicFilters)
        with pd.ExcelWriter(filepathSubmission, **wargsSubmission) as writer:
            clinicSubmissionInfoDf.to_excel(writer, sheet_name=f"{clinic} Clinic Submission Info", index=False)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Student-level query & report functions
# ═══════════════════════════════════════════════════════════════════════════

def getStudentData(engine, cohort, studentNumber, formsTable="rawform_forms", filters=None):
    """Fetch all form data for a single student with item codes extracted."""
    whereClause, params = _where(cohort, filters=filters)
    params["studentNumber"] = studentNumber

    sql = f"""
      SELECT f.*,
      COALESCE(
                NULLIF(f.assessor_data->'scale-practice-readiness'->>'scale', '')::int,
                NULLIF(f.assessor_data->'entrustment'->>'scale', '')::int,
                NULLIF(f.assessor_data->'practice-readiness'->>'scale', '')::int
            ) AS entrustment,
        COALESCE(
                NULLIF(f.assessor_data->'scale-professionalism'->>'scale', '')::int,
                NULLIF(f.assessor_data->'professionalism'->>'scale', '')::int
    )
        AS professionalism,
    COALESCE(
                NULLIF(f.assessor_data->'scale-communication'->>'scale', '')::int,
                NULLIF(f.assessor_data->'communication'->>'scale', '')::int
        )
        AS communication,
    COALESCE(
                NULLIF(f.assessor_data->'scale-time-mgmt'->>'scale', '')::int,
                NULLIF(f.assessor_data->'time_mgmt'->>'scale', '')::int
        ) AS time_management,        
      f.assessor_data->'scale-global-rating'->>'scale' AS global_rating,
      ic.item_codes AS item_codes
        FROM {formsTable} f
        LEFT JOIN LATERAL (
            SELECT array_agg(DISTINCT ic.key) AS item_codes
            FROM jsonb_each(COALESCE(f.assessor_data,'{{}}'::jsonb)) ic
            WHERE ic.key NOT LIKE 'scale-%%'
        ) ic ON true
      WHERE {whereClause}
        AND student_number = :studentNumber
    """
    if filters:
        params.update(filters)
    return readDf(engine, sql, params)


def calcScore(row, scoreMap=None):
    """Calculate normalised scores per item code from assessor_data."""
    if scoreMap is None:
        scoreMap = SCORE_MAP
    assessorData = row["assessor_data"]
    if assessorData is None or (row.get("role") not in (None, "Operator")):
        return {}
    scores = {}
    for itemCode, itemData in assessorData.items():
        if "scale" in itemCode:
            continue
        if not isinstance(itemData, dict):
            continue
        itemScore = 0
        validLength = 0
        for k, v in itemData.items():
            if v in scoreMap:
                itemScore += scoreMap[v]
                validLength += 1
        itemScore = itemScore / validLength if validLength > 0 else np.nan
        itemScore = round(itemScore, 2)
        scores[itemCode] = {"score": itemScore}
    return scores


def truncateText(textValue, maxLength=2000):
    if textValue is None:
        return ""
    textValue = str(textValue)
    if len(textValue) <= maxLength:
        return textValue
    return textValue[:maxLength] + "..."


def _getColor(row):
    if row["NA_Flag"]:
        return "gray"
    elif row["Patient Complexity"] == "complex":
        return "red"
    return "blue"


def explodeScoresToLong(df):
    """
    Explode the per-form ``scores`` dict into a long DataFrame with one row
    per (form, item_code).
 
    Expects *df* to already have a ``scores`` column (output of ``calcScore``).
 
    Returns a DataFrame with columns:
        datetimeutc, item_code, score, entrustment, global_rating
    """
    records = []
    for _, row in df.iterrows():
        scores = row.get("scores")
        if not isinstance(scores, dict) or not scores:
            continue
        for code, sd in scores.items():
            records.append({
                "datetimeutc": row["datetimeutc"],
                "Item Code": code,
                "Score": sd.get("score") if isinstance(sd, dict) else None,
                "Entrustment": row["entrustment"],
                "Global Rating": row["global_rating"],
                "Type": row["type"],
            })
    return pd.DataFrame(records)
# ═══════════════════════════════════════════════════════════════════════════
# 5. Plotting helpers
# ═══════════════════════════════════════════════════════════════════════════

def plotStudentScoresTimeSeries(df, dateCol="Date", scoreDictCol="scores", scoreKey="score", 
                                fallbackKey=None, title="Student Performance Over Time", pageSize=None):
    """Scatter plot of item-code scores over time."""
    if pageSize is None:
        pageSize = variableUtils.pageSize

    pecCodes = [
        "Consent", "Record_keeping", "infection_control", "positioning",
        "Record keeping", "Positioning", "Infection control",
    ]

    expandedRows = []
    for _, row in df.iterrows():
        if not isinstance(row[scoreDictCol], dict):
            continue
        complexity = (
            row["assessor_data"].get("scale-patient-complexity", {}).get("scale", None)
            if isinstance(row["assessor_data"], dict) else None
        )
        for itemCode, scoreDict in row[scoreDictCol].items():
            naFlag = False
            if itemCode in pecCodes:
                continue
            score = scoreDict.get(scoreKey)
            if score is None or pd.isna(score):
                if fallbackKey is not None:
                    score = scoreDict.get(fallbackKey)
                if score is None or pd.isna(score):
                    score = -5
                    naFlag = True
            expandedRows.append({
                "Date": row[dateCol],
                "Item": itemCode,
                "Score": score * 100,
                "Assessor Name": row["assessor_name"],
                "NA_Flag": naFlag,
                "Patient Complexity": complexity,
                "Clinic": row.get("clinic", "Unknown"),
            })

    expandedDf = pd.DataFrame(expandedRows)
    if expandedDf.empty:
        return None

    expandedDf.sort_values("Date", inplace=True)
    expandedDf["Date"] = expandedDf["Date"].dt.strftime("%Y-%m-%d")
    expandedDf["Color"] = expandedDf.apply(_getColor, axis=1)

    fig, ax = plt.subplots(figsize=(14, 8))
    ax.scatter(expandedDf["Date"], expandedDf["Score"], color=expandedDf["Color"], label="Scores")

    offsetCounter = defaultdict(int)
    for _, row in expandedDf.iterrows():
        key = (row["Date"], row["Score"])
        offset = offsetCounter[key] * 5
        offsetCounter[key] += 1
        ax.annotate(
            f"{row['Item']} SS" if row["Clinic"] == "Smile Squad" else f"{row['Item']}",
            (row["Date"], row["Score"]),
            textcoords="offset points", xytext=(10, 3 + 2 * offset),
            ha="center", fontsize=8,
        )

    ax.set_xlabel("Date")
    ax.set_ylabel("Score (% Yes or Weighted)")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.tick_params(axis="x", rotation=45)
    maxScore = 100
    ax.set_ylim(-10, 1.2 * maxScore)
    step = int(max(maxScore // 10, 1))
    ax.set_yticks(range(0, int(maxScore + 1), step))
    legendElems = [
        Line2D([0], [0], marker="o", color="w", label="Complex", markerfacecolor="red", markersize=8),
        Line2D([0], [0], marker="o", color="w", label="All NA", markerfacecolor="gray", markersize=8),
    ]
    ax.legend(handles=legendElems, bbox_to_anchor=(0.9, 0.97), loc="upper left")
    fig.tight_layout()
    return fig



def rubricPlot(ax, studentDf, label, color, xLabelRotation=45, maxY=None):
    """Single-axis time series of a scale value."""
    studentDf = studentDf.dropna(subset=[label])
    if studentDf.empty:
        ax.text(0.5, 0.5, "No data available", horizontalalignment="center",
                verticalalignment="center", transform=ax.transAxes)
        return
    # studentDf agg by Date to average multiple forms in a day
    studentDf = (studentDf.groupby("Date", sort=True)[label].mean().reset_index())
    ax.plot(studentDf["Date"], studentDf[label], label=label, color=color, marker="o")
    ax.set_title(label)
    if maxY is None:
        ax.set_ylim(0, studentDf[label].max() + 0.5)
        ax.set_yticks(range(0, int(studentDf[label].max() + 1), 1))
    else:
        ax.set_ylim(0, maxY)
        ax.set_yticks(range(0, int(maxY) + 1, 1))
    ax.tick_params(axis="x", rotation=xLabelRotation, labelsize=8)
    ax.grid(True, linestyle="--", alpha=0.5)
    # add space b/w plots
    plt.subplots_adjust(hspace=0.3)


def makeSafeParagraph(value):
    if pd.isna(value):
        textValue = ""
    else:
        textValue = str(value)
    textValue = escape(textValue).replace("\n", "<br/>")
    return textValue


def _computeSummaryMetrics(df, patientInfo=False, isSimulation=False):
    """
    Compute summary metrics from a student DataFrame (optionally pre-filtered
    by form type).
 
    Expects datetimeutc already converted.  The ``submitted_by_assessor``
    filter is applied internally so that total form counts reflect the
    unfiltered set while scale/item metrics use assessor-submitted forms only.
 
    When ``isSimulation`` is True, patient-age fields are left blank since
    simulation forms have no real patient.
 
    Returns an OrderedDict  {metricName: displayValue}  (empty if *df* is empty).
    """
    if df.empty:
        return OrderedDict()
 
    nForms = len(df)
    nAssessorSubmitted = int(df["submitted_by_assessor"].sum())
    nStudentSubmitted = int(df["submitted_by_student"].sum())
 
    # assessor-filtered subset for remaining metrics
    adf = df[df["submitted_by_assessor"]].copy()
 
    if adf.empty:
        return OrderedDict([
            ("# Forms", nForms),
            ("# Assessor Submitted", nAssessorSubmitted),
            ("# Student Submitted", nStudentSubmitted),
            # ("Entrustment Counts", "N/A"),
            ("Avg Global Rating", "N/A"),
            ("Critical Incidents", "0"),
        ])
 
    entrustmentCounts = adf["entrustment"].dropna().value_counts().to_dict()
    esCountsText = "<br/> ".join(
        f"Lvl {int(k)}: {v}" for k, v in sorted(entrustmentCounts.items())
    )
 
    avgGR = adf["global_rating"].dropna().astype(float).mean()
 
    ciCount = adf[adf["clinical_incident"].notna()].shape[0]
 
    metrics = OrderedDict([
        ("# Forms", nForms),
        ("# Assessor Submitted", nAssessorSubmitted),
        ("# Student Submitted", nStudentSubmitted),
        # ("Entrustment Counts", esCountsText),
        ("Avg Global Rating", f"{avgGR:.2f}/5" if not np.isnan(avgGR) else "N/A"),
        ("Critical Incidents", str(ciCount)),
    ])
 
    if patientInfo:
        if isSimulation:
            metrics["Mean Patient Age"] = ""
            metrics["Patient Age Dist."] = ""
            roleCounts = adf["role"].value_counts().to_dict()
            roleCountsText = "<br/> ".join(f"{k}: {v}" for k, v in roleCounts.items())
            patientDetails = adf["patient_details"].value_counts().to_dict()
            patientDetailsText = "<br/> ".join(f"{k}: {v}" for k, v in patientDetails.items())
            metrics["Role Counts"] = roleCountsText
            metrics["Patient Details"] = patientDetailsText
        else:
            patientAge = adf["patient_age"].clip(lower=0, upper=120)
            meanAge = patientAge.dropna().mean()
            ageBuckets = OrderedDict([
                ("0-6", adf[(adf["patient_age"] >= 0) & (adf["patient_age"] <= 6)].shape[0]),
                ("7-17", adf[(adf["patient_age"] >= 7) & (adf["patient_age"] <= 17)].shape[0]),
                ("18+", adf[adf["patient_age"] >= 18].shape[0]),
            ])
            ageCountsText = "<br/> ".join(f"{k}: {v}" for k, v in ageBuckets.items())
            roleCounts = adf["role"].value_counts().to_dict()
            roleCountsText = "<br/> ".join(f"{k}: {v}" for k, v in roleCounts.items())
            patientDetails = adf["patient_details"].value_counts().to_dict()
            patientDetailsText = "<br/> ".join(f"{k}: {v}" for k, v in patientDetails.items())
 
            metrics["Mean Patient Age"] = f"{meanAge:.2f}" if not np.isnan(meanAge) else "N/A"
            metrics["Patient Age Dist."] = ageCountsText
            metrics["Role Counts"] = roleCountsText
            metrics["Patient Details"] = patientDetailsText
 
    return metrics

# ── Pie-chart colour maps (red → green tier) ──
ENTRUSTMENT_COLORS = {
    1: "#d73027",   # red
    2: "#fc8d59",   # orange
    3: "#91cf60",   # light green
    4: "#1a9850",   # dark green
}
 
GR_COLORS = {
    1: "#d73027",   # red
    2: "#fc8d59",   # orange
    3: "#fee08b",   # yellow
    4: "#91cf60",   # light green
    5: "#1a9850",   # dark green
}
 
 
def _makeCountPctAutopct(counts):
    """Return an autopct callable that renders slices as 'count (pct%)'."""
    total = sum(counts)
    def autopct(pct):
        val = int(round(pct * total / 100.0))
        return f"{val} ({pct:.0f}%)"
    return autopct
 
 
def _plotEntrustmentPie(ax, df, title):
    """Plot entrustment-level pie chart on the given axis."""
    counts = df["entrustment"].dropna().astype(int).value_counts().sort_index()
    if counts.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.axis("off")
        return
    labels = [f"Lvl {lvl}" for lvl in counts.index]
    colors = [ENTRUSTMENT_COLORS.get(lvl, "#999999") for lvl in counts.index]
    ax.pie(
        counts.values, labels=labels, colors=colors,
        autopct=_makeCountPctAutopct(counts.values),
        startangle=90,
        labeldistance=1.1,
        pctdistance=0.7,
        textprops={"fontsize": 9},
    )
    ax.set_title(title, fontsize=11, fontweight="bold")
 
 
def _plotGlobalRatingPie(ax, df, title):
    """Plot global-rating pie chart with average shown in the title."""
    grNumeric = df["global_rating"].dropna().astype(float)
    counts = grNumeric.round().astype(int).value_counts().sort_index()
    avgGR = grNumeric.mean()
    avgText = f"  (Avg: {avgGR:.2f}/5)" if not np.isnan(avgGR) else ""
    if counts.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(f"{title}{avgText}", fontsize=11, fontweight="bold")
        ax.axis("off")
        return
    labels = [f"GR {gr}" for gr in counts.index]
    colors = [GR_COLORS.get(gr, "#999999") for gr in counts.index]
    ax.pie(
        counts.values, labels=labels, colors=colors,
        autopct=_makeCountPctAutopct(counts.values),
        startangle=90,
        labeldistance=1.1,
        pctdistance=0.7,
        textprops={"fontsize": 9},
    )
    ax.set_title(f"{title}{avgText}", fontsize=11, fontweight="bold")
 
 
def _makeRatingsFigure(simDf, clinicDf, hasSim, hasClinic):
    """
    Build a matplotlib figure with entrustment + global-rating pie charts.
 
    Layout: columns = type (Simulation first, then Clinic),
            rows = metric (Entrustment on top, Global Rating below).
    Returns the figure, or None if neither type has data.
    """
    nRows = int(hasSim) + int(hasClinic)
    if nRows == 0:
        return None
 
    fig, axes = plt.subplots(nRows, 2, figsize=(10, 4.2 * nRows))
    # Normalise to 2D shape (nRows, 2)
    if nRows == 1:
        axes = np.array([axes])
 
    rowIdx = 0
    if hasSim:
        simAdf = simDf[simDf["submitted_by_assessor"]]
        _plotEntrustmentPie(axes[rowIdx, 0], simAdf, "Simulation — Entrustment")
        _plotGlobalRatingPie(axes[rowIdx, 1], simAdf, "Simulation — Global Rating")
        rowIdx += 1
    if hasClinic:
        clinicAdf = clinicDf[clinicDf["submitted_by_assessor"]]
        _plotEntrustmentPie(axes[rowIdx, 0], clinicAdf, "Clinic — Entrustment")
        _plotGlobalRatingPie(axes[rowIdx, 1], clinicAdf, "Clinic — Global Rating")
 
    plt.tight_layout()
    return fig


def _addTimeSeriesPage(elements, df, typeLabel, subheadingStyle):
    """
    Append the time-series scatter + entrustment/GR rubric plots for a single
    form type ('Simulation' or 'Clinic') to *elements*.
 
    Caller is responsible for adding the PageBreak afterwards.
    *df* is expected to be assessor-submitted, type-filtered, sorted by date.
    """
    if df.empty:
        return
 
    elements.append(Spacer(1, 24))
    heading = Paragraph(f"{typeLabel} — Performance Over Time", subheadingStyle)
 
    # Item-score scatter plot
    timeSeriesDf = df[[
        "datetimeutc", "entrustment", "global_rating", "item_codes",
        "scores", "assessor_data", "assessor_name",
    ]].copy()
    timeSeriesDf["Date"] = timeSeriesDf["datetimeutc"]
    fig = plotStudentScoresTimeSeries(
        timeSeriesDf, dateCol="Date", scoreDictCol="scores",
        scoreKey="score", fallbackKey=None,
        title=f"{typeLabel} — Performance on Assessed Items Over Time",
    )
    timeSeriesImg = addPlotImage(fig) if fig is not None else None
    # if fig is not None:
        # elements.append(KeepTogether([heading, Spacer(1, 12), addPlotImage(fig)]))
        # plt.close(fig)
 
    # Entrustment + GR rubric panels
    fig, axes = plt.subplots(2, 1, figsize=(14, 6))
    rubricPlotDf = df[["datetimeutc", "entrustment", "global_rating"]].copy()
    rubricPlotDf.rename(columns={
        "datetimeutc": "Date",
        "entrustment": "Entrustment",
        "global_rating": "Global Rating",
    }, inplace=True)
    rubricPlotDf.sort_values("Date", inplace=True)
    rubricPlotDf["Date"] = rubricPlotDf["Date"].dt.strftime("%Y-%m-%d")
    rubricPlotDf["Entrustment"] = rubricPlotDf["Entrustment"].astype("Int64")
    rubricPlotDf["Global Rating"] = rubricPlotDf["Global Rating"].astype("Int64")
    rubricPlot(axes[0], rubricPlotDf, "Entrustment", "blue", maxY=4.5)
    rubricPlot(axes[1], rubricPlotDf, "Global Rating", "green", maxY=5.5)
    plt.subplots_adjust(hspace=0.5)
    rubricImg = addPlotImage(fig)
    plt.close(fig)
 
    elements.append(Spacer(1, 18))
    # elements.append(Paragraph(f"{typeLabel} — Entrustment and Global Rating Over Time", subheadingStyle,))
    elements.append(KeepTogether([heading, Spacer(1, 12), timeSeriesImg, rubricImg]))


def _addReflectionsTable(elements, df, typeLabel, subheadingStyle,
                         tableTextStyleSmall, uniColor):
    """
    Append a reflections table for a single form type to *elements*.
 
    Caller is responsible for adding a PageBreak afterwards.
    *df* is expected to be assessor-submitted and type-filtered.
    """
    if df.empty:
        return
 
    reflectionsDf = df[
        ["datetimeutc", "item_codes", "student_reflection", "assessor_reflection"]
    ].copy()
    reflectionsDf["item_codes"] = reflectionsDf["item_codes"].apply(
        lambda v: ", ".join(map(str, v)) if isinstance(v, (list, tuple)) and len(v) > 0 else ""
    )
    reflectionsDf["student_reflection"] = (
        reflectionsDf["student_reflection"].apply(truncateText).str.replace("\n", "<br/>")
    )
    reflectionsDf["assessor_reflection"] = (
        reflectionsDf["assessor_reflection"].apply(truncateText).str.replace("\n", "<br/>")
    )
    reflectionsDf.columns = ["Date", "Item Codes", "Student Reflection", "Assessor Reflection"]
    reflectionsDf = reflectionsDf.sort_values("Date")
    reflectionsDf["Date"] = reflectionsDf["Date"].dt.strftime("%Y-%m-%d")
 
    reflectionsTable = createTable(
        reflectionsDf,
        title=f"{typeLabel} — Reflections",
        colRatio=[1.2, 1.8, 4.5, 4.5],
        customTextCols=[0, 1, 2, 3],
        titleStyle=subheadingStyle,
        tableTextStyle=tableTextStyleSmall,
        headerColor=uniColor,
        bottomPadding=6, topPadding=6,
    )
    elements.append(reflectionsTable)


def _addItemCodeCountsBarChart(elements, df, classAvgItemCounts,
                               typeLabel, subheadingStyle,
                               maxCodesPerSubplot=25):
    """
    Append item-code counts bar chart(s) for *df* (already type-filtered and
    assessor-submitted).
 
    Codes are filtered: any code where the student's count is 0 *and* the
    class average (if present) is less than 1 is dropped.
 
    If more than *maxCodesPerSubplot* codes remain after filtering, the chart
    is split into stacked subplots with codes divided as evenly as possible
    across them (so 60 codes become 20+20+20, not 25+25+10).
 
    If *classAvgItemCounts* is a non-empty dict, a side-by-side class-average
    series is included; otherwise only the student's counts are shown.
 
    Caller is responsible for adding a PageBreak afterwards.
    """
    if df.empty:
        return
 
    studentCounts = (
        df["item_codes"].dropna().explode().value_counts().to_dict()
    )
    if not studentCounts:
        return
    # sort by count values
    
    hasAvg = bool(classAvgItemCounts)
    if hasAvg:
        allCodes = sorted(
            set(studentCounts.keys()) | set(classAvgItemCounts.keys()),
            key=lambda c: (-studentCounts.get(c, 0), c),
        )
    else:
        allCodes = sorted(
            studentCounts.keys(),
            key=lambda c: (-studentCounts[c], c),
        )
 
    # Drop codes where student count == 0 AND (no avg or avg < 1)
    filteredCodes = []
    for c in allCodes:
        sv = studentCounts.get(c, 0)
        av = classAvgItemCounts.get(c, 0.0) if hasAvg else 0.0
        if sv == 0 and av < 1:
            continue
        filteredCodes.append(c)
 
    if not filteredCodes:
        return
 
    # Split into roughly equal chunks (≤ maxCodesPerSubplot per chunk)
    n = len(filteredCodes)
    nSubplots = (n + maxCodesPerSubplot - 1) // maxCodesPerSubplot
    base = n // nSubplots
    remainder = n % nSubplots
 
    chunks = []
    start = 0
    for i in range(nSubplots):
        size = base + (1 if i < remainder else 0)
        chunks.append(filteredCodes[start:start + size])
        start += size
 
    # Shared y-axis ceiling so subplots are visually comparable
    studentMax = max(studentCounts.get(c, 0) for c in filteredCodes)
    if hasAvg:
        avgMax = max(classAvgItemCounts.get(c, 0.0) for c in filteredCodes)
        maxY = max(studentMax, avgMax)
    else:
        maxY = studentMax
    yLim = maxY * 1.15 + 1  # headroom for value labels above bars
 
    fig, axes = plt.subplots(
        nSubplots, 1,
        figsize=(14, 5 * nSubplots),
        sharey=True,
    )
    if nSubplots == 1:
        axes = [axes]
 
    for axIdx, (ax, chunk) in enumerate(zip(axes, chunks)):
        x = np.arange(len(chunk))
        studentVals = [studentCounts.get(c, 0) for c in chunk]
 
        if hasAvg:
            width = 0.4
            avgVals = [classAvgItemCounts.get(c, 0.0) for c in chunk]
            ax.bar(x - width / 2, studentVals, width,
                   label="Your count" if axIdx == 0 else None,
                   color="#1f77b4")
            ax.bar(x + width / 2, avgVals, width,
                   label="Class average" if axIdx == 0 else None,
                   color="#fc8d59")
            for xi, v in zip(x - width / 2, studentVals):
                if v > 0:
                    ax.text(xi, v + 0.1, str(int(v)),
                            ha="center", va="bottom", fontsize=8)
            for xi, v in zip(x + width / 2, avgVals):
                if v > 0:
                    ax.text(xi, v + 0.1, f"{v:.1f}",
                            ha="center", va="bottom", fontsize=8)
        else:
            width = 0.65
            ax.bar(x, studentVals, width, color="#1f77b4")
            for xi, v in zip(x, studentVals):
                if v > 0:
                    ax.text(xi, v + 0.1, str(int(v)),
                            ha="center", va="bottom", fontsize=8)
 
        ax.set_xticks(x)
        ax.set_xticklabels(chunk, rotation=45, ha="right", fontsize=8)
        ax.set_ylim(0, yLim)
        ax.set_ylabel("Count")
        ax.grid(axis="y", linestyle="--", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
 
    if hasAvg:
        axes[0].legend(loc="upper right")
 
    titleSuffix = " vs Class Average" if hasAvg else ""
    fig.suptitle(
        f"{typeLabel} — Item Code Counts{titleSuffix}",
        fontsize=13, fontweight="bold", y=1.0,
    )
    plt.tight_layout()
 
    img = addPlotImage(fig, 0.9)
    plt.close(fig)
 
    elements.append(Spacer(1, 18))
    elements.append(Paragraph(
        f"{typeLabel} — Procedures Performed",
        subheadingStyle,
    ))
    elements.append(img)

SECTION_DISPLAY_NAMES = {
    "Preventive, Prophylactic and Bleaching Services": "PPB",
}
 
 
def _sectionLabel(name):
    """Return shortened display label for a section name."""
    return SECTION_DISPLAY_NAMES.get(name, name)

def _addSectionPerformance(elements, longDf, typePages, subheadingStyle,
                           tableTextStyle, uniColor, minSectionsForSpider=3):
    """
    Append section-level performance for all form types present.
 
    When both Simulation and Clinic have ≥ *minSectionsForSpider* sections,
    their spider charts are rendered side-by-side in a single figure.
    When only one qualifies, a single smaller spider is shown.
    When fewer than *minSectionsForSpider* sections exist for a type, only
    a summary table is shown for that type.
 
    *longDf* must already contain columns:
        Item Code, Score, Entrustment, Global Rating, Type, Section
    """
    if longDf.empty or "Section" not in longDf.columns:
        return
 
    # ── Compute per-type section aggregates ──
    typeAggs = {}
    for typeLabel, _ in typePages:
        typeLongDf = longDf[
            (longDf["Type"] == typeLabel) & (longDf["Section"] != "Unmapped")
        ]
        if typeLongDf.empty:
            continue
        agg = (
            typeLongDf.groupby("Section")
            .agg(
                count=("Score", "size"),
                mean_score=("Score", "mean"),
                mean_gr=("Global Rating",
                         lambda s: s.dropna().astype(float).mean()),
                mean_es=("Entrustment",
                         lambda s: s.dropna().astype(float).mean()),
            )
            .sort_values("count", ascending=False)
        )
        agg = agg[agg["count"] > 0]
        if not agg.empty:
            typeAggs[typeLabel] = agg
 
    if not typeAggs:
        return
 
    # ── Spider chart(s): Score (left) and GR + ES overlay (right) ──
    spiderTypes = {
        t: a for t, a in typeAggs.items()
        if len(a) >= minSectionsForSpider
    }
    nSpiders = len(spiderTypes)
 
    if nSpiders > 0:
        fig, axes = plt.subplots(nSpiders, 2, figsize=(11, 5.2 * nSpiders), subplot_kw=dict(polar=True),)
        
        if nSpiders == 1:
            axes = axes.reshape(1, 2)
 
        for rowIdx, (typeLabel, agg) in enumerate(spiderTypes.items()):
            sections = agg.index.tolist()
            N = len(sections)
            angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
            angles_closed = angles + [angles[0]]
 
            spokeLabels = [_sectionLabel(s) + f"\n(n={int(agg.loc[s, 'count'])})" for s in sections]
 
            # ── Left spider: Mean Score (0–1) ──
            axScore = axes[rowIdx, 0]
            scoreVals = agg["mean_score"].tolist()
            scoreVals_c = scoreVals + [scoreVals[0]]
 
            axScore.fill(angles_closed, scoreVals_c, alpha=0.25, color="#1f77b4")
            axScore.plot(angles_closed, scoreVals_c, "o-", color="#1f77b4", linewidth=2, markersize=5)
            axScore.set_xticks(angles)
            axScore.set_xticklabels(spokeLabels, fontsize=8)
            axScore.set_ylim(0, 1)
            axScore.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
            axScore.set_yticklabels(["20%", "40%", "60%", "80%", "100%"], fontsize=7)
            axScore.set_title(f"{typeLabel} — Mean Score", fontsize=11, fontweight="bold", pad=30)
 
            # ── Right spider: GR (/5) and ES (/4) normalised to 0–1 ──
            axGrEs = axes[rowIdx, 1]
 
            grVals = [agg.loc[s, "mean_gr"] / 5 if not np.isnan(agg.loc[s, "mean_gr"]) else 0
                      for s in sections]
            esVals = [agg.loc[s, "mean_es"] / 4 if not np.isnan(agg.loc[s, "mean_es"]) else 0
                      for s in sections]
            grVals_c = grVals + [grVals[0]]
            esVals_c = esVals + [esVals[0]]
 
            axGrEs.fill(angles_closed, grVals_c, alpha=0.15, color="#2ca02c")
            axGrEs.plot(angles_closed, grVals_c, "o-", color="#2ca02c",
                        linewidth=2, markersize=5, label="Global Rating (/5)")
            axGrEs.fill(angles_closed, esVals_c, alpha=0.15, color="#ff7f0e")
            axGrEs.plot(angles_closed, esVals_c, "o-", color="#ff7f0e",
                        linewidth=2, markersize=5, label="Entrustment (/4)")
 
            axGrEs.set_xticks(angles)
            axGrEs.set_xticklabels(spokeLabels, fontsize=8)
            axGrEs.set_ylim(0, 1)
            axGrEs.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
            axGrEs.set_yticklabels(["20%", "40%", "60%", "80%", "100%"],
                                    fontsize=7)
            axGrEs.set_title(f"{typeLabel} — GR & Entrustment",
                             fontsize=11, fontweight="bold", pad=30)
            axGrEs.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1),
                          fontsize=8)
 
        # fig.suptitle("Section Performance", fontsize=13, fontweight="bold", y=1.02)
        plt.subplots_adjust(wspace=0.4, hspace=1)
        plt.tight_layout()

 
        spiderImg = addPlotImage(fig, 0.9)
        plt.close(fig)
 
        elements.append(Spacer(1, 18))
        elements.append(KeepTogether([Paragraph("Performance by Section", subheadingStyle), Spacer(1, 12), spiderImg]))
 
    # ── Summary table(s) — only for types without a spider chart ──
    tableOnlyTypes = {
        t: a for t, a in typeAggs.items() if t not in spiderTypes
    }
    for typeLabel, agg in tableOnlyTypes.items():
        sections = agg.index.tolist()
        tableDf = pd.DataFrame({
            "Section": [_sectionLabel(s) for s in sections],
            "# Items": [int(agg.loc[s, "count"]) for s in sections],
            "Mean Score": [f"{agg.loc[s, 'mean_score']:.0%}" for s in sections],
            "Mean GR": [
                f"{agg.loc[s, 'mean_gr']:.1f}/5"
                if not np.isnan(agg.loc[s, 'mean_gr']) else "N/A"
                for s in sections
            ],
            "Mean ES": [
                f"{agg.loc[s, 'mean_es']:.1f}/4"
                if not np.isnan(agg.loc[s, 'mean_es']) else "N/A"
                for s in sections
            ],
        })
 
        sectionTable = createTable(
            tableDf,
            title=f"{typeLabel} — Section Summary",
            colRatio=[3, 1, 1, 1, 1],
            customTextCols=list(range(tableDf.shape[1])),
            titleStyle=subheadingStyle,
            tableTextStyle=tableTextStyle,
            headerColor=uniColor,
            bottomPadding=6, topPadding=6,
        )
        elements.append(Spacer(1, 12))
        elements.append(sectionTable)
# ═══════════════════════════════════════════════════════════════════════════
# 6. Student PDF report builder
# ═══════════════════════════════════════════════════════════════════════════
def buildCohortTimeSeriesPdf(*, engine, cohort, outPath, bannerTitle,
                              formType=None, formsTable="rawform_forms",
                              scoreMap=None, subheadingStyle=None, uniColor=None,
                              pageSize=None, rightMargin=36, leftMargin=36,
                              topMargin=48, bottomMargin=36):
    """
    Scrollable PDF with every student's score scatter + rubric time series,
    optionally filtered to Simulation or Clinic.
    """
    if scoreMap is None:
        scoreMap = SCORE_MAP
    if uniColor is None:
        uniColor = variableUtils.uniColor
    if subheadingStyle is None:
        subheadingStyle = variableUtils.subheadingStyle
    if pageSize is None:
        pageSize = variableUtils.pageSize

    filters = {"type": formType} if formType else None

    elements = []
    elements.append(Spacer(1, 72+12))

    doc = SimpleDocTemplate(
        str(outPath), pagesize=pageSize, rightMargin=rightMargin,
        leftMargin=leftMargin, topMargin=topMargin, bottomMargin=bottomMargin,
    )

    studentsDf = getStudentsInCohort(engine, cohort, formsTable)
    studentsDf.sort_values("student_name", inplace=True)

    for _, sRow in studentsDf.iterrows():
        studentName = sRow["student_name"]
        studentNumber = sRow["student_number"]
        if cohort == 'BOH2' and studentNumber in BOH2_REMOVED_STUDENTS:
            continue
        if cohort == 'DDS2' and studentNumber in DDS2_REMOVED_STUDENTS:
            continue
        # studentIds = ['1678748', '1684643', '1362959', '1309866', '1362803', '1346824']
        # if str(studentNumber) not in studentIds:
        #     continue

        studentDataDf = getStudentData(engine, cohort, studentNumber, formsTable, filters=filters)
        if studentDataDf.empty:
            continue

        studentDataDf["datetimeutc"] = (
            pd.to_datetime(studentDataDf["datetimeutc"], utc=True)
            .dt.tz_convert("Australia/Melbourne")
        )
        if cohort == 'BOH2' and formType == 'Clinic':
            # filter out Smile Squad clinic, in these student_data is to be treated as assessor_data, to be filtered out by submitted_by_student
            smileSquadDf = studentDataDf[studentDataDf["clinic"] == "Smile Squad"]
            # display(smileSquadDf[["clinic", "student_data", "assessor_data", "submitted_by_student"]])
            # exchange the columns student_data and assessor_data for these rows
            studentDataDf.loc[smileSquadDf.index, ["student_data", "assessor_data"]] = studentDataDf.loc[smileSquadDf.index, ["assessor_data", "student_data"]].values
            studentDataDf.loc[smileSquadDf.index, ["submitted_by_student", "submitted_by_assessor"]] = studentDataDf.loc[smileSquadDf.index, ["submitted_by_assessor", "submitted_by_student"]].values
            # display(studentDataDf[["clinic", "student_data", "assessor_data", "submitted_by_student"]][studentDataDf["clinic"] == "Smile Squad"])
        
        studentDataDf = studentDataDf[studentDataDf["submitted_by_assessor"]].copy()
        if studentDataDf.empty:
            continue
        studentDataDf["scores"] = studentDataDf.apply(
            lambda row: calcScore(row, scoreMap), axis=1,
        )
        studentDataDf.sort_values("datetimeutc", inplace=True)

        titleText = f"{studentName} ({studentNumber})"
        elements.append(Paragraph(titleText, subheadingStyle))
        elements.append(Spacer(1, 6))

        # ── 1. Item-code score scatter ──
        timeSeriesDf = studentDataDf[
            ["datetimeutc", "entrustment", "global_rating", "communication", "professionalism", "time_management",
             "item_codes", "scores", "assessor_data", "assessor_name", 'clinic']
        ].copy()
        timeSeriesDf["Date"] = timeSeriesDf["datetimeutc"]
        scoreFig = plotStudentScoresTimeSeries(
            timeSeriesDf, dateCol="Date", scoreDictCol="scores",
            scoreKey="score", fallbackKey=None,
            title=f"Item Scores – {titleText}",
        )
        if scoreFig is not None:
            elements.append(addPlotImage(scoreFig, 0.9))
            elements.append(Spacer(1, 12))

        # ── 2. Rubric lines (entrustment + global rating) ──
        rubricDf = studentDataDf[["datetimeutc", "entrustment", "global_rating", "communication", "professionalism", "time_management"]].copy()
        rubricDf["entrustment"] = pd.to_numeric(rubricDf["entrustment"], errors="coerce")
        rubricDf["global_rating"] = pd.to_numeric(rubricDf["global_rating"], errors="coerce")
        rubricDf["communication"] = pd.to_numeric(rubricDf["communication"], errors="coerce")
        rubricDf["professionalism"] = pd.to_numeric(rubricDf["professionalism"], errors="coerce")
        rubricDf["time_management"] = pd.to_numeric(rubricDf["time_management"], errors="coerce")
        rubricDf["date"] = rubricDf["datetimeutc"].dt.strftime("%Y-%m-%d")

        # Average when multiple forms on the same day
        rubricDf = (
            rubricDf.groupby("date", sort=True)[["entrustment", "global_rating", "communication", "professionalism", "time_management"]]
            .mean()
            .reset_index()
        )
        rubricDf.rename(columns={
            "date": "Date",
            "entrustment": "Entrustment",
            "global_rating": "Global Rating",
            "communication": "Communication",
            "professionalism": "Professionalism",
            "time_management": "Time Management",
        }, inplace=True)

        fig, axes = plt.subplots(5, 1, figsize=(14, 10))
        rubricPlot(axes[0], rubricDf, "Entrustment", "steelblue", maxY=4.5)
        axes[0].tick_params(axis="x", labelbottom=False)
        rubricPlot(axes[1], rubricDf, "Global Rating", "darkorange", maxY=5.5)
        axes[1].tick_params(axis="x", labelbottom=False)
        rubricPlot(axes[2], rubricDf, "Communication", "green", maxY=3.0)
        axes[2].tick_params(axis="x", labelbottom=False)
        rubricPlot(axes[3], rubricDf, "Professionalism", "purple", maxY=3.0)
        axes[3].tick_params(axis="x", labelbottom=False)
        rubricPlot(axes[4], rubricDf, "Time Management", "red", maxY=5.0)
        plt.subplots_adjust(hspace=0.5)
        plt.close(fig)
        elements.append(addPlotImage(fig, 0.9))

        elements.append(PageBreak())
        # break  # TEMP: only first student for now

    doc.build(elements, onFirstPage=getBannerDrawer(bannerTitle, ""))


def buildStudentReport(studentDataDf, patientInfo=False, scoreMap=None, subheadingStyle=None, subsubheadingStyleL=None,
                       tableTextStyle=None, tableTextStyleSmall=None, uniColor=None, cohort=None, classAvgItemCounts:dict=None):
    """
    Build reportlab elements for a single student's PDF report.
 
    Returns a list of reportlab flowable elements.
    """
    if scoreMap is None:
        scoreMap = SCORE_MAP
    if uniColor is None:
        uniColor = variableUtils.uniColor
    if subheadingStyle is None:
        subheadingStyle = variableUtils.subheadingStyle
    if tableTextStyle is None:
        tableTextStyle = variableUtils.tableTextStyle
 
    elements = []
    elements.append(Spacer(1, 72))
 
    studentDataDf["datetimeutc"] = (
        pd.to_datetime(studentDataDf["datetimeutc"], utc=True)
        .dt.tz_convert("Australia/Melbourne")
    )

    # ── Summary table: split by form type (Simulation / Clinic) ──
    simDf = studentDataDf[studentDataDf["type"] == "Simulation"]
    clinicDf = studentDataDf[studentDataDf["type"] == "Clinic"]
 
    simMetrics = _computeSummaryMetrics(simDf, patientInfo=patientInfo, isSimulation=True)
    clinicMetrics = _computeSummaryMetrics(clinicDf, patientInfo=patientInfo)
 
    # Union of metric keys in insertion order
    allKeys = list(OrderedDict.fromkeys(
        list(simMetrics.keys()) + list(clinicMetrics.keys())
    ))
 
    hasSim = bool(simMetrics)
    hasClinic = bool(clinicMetrics)
    
    if cohort == 'DDS3':
        hasSim = False
    if cohort == 'BOH1':
        hasClinic = False

    if hasSim and hasClinic:
        summaryDf = pd.DataFrame({
            "Metric": allKeys,
            "Simulation": [simMetrics.get(k, "") for k in allKeys],
            "Clinic": [clinicMetrics.get(k, "") for k in allKeys],
        })
        colRatio = [2, 1, 1]
        customTextCols = [0, 1, 2]
    elif hasSim:
        summaryDf = pd.DataFrame({
            "Metric": allKeys,
            "Simulation": [simMetrics.get(k, "") for k in allKeys],
        })
        colRatio = [2, 1]
        customTextCols = [0, 1]
    else:
        summaryDf = pd.DataFrame({
            "Metric": allKeys,
            "Clinic": [clinicMetrics.get(k, "") for k in allKeys],
        })
        colRatio = [2, 1]
        customTextCols = [0, 1]
 
    summaryTable = createTable(
        summaryDf, title="Summary", colRatio=colRatio,
        customTextCols=customTextCols,
        titleStyle=subheadingStyle, tableTextStyle=tableTextStyle,
        headerColor=uniColor, bottomPadding=6, topPadding=6,
    )
 
    if subsubheadingStyleL is not None:
        elements.append(Paragraph(
            "This is a summary report of your activity so far in 2026. "
            "For detailed information please review your completed forms in the DASH program."
            "<br/> We are working on an interactive live dashboard for future reports.",
            subsubheadingStyleL,
        ))
    elements.append(summaryTable)
    elements.append(Spacer(1, 16))
 
    # ── Rating Distribution: entrustment + global-rating pies per type ──
    ratingsFig = _makeRatingsFigure(simDf, clinicDf, hasSim, hasClinic)
    if ratingsFig is not None:
        ratingElements = [
            Paragraph("Rating Distribution", subheadingStyle),
            Spacer(1, 6),
            addPlotImage(ratingsFig, ratio=0.75),
        ]
        elements.append(KeepTogether(ratingElements))
    elements.append(PageBreak())
    


    # ── Filter to assessor-submitted for plots & reflections ──
    studentDataDf = studentDataDf[studentDataDf["submitted_by_assessor"]].copy()
    studentDataDf["scores"] = studentDataDf.apply(lambda row: calcScore(row, scoreMap), axis=1)
    studentDataDf.sort_values("datetimeutc", inplace=True)
    # display(studentDataDf.head())

    # -- explode to longDf for item-code-level analyses and add sections
    longDf = explodeScoresToLong(studentDataDf)
    longDf = _mergeSection(longDf)
    # replace Unmapped section with Miscellaneous
    longDf["Section"] = longDf["Section"].replace("Unmapped", "Miscellaneous")
    # display(longDf.head(15))
    allSections = _loadSectionMapping()["Section"].dropna().unique().tolist()
    # print(f"Sections in mapping: {allSections}")

    # ── Per-type time series pages (Simulation, then Clinic) and Item Code counts ──
    simAdf = studentDataDf[studentDataDf["type"] == "Simulation"]
    clinicAdf = studentDataDf[studentDataDf["type"] == "Clinic"]
 
    typePages = []
    if not simAdf.empty and hasSim:
        typePages.append(("Simulation", simAdf))
    if not clinicAdf.empty and hasClinic:
        typePages.append(("Clinic", clinicAdf))
    
    if classAvgItemCounts['Simulation'] and not simAdf.empty and cohort not in ['DDS3', 'DDS2']:
        _addItemCodeCountsBarChart(
            elements, simAdf, classAvgItemCounts['Simulation'],
            "Simulation", subheadingStyle,
        )
    elements.append(Spacer(1, 18))

    if classAvgItemCounts['Clinic'] and not clinicAdf.empty and cohort not in ['BOH1']:
        _addItemCodeCountsBarChart(
            elements, clinicAdf, classAvgItemCounts["Clinic"],
            "Clinic", subheadingStyle)
    
    
    # Section performance (spider charts side-by-side + per-type tables)
    if not longDf.empty:
        _addSectionPerformance(
            elements, longDf, typePages,
            subheadingStyle=subheadingStyle,
            tableTextStyle=tableTextStyle,
            uniColor=uniColor,
        )   
    elements.append(PageBreak())

    # Time series pages (scatter + rubric lines) for each type, with PageBreak after each
    for idx, (typeLabel, typeDf) in enumerate(typePages):
        _addTimeSeriesPage(
            elements, typeDf, typeLabel,
            subheadingStyle=subheadingStyle,
        )
        elements.append(PageBreak())

    # ── Per-type reflections (Simulation, then Clinic) ──
    for typeLabel, typeDf in typePages:
        _addReflectionsTable(
            elements, typeDf, typeLabel,
            subheadingStyle=subheadingStyle,
            tableTextStyleSmall=tableTextStyleSmall,
            uniColor=uniColor,
        )
        elements.append(PageBreak())
 

    return elements



def buildEntireCohortStudentReports(engine, cohort, formsTable="rawform_forms",
                                     patientInfo=False,
                                     pageSize=None, leftMargin=None, rightMargin=None,
                                     topMargin=None, bottomMargin=None,
                                     subheadingStyle=None, subsubheadingStyleL=None,
                                     tableTextStyle=None, tableTextStyleSmall=None,
                                     uniColor=None, scoreMap=None):
    """Build individual student PDF reports for every student in a cohort."""
    if pageSize is None:
        pageSize = variableUtils.pageSize
    if leftMargin is None:
        leftMargin = variableUtils.leftMargin
    if rightMargin is None:
        rightMargin = variableUtils.rightMargin
    if topMargin is None:
        topMargin = variableUtils.topMargin
    if bottomMargin is None:
        bottomMargin = variableUtils.bottomMargin

    studentInfoDf = getStudentsInCohort(engine, cohort, formsTable).set_index("student_number")
    studentIds = studentInfoDf.index.tolist()
    savefolder = f"{cohort}/Individual Student Reports"
    os.makedirs(savefolder, exist_ok=True)
    # Cohort-level class averages for Simulation item-code counts (DDS2 only).
    # Computed once outside the loop and passed into each student report.
    classAvgItemCountsSim = None
    classAvgItemCountsClinic = None
    if cohort not in ["DDS2", "DDS3"]:
        classAvgItemCountsSim = getCohortItemCodeAverages(
            engine, cohort, formType="Simulation", formsTable=formsTable,
        )
        print(f"Computed class averages over {len(classAvgItemCountsSim)} item codes for {cohort} Simulation")
    if cohort not in ["BOH1"]:
        classAvgItemCountsClinic = getCohortItemCodeAverages(
            engine, cohort, formType="Clinic", formsTable=formsTable,
        )
        print(f"Computed class averages over {len(classAvgItemCountsClinic)} item codes for {cohort} Clinic")
    classAvgItemCounts = {
        "Simulation": classAvgItemCountsSim,
        "Clinic": classAvgItemCountsClinic,
    }
    # studentIds = ['1678748', '1684643', '1362959', '1309866', '1362803', '1346824']
    # studentIds = [int(id) for id in studentIds]
    for studentNumber in studentIds:
        if cohort == 'DDS2' and studentNumber in DDS2_REMOVED_STUDENTS:
            continue
        if cohort == 'BOH2' and studentNumber in BOH2_REMOVED_STUDENTS:
            continue
        studentName = studentInfoDf.loc[studentNumber, "student_name"]
        print(f"Building report for student {studentNumber} - {studentName}")
        studentDataDf = getStudentData(engine, cohort, studentNumber, formsTable)
        # studentDataDf = studentDataDf[studentDataDf['type'] == 'Simulation']
        filename = f"{savefolder}/{studentNumber}.pdf"
        doc = SimpleDocTemplate(
            filename, pagesize=pageSize,
            rightMargin=rightMargin, leftMargin=leftMargin,
            topMargin=topMargin, bottomMargin=bottomMargin,
        )
        elements = buildStudentReport(
            studentDataDf, patientInfo=patientInfo, scoreMap=scoreMap,
            subheadingStyle=subheadingStyle, subsubheadingStyleL=subsubheadingStyleL,
            tableTextStyle=tableTextStyle, tableTextStyleSmall=tableTextStyleSmall,
            uniColor=uniColor, cohort=cohort, classAvgItemCounts=classAvgItemCounts
        )
        doc.build(
            elements,
            onFirstPage=getBannerDrawer("Till Date performance report",
                                         f"{studentName} ({studentNumber})"),
        )
        print(f"Report saved to {filename}\n")
        # break  # TEMP - remove this to build for all students
