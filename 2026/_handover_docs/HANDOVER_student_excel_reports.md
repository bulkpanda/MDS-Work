# Handover — Student Excel Reports (BOH3 / DDS4)

**Date:** 2026-08-12
**Cohorts:** BOH3, DDS4 (final year)
**Files changed:** `boh3_dds4_utils.py` (new "section 9", ~1,800 lines appended), `main.ipynb` (3 new cells)
**Backup of the pre-change utils file:** `boh3_dds4_utils.py.bak_20260812_181136`
**Table read:** `dds4_boh3_forms_v3` (unchanged — no schema or pipeline changes in this session)

---

## 1. Why this exists

A DDS4 student (Gabrielle Mahon) asked for a spreadsheet alongside her PDF feedback report:

> "raw is fine. I just want to be able to compare all my different dash form feedback. I am
> thinking each row would be one form. Each column would have things such as my comments,
> supervisor comments, entrustment scores, commendations, areas of improvement etc. I would
> also like to see which supervisor marked each form too"

Two deliverables came out of that:

1. **`<studentNumber>_forms.xlsx`** — the flat "one row per form" comparison file she asked for.
2. **`<studentNumber>.xlsx`** — an Excel mirror of the PDF student report: KPI tiles, native
   (editable) Excel charts, and the supporting tables on their own tabs.

Design constraint the user added: **do not dump raw form data.** Curated, human-readable columns
only — no JSON blobs, no `*_config`, no schema snapshots, no internal IDs, no e-mail addresses.

---

## 2. Architecture

```
                    ┌───────────────────────────────────────────────┐
  main.ipynb   ───► │ buildStudentExcelReport()  (default sheets)   │
  cells 78/79       │ buildStudentFormExport()   (default sheets)   │
                    │ buildCohortStudentExcelReports()  (cohort loop)│
                    └──────────────────┬────────────────────────────┘
                                       │  all three are thin wrappers over
                                       ▼
                    ┌───────────────────────────────────────────────┐
                    │ buildStudentWorkbook(..., sheets=[...])       │
                    │  1. resolve name/cohort   → getStudentInfo    │
                    │  2. union of sheet "needs" → data groups      │
                    │  3. _collectStudentExcelData(needs=...)       │
                    │  4. for each sheet: STUDENT_SHEETS[n].builder │
                    │  5. deferred sheets last, then move into place│
                    │  6. _assertNoRawColumns(wb) → save            │
                    └──────────┬─────────────────────┬──────────────┘
                               │                     │
             ┌─────────────────▼──────┐   ┌──────────▼─────────────────┐
             │ DATA LAYER             │   │ PRESENTATION LAYER          │
             │ _collect*Data(needs)   │   │ one _sheet* fn per sheet    │
             │ 7 groups, lazily run   │   │ + _xl* formatting helpers   │
             └────────────────────────┘   └─────────────────────────────┘
```

The split matters: **sheet functions never touch the database and query functions never touch
openpyxl.** That is what makes both testable offline (see §9).

### 2.1 Sheet registry

`STUDENT_SHEETS` is an ordered dict — the single source of truth for the catalogue:

```python
STUDENT_SHEETS = {
    "Dashboard": dict(
        builder=_buildSheetDashboard, needs=("summary", "trend", "forms"), deferred=True,
        desc="Landing page: KPI tiles + trend line + entrustment/readiness doughnuts. …"),
    "Summary":              dict(builder=_buildSheetSummary,         needs=("summary",),    desc=…),
    "Trend":                dict(builder=_buildSheetTrend,           needs=("trend",),      desc=…),
    "Procedures":           dict(builder=_buildSheetProcedures,      needs=("procedures",), desc=…),
    "Feedback":             dict(builder=_buildSheetFeedback,        needs=("feedback",),   desc=…),
    "Self-Evaluation":      dict(builder=_buildSheetSelfChecklist,   needs=("checklist",),  desc=…),
    "Ratings by Form":      dict(builder=_buildSheetChecklistByForm, needs=("checklist",),  desc=…),
    "Comments & Incidents": dict(builder=_buildSheetComments,        needs=("comments",),   desc=…),
    "My Forms":             dict(builder=_buildSheetForms,           needs=("forms",),      desc=…),
    "Read Me":              dict(builder=_buildSheetReadMe,          needs=(),              desc=…),
}

DASHBOARD_SHEETS   = ["Read Me", "Dashboard", "Summary", "Trend", "Procedures", "Feedback",
                      "Self-Evaluation", "Ratings by Form", "My Forms"]
FORM_EXPORT_SHEETS = ["Read Me", "My Forms", "Self-Evaluation", "Ratings by Form"]
```

Every builder has the signature `(wb, ctx, sheetName)` and is a thin adapter over the real
`_sheet*` function, which keeps the sheet functions plain and independently callable.

`listStudentSheets()` returns the catalogue as a DataFrame (sheet · in each default · data groups
queried · description) — run it in the notebook to see the options.

**Usage:**

```python
# defaults
buildStudentExcelReport(engine, "DDS4", 1079984, name, path)

# any custom mix; list order == tab order
buildStudentWorkbook(engine, "DDS4", 1079984, name, path,
                     sheets=["Dashboard", "Summary", "Trend", "My Forms"])

# cohort loop, different sheet sets per file type
buildCohortStudentExcelReports(engine, cohort="DDS4", outputDir=…, kind="both",
                               exportSheets=["Read Me", "My Forms"])
```

Duplicates are de-duplicated keeping first position; unknown names raise `ValueError` listing the
valid ones; an empty list raises rather than writing a zero-sheet file.

**`Comments & Incidents` is registered but deliberately not in `DASHBOARD_SHEETS`** (user request).
Re-adding it is one word in that list.

### 2.2 Deferred sheets

The Dashboard's charts reference ranges on the *Summary* and *Trend* sheets, which must exist
first. `deferred=True` means: build it after everything else, then

```python
wb.move_sheet(name, offset=ordered.index(name) - wb.sheetnames.index(name))
```

puts it back at the position the caller asked for. So `sheets=["My Forms", "Summary",
"Dashboard", "Trend"]` yields exactly that tab order with working charts.

If Summary or Trend are *omitted*, the Dashboard renders without those charts rather than
raising — the builders read `ctx.get("summaryAnchors", {})` and skip on an empty dict.

### 2.3 Data groups (lazy querying)

```python
STUDENT_DATA_GROUPS = ("forms", "checklist", "summary", "trend",
                       "procedures", "feedback", "comments")
```

`buildStudentWorkbook` unions the `needs` of the chosen sheets and passes that set to
`_collectStudentExcelData(needs=…)`, which gates each block. `sheets=["Feedback"]` issues two
queries, not thirteen. Verified by wrapping every query stub with a counter:

| sheets | queries fired |
|---|---|
| `["My Forms"]` | `getStudentFormExport` ×1 |
| `["Feedback"]` | `getAssessorRollup` ×1, `getTopMultiSelectValues` ×1 |
| full default | each of the 12 exactly once |

`getAssessorRollup` feeds both the `summary` and `feedback` groups, so it goes through
`_assessorRollupCached(data, …)` which memoises into the `data` dict.

### 2.4 Reuse of the PDF's query functions

The dashboard deliberately calls the **same** functions that build the PDF report, so the two can
never disagree: `getStudentSummaryTable`, `getStudentRollup`, `getAssessorRollup`,
`getStudentTopItemCodes`, `getTopMultiSelectValues`, `getClinicalIncidentSummary`,
`getAdditionalConcerns`, `getSelfReflections`.

Only three queries are new, because no existing function returned what was needed:

| New function | Why it was needed |
|---|---|
| `getStudentFormExport` | one curated row per form — nothing existing produced this shape |
| `getStudentSelfChecklist` | needs the checklist wording + domain titles + option map (see §5) |
| `getStudentTrendDetail` | needs clinic + supervisor for chart hover; `getStudentTimeSeries` has neither |

**`getStudentTimeSeries` was left untouched on purpose** — `buildEntrustmentTimeSeriesPdf` depends
on its exact shape. `getStudentTrendDetail` is a parallel query using the same
`submitted_by_student AND submitted_by_assessor` filter, so both agree on which forms count.

---

## 3. The per-form export (`getStudentFormExport`)

One row per form, built by `_studentFormExportSql(formsTable)`. Column list, in order:

| Group (header band) | Columns |
|---|---|
| Form details | Form # · Date · Rotation · Clinic · Subject · Supervisor |
| Ratings | Entrustment (1-4) · Entrustment Level · My Practice Readiness (1-4) · My Practice Readiness · My Checklist Score (0-1) |
| Patients & procedures | Patients Seen · Patients FTA · Patient Ages · Item Codes |
| Written comments | My Reflection · Supervisor Comments |
| What went well | Commendations · Commendations (Other) |
| Areas for improvement | Time Management · Communication · Technical Skills · Person-Centred Care · Professional Behaviour · Risk Management · Knowledge & Clinical Reasoning · Other Feedback |
| Flagged | Clinical Incidents · Additional Concerns |
| Submission | Submitted by Me · Submitted by Supervisor |

### 3.1 SQL shape

```sql
WITH b AS (SELECT * FROM dds4_boh3_forms_v3
           WHERE cohort = :cohort AND student_number = :studentNumber),
caf   AS (…AVG over jsonb_each(student_data->'checklists'->'checklist-caf-final-eval')…),
pat   AS (…COUNT FILTER on (pd->>'patient_attended')::boolean, string_agg of ages…),
codes AS (…string_agg DISTINCT ic->>'code' over the nested item_codes arrays…)
SELECT
  ROW_NUMBER() OVER (ORDER BY b.datetimeutc, b.assessmentid)::int AS "Form #",
  b.datetimeutc::date                                            AS "Date",
  COALESCE(NULLIF(b.external_clinic,''), b.clinic)               AS "Clinic",
  b.assessor_name                                                AS "Supervisor",
  CASE b.assessor_data->'scales'->'scale-entrustment'->>'key'
    WHEN 'S1' THEN 1 … WHEN 'S4' THEN 4 END::smallint            AS "Entrustment (1-4)",
  b.assessor_config->'scales'->'scale-entrustment'->'fields'
    -> (b.assessor_data->'scales'->'scale-entrustment'->>'key')  AS "Entrustment Level",
  …
  NULLIF(b.student_data->'texts'->>'reflection','')              AS "My Reflection",
  NULLIF(b.assessor_data->'texts'->>'additional_comments','')    AS "Supervisor Comments",
  (SELECT NULLIF(string_agg(DISTINCT trim(x->>'value'), E'\n'), '')
   FROM jsonb_array_elements(COALESCE(b.assessor_data->'multi-select'->'strengths','[]'::jsonb)) x
   WHERE COALESCE(x->>'key','') <> 'Other' …)                    AS "Commendations",
  <one subquery per weakness-* key>                               AS "<friendly label>",
  …
FROM b LEFT JOIN caf … LEFT JOIN pat … LEFT JOIN codes …
ORDER BY b.datetimeutc, b.assessmentid;
```

The seven improvement columns are generated in Python from `WEAKNESS_KEY_LABELS`:

```python
WEAKNESS_KEY_LABELS = {
    "weakness-timeliness":                   "Time Management",
    "weakness-communication":                "Communication",
    "weakness-technical-skills":             "Technical Skills",
    "weakness-person-centered-care":         "Person-Centred Care",
    "weakness-professional-behaviour":       "Professional Behaviour",
    "weakness-risk-management":              "Risk Management",
    "weakness-knowledge-clinical-reasoning": "Knowledge & Clinical Reasoning",
}
```

Explicit keys rather than `LIKE 'weakness-%'` — the existing `STUDENT_ENTRIES_SQL` uses
`LIKE 'weakness-%%%%'`, which only works because `%%%%` collapses to one wildcard in LIKE. Not
a pattern to copy.

### 3.2 Grouped header band

Students see a column called "Time Management" with no context. `_xlGroupBand(ws, columns,
FORM_EXPORT_GROUPS, row)` draws a merged, colour-coded band above the header row — amber for
"Areas for improvement — supervisor comments by category", green for commendations, red for
flagged, navy for the rest.

Two implementation points:

- The band **matches by column name, not position**. Consecutive columns mapping to the same group
  are merged under one label; a column in no group gets a plain spacer cell. If the query gains or
  loses a column the band still lines up.
- It sits **outside** the Excel table range (the table starts at the header row below), so the
  autofilter, sorting and banded styling are unaffected. `print_title_rows` is set to
  `"{groupRow}:{headerRow}"` so both repeat on every printed page.

### 3.3 Real output (live run, DDS4 student 1082018)

```
97 forms · 35 supervisors
Form #  Date        Rotation    Clinic  Subject     Supervisor        Entrustment (1-4)
1       2026-01-19  Rotation 1  DTC     DENT90124   Marija Udovicic   2.0
        Entrustment Level: "Level 2: Student can be trusted to perform thi…"
        My Practice Readiness: "Level 3: I feel ready to perform today's tasks…"
```

---

## 4. Sheets

| Sheet | Contents | Charts |
|---|---|---|
| Read Me | Plain-English guide to the columns and scales | — |
| Dashboard | 9–10 KPI tiles + charts, no tables | trend line, 2 doughnuts |
| Summary | Metrics table (identical to the PDF) + entrustment / readiness distributions | — (feeds the doughnuts) |
| Trend | Per-form ratings with context + hidden plotting columns | trend line |
| Procedures | Item code · description · your count · class average · difference | clustered bars |
| Feedback | Improvement categories + top commendations | doughnut + bar |
| Self-Evaluation | Code · Domain · Question · average score | horizontal bars |
| Ratings by Form | Wide matrix: one row per form, one column per checklist domain | — |
| Comments & Incidents | Unified comment log with a Type column *(not in the default list)* | — |
| My Forms | The flat per-form export with the grouped band | — |

### 4.1 One column shape per sheet

The first build stacked several tables per sheet and they fought over column widths — Excel column
widths are per **sheet**, not per table, so the last table written squashed the first one's wrapped
text. The rule now: **a sheet holds one column shape.** Consequences:

- Summary holds three 2-column tables (all `label | count`) — compatible, widths pinned to 42/30.
- The Dashboard holds only KPI tiles and charts; its chart data lives on Summary and Trend.
  `Reference(otherWorksheet, …)` writes correctly sheet-qualified formulas.
- Self-evaluation averages and the wide by-form matrix are separate sheets.
- Incidents, concerns, weakness-other and self-reflections were merged into **one** filterable
  table with a `Type` column rather than four differently-shaped tables — which is also more
  useful for the student.

### 4.2 The trend chart

The most involved piece. Requirements were: hover shows clinic / supervisor / date; the two lines
must not sit on top of each other; the legend must say whose rating is whose; dotted vertical
dividers per rotation.

**Hover.** Native Excel charts have **no custom-tooltip API** — the tooltip shows the series name,
the *category text*, and the value. So the category is a composite string built in
`_collectTrendData`:

```
Form 7 · 03 May · MDC · L. Moreau
```

Clinic is truncated at `" ("` and supervisors are reduced to initial + surname (titles stripped),
because the category is *also* the axis tick label. The first version used full names plus the
rotation and the labels consumed half the plot area.

**Non-overlapping lines.** Two hidden helper columns hold `value ∓ TREND_PLOT_OFFSET` (0.045):

| Column | Role |
|---|---|
| `Entrustment (supervisor)` | visible, true value |
| `Practice readiness (self)` | visible, true value |
| `Supervisor (assessor): entrustment` | hidden, plotted, = true − 0.045 |
| `Me (student): practice readiness` | hidden, plotted, = true + 0.045 |
| `Rotation change` | hidden, 4.35 on the first form of each new rotation, else NULL |
| `Label` | hidden, the composite hover/axis string |

The helper column *headers* become the legend labels via `titles_from_data`, which is how the
legend ends up naming who gave each rating.

**Rotation dividers.** A `BarChart` series over the `Rotation change` column, `noFill` with a
`sysDash` grey outline, `gapWidth=500` (Excel's maximum → hairline), combined into the line chart
with `line += bar`. This is the standard Excel idiom for a vertical rule. Its legend entry
"Rotation change" doubles as the explanation.

**Axis.** `tickLblSkip = max(2, ceil(n/8))` so only ~8 of 97 labels are drawn, and −45° rotation
via `RichText(bodyPr=RichTextProperties(rot=deg*60000))`.

The whole chart is built once by `_buildTrendChart(sourceWs, anchors, title)` and used by both the
Trend sheet and the Dashboard.

### 4.3 Privacy guard

```python
_EXPORT_FORBIDDEN_COLS = ("patient_data", "student_data", "assessor_data", "student_config",
                          "assessor_config", "context_schema_snapshot", "assessmentid", "formid",
                          "assessorid", "student_email", "assessor_email", "insertedat")
```

Enforced twice: `_xlWriteDf` drops any matching column, and `_assertNoRawColumns(wb)` walks every
sheet before `wb.save()` and raises if one appears. Confirmed to fire when tested against a
deliberately poisoned workbook.

---

## 5. Finding: the checklist config path is one level deeper

**Symptom.** The Self-Evaluation "Question" column came back blank.

**Cause.** The checklist *definition* is not at the path the rest of the file assumes:

```
student_config -> 'checklists'                          = {"mode": "fixed", "selected": {…}}
student_config -> 'checklists' -> 'selected' -> 'checklist-caf-final-eval'
      -> 'fields'                          MC1..MC7 → full criterion wording
      -> 'extra_config' -> 'headers' -> MC1 -> [ {"title": "Knowledge & Clinical Reasoning"} ]
      -> 'extra_config' -> 'options' -> 'student'
                = {"O1":"Done well","O2":"Done","O3":"Mostly done",
                   "O4":"Sometimes done","O5":"Not done"}
```

Reading the bare `->'checklists'->'checklist-caf-final-eval'->'fields'` returns NULL.
`getStudentSelfChecklist` now COALESCEs both paths so either shape works.

**The ANSWER side is *not* nested** — `student_data->'checklists'->'checklist-caf-final-eval'` is
correct as written.

**Two bonuses from the same block:**

- `extra_config.headers` gives a short domain title per code. These are now the chart categories
  and the "Ratings by Form" column headers, so that sheet no longer shows bare MC1–MC7.
- `extra_config.options.student` maps O-codes to labels. A stored answer may be **either** the
  code (`"O2"`) or the label (`"Done"`) depending on form version, so the raw value is resolved
  through the form's own map before scoring. Tested both ways — identical averages.

```python
CAF_RATING_SCORES = {"Done well": 1.0, "Done": 0.8, "Mostly done": 0.6,
                     "Sometimes done": 0.4, "Not done": 0.0}
```

### ⚠️ Same bug, still open, in the PDF pipeline

`INDIVIDUAL_MC_SQL` (~line 2829) and `STUDENT_MC_SQL` (~line 2908) — behind the detailed-entry PDFs
in notebook cells 78/79 — both:

1. read `"Full MC Text"` from the bare config path → **NULL**, and
2. `CASE` directly on the literal rating text → **NULL scores** if answers are stored as O-codes.

Same one-line COALESCE fix applies. **Raised with the user, not yet actioned.**

---

## 6. `getStudentInfo` — replacing a brittle lookup

The notebook was doing:

```python
studentsDf = getStudentsInCohort(engine, testCohort)
testName = studentsDf.loc[studentsDf["student_number"] == testStudent, "student_name"].iloc[0]
```

which raises a bare `IndexError: single positional indexer is out-of-bounds` when the student is in
the *other* cohort — a real failure hit this session.

```python
getStudentInfo(engine, 1079884, "DDS4")
# LookupError: Student 1079884 has no forms in cohort 'DDS4' — found in: BOH3 (40 forms).
#              Pass that cohort, or cohort=None to auto-detect.

getStudentInfo(engine, 1079884)   # → ('BOH3', 1079884, 'Jordan Ellery')
```

`buildStudentWorkbook` calls it whenever `studentName` or `cohort` is `None`, so
`buildStudentExcelReport(engine, None, 1079984, None, path)` is enough.

---

## 7. Notebook changes (`main.ipynb`)

Three cells inserted after the `exportStudentTextWorkbook` cell (indices 77–79):

- **77 (markdown)** — what the two files are, how to choose sheets, the privacy guarantee, the
  header-band explanation.
- **78 (code)** — `display(listStudentSheets())`, `getStudentInfo(engine, 1079984)` to resolve the
  cohort and name, then one dashboard + one export build, plus sanity checks (form count,
  supervisor count, checklist wording).
- **79 (code)** — the cohort loop for DDS4 and BOH3 with a status log.

Note: `StudentReportMailer` only picks up `.pdf`, so these files are **not** e-mailed
automatically. Extending it to attach the xlsx alongside each PDF was offered and not taken up.

---

## 8. Key openpyxl traps found (all cost a debugging round)

| Trap | Consequence | Fix |
|---|---|---|
| `chart.plotVisOnly = False` | Not an openpyxl attribute — silently sets an unused field. With the plotted columns hidden the chart renders **completely empty**. | `chart.visible_cells_only = False` |
| Clustered `BarChart` with no explicit `overlap` | Series draw on top of each other; reads as one series. | `gapWidth=60, overlap=-12` (`_xlClusteredOffset`) |
| `DataLabelList()` with only `showVal=True` | Excel/LibreOffice also print category *and* series name — "S1 — full supervision; Count: 2; 18%". | `_xlDataLabels()` sets `showCatName/showSerName/showLegendKey/showBubbleSize = False` |
| `Reference(min_col=<index>)` | Adding the Domain column silently repointed the Self-Evaluation chart at the wrong column. | resolve column index by **name** from `df.columns` |
| `chart.title = "text"` | Unstyled default typography. | `_xlStyleTitleObj` pushes `CharacterProperties` into the rich-text runs; `_xlStyleChart` centralises it |
| `load_workbook` chart sizes | openpyxl does **not** restore `width`/`height` on read — always reports 15×7.5. | verify via `<ext cx cy>` in `xl/drawings/drawing*.xml` (EMU ÷ 360000 = cm) |
| Unaliased `from openpyxl.worksheet.table import Table` | Would shadow `reportlab.platypus.Table` in the notebook via `from boh3_dds4_utils import *` (cell 79 uses reportlab's). | imported as `_XlTable` / `_XlTableStyleInfo` |
| Column widths | Per **sheet**, not per table. | one column shape per sheet (§4.1) |
| Workbook title built in the wrapper | Read `"None — None feedback dashboard"` when the name was auto-resolved. | compose inside `buildStudentWorkbook`, after resolution, via `titleSuffix=` |

Also handled defensively: `_xlValue()` strips Excel-illegal control characters, converts leftover
`<br/>` (from the reportlab helpers) to real newlines, coerces numpy scalars, and truncates at
32,000 characters. `_scaleText()` normalises jsonb scale text that may arrive as a quoted string,
a dict, or a list.

---

## 9. How this was verified

The Cowork sandbox cannot reach the Postgres instance, so verification was in three layers:

1. **Stubbed query layer.** A harness replaced `readDf` and the ten reused query functions with
   fixtures modelled on the real JSON shapes — including jsonb values arriving as quoted strings,
   dicts and lists; a form missing its `headers` block; control characters in comment text; a
   supervisor of `None`; and a flag to flip stored answers between O-codes and literal labels.
2. **Rendering.** Every workbook was converted through LibreOffice to PDF and inspected as images —
   this is how the overlapping bars, the cluttered doughnut labels and the empty trend chart were
   caught. **Caveat:** LibreOffice ignores `tickLblSkip`, so the axis looks denser in those renders
   than it will in Excel.
3. **Live, by the user.** The single-student cell was run against the real database mid-session:
   DDS4 student 1082018 returned **97 forms / 35 supervisors** with entrustment and readiness text
   correctly unwrapped.

Cases exercised: normal student · student with **no forms at all** (every sheet writes a "No
records" line, no crash) · student in the wrong cohort · both answer encodings · custom sheet
lists · Dashboard without its source sheets · single-sheet workbook · unknown sheet name · empty
sheet list · sheet names containing Excel-illegal characters · the full cohort loop.

**Not verified:** the cohort-wide run against live data, and appearance in genuine Microsoft Excel
(only LibreOffice's renderer).

---

## 10. Open items

- **`INDIVIDUAL_MC_SQL` / `STUDENT_MC_SQL` config-path + O-code bug** (§5) — raised, awaiting
  go-ahead. This is the highest-value item here; it affects the existing PDF reports, not just Excel.
- **Duplication between the two workbooks.** `My Forms`, `Self-Evaluation`, `Ratings by Form` and
  `Read Me` appear in both files by design (each is standalone). De-duplication was offered; the
  user has not chosen. `kind="both"` also runs the export queries twice per student.
- **Mailer.** Extend `StudentReportMailer` to attach the xlsx alongside each PDF if these are to be
  sent out.
- **Excel-native check.** Open one file in real Excel and confirm tick-label thinning, the dashed
  rotation dividers and the table styles render as intended.
- **Cohort run.** The batch cell has not been run end-to-end against live data yet.

---

## 11. Quick reference

```python
# catalogue
listStudentSheets()

# resolve a student (cohort optional)
cohort, number, name = getStudentInfo(engine, 1079984)

# data only, no Excel
formDf                      = getStudentFormExport(engine, cohort, number)
wideDf, legendDf, itemAvgDf = getStudentSelfChecklist(engine, cohort, number)
trendDf                     = getStudentTrendDetail(engine, cohort, number)

# workbooks
buildStudentExcelReport(engine, cohort, number, name, "…/1079984.xlsx")
buildStudentFormExport(engine, cohort, number, name, "…/1079984_forms.xlsx")
buildStudentWorkbook(engine, cohort, number, name, "…/slim.xlsx",
                     sheets=["Dashboard", "Summary", "Trend", "My Forms"])

# whole cohort → DataFrame log with a status column
buildCohortStudentExcelReports(engine, cohort="DDS4",
                               outputDir="BOH3_DDS4/DDS4_ExcelReports",
                               kind="both", exportSheets=["Read Me", "My Forms"])
```

Tuning knobs: `DASHBOARD_SHEETS`, `FORM_EXPORT_SHEETS`, `FORM_EXPORT_GROUPS`,
`FORM_EXPORT_WIDTHS`, `WEAKNESS_KEY_LABELS`, `CAF_RATING_SCORES`, `TREND_PLOT_OFFSET`,
`_EXPORT_FORBIDDEN_COLS`, and the `XL_*` palette constants.
