"""
dcd_skills_utils.py — DCD (Endo) non-clinical skills forms: Case Report, Lit Review, Seminar Skills.

Qualtrics exports (3 header rows) -> cleaned long table -> (a) styled Excel workbook per form,
(b) per-student PDF reports (one combined PDF across all forms, or one PDF per form).

Public entry points (called from DCD.ipynb, "Other reports" section):
    loadDcdSkillsForm(source, formKey)          -> cleaned DataFrame for one form
    loadAllDcdSkillsForms(sources)              -> {formKey: cleaned df}, DCD Year harmonised across forms
    buildDcdSkillsWorkbook(df, formKey, outPath) -> styled xlsx (Summary / Forms / Comments / Excluded / Colour Key)
    buildDcdSkillsReports(formDfs, outFolder, combined=True, separate=False, students=None)
    buildDcdSkillsStudentPdf(formDfs, studentName, outFolder, mode='combined'|'separate')

Conventions: camelCase, no leading underscore on anything a notebook cell calls, openpyxl names that
collide with reportlab are aliased _Xl*.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from io import BytesIO

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether, Image, HRFlowable)
from reportlab.graphics.shapes import Drawing, Rect, String
from xml.sax.saxutils import escape

from openpyxl.styles import PatternFill as _XlPatternFill, Font as _XlFont, Alignment as _XlAlignment, \
    Border as _XlBorder, Side as _XlSide
from openpyxl.utils import get_column_letter

import variableUtils

try:
    from Utils import getBannerDrawer           # Windows kernel: reuse the shared banner
except Exception:                               # Utils.py needs win32com / Windows paths; local fallback keeps the same look
    def getBannerDrawer(firstline, secondline, bannerHeight=132):
        def drawBanner(canvas, doc):
            canvas.saveState()
            pageWidth, pageHeight = doc.pagesize
            canvas.setFillColor(colors.HexColor(variableUtils.uniColor))
            canvas.rect(0, pageHeight - bannerHeight, pageWidth, bannerHeight, fill=1, stroke=0)
            canvas.setFillColor(colors.white)
            try: canvas.setFont('Calibri-Bold', 30)
            except Exception: canvas.setFont('Helvetica-Bold', 30)
            canvas.drawString(variableUtils.leftMargin, pageHeight - 72, f"{firstline}")
            try: canvas.setFont('Calibri-Bold', 24)
            except Exception: canvas.setFont('Helvetica-Bold', 24)
            canvas.drawString(variableUtils.leftMargin, pageHeight - 108, f"{secondline}")
            canvas.restoreState()
        return drawBanner

# ═══════════════════════════════════════════════════════════════════════════
# 1. Configuration
# ═══════════════════════════════════════════════════════════════════════════
FORM_SPECS = {
    'Case Report':    dict(file='DCD/CaseReport.xlsx',    overallPrefix='Overall case skills'),
    'Lit Review':     dict(file='DCD/LitReview.xlsx',     overallPrefix='Overall literature review skills'),
    'Seminar Skills': dict(file='DCD/SeminarSkills.xlsx', overallPrefix='Overall seminar skills'),
}
FORM_ORDER = list(FORM_SPECS)
PROGRAM_NAME = 'DCD Endo'

# Overall % bands — from the rating-scale text printed in the Qualtrics header
OVERALL_BANDS = [  # (lower, upper, band)
    (0, 49, 'Fail'), (50, 64, 'Marginal'), (65, 69, 'Fair'),
    (70, 74, 'Good'), (75, 79, 'Very good'), (80, 100, 'Excellent'),
]
# Domain rating levels (label text in the export is "<n>-<name>")
LEVEL_NAMES = {0: 'Fail', 1: 'Marginal', 2: 'Fair', 3: 'Good', 4: 'Very good', 5: 'Excellent'}

# Colour-blind-safe ramp (Okabe–Ito) for the PDF: 0 → 5
LEVEL_COLORS_PDF = {0: '#D55E00', 1: '#E69F00', 2: '#F0E442', 3: '#56B4E9', 4: '#0072B2', 5: '#009E73'}
BAND_COLORS_PDF = {'Fail': '#D55E00', 'Marginal': '#E69F00', 'Fair': '#F0E442',
                   'Good': '#56B4E9', 'Very good': '#0072B2', 'Excellent': '#009E73'}
TILE_COLORS = {**BAND_COLORS_PDF, 'Fair': '#9C8B00', 'Good': '#2F86B8'}   # darker shades for big numbers on light tiles
DARK_TEXT_LEVELS = (2, 3)                  # light fills -> dark text for contrast
DARK_TEXT_BANDS = ('Fair', 'Good')
FORM_SERIES_COLORS = {'Case Report': variableUtils.uniColor, 'Lit Review': '#E69F00', 'Seminar Skills': '#009E73'}

# Excel palette — same scheme as flagging_utils / general_utils
XL_NAVY, XL_WHITE = '010D44', 'FFFFFF'
XL_LEVEL_FILLS = {  # level -> (bg, text); 3 = plain so the sheet does not wash out
    0: ('FFC7CE', '9C0006'), 1: ('FFEB9C', '9C6500'), 2: ('FFF2CC', '7F6000'),
    4: ('E2EFDA', '375623'), 5: ('C6EFCE', '276221'),
}
XL_BAND_FILLS = {'Fail': ('FFC7CE', '9C0006'), 'Marginal': ('FFEB9C', '9C6500'), 'Fair': ('FFF2CC', '7F6000'),
                 'Very good': ('E2EFDA', '375623'), 'Excellent': ('C6EFCE', '276221')}
XL_PLACEHOLDER_FILL = 'DDEBF7'   # light blue — placeholder assessor rows (info only)
XL_MID_GREY = 'D9D9D9'

# Cleaning defaults (override via cleanConfig=dict(...))
DEFAULT_CLEAN_CONFIG = dict(
    minDate='2026-02-25',               # anything earlier is a form-build test entry
    dropAnonymousChannel=False,         # Jul/Aug 2026 real assessments came in via the anonymous link — keep; minDate catches the Jan tests
    testAssessors=(),                   # extra assessor strings to treat as test rows
    placeholderAssessors=('ABC',),      # kept, but flagged (bulk baseline entries on 25 Feb 2026)
)
ASSESSOR_ALIASES = {
    'm. evans': 'Mark Evans', 'evans': 'Mark Evans', 'm evans': 'Mark Evans',
    'moragn wu': 'Morgan Wu',
}

# Standard cleaned column names
C_FORM, C_RID, C_STATUS, C_FIN, C_CHAN = 'Form', 'Response ID', 'Response Type', 'Finished', 'Channel'
C_SEM, C_YEAR_RAW, C_YEAR, C_DATE, C_DATE_TXT = 'Semester', 'DCD Year (form)', 'DCD Year', 'Date', 'Date (text)'
C_STUDENT, C_ASSESSOR_RAW, C_ASSESSOR = 'Student Name', 'Assessor (as entered)', 'Assessor'
C_OVERALL, C_BAND, C_AREAS, C_PLACEHOLDER, C_REASON = 'Overall %', 'Overall Band', 'Areas for Improvement', 'Placeholder Assessor', 'Excluded Reason'


# ═══════════════════════════════════════════════════════════════════════════
# 2. Loading + cleaning
# ═══════════════════════════════════════════════════════════════════════════
def overallBand(value):
    """0-100 overall % -> band name per OVERALL_BANDS (None if blank)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for lo, hi, band in OVERALL_BANDS:
        if lo <= v <= hi:
            return band
    return 'Fail' if v < 0 else 'Excellent'


def ratingToLevel(label):
    """'4-Very good' -> 4 ; blank/unparseable -> NaN."""
    if label is None or (isinstance(label, float) and np.isnan(label)):
        return np.nan
    m = re.match(r'\s*(\d+)', str(label))
    return int(m.group(1)) if m else np.nan


def cleanDomainName(label):
    """'Evaluation - Rating - ii. Treatment Planning\\n...' -> ('Treatment Planning', weight or None)."""
    txt = str(label).split(' - ', 2)[-1].split('\n')[0].strip()
    weight = None
    m = re.search(r'\((\d+)\s*%\)', txt)
    if m:
        weight = int(m.group(1))
        txt = txt[:m.start()].strip()
    txt = re.sub(r'^[ivxIVX]+\.\s*', '', txt)       # strip leading roman numerals "ii. " / "III. "
    txt = txt.rstrip('.').strip()
    return txt, weight


def normaliseAssessor(name):
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return None
    s = re.sub(r'\s+', ' ', str(name)).strip()
    return ASSESSOR_ALIASES.get(s.lower(), s)


def splitQualtricsFrame(source):
    """Accept an xlsx path (3 header rows) or a live Responses() df (2 label rows) and return
    (ids, labels, data) where data has the Qualtrics column IDs as columns."""
    if isinstance(source, (str, os.PathLike)):
        raw = pd.read_excel(source, header=None)
        ids, labels, data = raw.iloc[0].tolist(), raw.iloc[1].tolist(), raw.iloc[3:].copy()
    else:
        df = source
        ids = list(df.columns)
        labels = df.iloc[0].tolist()
        data = df.iloc[2:].copy() if str(df.iloc[1].iloc[0]).startswith('{') else df.iloc[1:].copy()
    data.columns = ids
    data = data.reset_index(drop=True)
    return ids, labels, data


def getDomainMap(ids, labels):
    """Pair Rating#1_k (rating) with Rating#2_k_1 (comment) using the ID row -> ordered list of dicts."""
    labelById = dict(zip(ids, labels))
    domains = []
    for cid in ids:
        m = re.fullmatch(r'Rating#1_(\d+)', str(cid))
        if not m:
            continue
        k = m.group(1)
        name, weight = cleanDomainName(labelById[cid])
        commentId = f'Rating#2_{k}_1'
        domains.append(dict(key=k, name=name, weight=weight, ratingId=cid,
                            commentId=commentId if commentId in labelById else None))
    return domains


def parseFormDate(series, fallback=None):
    d = pd.to_datetime(series.astype(str).str.strip(), format='%d %b %Y', errors='coerce')
    miss = d.isna()
    if miss.any():
        d[miss] = pd.to_datetime(series[miss], errors='coerce', dayfirst=True)
    if fallback is not None:
        miss = d.isna()
        if miss.any():
            d[miss] = pd.to_datetime(fallback[miss], errors='coerce').dt.normalize()
    return d


def loadDcdSkillsForm(source, formKey, cleanConfig=None, verbose=True):
    """One form -> cleaned df (all rows kept; excluded rows carry a non-empty `Excluded Reason`).
    `source` = xlsx path (default FORM_SPECS[formKey]['file']) or the live Responses() dataframe."""
    cfg = {**DEFAULT_CLEAN_CONFIG, **(cleanConfig or {})}
    if source is None:
        source = FORM_SPECS[formKey]['file']
    ids, labels, data = splitQualtricsFrame(source)
    labelById = dict(zip(ids, labels))
    domains = getDomainMap(ids, labels)

    def colByLabelPrefix(prefix):
        for cid, lab in labelById.items():
            if str(lab).startswith(prefix):
                return cid
        return None

    idSem, idYear, idDate = colByLabelPrefix('Semester'), colByLabelPrefix('DCD Year'), colByLabelPrefix('Date')
    idStudent, idAssessor = colByLabelPrefix('Student Name'), colByLabelPrefix('Assessor Name')
    idOverall = colByLabelPrefix(FORM_SPECS[formKey]['overallPrefix']) or colByLabelPrefix('Overall')
    idAreas = colByLabelPrefix('Areas for improvement')

    out = pd.DataFrame({
        C_FORM: formKey,
        C_RID: data.get('ResponseId'),
        C_STATUS: data.get('Status'),
        C_FIN: data.get('Finished').astype(str).str.strip().str.lower().eq('true'),
        C_CHAN: data.get('DistributionChannel'),
        C_SEM: pd.to_numeric(data.get(idSem), errors='coerce').astype('Int64'),
        C_YEAR_RAW: pd.to_numeric(data.get(idYear), errors='coerce').astype('Int64'),
        C_DATE_TXT: data.get(idDate),
        C_STUDENT: data.get(idStudent).astype(str).str.strip().replace({'nan': None, 'None': None}),
        C_ASSESSOR_RAW: data.get(idAssessor),
    })
    out[C_DATE] = parseFormDate(out[C_DATE_TXT], fallback=data.get('RecordedDate'))
    out[C_ASSESSOR] = out[C_ASSESSOR_RAW].map(normaliseAssessor)
    out[C_YEAR] = out[C_YEAR_RAW]                                   # harmonised later across forms
    for d in domains:
        out[f"{d['name']} Rating"] = data[d['ratingId']].map(ratingToLevel).astype('Int64')
        out[f"{d['name']} Comment"] = data[d['commentId']] if d['commentId'] else None
    out[C_OVERALL] = pd.to_numeric(data.get(idOverall), errors='coerce')
    out[C_BAND] = out[C_OVERALL].map(overallBand)
    out[C_AREAS] = data.get(idAreas)
    out[C_PLACEHOLDER] = out[C_ASSESSOR].isin(cfg['placeholderAssessors'])

    # ── exclusion reasons (first match wins, in this order) ──
    reason = pd.Series([None] * len(out), index=out.index, dtype=object)
    def setReason(mask, text):
        m = mask.fillna(False) & reason.isna()
        reason[m] = text
    setReason(out[C_STATUS].astype(str).str.strip() != 'IP Address', 'Survey preview')
    setReason(~out[C_FIN], 'Incomplete (Finished = False)')
    if cfg['dropAnonymousChannel']:
        setReason(out[C_CHAN].astype(str).str.lower() == 'anonymous', 'Anonymous channel (test)')
    if cfg['minDate']:
        setReason(out[C_DATE] < pd.Timestamp(cfg['minDate']), f"Before first session {cfg['minDate']} (test entry)")
    if cfg['testAssessors']:
        setReason(out[C_ASSESSOR].isin(cfg['testAssessors']), 'Test assessor')
    setReason(out[C_STUDENT].isna() | (out[C_STUDENT] == ''), 'No student name')
    setReason(out[C_DATE].isna(), 'Unparseable date')
    out[C_REASON] = reason
    out.attrs['domains'] = domains
    out.attrs['formKey'] = formKey

    if verbose:
        kept = out[C_REASON].isna().sum()
        print(f"[{formKey}] {len(out)} rows -> {kept} kept, {len(out) - kept} excluded "
              f"{dict(Counter(out[C_REASON].dropna()))}; students={out.loc[out[C_REASON].isna(), C_STUDENT].nunique()}, "
              f"domains={[d['name'] for d in domains]}")
    return out


def harmoniseDcdYear(formDfs):
    """DCD Year is typed by the assessor and disagrees within a student; use the modal value across
    all forms (kept rows only) and write it to `DCD Year`; the entered value stays in `DCD Year (form)`."""
    allKept = pd.concat([df[df[C_REASON].isna()][[C_STUDENT, C_YEAR_RAW]] for df in formDfs.values()])
    modal = (allKept.dropna().groupby(C_STUDENT)[C_YEAR_RAW]
             .agg(lambda s: s.value_counts().idxmax()))
    for df in formDfs.values():
        df[C_YEAR] = df[C_STUDENT].map(modal).astype('Int64').fillna(df[C_YEAR_RAW])
    return modal.to_dict()


def loadAllDcdSkillsForms(sources=None, cleanConfig=None, verbose=True):
    """sources: {formKey: path-or-df}; None -> FORM_SPECS files. Returns {formKey: cleaned df}."""
    sources = sources or {k: v['file'] for k, v in FORM_SPECS.items()}
    formDfs = {k: loadDcdSkillsForm(sources[k], k, cleanConfig, verbose) for k in FORM_ORDER if k in sources}
    years = harmoniseDcdYear(formDfs)
    if verbose:
        print(f"[DCD Year] modal per student: {years}")
    return formDfs


def keptRows(df):
    return df[df[C_REASON].isna()].copy()


def domainNames(df):
    return [d['name'] for d in df.attrs.get('domains', [])]


def fmtDate(ts):
    return '' if pd.isna(ts) else pd.Timestamp(ts).strftime('%-d %b %Y') if os.name != 'nt' else pd.Timestamp(ts).strftime('%#d %b %Y')


def fmtDateShort(ts):
    return '' if pd.isna(ts) else pd.Timestamp(ts).strftime('%-d %b') if os.name != 'nt' else pd.Timestamp(ts).strftime('%#d %b')


# ═══════════════════════════════════════════════════════════════════════════
# 3. Summary tables (shared by Excel + PDF)
# ═══════════════════════════════════════════════════════════════════════════
def studentSummary(df):
    """Per-student summary for one form (kept rows only)."""
    k = keptRows(df).sort_values([C_STUDENT, C_DATE])
    doms = domainNames(df)
    rows = []
    for name, g in k.groupby(C_STUDENT, sort=True):
        latest = g.iloc[-1]
        row = {
            C_STUDENT: name, C_YEAR: g[C_YEAR].iloc[0], 'Forms': len(g),
            'First Date': g[C_DATE].min(), 'Last Date': g[C_DATE].max(),
            'Assessors': g[C_ASSESSOR].nunique(),
            'Overall Mean': round(g[C_OVERALL].mean(), 1), 'Overall Min': g[C_OVERALL].min(),
            'Overall Max': g[C_OVERALL].max(), 'Latest Overall': latest[C_OVERALL],
            'Latest Band': overallBand(latest[C_OVERALL]),
            'Overall Trend': overallTrend(g[C_OVERALL]),
        }
        for d in doms:
            row[f'{d} Mean'] = round(g[f'{d} Rating'].astype(float).mean(), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def overallTrend(series, tol=2.0):
    """Last minus first overall % -> 'Improving' / 'Stable' / 'Declining' (needs >= 2 values)."""
    v = series.dropna().astype(float)
    if len(v) < 2:
        return ''
    delta = v.iloc[-1] - v.iloc[0]
    return 'Improving' if delta > tol else 'Declining' if delta < -tol else 'Stable'


def commentsLong(df):
    """One row per non-empty comment: Student, Date, Assessor, Domain, Rating, Comment."""
    k = keptRows(df).sort_values([C_STUDENT, C_DATE])
    rows = []
    for _, r in k.iterrows():
        for d in domainNames(df):
            c = r.get(f'{d} Comment')
            if isinstance(c, str) and c.strip():
                rows.append([r[C_STUDENT], r[C_DATE], r[C_ASSESSOR], d, r[f'{d} Rating'], c.strip()])
        a = r.get(C_AREAS)
        if isinstance(a, str) and a.strip():
            rows.append([r[C_STUDENT], r[C_DATE], r[C_ASSESSOR], 'Areas for improvement', r[C_OVERALL], a.strip()])
    return pd.DataFrame(rows, columns=[C_STUDENT, C_DATE, C_ASSESSOR, 'Domain', 'Rating / Overall', 'Comment'])


# ═══════════════════════════════════════════════════════════════════════════
# 4. Excel workbook per form
# ═══════════════════════════════════════════════════════════════════════════
def xlFill(hexColor):
    return _XlPatternFill(start_color=hexColor, end_color=hexColor, fill_type='solid')


def xlBorder():
    s = _XlSide(style='thin', color=XL_MID_GREY)
    return _XlBorder(left=s, right=s, top=s, bottom=s)


XL_HEADER_FONT = _XlFont(name='Arial', bold=True, color=XL_WHITE, size=10)
XL_BODY_FONT = _XlFont(name='Arial', size=9)
XL_TITLE_FONT = _XlFont(name='Arial', bold=True, size=14, color=XL_WHITE)


def xlTitleBand(ws, row, nCols, text):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=nCols)
    c = ws.cell(row=row, column=1, value=text)
    c.font, c.fill = XL_TITLE_FONT, xlFill(XL_NAVY)
    c.alignment = _XlAlignment(horizontal='left', vertical='center', indent=1)
    ws.row_dimensions[row].height = 28


def xlWriteFrame(ws, df, startRow, title=None, widths=None, wrapCols=(), dateCols=()):
    """Write df with navy headers at startRow (title band above if given). Returns header row index."""
    nCols = max(len(df.columns), 1)
    r = startRow
    if title:
        xlTitleBand(ws, r, nCols, title)
        r += 1
    for j, col in enumerate(df.columns, start=1):
        c = ws.cell(row=r, column=j, value=str(col))
        c.font, c.fill, c.border = XL_HEADER_FONT, xlFill(XL_NAVY), xlBorder()
        c.alignment = _XlAlignment(horizontal='center', vertical='center', wrap_text=True)
    ws.row_dimensions[r].height = 32
    headerRow = r
    for i, (_, rec) in enumerate(df.iterrows(), start=1):
        for j, col in enumerate(df.columns, start=1):
            v = rec[col]
            if isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            elif v is pd.NA or (isinstance(v, float) and np.isnan(v)):
                v = None
            elif isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating,)):
                v = float(v)
            elif isinstance(v, (np.bool_, bool)):
                v = 'Yes' if v else 'No'
            c = ws.cell(row=headerRow + i, column=j, value=v)
            c.font, c.border = XL_BODY_FONT, xlBorder()
            c.alignment = _XlAlignment(horizontal='left' if col in wrapCols else 'center',
                                       vertical='top' if col in wrapCols else 'center',
                                       wrap_text=col in wrapCols)
            if col in dateCols and v is not None:
                c.number_format = 'DD MMM YYYY'
    for j, col in enumerate(df.columns, start=1):
        w = (widths or {}).get(col, max(10, min(28, len(str(col)) + 2)))
        ws.column_dimensions[get_column_letter(j)].width = w
    if len(df):
        ws.auto_filter.ref = f"A{headerRow}:{get_column_letter(nCols)}{headerRow + len(df)}"
    return headerRow


def meanToLevelKey(m):
    """Mean rating -> level key for colouring: floor, except >= 4.75 counts as 5 (3.5 stays plain 'Good')."""
    return 5 if m >= 4.75 else int(np.floor(m))


def xlColourLevels(ws, df, headerRow, cols, fills=XL_LEVEL_FILLS, isMean=False):
    for col in cols:
        if col not in df.columns:
            continue
        j = list(df.columns).index(col) + 1
        for i in range(len(df)):
            c = ws.cell(row=headerRow + 1 + i, column=j)
            if c.value is None:
                c.fill = xlFill('F2F2F2'); continue
            key = meanToLevelKey(float(c.value)) if isMean else int(c.value)
            if key in fills:
                bg, fg = fills[key]
                c.fill, c.font = xlFill(bg), _XlFont(name='Arial', size=9, color=fg, bold=(key <= 1))


def xlColourBands(ws, df, headerRow, cols):
    for col in cols:
        if col not in df.columns:
            continue
        j = list(df.columns).index(col) + 1
        for i in range(len(df)):
            c = ws.cell(row=headerRow + 1 + i, column=j)
            band = c.value if isinstance(c.value, str) else overallBand(c.value)
            if band in XL_BAND_FILLS:
                bg, fg = XL_BAND_FILLS[band]
                c.fill, c.font = xlFill(bg), _XlFont(name='Arial', size=9, color=fg, bold=band in ('Fail', 'Marginal'))


def xlShadeRows(ws, df, headerRow, mask, color, firstCols=3):
    """Light shading of the first few identity columns for rows where mask is True."""
    for i, flag in enumerate(mask):
        if flag:
            for j in range(1, firstCols + 1):
                ws.cell(row=headerRow + 1 + i, column=j).fill = xlFill(color)


def buildDcdSkillsWorkbook(df, formKey=None, outPath=None, verbose=True):
    """Styled workbook for one form: Summary / Forms / Comments / Excluded / Colour Key."""
    formKey = formKey or df.attrs.get('formKey')
    outPath = outPath or f"DCD/Skills/DCD_{formKey.replace(' ', '')}_cleaned.xlsx"
    os.makedirs(os.path.dirname(outPath) or '.', exist_ok=True)
    doms = domainNames(df)
    kept = keptRows(df).sort_values([C_STUDENT, C_DATE]).reset_index(drop=True)

    from openpyxl import Workbook
    wb = Workbook()

    # ── Summary ──
    ws = wb.active; ws.title = 'Summary'
    summ = studentSummary(df)
    summCols = [C_STUDENT, C_YEAR, 'Forms', 'First Date', 'Last Date', 'Assessors', 'Overall Mean', 'Overall Min',
                'Overall Max', 'Latest Overall', 'Latest Band', 'Overall Trend'] + [f'{d} Mean' for d in doms]
    summ = summ[summCols] if len(summ) else pd.DataFrame(columns=summCols)
    hr = xlWriteFrame(ws, summ, 1, title=f"{PROGRAM_NAME} — {formKey}: per-student summary ({len(kept)} forms, {summ.shape[0]} students)",
                      widths={C_STUDENT: 22, 'First Date': 13, 'Last Date': 13, **{f'{d} Mean': 14 for d in doms}},
                      dateCols=('First Date', 'Last Date'))
    xlColourBands(ws, summ, hr, ['Overall Mean', 'Overall Min', 'Overall Max', 'Latest Overall', 'Latest Band'])
    xlColourLevels(ws, summ, hr, [f'{d} Mean' for d in doms], isMean=True)
    for i in range(len(summ)):   # trend colouring
        c = ws.cell(row=hr + 1 + i, column=summCols.index('Overall Trend') + 1)
        if c.value == 'Declining':
            c.fill, c.font = xlFill('FFC7CE'), _XlFont(name='Arial', size=9, color='9C0006', bold=True)
        elif c.value == 'Improving':
            c.fill, c.font = xlFill('C6EFCE'), _XlFont(name='Arial', size=9, color='276221')
    ws.freeze_panes = f"B{hr + 1}"

    # ── Forms (one row per completed form) ──
    ws = wb.create_sheet('Forms')
    formCols = ([C_STUDENT, C_YEAR, C_DATE, C_ASSESSOR, C_SEM] + [f'{d} Rating' for d in doms]
                + [C_OVERALL, C_BAND] + [f'{d} Comment' for d in doms] + [C_AREAS, C_PLACEHOLDER, C_YEAR_RAW, C_ASSESSOR_RAW, C_RID])
    forms = kept[formCols]
    widths = {C_STUDENT: 22, C_DATE: 13, C_ASSESSOR: 20, **{f'{d} Rating': 12 for d in doms},
              **{f'{d} Comment': 45 for d in doms}, C_AREAS: 55, C_ASSESSOR_RAW: 18, C_RID: 20}
    hr = xlWriteFrame(ws, forms, 1, title=f"{PROGRAM_NAME} — {formKey}: completed forms (ratings 0=Fail … 5=Excellent)",
                      widths=widths, wrapCols=tuple(f'{d} Comment' for d in doms) + (C_AREAS,), dateCols=(C_DATE,))
    xlColourLevels(ws, forms, hr, [f'{d} Rating' for d in doms])
    xlColourBands(ws, forms, hr, [C_OVERALL, C_BAND])
    xlShadeRows(ws, forms, hr, forms[C_PLACEHOLDER].tolist(), XL_PLACEHOLDER_FILL, firstCols=4)
    ws.freeze_panes = f"E{hr + 1}"

    # ── Comments (long) ──
    ws = wb.create_sheet('Comments')
    com = commentsLong(df)
    hr = xlWriteFrame(ws, com, 1, title=f"{PROGRAM_NAME} — {formKey}: all assessor comments",
                      widths={C_STUDENT: 22, C_DATE: 13, C_ASSESSOR: 20, 'Domain': 24, 'Rating / Overall': 12, 'Comment': 90},
                      wrapCols=('Comment',), dateCols=(C_DATE,))
    for i in range(len(com)):
        c = ws.cell(row=hr + 1 + i, column=5)
        if com['Domain'].iloc[i] == 'Areas for improvement':
            band = overallBand(c.value)
            if band in XL_BAND_FILLS:
                c.fill = xlFill(XL_BAND_FILLS[band][0])
        elif c.value is not None and int(c.value) in XL_LEVEL_FILLS:
            c.fill = xlFill(XL_LEVEL_FILLS[int(c.value)][0])
    ws.freeze_panes = f"A{hr + 1}"

    # ── Excluded ──
    ws = wb.create_sheet('Excluded')
    exc = df[df[C_REASON].notna()][[C_REASON, C_STUDENT, C_DATE_TXT, C_ASSESSOR_RAW, C_STATUS, C_FIN, C_CHAN, C_OVERALL, C_RID]]
    hr = xlWriteFrame(ws, exc, 1, title=f"Excluded rows ({len(exc)}) — not used in any summary or report",
                      widths={C_REASON: 38, C_STUDENT: 22, C_DATE_TXT: 14, C_ASSESSOR_RAW: 18, C_RID: 20})
    ws.freeze_panes = f"A{hr + 1}"

    # ── Colour Key ──
    ws = wb.create_sheet('Colour Key')
    xlTitleBand(ws, 1, 3, 'Colour key')
    r = 3
    ws.cell(row=r, column=1, value='Domain rating').font = _XlFont(name='Arial', bold=True, size=10); r += 1
    for lvl in range(6):
        c = ws.cell(row=r, column=1, value=f"{lvl} - {LEVEL_NAMES[lvl]}"); c.font = XL_BODY_FONT
        if lvl in XL_LEVEL_FILLS:
            c.fill = xlFill(XL_LEVEL_FILLS[lvl][0]); c.font = _XlFont(name='Arial', size=9, color=XL_LEVEL_FILLS[lvl][1])
        r += 1
    r += 1
    ws.cell(row=r, column=1, value='Overall % band').font = _XlFont(name='Arial', bold=True, size=10); r += 1
    for lo, hi, band in OVERALL_BANDS:
        c = ws.cell(row=r, column=1, value=f"{lo}-{hi}  {band}"); c.font = XL_BODY_FONT
        if band in XL_BAND_FILLS:
            c.fill = xlFill(XL_BAND_FILLS[band][0]); c.font = _XlFont(name='Arial', size=9, color=XL_BAND_FILLS[band][1])
        r += 1
    r += 1
    c = ws.cell(row=r, column=1, value='Placeholder assessor (e.g. "ABC") — kept, identity columns shaded'); c.font = XL_BODY_FONT
    c.fill = xlFill(XL_PLACEHOLDER_FILL); r += 1
    c = ws.cell(row=r, column=1, value='Blank rating — not assessed'); c.font = XL_BODY_FONT; c.fill = xlFill('F2F2F2'); r += 2
    ws.cell(row=r, column=1, value='Cleaning rules').font = _XlFont(name='Arial', bold=True, size=10); r += 1
    for line in ['Survey Preview rows dropped', 'Finished = False dropped',
                 f"Dated before {DEFAULT_CLEAN_CONFIG['minDate']} dropped (form-build tests)",
                 'Anonymous-link submissions kept (Jul/Aug 2026 real assessments used that link)',
                 'Assessor names normalised (M. Evans / Evans -> Mark Evans, Moragn Wu -> Morgan Wu)',
                 'DCD Year = modal value per student across all three forms; as-entered value kept in "DCD Year (form)"']:
        ws.cell(row=r, column=1, value='• ' + line).font = XL_BODY_FONT; r += 1
    ws.column_dimensions['A'].width = 95

    wb.save(outPath)
    if verbose:
        print(f"[{formKey}] workbook -> {outPath}  (Forms={len(kept)}, Comments={len(com)}, Excluded={len(exc)})")
    return outPath


# ═══════════════════════════════════════════════════════════════════════════
# 5. PDF building blocks
# ═══════════════════════════════════════════════════════════════════════════
PAGE_SIZE = variableUtils.pageSize
LM, RM, TM, BM = variableUtils.leftMargin, variableUtils.rightMargin, variableUtils.topMargin, variableUtils.bottomMargin
CONTENT_W = PAGE_SIZE[0] - LM - RM
NAVY = colors.HexColor(variableUtils.uniColor)
TEXT = colors.HexColor(variableUtils.textcolor)
GREY = colors.HexColor('#6f6f6f')
LIGHT = colors.HexColor('#f3f4f8')

stSection = ParagraphStyle('dcdSection', fontName='Helvetica-Bold', fontSize=20, leading=24, textColor=colors.white)
stSectionSub = ParagraphStyle('dcdSectionSub', fontName='Helvetica', fontSize=11, leading=14, textColor=colors.HexColor('#dfe3f2'))
stH2 = ParagraphStyle('dcdH2', fontName='Helvetica-Bold', fontSize=15, leading=19, textColor=NAVY, spaceBefore=10, spaceAfter=6)
stBody = ParagraphStyle('dcdBody', fontName='Helvetica', fontSize=10.5, leading=14, textColor=colors.HexColor('#222222'))
stBodyGrey = ParagraphStyle('dcdBodyGrey', parent=stBody, textColor=GREY, fontSize=9.5, leading=12)
stCell = ParagraphStyle('dcdCell', fontName='Helvetica', fontSize=9.5, leading=12, textColor=colors.HexColor('#222222'))
stCellB = ParagraphStyle('dcdCellB', parent=stCell, fontName='Helvetica-Bold')
stCellW = ParagraphStyle('dcdCellW', parent=stCell, fontName='Helvetica-Bold', textColor=colors.white, alignment=TA_CENTER)
stTileNum = ParagraphStyle('dcdTileNum', fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=NAVY, alignment=TA_CENTER)
stTileLab = ParagraphStyle('dcdTileLab', fontName='Helvetica', fontSize=9, leading=11, textColor=GREY, alignment=TA_CENTER)


def P(text, style=stCell):
    return Paragraph(escape('' if text is None else str(text)).replace('\n', '<br/>'), style)


def sectionBand(title, subtitle=''):
    """Full-width navy band used to open each form section."""
    inner = [[P(title, stSection)], [P(subtitle, stSectionSub)]] if subtitle else [[P(title, stSection)]]
    t = Table(inner, colWidths=[CONTENT_W])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), NAVY), ('LEFTPADDING', (0, 0), (-1, -1), 14),
                           ('TOPPADDING', (0, 0), (0, 0), 12), ('BOTTOMPADDING', (0, -1), (0, -1), 12),
                           ('TOPPADDING', (0, -1), (0, -1), 0 if subtitle else 12)]))
    return t


def statTiles(items):
    """items: list of (value, label, hexColor|None). Renders a row of equal tiles."""
    n = len(items)
    cells, styleCmds = [], [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 10),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]
    for i, (val, lab, col) in enumerate(items):
        size = 22 if len(str(val)) <= 6 else 17 if len(str(val)) <= 9 else 14
        numStyle = ParagraphStyle(f'tile{i}', parent=stTileNum, fontSize=size, leading=size + 4,
                                  textColor=colors.HexColor(col) if col else NAVY)
        cells.append([P(val, numStyle), P(lab, stTileLab)])
        styleCmds += [('BACKGROUND', (i, 0), (i, 0), LIGHT), ('BOX', (i, 0), (i, 0), 0.75, colors.HexColor('#d5d9e8'))]
    t = Table([[Table([[c[0]], [c[1]]], colWidths=[CONTENT_W / n - 10]) for c in cells]],
              colWidths=[CONTENT_W / n] * n, hAlign='LEFT')
    t.setStyle(TableStyle(styleCmds))
    return t


def levelLegend(width=CONTENT_W):
    d = Drawing(width, 16)
    x = 0
    for lvl in range(6):
        d.add(Rect(x, 3, 10, 10, fillColor=colors.HexColor(LEVEL_COLORS_PDF[lvl]), strokeColor=colors.HexColor('#444444'), strokeWidth=0.5))
        d.add(String(x + 14, 5, f"{lvl} {LEVEL_NAMES[lvl]}", fontName='Helvetica', fontSize=8, fillColor=GREY))
        x += width / 6
    return d


def levelBar(domainName, levels, dates, assessors, width=CONTENT_W, cellH=22):
    """Chronological segmented bar: one cell per form, coloured by level, level number inside,
    short date underneath. Blank/NaN -> white cell with '–'."""
    n = max(len(levels), 1)
    h = cellH + 40
    d = Drawing(width, h)
    d.add(String(0, h - 12, domainName, fontName='Helvetica-Bold', fontSize=11, fillColor=NAVY))
    vals = [v for v in levels if not pd.isna(v)]
    if vals:
        d.add(String(width, h - 12, f"mean {np.mean(vals):.1f}", fontName='Helvetica', fontSize=9, fillColor=GREY, textAnchor='end'))
    cw = width / n
    y = 16
    for i, (lvl, dt) in enumerate(zip(levels, dates)):
        x = i * cw
        if pd.isna(lvl):
            d.add(Rect(x, y, cw, cellH, fillColor=colors.white, strokeColor=colors.HexColor('#999999'), strokeWidth=0.6))
            d.add(String(x + cw / 2, y + 7, '–', fontName='Helvetica', fontSize=10, fillColor=GREY, textAnchor='middle'))
        else:
            lvl = int(lvl)
            fill = colors.HexColor(LEVEL_COLORS_PDF.get(lvl, '#cccccc'))
            d.add(Rect(x, y, cw, cellH, fillColor=fill, strokeColor=colors.white, strokeWidth=1.2))
            txtCol = colors.black if lvl in DARK_TEXT_LEVELS else colors.white
            d.add(String(x + cw / 2, y + 7, f"{lvl}", fontName='Helvetica-Bold', fontSize=10, fillColor=txtCol, textAnchor='middle'))
        d.add(String(x + cw / 2, 3, fmtDateShort(dt), fontName='Helvetica', fontSize=7.5, fillColor=GREY, textAnchor='middle'))
    d.add(Rect(0, y, width, cellH, fillColor=None, strokeColor=colors.HexColor('#444444'), strokeWidth=0.8))
    return d


def overallChart(series, width=CONTENT_W, height=2.4 * inch, title='Overall % by session'):
    """series: {label: (dates, values, hexColor)}. Band shading from OVERALL_BANDS."""
    fig, ax = plt.subplots(figsize=(width / 72, height / 72), dpi=200)
    bandFills = {'Fail': '#fbe3d6', 'Marginal': '#fdf0d5', 'Fair': '#fcf9d9', 'Good': '#ffffff', 'Very good': '#e6f0f7', 'Excellent': '#dff3ec'}
    for lo, hi, band in OVERALL_BANDS:
        ax.axhspan(lo if lo else 40, hi + 1, color=bandFills[band], zorder=0, lw=0)
        ax.text(1.003, (max(lo, 40) + hi + 1) / 2, band, transform=ax.get_yaxis_transform(), fontsize=6, color='#555555', va='center')
    allDates = []
    for lab, (dates, vals, col) in series.items():
        d = list(dates); v = list(vals)
        allDates += d
        ax.plot(d, v, '-', color=col, lw=1.8, zorder=3, label=lab)
        ax.scatter(d, v, s=28, color=col, edgecolor='white', lw=0.8, zorder=4)
        for x, y in zip(d, v):
            if not pd.isna(y):
                ax.annotate(f"{y:.0f}", (x, y), textcoords='offset points', xytext=(0, 6), ha='center', fontsize=6.5, color=col)
    ax.set_ylim(40, 101)
    if allDates:
        lo, hi = min(allDates), max(allDates)
        pad = max((hi - lo).days * 0.06, 6)
        ax.set_xlim(lo - pd.Timedelta(days=pad), hi + pd.Timedelta(days=pad))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    ax.tick_params(labelsize=7, colors='#444444')
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.set_ylabel('Overall %', fontsize=7.5, color='#444444')
    ax.set_title(title, fontsize=9, color=variableUtils.uniColor, loc='left', fontweight='bold')
    ax.grid(axis='y', color='#dddddd', lw=0.5, zorder=1)
    if len(series) > 1:
        ax.legend(fontsize=7, frameon=False, loc='lower right', ncol=len(series))
    fig.tight_layout()
    buf = BytesIO(); fig.savefig(buf, format='png', bbox_inches='tight', dpi=200); plt.close(fig); buf.seek(0)
    img = Image(buf)
    scale = min(width / img.drawWidth, height * 1.15 / img.drawHeight)
    img.drawWidth *= scale; img.drawHeight *= scale
    img.hAlign = 'LEFT'
    return img


def styledTable(header, rows, colWidths, cellStyles=None, zebra=True, fontSize=9.5):
    """Generic navy-header table. rows = list of lists of Paragraph/str. cellStyles = extra TableStyle cmds."""
    data = [[P(h, stCellW) for h in header]] + rows
    t = Table(data, colWidths=colWidths, repeatRows=1, hAlign='LEFT')
    cmds = [('BACKGROUND', (0, 0), (-1, 0), NAVY), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#cfd3e3')),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#9aa0b8')),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6)]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                cmds.append(('BACKGROUND', (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(cmds + (cellStyles or [])))
    return t


def levelCell(lvl):
    if pd.isna(lvl):
        return P('–', ParagraphStyle('lc', parent=stCell, alignment=TA_CENTER, textColor=GREY))
    lvl = int(lvl)
    col = colors.black if lvl in DARK_TEXT_LEVELS else colors.white
    return P(f"{lvl}", ParagraphStyle(f'lc{lvl}', parent=stCellB, alignment=TA_CENTER, textColor=col))


def ratingsTable(g, doms):
    """Date | Assessor | domain levels (coloured) | Overall % (coloured by band)."""
    header = ['Date', 'Assessor'] + doms + ['Overall %']
    nd = len(doms)
    domW = min(1.05 * inch, (CONTENT_W - 2.9 * inch) / (nd + 1))
    colWidths = [1.0 * inch, 1.9 * inch] + [domW] * nd + [domW]
    rows, cmds = [], []
    for i, (_, r) in enumerate(g.iterrows(), start=1):
        row = [P(fmtDate(r[C_DATE])), P(r[C_ASSESSOR] or '')]
        for j, d in enumerate(doms):
            lvl = r[f'{d} Rating']
            row.append(levelCell(lvl))
            if not pd.isna(lvl):
                cmds.append(('BACKGROUND', (2 + j, i), (2 + j, i), colors.HexColor(LEVEL_COLORS_PDF[int(lvl)])))
        ov = r[C_OVERALL]
        band = overallBand(ov)
        row.append(P('–' if pd.isna(ov) else f"{ov:.0f}", ParagraphStyle('ov', parent=stCellB, alignment=TA_CENTER,
                                                                         textColor=colors.black if band in DARK_TEXT_BANDS else colors.white)))
        if band:
            cmds.append(('BACKGROUND', (2 + nd, i), (2 + nd, i), colors.HexColor(BAND_COLORS_PDF[band])))
        rows.append(row)
    return styledTable(header, rows, colWidths, cellStyles=cmds, zebra=False)


def commentsTable(g, doms):
    """Per-domain assessor comments, one row per (date, domain) with a non-empty comment."""
    rows, cmds = [], []
    for _, r in g.iterrows():
        for d in doms:
            c = r.get(f'{d} Comment')
            if isinstance(c, str) and c.strip():
                lvl = r[f'{d} Rating']
                i = len(rows) + 1
                rows.append([P(fmtDate(r[C_DATE])), P(r[C_ASSESSOR] or ''), P(d, stCellB), levelCell(lvl), P(c.strip())])
                if not pd.isna(lvl):
                    cmds.append(('BACKGROUND', (3, i), (3, i), colors.HexColor(LEVEL_COLORS_PDF[int(lvl)])))
    if not rows:
        return P('No domain comments recorded.', stBodyGrey)
    cw = [1.0 * inch, 1.6 * inch, 1.6 * inch, 0.55 * inch]
    cw.append(CONTENT_W - sum(cw))
    return styledTable(['Date', 'Assessor', 'Domain', 'Lvl', 'Comment'], rows, cw, cellStyles=cmds + [('VALIGN', (0, 1), (-1, -1), 'TOP')])


def areasTable(g):
    rows, cmds = [], []
    for _, r in g.iterrows():
        a = r.get(C_AREAS)
        if isinstance(a, str) and a.strip():
            i = len(rows) + 1
            band = overallBand(r[C_OVERALL])
            rows.append([P(fmtDate(r[C_DATE])), P(r[C_ASSESSOR] or ''),
                         P('–' if pd.isna(r[C_OVERALL]) else f"{r[C_OVERALL]:.0f}",
                           ParagraphStyle('ov2', parent=stCellB, alignment=TA_CENTER, textColor=colors.black if band in DARK_TEXT_BANDS else colors.white)),
                         P(a.strip())])
            if band:
                cmds.append(('BACKGROUND', (2, i), (2, i), colors.HexColor(BAND_COLORS_PDF[band])))
    if not rows:
        return P('No "areas for improvement" comments recorded.', stBodyGrey)
    cw = [1.0 * inch, 1.6 * inch, 0.8 * inch]
    cw.append(CONTENT_W - sum(cw))
    return styledTable(['Date', 'Assessor', 'Overall', 'Areas for improvement and other comments'], rows, cw,
                       cellStyles=cmds + [('VALIGN', (0, 1), (-1, -1), 'TOP')])


def formSection(df, studentName, withBand=True):
    """All flowables for one form for one student (no leading PageBreak)."""
    formKey = df.attrs.get('formKey', '')
    doms = domainNames(df)
    g = keptRows(df)
    g = g[g[C_STUDENT] == studentName].sort_values(C_DATE)
    el = []
    if withBand:
        sub = (f"{len(g)} completed form{'s' if len(g) != 1 else ''} · {fmtDate(g[C_DATE].min())} – {fmtDate(g[C_DATE].max())}"
               if len(g) else 'No completed forms')
        el += [sectionBand(formKey, sub), Spacer(1, 12)]
    if g.empty:
        el.append(P(f"No completed {formKey} forms were found for {studentName}.", stBody))
        return el

    latest = g.iloc[-1]
    band = overallBand(latest[C_OVERALL])
    mean = g[C_OVERALL].mean()
    trend = overallTrend(g[C_OVERALL])
    trendCol = {'Improving': '#009E73', 'Declining': '#D55E00'}.get(trend)
    el.append(statTiles([
        (f"{len(g)}", 'Completed forms', None),
        ('–' if pd.isna(mean) else f"{mean:.1f}", 'Mean overall %', TILE_COLORS.get(overallBand(mean))),
        ('–' if pd.isna(latest[C_OVERALL]) else f"{latest[C_OVERALL]:.0f}", f"Latest overall % ({fmtDate(latest[C_DATE])})", TILE_COLORS.get(band)),
        (band or '–', 'Latest band', TILE_COLORS.get(band)),
        (trend or '–', 'Trend (first → last)', trendCol),
    ]))
    el.append(Spacer(1, 12))

    # Overall trajectory
    el.append(overallChart({formKey: (g[C_DATE], g[C_OVERALL], FORM_SERIES_COLORS.get(formKey, variableUtils.uniColor))},
                           title=f"{formKey} — overall % by session"))
    el.append(Spacer(1, 10))

    # Domain bars
    bars = [P('Domain ratings by session', stH2), levelLegend(), Spacer(1, 6)]
    for d in doms:
        bars += [levelBar(d, g[f'{d} Rating'].tolist(), g[C_DATE].tolist(), g[C_ASSESSOR].tolist()), Spacer(1, 4)]
    el.append(KeepTogether(bars))
    el.append(Spacer(1, 8))

    # Ratings table
    el.append(KeepTogether([P('Session detail', stH2), ratingsTable(g, doms)]))
    el.append(Spacer(1, 10))

    # Comments
    el.append(P('Assessor comments by domain', stH2))
    el.append(commentsTable(g, doms))
    el.append(Spacer(1, 10))
    el.append(KeepTogether([P('Areas for improvement', stH2), areasTable(g)]))
    return el


def overviewSection(formDfs, studentName):
    """Cover content for the combined report: cross-form table + combined trajectory chart + legend."""
    el = [Spacer(1, 10)]
    rows, series, cmds = [], {}, []
    year = None
    for i, (formKey, df) in enumerate(formDfs.items(), start=1):
        g = keptRows(df); g = g[g[C_STUDENT] == studentName].sort_values(C_DATE)
        if g.empty:
            rows.append([P(formKey, stCellB), P('0'), P('–'), P('–'), P('–'), P('–'), P('–')])
            continue
        year = year or g[C_YEAR].iloc[0]
        doms = domainNames(df)
        means = {d: g[f'{d} Rating'].astype(float).mean() for d in doms}
        lowest = min(means, key=lambda k: (np.nan_to_num(means[k], nan=99))) if means else '–'
        mean = g[C_OVERALL].mean(); latest = g[C_OVERALL].iloc[-1]
        bandM, bandL = overallBand(mean), overallBand(latest)
        rows.append([P(formKey, stCellB), P(str(len(g)), ParagraphStyle('c', parent=stCell, alignment=TA_CENTER)),
                     P(f"{fmtDate(g[C_DATE].min())} – {fmtDate(g[C_DATE].max())}"),
                     P(f"{mean:.1f}", ParagraphStyle('m', parent=stCellB, alignment=TA_CENTER, textColor=colors.black if bandM in DARK_TEXT_BANDS else colors.white)),
                     P(f"{latest:.0f} ({bandL})", ParagraphStyle('l', parent=stCellB, alignment=TA_CENTER, textColor=colors.black if bandL in DARK_TEXT_BANDS else colors.white)),
                     P(overallTrend(g[C_OVERALL]) or '–', ParagraphStyle('t', parent=stCell, alignment=TA_CENTER)),
                     P(f"{lowest} ({means[lowest]:.1f})" if lowest != '–' else '–')])
        if bandM: cmds.append(('BACKGROUND', (3, i), (3, i), colors.HexColor(BAND_COLORS_PDF[bandM])))
        if bandL: cmds.append(('BACKGROUND', (4, i), (4, i), colors.HexColor(BAND_COLORS_PDF[bandL])))
        series[formKey] = (g[C_DATE], g[C_OVERALL], FORM_SERIES_COLORS.get(formKey, variableUtils.uniColor))

    nForms = sum(int(r[1].text) for r in rows)
    el.append(statTiles([(f"{nForms}", 'Completed forms (all skills)', None),
                         (f"{year if year is not None else '–'}", 'DCD Year', None),
                         (f"{len([r for r in rows if r[1].text != '0'])}/{len(formDfs)}", 'Skills with forms', None)]))
    el.append(Spacer(1, 14))
    el.append(P('Overview across skills', stH2))
    cw = [1.5 * inch, 0.6 * inch, 2.2 * inch, 0.9 * inch, 1.5 * inch, 0.9 * inch]
    cw.append(CONTENT_W - sum(cw))
    el.append(styledTable(['Skill', 'Forms', 'Date range', 'Mean %', 'Latest % (band)', 'Trend', 'Lowest domain (mean 0-5)'],
                          rows, cw, cellStyles=cmds, zebra=False))
    el.append(Spacer(1, 14))
    if series:
        el.append(overallChart(series, title='Overall % by session — all skills'))
    el.append(Spacer(1, 12))
    el.append(KeepTogether([
        P('How to read this report', stH2),
        P('Each skill has its own section (starting on a new page): headline figures, the overall % trajectory, '
          'per-domain ratings for every session in date order, then the assessors\' comments verbatim.', stBody),
        Spacer(1, 4),
        P('Domain ratings: 0 Fail · 1 Marginal · 2 Fair · 3 Good · 4 Very good · 5 Excellent. '
          'Overall %: 0-49 Fail · 50-64 Marginal · 65-69 Fair · 70-74 Good · 75-79 Very good · 80-100 Excellent. '
          'Trend compares the first and last overall % (±2 points = stable).', stBodyGrey),
        Spacer(1, 4), levelLegend(),
    ]))
    return el


def laterPagesDrawer(leftText, rightText):
    """Slim navy strip + page number on pages 2+."""
    def draw(canvas, doc):
        canvas.saveState()
        w, h = doc.pagesize
        strip = 34
        canvas.setFillColor(NAVY); canvas.rect(0, h - strip, w, strip, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 12); canvas.drawString(LM, h - strip + 11, leftText)
        canvas.setFont('Helvetica', 10); canvas.drawRightString(w - RM, h - strip + 12, rightText)
        canvas.setFillColor(GREY); canvas.setFont('Helvetica', 8)
        canvas.drawRightString(w - RM, BM * 0.5, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def firstPageDrawer(firstline, secondline):
    banner = getBannerDrawer(firstline, secondline)
    def draw(canvas, doc):
        banner(canvas, doc)
        canvas.saveState(); canvas.setFillColor(GREY); canvas.setFont('Helvetica', 8)
        canvas.drawRightString(doc.pagesize[0] - RM, BM * 0.5, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def safeFileName(name):
    return re.sub(r'[\\/:*?"<>|]+', '_', str(name)).strip()


def buildDcdSkillsStudentPdf(formDfs, studentName, outFolder='DCD/Skills', mode='combined', programName=PROGRAM_NAME, verbose=True):
    """mode='combined' -> one PDF with a cover/overview page and one section per form (page break between).
    mode='separate' -> one PDF per form in outFolder/<Form>/. Returns list of written paths."""
    written = []
    if mode == 'combined':
        folder = os.path.join(outFolder, 'Combined'); os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{safeFileName(studentName)}.pdf")
        doc = SimpleDocTemplate(path, pagesize=PAGE_SIZE, leftMargin=LM, rightMargin=RM, topMargin=TM + 60, bottomMargin=BM)
        el = overviewSection(formDfs, studentName)
        for formKey, df in formDfs.items():
            el.append(PageBreak())
            el += formSection(df, studentName, withBand=True)
        doc.build(el, onFirstPage=firstPageDrawer(f"{programName} skills feedback", studentName),
                  onLaterPages=laterPagesDrawer(studentName, f"{programName} skills feedback"))
        written.append(path)
    elif mode == 'separate':
        for formKey, df in formDfs.items():
            folder = os.path.join(outFolder, safeFileName(formKey)); os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{safeFileName(studentName)}.pdf")
            doc = SimpleDocTemplate(path, pagesize=PAGE_SIZE, leftMargin=LM, rightMargin=RM, topMargin=TM + 60, bottomMargin=BM)
            el = [Spacer(1, 10)] + formSection(df, studentName, withBand=False)
            doc.build(el, onFirstPage=firstPageDrawer(f"{programName} — {formKey}", studentName),
                      onLaterPages=laterPagesDrawer(studentName, f"{programName} — {formKey}"))
            written.append(path)
    else:
        raise ValueError("mode must be 'combined' or 'separate'")
    if verbose:
        for p in written:
            print(f"  -> {p}")
    return written


def buildDcdSkillsReports(formDfs, outFolder='DCD/Skills', combined=True, separate=False, students=None, verbose=True):
    """Build PDFs for every student seen in any form (or `students`). Returns {student: [paths]}."""
    names = students or sorted(set().union(*[set(keptRows(df)[C_STUDENT].dropna()) for df in formDfs.values()]))
    out = {}
    for name in names:
        if verbose:
            print(f"[DCD skills PDF] {name}")
        paths = []
        if combined:
            paths += buildDcdSkillsStudentPdf(formDfs, name, outFolder, 'combined', verbose=verbose)
        if separate:
            paths += buildDcdSkillsStudentPdf(formDfs, name, outFolder, 'separate', verbose=verbose)
        out[name] = paths
    return out


def buildDcdSkillsWorkbooks(formDfs, outFolder='DCD/Skills', verbose=True):
    """One styled workbook per form."""
    os.makedirs(outFolder, exist_ok=True)
    return {k: buildDcdSkillsWorkbook(df, k, os.path.join(outFolder, f"DCD_{k.replace(' ', '')}_cleaned.xlsx"), verbose) for k, df in formDfs.items()}
