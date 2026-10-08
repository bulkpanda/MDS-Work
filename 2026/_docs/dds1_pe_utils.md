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
