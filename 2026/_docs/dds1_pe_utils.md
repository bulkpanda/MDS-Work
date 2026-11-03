# `dds1_pe_utils.py`

> Builds the DDS1 Periodontics (PE-01 … PE-06) coordinator progress workbook from the DASH CAF JSON export. It scores each checklist item with the published PE0x marking-sheet rules and tracks every student across sessions.

| | |
|---|---|
| **Added** | 2026-09-24 (see `_handover_docs/HANDOVER_dds1_pe_progress_report.md`) |
| **Public API** (`__all__`) | `PE_SESSIONS`, `PE_ITEMS`, `PE_FLAG_CONFIG`, `PE_MARKED_MIN_FRACTION`, `loadPeForms`, `scorePeForms`, `buildPeTables`, `validatePeScoring`, `buildDds1PeProgressReport` |
| **Imports from this codebase** | optional, lazy: `general_utils.EXCLUDED_STUDENT_NUMBERS` (falls back to `{40029860}`) |
| **Dependencies** | `json`, `re`, `math`, `numpy`, `pandas`, `openpyxl` (`Font` aliased `_XlFont`) |
| **Input** | `temp 2026 caf.json` |
| **Output** | `DDS1/DDS1 PE Progress Report.xlsm` (macro-enabled; `macroEnabled=False` → .xlsx) |
| **Run how** | `from dds1_pe_utils import *` → `buildDds1PeProgressReport("temp 2026 caf.json", "DDS1/DDS1 PE Progress Report.xlsx")` |

## Constants

| Name | Purpose |
|---|---|
| `PE_ITEMS` | 14 canonical checklist items: `itemId → (label, section, [normalised field-name aliases])`. They are matched by **criterion name**, because MC numbers differ between sessions. |
| `PE_SESSIONS` | For each code: `short` (S1…S6), `weightage`, `propWeights` (the scored items and their weights), optional `adjustRule` (`"up"` for PE-01) and `assumedScheme` (PE-06). |
| `PE_SAFETY_ITEMS` / `PE_DAMAGE_ITEMS` | The items whose bottom level is a safety event (Infection control, Instrument use) and the Major-damage items. |
| `PE_MARKED_MIN_FRACTION` | 0.5 — the share of the roster that must be scored before a session counts as marked (missing forms are only flagged after that). |
| `PE_FLAG_CONFIG` | Flag thresholds (see the handover doc, §7). |

## Functions

| Function | Returns / does |
|---|---|
| `loadPeForms(jsonPath, cohort, excludeStudents, sessions)` | Returns `(rosterDf, forms)`. Routes by **checklist code**, not `clinic_type` (some PE forms are saved as `CD`). Drops excluded students and the test account. Dates are Melbourne-local. |
| `scorePeForms(forms, sessions)` | Returns `(formsDf, itemsDf, adjustDf, dupDf)`. Keeps one form per student × session (assessor-submitted, then student-submitted, then latest `created_at`). Scores items for both the assessor and the student side. Computes Equal and Prop %. |
| `buildPeTables(roster, formsDf, itemsDf, sessions, flagConfig)` | Returns `(sessDf, progDf, fd)`: the session summary, within-session z-scores, trend and change, safety and damage events, missing sessions, self gap, and flag plus reasons. |
| `validatePeScoring(formsDf, expected)` | Compares the calculated session means with the published marking sheets. |
| `buildDds1PeProgressReport(...)` | Writes the 11-sheet workbook (Read Me, Overview, Progress Grid, Flags, Student Tracker, Item Pivot, Criterion x Session, Self vs Assessor, Adjustments, hidden TrackerData, hidden Lists) and returns a dict of the DataFrames. |

Internal helpers (underscore; not called from the notebook): `_norm`, `_localDate`, `_excludedStudents`, `_isTestAccount`, `_oNum`, `_checklistMeta`, `_scoreOption`, `_scale`, `_slope`, `_title`, `_header`, `_put`, `_widths`, `_sessLabel`, `_levelFill`, `_lineChart`, `_styleSeries`.

## Scoring in one line

The valid levels for an item are the options minus the row's `disabled_options`. Level = rank from the worst option (worst = 1). An out-of-rubric selection maps to the nearest valid level below it (S1: above it). Item % = level ÷ number of levels. Session % is the Equal mean or the Proportional weighted mean.

## Update 2026-09-24 (rev 4)

- New sheet **Student Charts**: one chart per student vs the cohort mean, A–Z, left→right then down. Data is on the hidden sheet **GridData**.
- **Student Tracker** has a clickable side list (A:B). The tracker content moved to column D onwards. Named ranges are `StudentPick` and `StudentPickList`.
- New helpers: `_smallTitle(chart, text, sizeHundredths, color)` and `_addVbaProject(xlsxBytes)`. New constant: `_VBA_PROJECT_B64`. New parameter: `buildDds1PeProgressReport(..., macroEnabled=True)`.
- VBA rebuild recipe: handover doc §13; sources in `_assets/dds1_pe_vba/`.

## Update 2026-10-27 — student-report scoring (PE + Cons Dent) and the CD section-scores workbook

Everything below is additive. The PE Progress Report workbook (`PE_SESSIONS`, `scorePeForms`, `buildDds1PeProgressReport`) is **unchanged**. PE and Cons Dent use completely separate scoring.

### A. PE form % for the student reports (`peFormPercent`)

Used by the DDS1 V2 student reports for the PE time-series panel and the Periodontics section page (`boh2_dds2_dds3_utils._v2ApplyPeScores`, `_addPeSectionPageV2`).

| Name | Purpose |
|---|---|
| `PE_WEIGHTS_PATH` | `"DDS1/DDS1 Perio DASH Forms.xlsx"`. Weights are read from its **Weighting** sheet (Session N = PE-0N; blank cell = item not scored that session, even if the MC is on the form). |
| `PE_LENIENT_CODES` | `("PE-01", "PE-02", "PE-03", "PE-04")`. Every later code uses strict levels. |
| `loadPeWeights(path=None, refresh=False)` | `{code: {itemId: weight}}`, cached. Falls back to `_PE_WEIGHT_ROWS_FALLBACK` (copy of the sheet as of 2026-10-27, incl. the reweighted PE-02: 10/10/10/20/20/10/10/10, no debridement/damage). |
| `peLevelPoints(rank, nLevels, strict)` | `(points, max)` for one item level (rank 1 = worst). |
| `peFormPercent(assessorData, assessorConfig, code, weights=None, lenientCodes=None, returnItems=False)` | Weighted % (0–100) for one PE checklist on one form, or `None` when no weighted item was answered. `returnItems=True` also returns the per-item rows. |
| `peSectionScores(assessorData, assessorConfig, code, ...)` | `(formPct, {section: (marks, weight)})` in `PE_SECTIONS` order. Sections add up to the form total. |

**Level → points.** Level = rank among the item's **enabled** options (`row_config` disabled options removed), so the O-key spelling (O1/O2/O3 vs O2/O4/O5) doesn't matter.

| Item type | Lenient (PE-01…PE-04) | Strict (PE-05 onwards) |
|---|---|---|
| 2-level (Lighting, Angulation, Finger rests) | 2 / 1 (out of 2) | 1 / 0 (out of 1) |
| 3-level (Seating, Posture, Infection control, Instrument use, Cheek retraction, Damage) | 3 / 2 / 1 (out of 3) | 2 / 1 / 0 (out of 2) |
| 4-level (none today) | 4 / 3 / 2 / 1 | 4 / 3 / 2 / 0 (out of 4) |
| 5-level debridement | 5 / 4 / 3 / 2 / 1 | 5 / 4 / 3 / 2 / 0 (out of 5) |

**Form %** = Σ(points ÷ max × weight) ÷ Σ(weights of answered weighted items) × 100. Out-of-rubric picks map **down** to the nearest valid level (PE-01: **up**, as its published sheet).

Example (student 1473122, PE-06, strict): Ergonomics 9/12 + Instrument Handling 12/12 + Quality of Scaling 49.6/66 + Damage 2.5/10 = **73.1**.

Validation (CAF export 5 Oct, assessor-submitted forms, per student): PE-01 100/100, PE-02 98/99 (1805234's form was edited after the sheet), PE-03 102/102, PE-04 101/101, PE-06 strict 101/102, PE-07 strict 100/100. PE-05 intentionally differs from the published lenient `DDS1_PE05.xlsx`. Every mismatch was a form-selection difference, not a scoring error.

### B. Cons Dent section scoring (Task 7 / Task 8 / mock / practice)

Deductive band scoring from **`DDS1/DDS1 Cons Dent CAF.xlsx`** (rubric tabs + GRADING SYSTEM tab). First added 2026-09-24 for Task 7 (`scoreTask7Section`, `scoreTask7Checklist`, `scoreTask7Forms`, `task7FormPercent`, `validateTask7Scoring`); extended on 2026-10-27:

| Name | Purpose |
|---|---|
| `TASK7_BANDS` | `bandKey → {column: (upper, lower)}`. Added `caoh` and `liner` (2 / 1.5–1 / ≤0.5; columns 1, 3, 5). Now only the **fallback**. |
| `CD_CAF_PATH`, `loadCdBands(path=None, refresh=False)`, `cdBands()` | Band tables read live from the CAF workbook rubric tabs (band row under the `1 2 3 4 5` column header; `≤ x` lower = next column's upper). `scoreTask7Section` now uses `cdBands()`. Parsed values = old `TASK7_BANDS` exactly. |
| `TASK7_SECTIONS` | `("Isolation", "Preparation", "CaOH cement", "Liner or base", "Matrix", "Restoration")`; `TASK7_CORE_SECTIONS` = the original four. `TASK7_SECTION_MAX` adds CaOH /2, Liner /2. |
| `TASK7_LAYOUT` | Static fallback layouts. Added Task 8.1 (= amalgam 7.2 form) and Task 8.2/8.3/8.4 (= adhesive 7.1/7.4 form; fields, disabled options and headers identical). |
| `CD_SECTION_CODE_RE`, `isCdSectionCode(code)` | Codes scored by section: `Task 7.x`, `Task 8.x`, `MA*`, `P*`, `AP*`. |
| `CD_HEADER_SECTIONS`, `cdLayoutFromConfig(cfg)` | Builds `[(section, bandKey, [MCs])]` from a form's own checklist **section headers** (Isolation, Preparation - adhesive/amalgam, Calcium hydroxide cement, Liner or base, Sectional matrix / Tofflemire placement, Restoration - composite/amalgam). Sub-headers are ignored. |
| `_cdLayout(code, row)` | Header-derived layout when `assessor_config` is present, else `TASK7_LAYOUT`. Used by `scoreTask7Forms`. |
| `scoreTask7Checklist(code, checklist, layout=None)` | Section rows now also carry `attempted` (`nReviewed > 0`). |

Rule (unchanged): the most severe error sets the band (start at its upper limit, not itself deducted); every other error deducts 0.25 (col 2/3) or 0.5 (col 4/5); floored at the band's lower limit. A section is **Incomplete** until every criterion is assessed (no O6/blank). Disabled-column picks snap to the nearest enabled column (ties → more severe).

In the student reports a section whose criteria are **all** Not Reviewed shows "–" (not attempted) instead of Incomplete; partly reviewed stays Incomplete. CaOH / Liner rows only appear for students who have one.

**Code structure in the data (CAF export 5 Oct) vs the CAF workbook TASKS tab.** One layout per code across all forms.

| Code | Sections in the DASH forms | Differs from the TASKS tab |
|---|---|---|
| Task 7.1 / 7.4, Task 8.2 / 8.3 / 8.4, MA3, P1 | Isolation · Prep adhesive · Sectional · Resto composite | 8.2: sheet adds CaOH + Liner · MA3: sheet column has no rubrics · P1: sheet has Isolation + Prep only |
| Task 7.2 / 7.5, Task 8.1 | Isolation · Prep amalgam · Tofflemire · Resto amalgam | 8.1: sheet adds CaOH + Liner |
| Task 7.3, P4 | Isolation · Resto amalgam | P4: sheet adds Liner + Tofflemire |
| P2 | Isolation · Resto composite | sheet adds Sectional |
| P3 | Isolation · Prep amalgam · Sectional · Resto composite | sheet has Isolation + Prep amalgam only |
| AP1 / AP2 | Isolation · Prep adhesive · CaOH · Liner · Sectional · Resto composite | AP1: sheet has no CaOH / Liner |

The forms are scored on the sections they actually have.

### C. Cons Dent section-scores workbook

Replicates `DDS1/DDS1_Task7_section_scores.xlsx` (that workbook had no generating code in the project) for any selection of codes.

| Function | Returns / does |
|---|---|
| `CD_CODE_GROUPS` | `task7`, `task8`, `mock` (MA*), `practice` (P*), `additional` (AP*) → (regex, label). Order = sheet order. Add new code types here. |
| `cdCodeGroup(code)` | Group key or `None`. |
| `collectCdForms(jsonPath, cohort="DDS1", include=("task7","task8"), submittedOnly=True, excludeStudents=None)` | One dict per form × code: date, student, assessor, layout, answers, fields, section scores, reflection / comments / clinical incident, record_id, form_id. Streams with `ijson` when installed. Drops excluded students and the test account. |
| `listCdCodeStructure(jsonPath, cohort, include="all", forms=None)` | DataFrame per code: group, name, forms, submitted, students, layout variants, MC count, sections with MC ranges. |
| `buildCdSectionScoresWorkbook(jsonPath, outPath=None, cohort="DDS1", include=("task7","task8"), submittedOnly=True, codeStructureSheet=True, excludeStudents=None)` | Writes the workbook and returns its path. Default path `DDS1/DDS1_CD_section_scores (<groups>).xlsx`. |
| `compareCdSectionWorkbooks(newPath, oldPath)` | Cell check of section scores / reviewed counts matched on (sheet, form_id). |

`include=` accepts `"all"`, a group key, an exact code, a regex, or a list of these.

```python
listCdCodeStructure("temp 2026 caf.json")                                   # what codes / sections exist
buildCdSectionScoresWorkbook("temp 2026 caf.json", include="task7")         # Task 7 only
buildCdSectionScoresWorkbook("temp 2026 caf.json", include=("task7", "task8", "mock"))
buildCdSectionScoresWorkbook("temp 2026 caf.json", include="all")           # Task 7, 8, MA, P, AP
buildCdSectionScoresWorkbook("temp 2026 caf.json", include=["Task 7.1", "MA3", r"^AP\d+$"],
                             outPath="DDS1/my_selection.xlsx")
```

Sheets:

| Sheet | Content |
|---|---|
| one per code (`Task_7.1`, `MA3`, `AP1` …) | One row per form (sorted student, date; same-session forms keep DASH order): date, student, student_number, assessor, submitted, `<Section> /max` + `<Section> reviewed` (n/N), MC1…MCn option keys, student_reflection, assessor_comments, clinical_incident, record_id, form_id. Fills: score green `E2EFDA` / Incomplete `F4B0A0`; O1 `E2EFDA`, O2 `FFF2CC`, O3 `FCE4D6`, O4 `F8CBAD`, O5 `F4B0A0`, O6 `F2F2F2`. |
| Consolidated | Student × code: every completed score per section (`"2; 2"`, date order), `Incomplete` when none, `—` when the code has no such section; `task_complete`; `n_forms` (forms for that student × code); `n_completed` (completed section scores — what the 2026-09 workbook's `n_forms` column actually held). |
| Code_Structure | `listCdCodeStructure` output (optional). |
| Band_Tables | Bands used by the selected codes, as loaded from the CAF workbook. |
| Criteria_Legend | code, MC, section, criterion text per code. |
| Method_&_Caveats | Method notes + selection and source/record count. |

Text fields: `assessor_comments` = all assessor `texts` keys except `clinical-incident*`; `clinical_incident` = `texts['clinical-incident-additional-details']`; `student_reflection` = student `texts['reflection']`.

Validation vs `DDS1_Task7_section_scores (new).xlsx` (Task 7 rebuild): 7,432/7,432 section cells match, Band_Tables and Criteria_Legend identical, task-sheet row order identical. The only Consolidated differences come from 12 forms that differ between the two exports (since unsubmitted / newly submitted, and the Test1 Student1 account the old file included). A full `include="all"` build takes about 15 s.

The two existing workbooks hold identical values: `(new)` is the untouched generated file (17 Sep); the other is the same file re-saved in Excel on 24 Sep (wider Consolidated columns, freeze pane moved to A215).

### Related changes in `boh2_dds2_dds3_utils.py` (DDS1 V2 student reports)

- `_v2ApplyPeScores` + `peScoring=True` on `buildStudentReportV2` / `buildEntireCohortStudentReportsV2`: PE points = `peFormPercent`.
- Periodontics section page (`_v2PeSectionLong`, `plotPeSectionPanel`, `_addPeSectionPageV2`) via `peSectionChart="heatmap"` (default) | `"bars"` | `"both"` | `None`.
- Cons Dent: the Task 7 page is now "Cons Dent Tasks 7 & 8 — Section Scores" and includes Task 8, MA, P and AP columns (date order); rows sized to the student (`_t7Sections`); all-Not-Reviewed sections dropped to "–" (`_t7Attempted`); CD time-series points use the section method for every `isCdSectionCode` code.
- `_computeSummaryMetrics(..., smileSquadAsAssessor=False)`: V2 passes `True`, so BOH2 student-submitted Smile Squad forms also count as assessor-submitted.
