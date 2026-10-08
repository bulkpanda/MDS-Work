# Handover — BOH1 Simulation flagging: own preset, student removals, Item Code Score Pivot

**Date:** 2026-09-30 · **Cohort:** BOH1 (Simulation) · **Files:** `variableUtils.py`, `flagging_utils.py`, `general_utils.py`, `main.ipynb` (cells 6, 15)
**Backups:** `_bak/{variableUtils.py,flagging_utils.py,main.ipynb}.bak_20260930_034610`, `_bak/{variableUtils.py,general_utils.py,main.ipynb}.bak_20260930_035845` (§8)
**Builds on:** `HANDOVER_boh2_flagging_summary_declining_itempivot.md`, `HANDOVER_unique_item_code_flag_and_cohort_ts_rolling_avg.md`, `flagging_system_handover.md`

---

## 1. Requests and outcome

| # | Request | Found | Change |
|---|---|---|---|
| 1 | Remove-student list for flagging reports | **Already existed**: `variableUtils.REMOVE_STUDENTS_DICT[cohort]`, applied in `createFlaggingReport` (cell 15) right after `getDataDf` | Added 5 BOH1 students (below) |
| 2 | Move entrustment from high-level flags to low-level (BOH1 Sim) | BOH1 Sim ran on `PRESETS["boh2_sim"]`, where `low_es` and `high_es_lvl1` are HIGH tier | New preset `boh1_sim`: both flags moved to `lowTierFlags`; BOH2 untouched |
| 3 | Item-code score pivot sheet | **Already existed**: `section_score_pivot` → for `formType=="Simulation"` it groups by `item_code` and is written as **"Item Code Score Pivot"** (`buildSectionScorePivot`) | Added `"section_score_pivot"` to `boh1_sim.sheets` |

User decisions (2026-09-30): new separate preset (don't edit `boh2_sim`); move **both** entrustment flags (`low_es` + `high_es_lvl1`).

## 2. Student removals (`variableUtils.py`)

Numbers matched by name from `boh1 student email list.csv`:

| Requested name | Roster name | Student number |
|---|---|---|
| Nazia | nazia popal | 1639983 |
| Ella | Ella Zou | 1756946 |
| Imijen | Imijen Ellis | 1766318 |
| Hanna Kaur | Hannah Kaur | 1895683 |
| Qosaay Oukal | Qossay Oukal | 1840287 |

```python
BOH1_REMOVED_STUDENTS = [1895048, 1895910, 1904651,
                         1639983,   # Nazia Popal   (added 2026-09-30)
                         1756946,   # Ella Zou      (added 2026-09-30)
                         1766318,   # Imijen Ellis  (added 2026-09-30)
                         1895683,   # Hannah Kaur   (added 2026-09-30)
                         1840287]   # Qossay Oukal  (added 2026-09-30)
```

**Scope of effect.** `REMOVE_STUDENTS_DICT["BOH1"]` is read by `createFlaggingReport` (cell 15) **and** `boh2_dds2_dds3_utils.py:913` (cohort reports). So these 5 students also drop out of any BOH1 report built through that path, not just flagging. This is separate from `general_utils.EXCLUDED_STUDENT_NUMBERS`, which deletes rows at the DB level for every cohort. Removal happens **before** thresholds are computed, so cohort-relative auto thresholds (mean − 1.5·SD) no longer include them.

## 3. `boh1_sim` preset (`flagging_utils.PRESETS`)

Inserted directly after `boh2_sim`. Diff vs `boh2_sim`:

| Field | boh2_sim | boh1_sim |
|---|---|---|
| `highTierFlags` | includes `low_es`, `high_es_lvl1` | `low_item_code_count, low_gr, low_score, low_checklist_count, low_class_count, clinical_incident` |
| `lowTierFlags` | `low_cs, low_ps, low_declining_*` | **`low_es, high_es_lvl1`**, `low_cs, low_ps, low_declining_es/gr/score` |
| `sheets` | legend, summary, level_distribution, count_pivot, gr_pivot, clinical_incidents | same + **`section_score_pivot`** (after count_pivot) |
| `minChecklists` / `minClasses` | 25 / 14 | `None` / `None` (auto) — carries the old cell-15 `.copy(...)` overrides |
| everything else | — | identical (`esThreshold=2`, `grThreshold=2.5`, `scoreThreshold=0.6`, `maxEsLvl1Pct=20`, `sdMultiplier=1.5`, `countLowPercentile=0.2`, `minForms=None`) |

Entrustment flags are still **computed and shown** (Summary cells, Legend). They only count toward `low_risk_flag_count` / the Low Risk column now, not High. `low_declining_es` was already low tier.

## 4. Notebook (`main.ipynb` cell 15)

```python
# before
createFlaggingReport("BOH1", "Simulation", config=PRESETS["boh2_sim"].copy(minForms=None, minClasses=None, minChecklists=None), period="SHY")
# after
createFlaggingReport("BOH1", "Simulation", config=PRESETS["boh1_sim"], period="SHY")
```
Output unchanged: `BOH1/BOH1 Simulation Flagging (2026) (SHY).xlsx`. To tweak a threshold for one run: `PRESETS["boh1_sim"].copy(minForms=10)`.

## 5. Item Code Score Pivot — how it's built (existing code, now enabled)

`_build_section_score_pivot_sheet` → `buildSectionScorePivot(cohortDf, "Simulation")`:
- Explodes each form's `scores` dict `{item_code: {"score": float}}` into long rows. Null or "Not Observed" items are skipped.
- `formType=="Simulation"` → `groupBy` item_code (Clinic → Section via `item_section_mapping.xlsx`).
- Pivot = student × item_code mean score, plus two totals: **Overall (per item)** and **Overall (per form)**. The per-form total matches Summary's Score and `low_score` (see `score-per-item-vs-per-form`). There is also a count pivot of scored items per cell and a cohort-average row. Written by `_writeScorePivotSheet` with sheet name "Item Code Score Pivot".
- `item_code_score_pivot` (the Clinic twin) is **not** used: it self-skips for Simulation because the names would collide.

## 6. Verification (2026-09-30, no live DB)

Run on the device with third-party/Windows imports auto-stubbed:
- `PRESETS["boh1_sim"].resolve_sheets()` gives 7 builders incl. `_build_section_score_pivot_sheet`. `resolve_tiers()` puts `flag_low_es` and `flag_high_es_lvl1` in LOW. `unclassified_flags()` returns `[]`.
- `PRESETS["boh2_sim"].highTierFlags` is unchanged (still includes `low_es`, `high_es_lvl1`).
- Synthetic Sim frame (12 students × 10 forms; student 0 with all-ES=1): `flag_low_es=True`, `flag_high_es_lvl1=True`, **high=0, low=2**. The workbook wrote sheets `Legend, Summary, Level Distribution, Item Code Score Pivot, Clinical Incidents`. Count/GR pivots were absent only because the synthetic frame lacked their inputs, which is unrelated to this change.
- `REMOVE_STUDENTS_DICT["BOH1"]` has 8 entries.

## 7. Open / gotchas
- Not yet run against live Postgres. Re-run cell 15 and confirm the 5 students are absent and "Item Code Score Pivot" appears.
- ~~Removals only partially applied~~ → superseded by §8 (complete removal at ingest).
- `boh1_sim` is a copy, so later edits to `boh2_sim` won't carry over.

---

## 8. Follow-up (same day): remove the students COMPLETELY from analysis

**Why.** `REMOVE_STUDENTS_DICT` was only applied in two places (`createFlaggingReport`, `getCohortReports` scale summary). Student reports (V1/V2/HTML), cohort time-series, weekly sim (`general_utils`), `boh1_utils` and the pivots use four separate query builders (`getWhereStatement`/`_where`, `boh1_utils` builder, weekly-sim builder, `getChecklistBank`), and none of them filtered. The old source-level delete in cell 6 was commented out, and its constant `EXCLUDED_STUDENT_NUMBERS` no longer existed (cell 19 and `dds1_pe_utils` referenced it with fallbacks).

**User decision.** Delete at ingest. Scope = **all 8 BOH1 removed students** (the 3 existing + 5 new). BOH2/DDS2 lists keep their current (flagging/scale-summary-only) behaviour.

**Changes**
1. `variableUtils.py` — new single source of truth:
   ```python
   EXCLUDED_STUDENT_NUMBERS = list(BOH1_REMOVED_STUDENTS)
   ```
   (re-exported through `general_utils`'s `from variableUtils import *`, so `from general_utils import EXCLUDED_STUDENT_NUMBERS` works again for `dds1_pe_utils` / cell 19).
2. `general_utils.py` — re-added helper (placed after `getDeleteSql`):
   ```python
   getDeleteStudentsSql(tableName, studentNumbers=None, colName="student_number")
   # -> "DELETE FROM rawform_forms_v3 WHERE student_number IN (1639983, 1756946, 1766318, 1840287, 1895048, 1895683, 1895910, 1904651);"
   # -> "" for an empty list (callers guard with `if sql:`); values int()-coerced, deduped, sorted
   ```
3. `main.ipynb` cell 6 `processForms()` — uncommented the delete right after `getDeleteSql`, inside the same `engine.begin()` transaction. Prints `rawform_forms_v3: removed N rows for 8 excluded students`.

**Data flow.** `rawforms` → (cell 6 insert) `rawform_forms_v3` → test-account delete → **excluded-student delete** → every report / pivot / flag / time-series. All report SQL reads `rawform_forms_v3` (`RAWFORM_FORMS_NAME` or `formsTable` default), so nothing downstream can see these students. The in-memory filters in cell 15 / `getCohortReports` are now redundant but harmless, so they were left in place.

**Reversibility.** The raw `rawforms` table is untouched. Remove a number from `BOH1_REMOVED_STUDENTS` (or from `EXCLUDED_STUDENT_NUMBERS`) and re-run cell 6. The insert re-populates the student's rows.

**Must-do.** Run **cell 6 before any report**. Until it runs, the live table still holds these students. `dds4_boh3_forms_v3` (cell 68) is not affected (BOH1 isn't in it). Cell 68 still has its own commented delete, which could now be re-enabled with the same helper if ever needed.

**Verified.** Helper output above for the 8 numbers and the empty-list case; `general_utils` imports cleanly with the constant exposed. Not executed against live Postgres.

---

## 9. Follow-up (same day): "Professionalism 1" sheet (BOH1 Sim)

**Request.** A sheet listing students and their forms on dates where professionalism was 1, with date, item codes, GR and comments.

**Change** (`flagging_utils.py` only; backup `_bak/flagging_utils.py.bak_20260930_071902`):
- New builder `_build_low_professionalism_sheet` registered as `"low_professionalism"` in `SHEET_REGISTRY`. It is **opt-in**: added to `_BOH2_ONLY_SHEETS` so it stays out of `_ALL_SHEETS`, which means no other preset changes. Enabled only in `PRESETS["boh1_sim"].sheets` (after `clinical_incidents`).
- Helpers: `_stripTags` (drops the `<b>Label: </b>` markup from the reflection composites) and `_formItemCodes` (`item_codes` list, falling back to the `scores` keys; `scale…` excluded; de-duplicated).
- Level configurable: `config.professionalismLevel` (default `1`, read with `getattr`, so no `FlaggingConfig` change was needed). The sheet name follows the level: `Professionalism {level}`.

**Sheet layout** — title row `BOH1 Simulation — Forms with Professionalism = 1 (N forms, M students)`, header on row 3, freeze panes at `C4`:

| ID | Student | Date | Item Codes | GR | ES | PS | Assessor | Clinic | Assessor Comments | Student Comments |
|---|---|---|---|---|---|---|---|---|---|---|
| 1001 | Stu 1 | 02/07/2026 | BOH1-0 | 3 | 3 | 1 | Dr A | Sim | Feedback: Late to class, no PPE. | Reflection: Will improve. |

- One row per **form** with PS = level. Sorted by student name, then date. Shading alternates per **student block**.
- Date = **Melbourne-local** (`datetimeutc` → `Australia/Melbourne`), formatted `dd/mm/yyyy`.
- Comments come from `assessor_reflection_full` / `student_reflection_full` (the dynamic all-text-keys composites from `getDataDf`), falling back to the plain `*_reflection` columns. Wrapped text.
- It uses the same `cohortDf` as the rest of the workbook, so the period filter, ignored dates and excluded students apply.

**Verified** on a synthetic Sim frame (8 students × 6 forms, PS = 1 on 6 forms for 2 students): the sheet is written last, with 6 rows. `2026-07-01T20:00Z` shows as 02/07/2026. Tags are stripped. `boh2_sim` and `_ALL_SHEETS` don't include it. Not yet run on live data (re-run cell 15).
