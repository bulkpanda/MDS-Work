# `osce_utils.py`

> Builds an OSCE **station workbook** and **analysis workbook** from a DASH OSCE v3 JSON dump (DDS2, DDS4, …), plus the BLR/harshness figures. Single public entry point `buildOsceWorkbook(...)`; the AMEE psychometric sheets are delegated to `osce_metrics.py`.
>
> **2026-09-09:** scoring is now **dynamic per MC item** (DDS4 has different option counts per item, even within one checklist). See `_handover_docs/HANDOVER_osce_dds4_dynamic_item_scoring.md`.

| | |
|---|---|
| **Lines** | ~915 |
| **Deps** | numpy, scipy (`stats`), matplotlib (Agg), openpyxl |
| **Imports from this codebase** | lazily imports `osce_metrics` inside `buildOsceWorkbook` |
| **Run how** | Imported by `main.ipynb` (cell ~34). Pure library, no `__main__`. |
| **Handover** | `_handover_docs/HANDOVER_osce_stationwise_blr_analysis.md` |

---

## 1. Purpose

OSCE = station-based practical exam. Each student rotates through numbered **stations**; at each, an assessor fills a **checklist** of criteria (`MC1..MCn`, n up to 14 in DDS4) plus a **global rating** (GR). A station number can host **several checklists**. The item list is read from `form_config.checklists.<ck>.fields` — no fixed item count (the old hard-coded `MC1..MC10` cap is gone).

This module turns the raw JSON into two workbooks (see the handover doc §7 for the full sheet inventory) and never touches a database.

---

## 2. Data & scoring rules (the load-bearing decisions)

- **Score by RANK, per item, by the `O`-key — not the label** (`itemScale` / `checklistItemScales`). `form_data.checklists.<ck>.MCn = {key, value}`; label text is unreliable (typo `"Unsatifactory"`, `Very Good` vs `Very good` casing, and `extra_config.options` maps differ per checklist). An item's **level = number of O-keys in its `extra_config.rubric[MCn]`** (excluding the `label` sub-key). Points by rank best→worst: **4-level `4/3/2/0`, 3-level `2/1/0`, 2-level `1/0`** (`LEVEL_POINTS`, `LEVEL_MAX`).
- **Different items in one checklist can have different levels** (DDS4 Fixed Prosth = 2- & 4-level; Removable Prosth = 2- & 3-level).
- **Equal weight via normalisation:** each item → `frac = points / itemMax`; **checklist `Score% = mean(answered item fractions) × 100`** (a 2-level item weighs the same as a 4-level item). For a uniform-level checklist this equals the old `pts/(n×max)` exactly.
- **GR normalised** to `5=Excellent .. 1=Fail` so BLR slope is positive; borderline grade = 2. Direction is set by `reverseGr` (True/False/`"auto"`, default auto): DDS2 stores `1=Excellent..5=Fail` → reversed (`maxGr+1-key`); **DDS4 stores `1=Fail..5=Excellent` → NOT reversed**. Auto decides from the scale's own labels (`GRADE_RANK`); a corrupt GR value (`[object Object]`, seen 12× in DDS4) is non-numeric so it drops out of BLR.
- **1-dp rounding is canonical for pass/fail**: `pct1(x)=round(x*100,1)`, `countBelow(scs, cutFrac)`; a student fails when `pct1(score) < cutPct`.

---

## 3. Function reference

| Function | Role |
|---|---|
| `isTestStudent(name)` | Drop dummy/model/test placeholders. |
| `loadRoster(path)` / `resolveIgnoreNames(nums, path)` | Map `student_number → student_name` from `studentEmailList.csv` (records are name-keyed). |
| `loadOsceRecords(srcPath, ignoreStudentNumbers=None, rosterPath=..., cohort=None)` | Submitted, real, non-ignored records. `cohort` (e.g. `"DDS4"`) keeps only records whose `session` contains it — a guard for a mixed-cohort JSON; there is no `cohort` field, `session` is the only marker. `buildOsceWorkbook` defaults it to `cohortLabel`; pass `cohort=""` to disable. |
| `_okeyNum(k)` · `checklistItems(cfg)` · `itemOptionOrder(rub)` | O-key ordering; item list from `fields`; an item's O-keys best→worst. |
| `itemScale(rubItem)` | `(keyPoints, maxPts, level, order)` for ONE item — points by rank per `LEVEL_POINTS`. |
| `checklistItemScales(cfg)` · `checklistOptionLabels(cfg)` · `levelsText(itemLevel)` | Per-item scales for a checklist; display label map; `"4-level"`/`"mixed 2/4"`. (Replaces the old `checklistScale`.) |
| `buildStationSpecs(records)` | Groups by (station, checklist); rows carry `points[i]` (rank pts, display), `frac[i]` (0..1, scoring/stats), `labels[i]`, `score` (mean of fracs), `gr` (reversed), texts. Spec dict adds `items, itemLevel, itemMax, scales, optLabels, levels`(text), `maxPerItem`(single max or `None` if mixed). |
| `computeBlr(rows, borderlineGr=2)` | `linregress(score~GR)`; returns `cut, cutPct, mean, sd, mean2sd, mean2sdPct, r2, p, grs, scs, valid`. Returns **`valid=False`** (NaN stats, `cutPct=None`) when `<2` paired GR+score points or `<2` distinct GR — no `linregress` on empty input. Callers skip BLR/analysis for `valid=False` stations (still shown in the station workbook). |
| `pct1`, `countBelow`, `gradientHex` | Rounding + fail-count + red→yellow→green colour helpers. |
| `cronbachAlpha(rows, items)`, `itemTotalCorrs(rows, items)` | Item-level reliability on the **normalised fractions** (comparable across levels); take the dynamic item list. |
| `buildBlrFigure(spec, blr, imgDir, borderlineGr)` | 4-panel PNG (scatter+regression, boxplot by GR, item analysis, histogram). |
| `computeAssessorHarshness(spec, blr)` / `buildHarshnessFigure(...)` | Per-assessor Δ% / ΔGR vs station mean + BLR residual + diverging-bar PNG. |
| `stationTitle(st, ck)` | Abbreviated sheet name via `CHECKLIST_ABBR` (e.g. `S1 IC`). |
| `buildOsceWorkbook(...)` | Orchestrates both workbooks; lazily calls `osce_metrics` for the AMEE sheets. |

---

## 4. `buildOsceWorkbook` — sheets it writes

**Station workbook:** Read Me · Station Summary (grade counts + Fails(BLR) + BLR Cut%; `Levels` column shows e.g. `mixed 2/4`) · detail sheets (dynamic MC columns; MC cells coloured by a red→green gradient on the item **fraction**, sorted by Score desc, Borderline/Fail Info last) · MC Item Stats (per-item `Level`, best→worst option counts, `Avg Points`, `Max`, `Avg %`) · Checklist Legend (per-item `Item Level`) · Assessors.

**Analysis workbook:** Read Me · Student x Station (3-colour fail pivot + legend) · BLR Analysis (banner-separated panels + figures) · [Station Metrics (AMEE)] · [BLR Cut per Circuit] · [Assessor Analysis (AMEE)] · Standard Setting (fail counts) · Assessor Grid (assessor names, red→green by mean %). Sheets in [brackets] are built by `osce_metrics`.

---

## 5. Gotchas

- **Only submitted forms** are analysed (`loadOsceRecords` drops `submitted != True`). A checklist-only station (no GR) or a GR-only station (no scored items) yields `computeBlr(valid=False)` and is kept in the station workbook but skipped in the analysis workbook — see `skippedAnalysis` in the return.
- **Score by `key` + rank, per item** (not by label). MC cell colour is now by the item fraction (red→green), so it stays correct across levels.
- **`maxPerItem` is `None` for a mixed-level checklist** — any consumer must handle that (only `osce_metrics.interGradeDiscrimination` uses it).
- Points are read by rank *position*, so relative spacing matters: 4-level is `4/3/2/0` (Borderline = 0.5 normalised), not linear.
- Output `.xlsx` often open in Excel → on `PermissionError` write a `…(refreshed).xlsx` sibling.
- `scipy` required. `importlib.reload(osce_utils)` picks up edits (reload `osce_metrics` too).
