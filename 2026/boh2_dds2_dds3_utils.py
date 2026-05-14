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
from collections import defaultdict
from xml.sax.saxutils import escape
from sqlalchemy import text

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, PageBreak, Paragraph, Spacer,
)
from reportlab.lib.units import inch
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D

from Utils import createTable, addPlotImage, getBannerDrawer, getmodeArgs, readDf, runDdl, toInt, autoFitColumns
import variableUtils

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


def _mergeSection(df, mappingDf, codeCol="Item Code"):
    """
    Merge a DataFrame that has an item-code column with the section mapping.

    Handles compound codes like "022/024" by splitting on "/" and matching
    the first component.  Unmatched codes get Section/Sub-section = "Unmapped".

    Always adds both "Section" and "Sub-section" columns.
    """
    merged = df.copy()
    merged["_MappingCode"] = merged[codeCol].astype(str).str.split("/").str[0].str.split("-").str[0].str.strip()

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


# ═══════════════════════════════════════════════════════════════════════════
# 5. Plotting helpers
# ═══════════════════════════════════════════════════════════════════════════

def plotStudentScoresTimeSeries(df, dateCol="Date", scoreDictCol="scores",
                                scoreKey="score", fallbackKey=None,
                                title="Student Performance Over Time",
                                pageSize=None):
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
            f"{row['Item']}",
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


def makeSafeParagraph(value):
    if pd.isna(value):
        textValue = ""
    else:
        textValue = str(value)
    textValue = escape(textValue).replace("\n", "<br/>")
    return textValue


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
            ["datetimeutc", "entrustment", "global_rating",
             "item_codes", "scores", "assessor_data", "assessor_name"]
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
        rubricDf = studentDataDf[["datetimeutc", "entrustment", "global_rating"]].copy()
        rubricDf["entrustment"] = pd.to_numeric(rubricDf["entrustment"], errors="coerce")
        rubricDf["global_rating"] = pd.to_numeric(rubricDf["global_rating"], errors="coerce")
        rubricDf["date"] = rubricDf["datetimeutc"].dt.strftime("%Y-%m-%d")

        # Average when multiple forms on the same day
        rubricDf = (
            rubricDf.groupby("date", sort=True)[["entrustment", "global_rating"]]
            .mean()
            .reset_index()
        )
        rubricDf.rename(columns={
            "date": "Date",
            "entrustment": "Entrustment",
            "global_rating": "Global Rating",
        }, inplace=True)

        fig, axes = plt.subplots(2, 1, figsize=(14, 5))
        rubricPlot(axes[0], rubricDf, "Entrustment", "steelblue", maxY=4.5)
        axes[0].tick_params(axis="x", labelbottom=False)
        rubricPlot(axes[1], rubricDf, "Global Rating", "darkorange", maxY=5.5)
        plt.subplots_adjust(hspace=0.5)
        plt.close(fig)
        elements.append(addPlotImage(fig, 0.9))

        elements.append(PageBreak())

    doc.build(elements, onFirstPage=getBannerDrawer(bannerTitle, ""))


def buildStudentReport(studentDataDf, patientInfo=False, scoreMap=None,
                       subheadingStyle=None, subsubheadingStyleL=None,
                       tableTextStyle=None, tableTextStyleSmall=None,
                       uniColor=None):
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

    nForms = len(studentDataDf)
    nAssessorSubmittedForms = studentDataDf["submitted_by_assessor"].sum()
    nStudentSubmittedForms = studentDataDf["submitted_by_student"].sum()

    studentDataDf["datetimeutc"] = (
        pd.to_datetime(studentDataDf["datetimeutc"], utc=True)
        .dt.tz_convert("Australia/Melbourne")
    )
    studentDataDf = studentDataDf[studentDataDf["submitted_by_assessor"]].copy()
    studentDataDf["scores"] = studentDataDf.apply(lambda row: calcScore(row, scoreMap), axis=1)
    studentDataDf.sort_values("datetimeutc", inplace=True)

    roleCounts = studentDataDf["role"].value_counts().to_dict()
    roleCountsText = "<br/> ".join(f"{k}: {v}" for k, v in roleCounts.items())
    entrustmentCounts = studentDataDf["entrustment"].value_counts().to_dict()
    esCountsText = "<br/> ".join(f"Lvl {int(k)}: {v}" for k, v in sorted(entrustmentCounts.items()))
    avgGlobalRating = studentDataDf["global_rating"].dropna().astype(float).mean()
    ciDf = studentDataDf[studentDataDf["clinical_incident"].notna()][
        ["datetimeutc", "clinical_incident", "assessor_name", "clinic"]
    ]
    ciCounts = ciDf.shape[0]
    allItemCodes = studentDataDf["item_codes"].dropna().explode().value_counts().to_dict()
    topItemCodes = dict(sorted(allItemCodes.items(), key=lambda x: x[1], reverse=True)[:5])
    topItemCodesText = ", ".join(f"{k}: {v}" for k, v in topItemCodes.items())

    summaryDf = pd.DataFrame({
        "Metric": [
            "# Forms", "# Forms Submitted by Assessor", "# Forms Submitted by Student",
            "Entrustment Counts", "Average Global Rating", "Critical Incidents", "Top Item Codes",
        ],
        "": [
            nForms, nAssessorSubmittedForms, nStudentSubmittedForms, esCountsText,
            f"{avgGlobalRating:.2f}/5" if not np.isnan(avgGlobalRating) else "N/A",
            f"{ciCounts}", topItemCodesText,
        ],
    })

    if patientInfo:
        # patient details clip 0 to 120 
        patientAge = studentDataDf["patient_age"].clip(lower=0, upper=120)
        meanAge = patientAge.dropna().mean()
        patientDetails = studentDataDf["patient_details"].value_counts().to_dict()
        patientDetailsText = "<br/> ".join(f"{k}: {v}" for k, v in patientDetails.items())
        ageBuckets = {
            "0-6": studentDataDf[
                (studentDataDf["patient_age"] >= 0) & (studentDataDf["patient_age"] <= 6)
            ].shape[0],
            "7-17": studentDataDf[
                (studentDataDf["patient_age"] >= 7) & (studentDataDf["patient_age"] <= 17)
            ].shape[0],
            "18+": studentDataDf[studentDataDf["patient_age"] >= 18].shape[0],
        }
        ageCountsText = "<br/> ".join(f"{k}: {v}" for k, v in ageBuckets.items())
        summaryDf = pd.concat([
            summaryDf,
            pd.DataFrame({
                "Metric": ["Mean Patient Age", " Patient age distribution", "Role Counts", "Patient Details"],
                "": [
                    f"{meanAge:.2f}" if not np.isnan(meanAge) else "N/A",
                    ageCountsText, roleCountsText, patientDetailsText,
                ],
            }),
        ], ignore_index=True)

    summaryTable = createTable(
        summaryDf, title="Summary", colRatio=[2, 1], customTextCols=[0, 1],
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
    elements.append(PageBreak())

    # Time series plot of scores
    timeSeriesDf = studentDataDf[
        ["datetimeutc", "entrustment", "global_rating", "item_codes", "scores", "assessor_data", "assessor_name"]
    ].copy()
    timeSeriesDf["Date"] = timeSeriesDf["datetimeutc"]
    fig = plotStudentScoresTimeSeries(timeSeriesDf, dateCol="Date", scoreDictCol="scores",
                                      scoreKey="score", fallbackKey=None,
                                      title="Performance on Assessed Items Over Time")
    if fig is not None:
        timeSeriesImg = addPlotImage(fig)
        elements.append(Spacer(1, 24))
        elements.append(Paragraph("Performance Over Time", subheadingStyle))
        elements.append(timeSeriesImg)

    # Rubric plots for entrustment and global rating
    fig, axes = plt.subplots(2, 1, figsize=(14, 6))
    rubricPlotDf = studentDataDf[["datetimeutc", "entrustment", "global_rating"]].copy()
    rubricPlotDf.rename(columns={
        "datetimeutc": "Date", "entrustment": "Entrustment", "global_rating": "Global Rating",
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
    elements.append(Spacer(1, 24))
    elements.append(Paragraph("Entrustment and Global Rating Over Time", subheadingStyle))
    elements.append(rubricImg)

    # Reflections table
    reflectionsDf = studentDataDf[
        ["datetimeutc", "role", "student_reflection", "assessor_reflection"]
    ].copy()
    reflectionsDf["student_reflection"] = reflectionsDf["student_reflection"].apply(truncateText).str.replace("\n", "<br/>")
    reflectionsDf["assessor_reflection"] = reflectionsDf["assessor_reflection"].apply(truncateText).str.replace("\n", "<br/>")
    reflectionsDf.columns = ["Date", "Role", "Student Reflection", "Assessor Reflection"]
    reflectionsDf = reflectionsDf.sort_values("Date")
    reflectionsDf["Date"] = reflectionsDf["Date"].dt.strftime("%Y-%m-%d")
    reflectionsTable = createTable(
        reflectionsDf, title="Reflections", colRatio=[1.2, 1, 5, 5],
        customTextCols=[0, 1, 2, 3], titleStyle=subheadingStyle,
        tableTextStyle=tableTextStyleSmall, headerColor=uniColor,
        bottomPadding=6, topPadding=6,
    )
    elements.append(reflectionsTable)
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
    # studentIds = ['1678748', '1684643', '1362959', '1309866', '1362803', '1346824']
    # studentIds = [int(id) for id in studentIds]
    for studentNumber in studentIds:
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
            uniColor=uniColor,
        )
        doc.build(
            elements,
            onFirstPage=getBannerDrawer("Till Date performance report",
                                         f"{studentName} ({studentNumber})"),
        )
        print(f"Report saved to {filename}\n")
