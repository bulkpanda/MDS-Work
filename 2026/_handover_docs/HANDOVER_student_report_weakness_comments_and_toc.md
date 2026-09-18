# HANDOVER — DDS4/BOH3 student report: weakness-over-time, all-comments, cover contents & page numbers

**Date:** 2026-09-16
**Cohorts:** DDS4, BOH3 (all code is cohort-generic within `boh3_dds4_utils.py`)
**File changed:** `boh3_dds4_utils.py` only. `main.ipynb` **not** edited — existing cells pick everything up.
**Backups (this session, in `_bak/`):** `boh3_dds4_utils.py.bak_20260916_184017` (first) → … → `boh3_dds4_utils.py.bak_20260916_204615` (last, pre the comment-truncation revert). Each numbered backup precedes one committed change; the latest is the newest baseline.
**Shared files (`Utils.py`, `variableUtils.py`, other cohort utils):** untouched.

> DB is not reachable from the Cowork Linux VM (Postgres is on the user's Windows `localhost`), so everything was verified offline (stubbed `readDf` + fixtures, `py_compile`, star-import checks, real reportlab/matplotlib/openpyxl renders) and the raw `temp 2026 caf.json` (1.15 GB) was stream-parsed with `ijson`. Kunal runs the cells on the real machine for live confirmation.

---

## 1. What was added (four features + one fix)

1. **Weakness over time & by item code** — new analytics in the per-student PDF *and* the Excel dashboard: how areas-for-improvement evolve per rotation and per form, and which item codes carry them (split into rotation-group panels).
2. **All comments** — every free-text field on a form (supervisor + student) surfaced in the PDF and a new Excel "All Comments" sheet. This fixed the "no assessor comments from July" problem (see §3, a real data-structure migration).
3. **Student PDF cover** — a clickable, two-level **table of contents** and a **page number** on every content page.
4. **Cohort entrustment time-series PDF** (`buildEntrustmentTimeSeriesPdf`) now also shows each student's weakness-over-time panels under their entrustment chart.
5. **Fix** — a `LayoutError` from an over-tall comment row; resolved by truncating long comments in the PDF (see §6).

---

## 2. Weakness analytics

### 2.1 Data model / where weaknesses live
Assessor "areas for improvement" are tag arrays under `assessor_data->'multi-select'->'weakness-*'`. Seven counted buckets (`WEAKNESS_KEY_LABELS`, defined in section 9):

| key | label |
|---|---|
| weakness-timeliness | Time Management |
| weakness-communication | Communication |
| weakness-technical-skills | Technical Skills |
| weakness-person-centered-care | Person-Centred Care |
| weakness-professional-behaviour | Professional Behaviour |
| weakness-risk-management | Risk Management |
| weakness-knowledge-clinical-reasoning | Knowledge & Clinical Reasoning |

Also read: `clinical-incident` (count), `additional_concerns` (top-level column → concern flag), entrustment `assessor_data->'scales'->'scale-entrustment'->>'key'` (S1..S4 → 1..4). `weakness-other` is free text (handled as a comment, not a counted category).

**IMPORTANT caveat (baked into the report text):** feedback is recorded per **form**, not per procedure. A form has one set of weakness tags and often several item codes, so every "weakness by item code" figure is a **co-occurrence** (the code was on a form that also logged a weakness), not a strict cause.

### 2.2 New query functions (section 5, all public / no leading underscore)
- `getStudentWeaknessTimeline(engine, cohort, studentNumber, formsTable)` → one row per assessor-submitted form: `Form #`, `Date`, `Rotation`, `Entrustment`, the 7 category counts, `Total areas for improvement`, `Clinical incidents`, `Concern flag`, **`Item Codes`** (STRING_AGG of the form's distinct codes, for the per-form bar labels).
- `summariseWeaknessByRotation(timelineDf)` → one row per rotation: `Forms`, 7 categories, `Total…`, `Clinical incidents`, `Mean entrustment`; rotations sorted numerically.
- `getStudentWeaknessByCodeRotation(engine, cohort, studentNumber, formsTable)` → per **(Item Code, Rotation #)** detail (no HAVING filter, so any rotation grouping can be summed from it). Rotation number = `NULLIF(substring(COALESCE(rotation,'') from '[0-9]+'),'')::int`.
- `aggregateWeaknessByCode(detailDf, rotationNums=None, descMap=None, minWeaknessForms=1)` → collapses the detail to one row per code (optionally filtered to `rotationNums`), adds `Description` + `Weakness rate %`, keeps a code if it has ≥`minWeaknessForms` weakness-forms **or** any low-entrustment/incident/concern flag, sorts worst-first.
- `getStudentWeaknessByItemCode(engine, cohort, studentNumber, formsTable, rotations=None, minWeaknessForms=1)` → convenience wrapper = `getStudentWeaknessByCodeRotation` + `getItemCodeDescriptionMap` + `aggregateWeaknessByCode`.
- Helpers: `rotationSortKey`, `rotationNumber`, `weaknessRotationGroups(present, groups=None)`.

Aggregated by-code columns: `Item Code · Description · Forms with code · Forms with a weakness · Weakness rate % · Total areas for improvement · <7 categories> · Low-entrustment forms · Clinical incidents · Concern forms`.

**SQL shape (by-code detail):** CTE `form_level` (per assessmentid: entrustment, rot_num, 7 `jsonb_array_length(COALESCE(...,'[]'))` counts, total, incident count, concern 0/1) JOIN CTE `codes` (distinct `ic->>'code'` per form, `submitted_by_assessor` only) `USING (assessmentid)`, GROUP BY code, rot_num.

### 2.3 PDF (section 6)
- `plotWeaknessOverTime(timelineDf, byRotationDf, uniColor=None, figWidth=None)` — two stacked-bar panels: **by rotation** (mean entrustment overlaid on a secondary axis) and **per form** (only forms with feedback; numeric `YYYY-MM-DD` date ticks like the entrustment series; broader bars; the form's item codes printed above each bar). `figWidth` lets it fill a wide page (used by `buildEntrustmentTimeSeriesPdf`).
- `plotWeaknessByItemCodeGroups(groupTables, uniColor=None, topN=None)` — one horizontal stacked-bar panel per rotation group; `topN` defaults to `WEAKNESS_CODE_TOPN`.
- `buildStudentWeaknessSection(..., rotationGroups=None, tocMark=None)` — appends the "Areas for Improvement — When & Where" section: over-time chart, per-group by-code charts, and a compact top-codes table per group. Wired into `buildStudentPdf` after Procedures.

### 2.4 Excel (section 9)
- Data group **`weakness`** (added to `STUDENT_DATA_GROUPS`); `_collectWeaknessData` stores `weaknessTimelineDf`, `weaknessByRotationDf`, `weaknessByCodeDetailDf`, `weaknessDescMap`, `weaknessRotationGroupsResolved`, `weaknessByCodeDf`.
- Two sheets (native openpyxl stacked charts, `grouping="stacked"`, `overlap=100`, palette `WEAKNESS_PALETTE`): **"Weakness Over Time"** (by-rotation table + chart, per-form table + chart incl. Item Codes) and **"Weakness by Item Code"** (one table + chart **per rotation group**; the table lists **every** code; red conditional fill on low-entrustment/incident/concern > 0; colour scale on the total).
- Both added to `DASHBOARD_SHEETS` default, so `buildStudentExcelReport` / `buildCohortStudentExcelReports` include them automatically.

### 2.5 Rotation-group split — the knob
`WEAKNESS_ROTATION_GROUPS` (module global; `None` → auto "Rotations 1–3" / "Rotations 4+"). Drives **both** the PDF and Excel by-code panels.

```python
# Change the split (call once before building; star-import safe):
setWeaknessRotationGroups([("Rotations 1–4", [1,2,3,4]),
                           ("Rotations 5+", [5,6,7,8,9,10,11,12])])
setWeaknessRotationGroups(None)      # restore default
setWeaknessCodeTopN(30)              # how many codes each chart/table shows (worst-first)
```
**Gotcha:** because `main.ipynb` does `from boh3_dds4_utils import *`, a bare `WEAKNESS_ROTATION_GROUPS = …` in a cell only rebinds the notebook-local name; the builders read the *module* global. Use the setters (they assign the module global) — verified.

**"Missing codes" is not a bug:** the by-code chart/table show the top `WEAKNESS_CODE_TOPN` (default 20) codes per group, worst-first; low-total codes fall below the cut. The Excel "Weakness by Item Code" **table lists every code** per group. Raise `setWeaknessCodeTopN(...)` to surface more.

---

## 3. All comments (and the July migration finding)

### 3.1 The finding
Streaming `temp 2026 caf.json` (BOH3, per month) showed assessor written feedback **moved out of `multi-select.weakness-other` into `texts.additional_comments` around July 2026**:

| Month | weakness-other | texts.additional_comments |
|---|---|---|
| May | 374 | 63 |
| Jun | 97 | 84 |
| **Jul** | **0** | **537** |
| **Aug** | **0** | **489** |

The structured weakness **category** tags and `strengths` still populate through Sept, so the weakness analytics (§2) are unaffected. But the old report tables read only `weakness-other`, so supervisor comments looked empty from July.

### 3.2 Current form text fields (July+, BOH3+DDS4)
- Assessor `texts.*`: **`additional_comments`** (the main overall comment, ~3055), `additional-concerns` (rare), `clinical-incident-additional-details` (rare).
- Student `texts.*`: **`reflection`**.
- Assessor `multi-select` free text: `strengths`, `weakness-other` (historical only), `clinical-incident`; the 7 `weakness-*` are structured tags.

### 3.3 `getAllStudentComments(engine, cohort, studentNumber, formsTable, multiSelectFields=("strengths","weakness-other","clinical-incident"))`
Single source for every comment. SQL is a UNION ALL of three legs over a `forms` CTE (adds each form's item codes):
1. **assessor texts** — `jsonb_each_text(assessor_data->'texts')` (submitted_by_assessor, non-blank).
2. **student texts** — `jsonb_each_text(student_data->'texts')` (submitted_by_student).
3. **assessor multi-select free text** — `jsonb_array_elements(assessor_data->'multi-select'->ms.key)` over `VALUES` of `multiSelectFields`, value = `COALESCE(elem->>'value', elem#>>'{}')`.

Returns `Date · Rotation · From (Supervisor/You) · Type · Comment · Item Codes · Supervisor`. `Type` is mapped from the field key via `COMMENT_TEXT_LABELS` / `COMMENT_MULTISELECT_LABELS`, with a title-cased fallback so **a new form field appears automatically** (just with a generic name). `additional_comments` → "Overall comment", `weakness-other` → "Written feedback", `strengths` → "Commendation", `reflection` → "Reflection", etc.

### 3.4 PDF (`buildStudentCommentsTables`)
Two tables — **"Supervisor comments & feedback"** and **"Your reflections & comments"** — columns `Date · Type · Comment · Item Codes` (older/simple style, rendered inline). The supervisor table is filtered to `PDF_SUPERVISOR_COMMENT_TYPES = ("Overall comment", "Written feedback")` (non-standard free comments only; commendations/concerns/incidents are structured and shown elsewhere). Long comments are **truncated to `PDF_COMMENT_MAXCHARS = 500`** chars + "…" (set 0/None to disable). This replaced the old "Other weaknesses/strengths" + reflections tables (which read only `weakness-other`).

### 3.5 Excel — "All Comments" sheet
`_collectCommentData` now feeds `getAllStudentComments`; sheet renamed **"All Comments"** (registry key + `DASHBOARD_SHEETS`), columns `Date · From · Type · Supervisor · Rotation · Detail · Item Codes`, **full untruncated text**, filterable by `From`/`Type`.

---

## 4. Student PDF cover — contents + page numbers
Mirrors the V2 report pattern (`boh2_dds2_dds3_utils.py`).
- `class _StudentTocMark(Flowable)` — zero-size marker (`tocKey = f"stutoc_{id(self)}"`).
- `class _StudentTocDoc(SimpleDocTemplate)` — `afterFlowable` bookmarks the page and `notify("TOCEntry", (level, text, page, key))` (the 4th element makes the entry a clickable link).
- `_makeStudentToc(uniColor)` — `TableOfContents` with **two** level styles (level 0 = bold section, level 1 = indented sub-entry).
- `_studentPageDecorators(bannerTitle, bannerSubtitle)` → `(first, later)`; banner on the cover, centred page number on every content page.
- `buildStudentPdf` builds a **cover page** (intro + "Contents" + TOC + PageBreak), drops **level-0 markers** per section and **level-1 markers** before each table/chart (Summary table, entrustment chart, procedures chart, weakness over-time, weakness by item code, per-group code tables, the distributions, the **weakness pie**, top commendations, and **separate** supervisor / student comment entries), then `doc.multiBuild(elements, onFirstPage=…, onLaterPages=…)` (two passes so page numbers resolve). Empty sections/tables get no entry (marker only added when content renders). Import added: `from reportlab.platypus.tableofcontents import TableOfContents`.

New import requirement: none beyond that; `Flowable`, `SimpleDocTemplate`, `colors`, `ParagraphStyle` already imported.

---

## 5. Cohort entrustment time-series PDF
`buildEntrustmentTimeSeriesPdf` now appends each student's `plotWeaknessOverTime(...)` (rotation + per-form panels, `figWidth=chartWidthInch` to match the wide page) to their block, right after the entrustment/readiness chart. Students with no recorded areas for improvement just show the entrustment chart as before. `plotWeaknessOverTime` gained the `figWidth` param for this.

---

## 6. The `LayoutError` fix (and why truncation)
A single very long comment made one table **row taller than a page**; reportlab can't split a row across pages by default → `LayoutError: Flowable <Table …(tallest row 1284)> too large`. `createTable` (in `Utils.py`) wraps its table in a `KeepTogether`.

- First fix: `_enableRowSplit(flowable)` reaches into the returned `KeepTogether._content`, finds the `Table`, sets `splitInRow = 1` + `repeatRows = 1` (reportlab ≥ 3.5 / device has 5.0.1). This keeps `Utils.py` untouched. Still applied to the **weakness by-item-code** tables.
- Final choice for comments (per user): **truncate** instead of splitting — `PDF_COMMENT_MAXCHARS = 500` in `buildStudentCommentsTables`, and the comment tables reverted to the simpler inline style (no forced page breaks, no row-splitting). Excel keeps full text.

---

## 7. New public API surface (quick reference)
```
# queries
getStudentWeaknessTimeline(engine, cohort, studentNumber, formsTable="dds4_boh3_forms_v3")
summariseWeaknessByRotation(timelineDf)
getStudentWeaknessByCodeRotation(engine, cohort, studentNumber, formsTable=…)
aggregateWeaknessByCode(detailDf, rotationNums=None, descMap=None, minWeaknessForms=1)
getStudentWeaknessByItemCode(engine, cohort, studentNumber, formsTable=…, rotations=None, minWeaknessForms=1)
getAllStudentComments(engine, cohort, studentNumber, formsTable=…, multiSelectFields=(…))
rotationSortKey(rotation) · rotationNumber(rotation) · weaknessRotationGroups(present, groups=None)
# config setters + globals
setWeaknessRotationGroups(groups) · WEAKNESS_ROTATION_GROUPS
setWeaknessCodeTopN(n)          · WEAKNESS_CODE_TOPN   (default 20)
PDF_SUPERVISOR_COMMENT_TYPES   (default ("Overall comment","Written feedback"))
PDF_COMMENT_MAXCHARS           (default 500; 0/None disables truncation)
WEAKNESS_PALETTE               (7 hex, shared PDF+Excel)
# PDF builders
plotWeaknessOverTime(timelineDf, byRotationDf, uniColor=None, figWidth=None)
plotWeaknessByItemCodeGroups(groupTables, uniColor=None, topN=None)
buildStudentWeaknessSection(engine, cohort, sn, elements, styles, formsTable=…, …, rotationGroups=None, tocMark=None)
buildStudentCommentsTables(elements, engine, cohort, sn, formsTable=…, subheadingStyle=None, uniColor=None, tableTextStyleSmall=None)
```
New Excel sheet keys: **"Weakness Over Time"**, **"Weakness by Item Code"**, **"All Comments"** (all in `DASHBOARD_SHEETS`; `STUDENT_DATA_GROUPS` gained `"weakness"`). Internal helpers (underscored, not notebook-callable): `_collectWeaknessData`, `_xlStackedWeaknessChart`, `_sheetWeaknessOverTime`, `_weaknessCodeBlockXl`, `_sheetWeaknessByItemCode`, `_weaknessCodeTablePdf`, `_shortCodes`, `_commentTypeLabel`, `_enableRowSplit`, `_StudentTocMark`, `_StudentTocDoc`, `_makeStudentToc`, `_studentPageDecorators`.

---

## 8. How to run (no cell edits needed)
- **PDF:** `buildCohortStudentReports(engine, "DDS4", …)` / `"BOH3"` → each student report now has the cover/contents, page numbers, weakness section, and all-comments tables.
- **Excel:** `buildCohortStudentExcelReports(engine, "DDS4"|"BOH3", …)` → adds Weakness Over Time, Weakness by Item Code, All Comments sheets.
- **Entrustment time-series:** `buildEntrustmentTimeSeriesPdf(...)` → now includes weakness panels per student.
- Change the split / caps first with the setters in §2.5.

---

## 9. Verification
- `py_compile` clean (container + device VM).
- Offline test suites (stubbed `readDf` + fixtures): weakness shaping/rotation-sort/description map/rate; both PDF plots; both Excel sheets (native charts present on save+reload); registry wiring; comments Type mapping + supervisor filter + truncation; TOC (real PDF built — clickable link annotations present, 2-level contents lists every table/chart, page numbers render); over-tall-comment case builds (truncated) instead of raising LayoutError.
- `weakness-other` → `additional_comments` migration confirmed by stream-parsing the raw CAF JSON.
- **Not** run vs the live DB / on Windows (VM lacks `win32com`, fonts, DB). Kunal to confirm on one real DDS4 + one BOH3 student.

## 10. Gotchas
- **Star-import setter** — use `setWeaknessRotationGroups`/`setWeaknessCodeTopN`, not bare reassignment (§2.5).
- **`weakness-other` empty from July** — historical only; current supervisor free text is `additional_comments`.
- **Co-occurrence** — item-code weakness figures are associations, not per-procedure attribution.
- **Top-N cap** — low-frequency codes are omitted from PDF chart/table by design; full list is the Excel table.
- **`createTable` returns `KeepTogether`**, not a bare `Table`; `_enableRowSplit` reaches into `_content`.
- Other cohorts (BOH2/DDS2/DDS1/DDS3) have a **different data structure** — per Kunal, **no change needed** there; this migration/fix is DDS4/BOH3 only.

## 11. Open items
- Live-DB validation on real DDS4/BOH3 students (numbers, weakness JSON keys, comment rendering).
- Optional: expose `rotationGroups`/topN as per-call params threaded through `buildCohortStudentReports`/`buildCohortStudentExcelReports` (currently the module globals via setters).
