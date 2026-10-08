# Handover — DDS3 Clinic flagging: Reportable Item Score Pivot + count-based ES level-1 flag

**Date:** 2026-10-01
**Cohort:** DDS3 (Clinic). All changes are opt-in; no other preset changes behaviour.
**Files changed:** `flagging_utils.py` only (4060 → 4141 lines).
**Backup:** `_bak/flagging_utils.py.bak_20261001_034606` (pre-session).
**Notebook:** `main.ipynb` **not edited**. Re-run the existing DDS3 flagging line (cell 15):

```python
createFlaggingReport("DDS3", "Clinic", config=PRESETS["dds3_clinic"], period="FHY")
```

---

## 1. What was asked

1. *"In flagging reports for DDS3 I want item code score pivot sheet but only with reportable items for DDS3."*
2. *"For ES1 levels add an option to threshold counts and not percentage. For DDS3 I want to keep leeway of 1 level 1 ES — if more than 1 level 1 then student be flagged."*

Decisions confirmed with the user during the session:

| Question | Decision |
|---|---|
| ES level 2 for DDS3 — % or count? | **Keep % (> 20%)**. Only level 1 moves to a count. |
| Which reportable list drives the pivot? | **Code constant `DDS3_REPORTABLE_ITEMS`** (not the Excel file). |
| The `"LA"` entry in `DDS3_REPORTABLE_ITEMS` (crashing two sheets) | **Remove `LA`** from the list. |

---

## 2. Summary of changes

| # | Change | Where | Scope |
|---|---|---|---|
| A | New **Reportable Item Score Pivot** sheet (Item Code Score Pivot filtered to reportable items, category-ordered) | `buildSectionScorePivot(..., reportableItems=)`, `_build_item_code_score_pivot_sheet`, config `itemScorePivotReportableOnly`, `reportableItems` | `dds3_clinic` only |
| B | Per-student **ES level counts** `es_lvl1_count … es_lvl4_count` on `flagDf` | `getFlagDf` | all cohorts (extra columns only — no flag reads them unless opted in) |
| C | New opt-in flags **`high_es_lvl1_count`**, **`high_es_lvl2_count`** + config `maxEsLvl1Count`, `maxEsLvl2Count` | `FLAG_REGISTRY`, `_OPT_IN_FLAGS`, `FlaggingConfig`, thresholds dict, Legend labels | `dds3_clinic` uses L1 only |
| D | `dds3_clinic`: `high_es_lvl1` (%) **replaced** by `high_es_lvl1_count` with `maxEsLvl1Count=1`, HIGH tier | `PRESETS["dds3_clinic"]` | DDS3 |
| E | **Bug fix:** removed `"LA"` from `DDS3_REPORTABLE_ITEMS` — it made `sorted(..., key=int)` raise, so **Reportable Items** and **Item Scale Distribution** were silently missing from every DDS3 workbook | `DDS3_REPORTABLE_ITEMS` | DDS3 (+ PDF reportable section) |

---

## 3. Architecture / data flow

```
cohortDf (one row per form; `scores` = {item_code: {"score": 0-1}}, `entrustment` 1-4)
   │
   ├── getFlagDf(cohortDf, "Clinic", PRESETS["dds3_clinic"])
   │      per student grp:
   │        es_dist  = % at each ES level          → es_lvl{1..4}_pct     (existing)
   │        es_cnt   = count at each ES level      → es_lvl{1..4}_count   (NEW, B)
   │      thresholds["max_es_lvl1_count"] = config.maxEsLvl1Count (=1)     (NEW)
   │      FlagSpec high_es_lvl1_count: es_lvl1_count  >  1   → flag_high_es_lvl1_count (HIGH)
   │      FlagSpec high_es_lvl2      : es_lvl2_pct    > 20%  → flag_high_es_lvl2       (LOW, unchanged)
   │
   └── saveFlagDfToExcel2(... config.sheets ...)
          "item_code_score_pivot" → _build_item_code_score_pivot_sheet
               config.itemScorePivotReportableOnly = True
               reportable = config.reportableItems or DDS3_REPORTABLE_ITEMS
               buildSectionScorePivot(cohortDf, groupBy="item_code", reportableItems=reportable)
                  └─ keep code if exact match OR numeric base ("511-2" / "511/x" → "511") is reportable
                  └─ columns ordered by category (Diagnostics → … → General) + Overall
               _writeScorePivotSheet(..., sheet="Reportable Item Score Pivot")
```

### DDS3 workbook sheet order (after this session)

`Summary` · `Reportable Items` · **`Reportable Item Score Pivot`** · `Item Scale Distribution` · `Item Scale Donuts` · `Section Comparison` · `Level Distribution` · `Section Score Pivot` · `Clinical Incidents` · `Legend`

(Before: `Reportable Items` and `Item Scale Distribution` were absent — see §6.)

---

## 4. Implementation details

### 4.1 Count-based ES flags (registry)

```python
"high_es_lvl1_count": FlagSpec(
    "flag_high_es_lvl1_count", "es_lvl1_count", "max_es_lvl1_count", "above",
    "ES L1 #", "Flag if the number of level-1 entrustment ratings is above X",
),
"high_es_lvl2_count": FlagSpec(
    "flag_high_es_lvl2_count", "es_lvl2_count", "max_es_lvl2_count", "above",
    "ES L2 #", "Flag if the number of level-2 entrustment ratings is above X",
),
```

- Direction `"above"` (strict `>`): `maxEsLvl1Count=1` ⇒ **0 or 1 L1 rating = not flagged; ≥ 2 = flagged** (the requested one-rating leeway).
- Can be promoted to `>=` per run via `inclusiveFlags=["high_es_lvl1_count"]` like any FlagSpec.
- Both keys are in `_OPT_IN_FLAGS`, so they are **not** in `_ALL_FLAGS` — presets built from `_ALL_FLAGS` (`clinic_full` etc.) are unaffected.

### 4.2 Counting (getFlagDf)

```python
es_dist = _lvl_dist(grp["entrustment"], [1, 2, 3, 4])           # existing %
_esVals = pd.to_numeric(grp["entrustment"], errors="coerce").dropna().astype(int)
es_cnt  = {lvl: int((_esVals == lvl).sum()) for lvl in [1, 2, 3, 4]}
...
for lvl, n in es_cnt.items(): rec[f"es_lvl{lvl}_count"] = n
```

- Counts **forms with an ES rating** at that level; blank/NaN ES is ignored (same denominator logic as the %).
- Respects every upstream filter (period FHY/SHY, `ignoreDates`, excluded students), because it runs on the already-filtered `cohortDf`.

### 4.3 FlaggingConfig additions

| Parameter | Default | Meaning |
|---|---|---|
| `maxEsLvl1Count` | `None` | Threshold for `high_es_lvl1_count` (flag if count > X) |
| `maxEsLvl2Count` | `None` | Threshold for `high_es_lvl2_count` |
| `itemScorePivotReportableOnly` | `False` | Item Code Score Pivot limited to reportable items; sheet renamed "Reportable Item Score Pivot" |
| `reportableItems` | `None` | `{category: [codes]}` override; `None` ⇒ `DDS3_REPORTABLE_ITEMS`. (Previously read via `getattr` by the Reportable Items sheet but never settable — now a real attribute.) |

- All four are carried by `copy()` and shown by `describe()`.
- **Guard:** if `high_es_lvl1_count` / `high_es_lvl2_count` is in `flags` while its max count is `None`, the constructor **raises** `ValueError` (otherwise the comparison against `None` would crash deep inside `getFlagDf`).
- Thresholds dict gains `max_es_lvl1_count`, `max_es_lvl2_count`; Legend labels "Max ES L1 count" / "Max ES L2 count".

### 4.4 Reportable filter in `buildSectionScorePivot`

New kwarg `reportableItems=None` (only meaningful with `groupBy="item_code"`):

```python
_repOrder = [str(c) for codes in reportableItems.values() for c in codes]
def _repMap(code):
    code = str(code).strip()
    if code in _repSet: return code
    base = code.split("/")[0].strip().split("-")[0].strip()
    return base if base in _repSet else None        # None ⇒ item dropped
```

- Non-reportable items are dropped **before** the per-form mean, so **both Overall columns are computed over reportable items only** (the sheet shows only the active one, per `scoreWeighting`).
- Variant codes are folded onto their reportable code (`511` and `511-2` on the same form both land in column `511`; the counts pivot shows 2).
- Columns: reportable codes that actually have scores, in `DDS3_REPORTABLE_ITEMS` order, then Overall. Never-assessed codes are **not** added as empty columns (unlike the count-based Reportable Items sheet).
- Colouring/legend reuse `_writeScorePivotSheet` unchanged (red ≤ score threshold, amber < cohort column avg, green ≥, grey not assessed, italic < 3 items, cohort-average row).
- If no reportable item is scored, the sheet is skipped with a printed message.

### 4.5 `dds3_clinic` preset diff

```python
flags = [..., "low_pt_seen",
         "high_es_lvl1_count",     # was "high_es_lvl1"
         "high_es_lvl2"],
sheets = ["summary", "reportable_items_pivot",
          "item_code_score_pivot",  # NEW (reportable-only)
          "item_scale_dist", ...],
maxEsLvl1Pct   = 0.0,               # now unused
maxEsLvl1Count = 1,                 # NEW
itemScorePivotReportableOnly = True,# NEW
highTierFlags  = [..., "low_pt_seen", "high_es_lvl1_count"],  # was high_es_lvl1
```

### 4.6 `DDS3_REPORTABLE_ITEMS` (current)

| Category | Codes |
|---|---|
| Diagnostics | 011, 012, 013, 015, 022 |
| Preventative | 114, 161 |
| Perio | 221, 222 |
| Oral Surg | 311 |
| Endodontics | 415, 416, 417, 418, 419, 445, 455 |
| Restorative | 511–515, 521–526, 531–535, 572, 586, 587 |
| Fixed Pros | 613, 615, 618, 625, 627, 643 |
| Pros | 711, 712, 719, 721, 722, 727, 728 |
| General | 965 |

Note: the code list still contains **572** and **627**, which are **not** in `DDS3 Reportable Item numbers.xlsx`; user chose the code constant as the source of truth.

---

## 5. Examples

### 5.1 Flag behaviour (synthetic test, ES per form)

| Student | ES ratings | `es_lvl1_count` | `es_lvl1_pct` | `flag_high_es_lvl1_count` |
|---|---|---|---|---|
| 1 | 1,3,3,3,4,3 | 1 | 16.7 | False (leeway) |
| 2 | 1,1,3,3,3,3 | 2 | 33.3 | **True** |
| 3 | 3,3,4,4,3,3 | 0 | 0.0 | False |
| 4 | 1,1,1,2,3,3 | 3 | 50.0 | **True** |

Under the old rule (`maxEsLvl1Pct=0.0`) student 1 would have been flagged.

### 5.2 Pivot payload

Input `scores` payloads:

```python
{"511": {"score": 0.8}, "511-2": {"score": 0.6}, "999": {"score": 0.1}, "LA": {"score": 1.0}}   # student A
{"011": {"score": 0.5}, "721/x": {"score": 0.9}}                                                 # student B
```

Reportable pivot:

| ID | Student | 011 | 511 | 721 | Overall (per form) |
|---|---|---|---|---|---|
| 1 | A |  | 0.70 |  | 0.70 |
| 2 | B | 0.50 |  | 0.90 | 0.70 |

`999` and `LA` dropped; `511-2` folded into `511`; `721/x` → `721`.

### 5.3 Using the option for another cohort

```python
cfg = PRESETS["dds2_clinic"].copy(
    flags=[f if f != "high_es_lvl1" else "high_es_lvl1_count" for f in PRESETS["dds2_clinic"].flags],
    highTierFlags=[f if f != "high_es_lvl1" else "high_es_lvl1_count" for f in PRESETS["dds2_clinic"].highTierFlags],
    maxEsLvl1Count=2,          # allow two L1 ratings
)
createFlaggingReport("DDS2", "Clinic", config=cfg, period="FHY")
```

Reportable-only score pivot for any cohort with its own list:

```python
cfg = PRESETS["boh2_clinic"].copy(itemScorePivotReportableOnly=True,
                                  reportableItems={"Restorative": ["511", "512"]})
```

---

## 6. Bug found & fixed — `LA` in `DDS3_REPORTABLE_ITEMS`

- `"LA": ['LA']` had been added to the constant. `_buildItemCountPivot` / `_build_reportable_items_pivot_sheet` / `_buildItemScaleDist` sort codes with `key=lambda x: int(x)` → `ValueError: invalid literal for int() with base 10: 'LA'`.
- `saveFlagDfToExcel2` **catches and prints** per-sheet exceptions, so the workbook still saved — just without **Reportable Items** and **Item Scale Distribution**. Easy to miss in the notebook output.
- Fix (user's choice): remove `LA` from the list (commented in code). If LA is ever wanted back, change the two sort keys to something like `key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x)` first.

---

## 7. Verification

Run in the Cowork VM against synthetic data (live Postgres not reachable; `win32com` stubbed, Lato font substituted for Arial):

- `PRESETS["dds3_clinic"]` resolves: count flag present, in HIGH tier; `copy()` preserves new attributes.
- Constructor raises when a count flag is active with a `None` max.
- `getFlagDf` → counts and flag values per §5.1.
- Full `saveFlagDfToExcel2` build read back with openpyxl: **10 sheets, no sheet failures**; Summary column "ES L1 #"; Legend rows `Max ES L1 count | > 1` and tier row `High | ES L1 #`.
- Reportable pivot per §5.2; unfiltered pivot (no `reportableItems`) unchanged.
- **Regression:** for all 10 other presets, new vs pre-session `getFlagDf` output is **identical** (`assert_frame_equal`, after dropping the new `es_lvl*_count` columns).

---

## 8. Gotchas

- `maxEsLvl1Pct` is still set on `dds3_clinic` but **unused** (the % flag is no longer active). Don't read it as the live rule — the Legend shows the count rule.
- Count rule is **not normalised by number of forms**: a student with many forms has more chances to collect L1s. This is deliberate (user's fixed leeway), but worth stating when sharing the workbook.
- `es_lvl*_count` columns are now on `flagDf` for **every** cohort (harmless; not shown unless a count flag is active).
- The pivot folds variant codes onto the reportable base; a code like `5110` will **not** match `511` (base split is only on `-` and `/`).
- Pre-existing: `low_checklist_count` is in `dds3_clinic.flags` but not in `highTierFlags`/`lowTierFlags` → shown in Summary, excluded from both risk counts (prints a WARNING). Not changed.

---

## 9. Open

- Not run against live DB — re-run the DDS3 FHY line and check the Reportable Item Score Pivot columns look right on real codes, and that Reportable Items / Item Scale Distribution now appear.
- Decide tier for `low_checklist_count` in `dds3_clinic` (currently unscored).
- `DDS3_REPORTABLE_ITEMS` vs `DDS3 Reportable Item numbers.xlsx` mismatch (572, 627) — confirm with coordinator which is current.
