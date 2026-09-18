# Final-Year (BOH3 / DDS4) Reporting — Session Handover

**Date:** 2026-08-03
**File primarily touched:** `boh3_dds4_utils.py` (+ notebook cells that call it)
**Predecessor doc:** `_handover_docs/finalyear_v3_reports_handover.md` (the v2→v3 rewiring; this doc continues it)
**Status:** Excel summary workbook, PBN/Leave enrichment, entrustment time-series (PDF polish + interactive HTML), and the student-report v3 fixes are **done**. One **open blocker**: DDS4 reports render empty patient/entrustment values — root cause isolated to the v3 table's `patient_data`/`assessor_data` for the DDS4 cohort; fix pending a one-query confirmation (see §8).

---

## 1. Scope of this session

Seven threads of work, all in `boh3_dds4_utils.py` unless noted:

1. `BOH3_Summary_Details.xlsx` — added Student ID / Rotation to the Incidents & Concerns sheets.
2. Entrustment sheet — added Clinical-Incident and Additional-Concern **counts**, plus two rotation-split sheets (R1–3, R4–6).
3. A reusable **professional Excel formatter** (`formatSummaryExcel`).
4. Two new Entrustment columns sourced from **external workbooks**: `PBNs 2026` and `Leave Days 2026` (VIC working days).
5. Entrustment **time-series PDF** polish + a self-contained **interactive HTML** version.
6. **Student-report v3 fixes** (CAF scoring, item descriptions, a table-width crash).
7. **Sections 7 & 8** (Excel textual report + individual entry report) migrated off the v2 table.

Open blocker in §8.

---

## 2. Data shape reference (v3) — quick recall

Table `dds4_boh3_forms_v3` holds **both** BOH3 and DDS4 final-year forms. Relevant JSON columns:

- `patient_data` — JSON **array** of patient objects:
  ```json
  [{"item_codes":[{"code":"013","quantity":1}],
    "patient_age":"82","visit_number":"4",
    "patient_attended":true,"priority_present":"no","priority_group":null}]
  ```
  Item elements carry only `{code, quantity}` (no inline `description` — see §6.2).
- `assessor_data` — object with buckets `scales / texts / multi-select / radio`:
  - entrustment level: `assessor_data->'scales'->'scale-entrustment'->>'key'` → `S1..S4`
  - multi-select items: `{"key":"STR3","value":"…"}` (v2 used `name` instead of `key`)
- `student_data` — object; CAF checklist:
  ```json
  "checklists": {"checklist-caf-final-eval": {"MC1": {"key":"O1","value":"Done well"}, …}}
  ```
  Option scores: O1=Done well 1.0, O2=Done 0.8, O3=Mostly done 0.6, O4=Sometimes done 0.4, O5=Not done 0.0.
- practice readiness: `student_data->'scales'->'scale-practice-readiness'->>'key'` → `S1..S4`.

**v3 upsert source paths** (`getBoh3Dds4FormsV3ProcessSql`, ~L413):
```sql
f.form_value->'form_context'->'patients'  AS patient_data
f.form_value->'student_data'              AS student_data
f.form_value->'assessor_data'             AS assessor_data
```
These paths are correct for **BOH3** (verified live). They appear to be wrong for **DDS4** — see §8.

---

## 3. Excel summary workbook (`BOH3_DDS4/<cohort>_Summary_Details.xlsx`)

Built inside the cohort-summary routine (the block that writes `superExcelPath`). Sheet order:

`Age Counts → Entrustment → Entrustment R1-3 → Entrustment R4-6 → Incidents → Concerns → Merged Item-Section → Section Pivot`

### 3.1 Student ID + Rotation on Incidents / Concerns
- `getClinicalIncidentSummary` (~L803) and `getAdditionalConcerns` (~L784) now select `student_number AS "Student ID"` and `rotation AS "Rotation"`, placed **after** `Student Name`.
- `getClinicalIncidentSummary` groups by the extra columns; both feed the Excel sheets.
- **Important coupling:** the same `getClinicalIncidentSummary` is reused by the *student PDF*; adding these columns broke a fixed-width table there — see §6.3.

### 3.2 Entrustment sheet: incident/concern counts + rotation splits
`getEntrustmentPerStudentBatch(engine, cohort, formsTable, rotationRange=None)`:
- Two new **trailing** columns:
  - `Clinical Incidents` = `COUNT(*) FILTER (WHERE jsonb_array_length(COALESCE(multi->'clinical-incident','[]'::jsonb)) > 0)`
  - `Additional Concerns` = `COUNT(*) FILTER (WHERE additional_concerns IS NOT NULL)` (form-level counts, so they line up with the Incidents/Concerns sheet row counts).
- `rotationRange=(lo,hi)` filters via a robust rotation-number parse (handles `Rotation 6` **and** `R6`):
  ```sql
  AND NULLIF(regexp_replace(COALESCE(rotation,''),'[^0-9]','','g'),'')::int BETWEEN :rotLo AND :rotHi
  ```
- Pipeline builds three DataFrames: full, `rotationRange=(1,3)`, `rotationRange=(4,6)` → sheets `Entrustment`, `Entrustment R1-3 {cohort}`, `Entrustment R4-6 {cohort}`. (Annual counts like PBN/Leave live **only** on the main sheet.)

### 3.3 Student ID on Age Counts & Section Pivot
- `getAgeCountsBatch` now selects `student_number` (grouped by it). The Excel copy renames `student_number→"Student ID"`, `student_name→"Student Name"`; the raw df keeps lowercase names so downstream merges are unaffected.
- `sectionPivot` is now `pivot_table(index=["Student ID","Student Name"], …)`; `Total` sums **only** the section columns (so the numeric ID isn't added in).

---

## 4. Professional Excel formatter — `formatSummaryExcel(path, cohort, sheetOrder=None)`

Reopens the written workbook and styles every sheet, then saves. Called at the end of the Excel-write block (replaced the old autofit-only pass). Brand palette matches `variableUtils.uniColor` (navy `#010D44`).

Foundation (all sheets): navy header fill + white bold text, `freeze_panes` (header row always; also the first two columns when both `Student ID` and `Student Name` are present), zebra banding (`#EEF1F8`), thin light-grey borders, per-column widths, `Entrustment Avg` number format `0.00`, no text wrapping.

Conditional highlights (sheets whose title starts with `Entrustment`):
- `Entrustment Avg` → 3-colour scale (red@1 → yellow@2.5 → green@4).
- `Clinical Incidents`, `PBNs 2026`, `Additional Concerns` > 0 → filled flag cell.
- Weakness columns → subtle white→orange heatmap, **excluding** `Weakness Other`.

**Gotcha (documented so it isn't re-hit):** conditional-format fills in openpyxl must use `PatternFill(bgColor=…)`, *not* `fgColor`, or the fill won't render. Sheet reordering is done by reassigning `wb._sheets` (append mode otherwise pushes newly-created sheets to the end of the workbook).

---

## 5. PBN + Leave enrichment (external workbooks)

Adds two **trailing** columns to the **main** Entrustment sheet: `PBNs 2026`, `Leave Days 2026`. Wired via `addPbnLeaveColumns(entrustmentDf, year=2026)` just after `getEntrustmentPerStudentBatch(...)`.

Module constants:
```python
PBN_FILE   = "MDS Professional Behaviour Notification Form.xlsx"
LEAVE_FILE = "Melbourne Dental School Student Leave Form_July 31, 2026_13.05.xlsx"  # raw Qualtrics export
VIC_HOLIDAYS_2026 = ["2026-01-01","2026-01-26","2026-03-09","2026-04-03","2026-04-06",
                     "2026-06-08","2026-09-25","2026-11-03","2026-12-25","2026-12-28"]
```

### 5.1 PBNs — `getPbnCountByStudent(rosterDf, year=2026)`
- Reads PBN xlsx `Sheet1`. Matches on `Student ID (if known)`; **falls back to name** (many PBN rows have no ID). Filters `Date of incident` year == 2026 (keeps `NaT`). Returns `{student_id: count}`.

### 5.2 Leave working-days — `getLeaveDaysByStudent(ids, year=2026)`
- Reads the raw **Qualtrics** export: `sheet_name=0, header=1` (row 0 = question codes, row 1 = human headers). Keeps `Finished == True`, excludes `Response Type == 'Survey Preview'`, matches on `Student ID`.
- Per-row duration = `leaveWorkingDays(planned, start, end, year)` (**category-guided**, chosen by the user):
  - `Hours …` or `Half day` (partial) → **0**
  - `1 day` → 1 working day on Start (0 if Start is a weekend/holiday)
  - `2 or more days` / `Other` → inclusive VIC **working days** across Start→End
  - Guards: year-typo clamp (e.g. end `2027`), range ordering.
- Working days = `np.busday_count` excluding weekends **and** `VIC_HOLIDAYS_2026`.

### 5.3 Why the leave file was switched (important)
The earlier `Combined_Leave_Report.xlsx` had **corrupted dates**: dd/mm strings whose day ≤ 12 had been parsed with a US (mm/dd) convention and stored as datetimes with month/day swapped (e.g. Wendy Phung's stated *1 April* was stored as *4 Jan*; a single "62-day" leave was really a 2-day one). We switched to the **raw Qualtrics export**, where dates are clean `dd/mm/yyyy` **text**, so no un-swapping is needed. `_parseLeaveDate` therefore parses strings day-first and trusts datetimes as-is. New wrinkle: the raw file has a **`Half day`** category (counted as 0 per the user's "partial = 0" choice).

**Example result (BOH3):** total 77 working days across 33 students; Steven Hanna = 8; PBNs total 8 across 5 students.

---

## 6. Entrustment time-series report

Data: `getStudentTimeSeries(engine, cohort, studentNumber)` — per-form entrustment + practice readiness (both `->>'key'` → 1..4), only where `submitted_by_student AND submitted_by_assessor`. This function is v3-correct.

### 6.1 PDF — `buildEntrustmentTimeSeriesPdf(...)`
- `onlyLevel1=True` (default) keeps the original "students with entrustment Level 1 (ES1) at least once" report; pass `onlyLevel1=False` for everyone.
- Sorted **worst-first** (most ES1 forms, then lowest average).
- One `KeepTogether` block per student (heading + chart + stats line) → packs multiple per page (fixed the earlier one-per-page empty space).
- Clickable **PDF outline bookmarks** via `_OutlineBookmark(Flowable)`.
- Wider **portrait** page for this report only: `pageSize = (15*inch, variableUtils.pageSize[1])` (default is **A3 portrait**, `11.69 × 16.54 in / 297 × 420 mm`). Chart figure width flows from the page (`figWidth`), and `addPlotImage(fig, 0.98, pageSize=pageSize)` scales to it.
- `plotEntrustmentReadinessTimeSeries(df, title, uniColor, useDateAxis, subtitle, figWidth)` additions: risk-zone shading (red Level 1, amber Level 2), dashed mean line, red-X ES1 markers (from raw per-form values), stats subtitle, legend dropped **below** the axis so it never hides the ES1 markers. `useDateAxis=False` (string dates) is used in the PDF for uniformity.

### 6.2 Interactive HTML — `buildEntrustmentTimeSeriesHtml(engine, cohort, outPath, title=None, onlyLevel1=False)`
- One **self-contained** HTML file (all data embedded as JSON; Plotly from CDN, works offline).
- **Searchable student sidebar** (type name/ID or click), an "Only ES1 ≥ 1" toggle (client-side; every student is embedded so the toggle always works), per-student ES1 badge, worst-first order.
- Interactive Plotly chart: hover tooltips (date/level), zoom/pan, risk-zone shading, dashed mean line, ES1 flags.
- Template lives in `_TS_HTML_TEMPLATE` (placeholders `__TITLE__ / __DATA__ / __ORDER__`).
- Suggested calls:
  ```python
  buildEntrustmentTimeSeriesHtml(engine, "BOH3", "BOH3_DDS4/BOH3_Entrustment_TimeSeries.html")
  buildEntrustmentTimeSeriesHtml(engine, "DDS4", "BOH3_DDS4/DDS4_Entrustment_TimeSeries.html")
  ```

---

## 7. Student-report v3 fixes (PDF path: `buildStudentPdf` / `buildStudentVsAssessorSection`)

### 7.1 CAF checklist object shape (was NULL scores) — DONE
`getStudentSelfSummary` (~L1740) and `getStudentRollup` (~L1862): `jsonb_each_text` → `jsonb_each`, and match on `COALESCE(kv.value->>'value', kv.value#>>'{}')` (robust to v3 objects **and** legacy strings). Powers "Avg Self CAF Score".

### 7.2 Item descriptions (were blank) — DONE
v3 item_codes have no inline description. `getStudentTopItemCodes` now selects `NULL::text AS description` and fills it in pandas from `getItemCodeDescriptionMap(engine, cohort, formsTable)` (the `context_schema_snapshot`), mirroring the cohort-level fix.

### 7.3 Table-width crash (this made the whole PDF fail) — DONE
Because §3.1 added `Student ID` + `Rotation` to `getClinicalIncidentSummary`, the two `.drop(...)` calls in `buildStudentVsAssessorSection` left **5** columns against `createTable(..., colRatio=[1,1,4])` (3) — a length mismatch that raises in ReportLab and aborts the build. Fix: both drops now also remove `'Student ID','Rotation'` (with `errors='ignore'`), restoring the 3-column layout. All `createTable` calls in the student path were re-audited and match their `colRatio`.

---

## 8. Sections 7 & 8 migration + the OPEN DDS4 BLOCKER

### 8.1 Sections 7 & 8 — migrated to v3 (DONE)
The Excel textual report (`_MAIN_SQL`, `_WEAKNESS_SQL`, `_STRENGTH_SQL`, `_CONCERNS_SQL`, `buildStudentSheet`/`exportStudentTextWorkbook`) and the individual entry report (`INDIVIDUAL_ENTRY_SQL`, `INDIVIDUAL_MC_SQL`, `STUDENT_ENTRIES_SQL`, `STUDENT_MC_SQL`) previously read the **v2** table `dds4_boh3_forms` with v2 shapes. Migrated (scoped to those sections only — the `CREATE TABLE`/index DDL and the v2 pipeline builder were left untouched):
- all SELECTs → `dds4_boh3_forms_v3` (9 references);
- CAF (`INDIVIDUAL_MC_SQL`, `STUDENT_MC_SQL`): `jsonb_each_text` → `jsonb_each`, "MC Rating" and scoring `CASE` now read `COALESCE(kv.value->>'value', kv.value#>>'{}')`;
- multi-select "Other" filter: `e->>'name'` → `e->>'key'` (6 places).
- **To verify:** the exact v3 key for a free-text "Other" strength (handover recommended `key`; confirm against a real `assessor_data->'multi-select'->'strengths'` row). `mc1..mc7` columns in the two entry SQLs still read `->>'MC1'` (returns the whole object in v3) but are **not** in the final SELECT — dead columns, no output impact.

### 8.2 OPEN BLOCKER — DDS4 reports render empty patient + entrustment
**Symptom:** every DDS4 report (cohort summary *and* per-student) shows `Patients Attended = 0`, `Avg Assessor Entrustment = None`, empty entrustment distribution, and an empty time-series chart — while `student_data`-sourced fields work (Avg Self CAF `0.96`, reflections). Reported as affecting **all reports**, i.e. systemic to the DDS4 cohort.

**What's proven:**
- **BOH3 is fine.** For BOH3 `student_number=1606096`, a direct diagnostic showed `patient_data` = `array` with real patients and `assessor_data->'scales'->'scale-entrustment'->>'key'` = `S1..S4`; calling the report functions directly returned **162** patients attended and **89/89** forms with entrustment, **71** time-series points. So the reporting SQL and BOH3 data are correct.
- The failing report is **DDS4** (`Alexandra Sobry, 1391557`); DDS4 was never validated in the predecessor session ("DDS4 not run", "Nothing validated against DDS4 student PDFs").

**Leading hypothesis:** DDS4's raw forms nest patients / assessor data at **different paths** than the v3 upsert expects. Since `student_data` populates for DDS4 (CAF works), only `patient_data` (`form_value->'form_context'->'patients'`) and `assessor_data` (`form_value->'assessor_data'`) are wrong for the DDS4 template.

**Next step (single, cohort-wide diagnostic to run against the live `engine`):**
```python
readDf(engine, """
SELECT cohort,
  COUNT(*)                                                                   AS forms,
  COUNT(*) FILTER (WHERE jsonb_typeof(patient_data)='array')                 AS pd_is_array,
  COUNT(*) FILTER (WHERE jsonb_typeof(assessor_data)='object')               AS ad_is_object,
  COUNT(*) FILTER (WHERE assessor_data->'scales'->'scale-entrustment'->>'key' IS NOT NULL) AS has_entrustment,
  COUNT(*) FILTER (WHERE jsonb_typeof(student_data)='object')                AS sd_is_object
FROM dds4_boh3_forms_v3
GROUP BY cohort ORDER BY cohort
""", {})
```
Interpretation → fix:
- **DDS4 `pd_is_array`/`has_entrustment` ≈ 0, BOH3 fine** → branch the DDS4 source paths in `getBoh3Dds4FormsV3ProcessSql` (inspect one raw DDS4 form's top-level keys + `form_context` to find where patients/assessor live), then reprocess DDS4.
- **Both ≈ 0** → the table was rebuilt into a bad state; same upsert-path fix, then reprocess.
- **Both look fine** → data is good and the empties come from the generation step reading a stale/other table; trace the report cell's `engine`/`formsTable`.

> Note: the Postgres DB is on `localhost:5432` (not reachable from the sandbox), so this query must be run in the notebook.

---

## 9. Files & entry points

- **Code:** `boh3_dds4_utils.py` (all report functions), notebook cells: cohort summary + `superExcelPath` write; `buildCohortStudentReports(engine, cohort=…, outputDir=…, **studentPdfArgs)`; `buildEntrustmentTimeSeriesPdf(...)` / (new) `buildEntrustmentTimeSeriesHtml(...)`.
- **Inputs:** `dds4_boh3_forms_v3` (Postgres); `MDS Professional Behaviour Notification Form.xlsx`; `Melbourne Dental School Student Leave Form_July 31, 2026_13.05.xlsx`; `item_section_mapping.xlsx`.
- **Outputs:** `BOH3_DDS4/<cohort>_Summary_Details.xlsx`; `BOH3_DDS4/<cohort>_Entrustment_TimeSeries*.pdf` / `.html`; `BOH3_DDS4/<cohort>_StudentReports/*.pdf`.
- **Config:** `Config.xlsx` holds per-cohort notes; DB creds in `.env` (`DB_*`).

## 10. Verify / how to run
- Regenerate one student PDF: `buildStudentPdf(engine, "BOH3", 1606096, "Aidah Khan", "BOH3_DDS4/_test.pdf", **studentPdfArgs)` → expect 162 patients, populated entrustment + chart (confirms §7 fixes on BOH3).
- Regenerate the summary workbook, then it is auto-formatted by `formatSummaryExcel`.
- **Do NOT ship DDS4 reports** until §8.2 is resolved.

## 11. Line numbers
Approximate as of 2026-08-03 and **will drift** — search by symbol name rather than trusting the numbers.
