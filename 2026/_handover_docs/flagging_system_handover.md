# Flagging System Handover — PRP Section

**Date:** 2026-07-02 (updated 2026-07-02 with DDS2 Clinic team changes)  
**Files touched:** `flagging_utils.py`, `main.ipynb` (cell 22)  
**Purpose:** Student at-risk flagging + Excel dashboard for Progress Review Panel (PRP) reports

---

## 1. What This System Does

For a given cohort (e.g. DDS2) and form type (Clinic or Simulation), it:

1. Pulls submitted assessment data from the DASH API via `getDataDf(engine, cohort, filters)`
2. Computes per-student aggregate stats: scale averages, trend slopes, first/last-third splits, level distributions, role/patient breakdown, clinical incident counts
3. Evaluates a configurable set of **flags** against those stats
4. Writes a multi-sheet **Excel workbook** — sheets are also configurable
5. Output path: `{cohort}/{cohort} {formType} Flagging (2026).xlsx`

---

## 2. File Structure

```
flagging_utils.py        # All flagging logic — imports into main.ipynb via getDataDf etc.
main.ipynb               # Notebook — cell 22 is "Build a PRP section"
Utils.py                 # Shared helpers: createTable, _loadSectionMapping, _mergeSection, etc.
variableUtils.py         # Shared variable definitions
item_section_mapping.xlsx  # Maps item codes → clinic sections (used for Clinic formType)
```

`flagging_utils.py` is **not** imported with `from flagging_utils import *` — it must be manually run or imported. Check how the notebook loads it (likely a cell near the top).

---

## 3. Architecture

```
FlaggingConfig
  ├── flags: List[str]      →  resolves via FLAG_REGISTRY  →  FlagSpec / CustomFlagSpec
  ├── sheets: List[str]     →  resolves via SHEET_REGISTRY →  _build_*() functions
  └── threshold overrides   →  passed into getFlagDf()

PRESETS: Dict[str, FlaggingConfig]   (named ready-to-use configs)

getFlagDf(cohortDf, formType, config)
  └── returns (flagDf, compDf, thresholds)

saveFlagDfToExcel2(flagDf, compDf, thresholds, cohortDf, filepath, formType, cohort, config)
  └── loops config.sheets → calls each _build_*() function
```

### Key design decisions

- **Registry pattern**: flags and sheets are registered by short string key. Adding either = one new dict entry + optionally a new function. Nothing else needs changing.
- **`FlaggingConfig.copy(**overrides)`**: presets are immutable starting points — callers override specific fields without touching the preset definition.
- **Summary sheet is config-aware**: `FLAG_COLS` and friendly column names are derived from the active flag specs at render time, so new flags appear automatically.
- **Legend sheet is config-aware**: threshold rows are derived from active `FlagSpec` entries (deduped by `thresh_key`), so it always reflects what was actually run.
- **All metrics are always computed** in `getFlagDf` regardless of selected flags — computation is cheap and this keeps the aggregation loop simple.

---

## 4. FLAG_REGISTRY

Located at module level in `flagging_utils.py`. Each entry maps a short key to a `FlagSpec` or `CustomFlagSpec`.

### FlagSpec (simple threshold comparison)

```python
@dataclass
class FlagSpec:
    name: str        # column written to flagDf, e.g. "flag_low_es"
    col: str         # column in flagDf to compare, e.g. "avg_es"
    thresh_key: str  # key in thresholds dict, e.g. "es"
    direction: str   # "below" or "above"
    label: str       # short Excel header, e.g. "Low ES"
    description: str # Legend sheet text
```

Logic applied: `flagDf[name] = flagDf[col] < thresholds[thresh_key]`  (or `>` if direction is "above")

### CustomFlagSpec (arbitrary function)

```python
@dataclass
class CustomFlagSpec:
    name: str
    fn: Callable   # fn(row: pd.Series, thresholds: dict) -> bool
    label: str
    description: str = ""
```

### All current flags

| Key | Type | Column | Threshold key | Direction |
|-----|------|--------|---------------|-----------|
| `low_es` | FlagSpec | `avg_es` | `es` | below |
| `low_gr` | FlagSpec | `avg_gr` | `gr` | below |
| `low_ts` | FlagSpec | `avg_ts` | `ts` | below |
| `low_cs` | FlagSpec | `avg_cs` | `cs` | below |
| `low_ps` | FlagSpec | `avg_ps` | `ps` | below |
| `low_score` | FlagSpec | `avg_score` | `score` | below |
| `low_form_count` | FlagSpec | `form_count` | `forms` | below |
| `declining_es` | FlagSpec | `es_slope` | `slope` | below |
| `declining_gr` | FlagSpec | `gr_slope` | `slope` | below |
| `declining_score` | FlagSpec | `score_slope` | `slope` | below |
| `no_improvement_es` | CustomFlagSpec | — | — | `last_third_es <= first_third_es + margin` |
| `no_improvement_gr` | CustomFlagSpec | — | — | `last_third_gr <= first_third_gr + margin` |
| `low_operator_pct` | FlagSpec | `pct_operator` | `min_operator_pct` | below |
| `high_fta` | FlagSpec | `pct_fta` | `max_fta_pct` | above |
| `clinical_incident` | CustomFlagSpec | — | — | `ci_count > 0` |
| `low_pt_seen` | FlagSpec | `patient_seen` | `min_pt_seen` | below |
| `high_es_lvl1` | FlagSpec | `es_lvl1_pct` | `max_es_lvl1_pct` | above |

> **`low_pt_seen`** — added for DDS2 Clinic team (2026-07). Replaces `high_fta` as a more clinically meaningful attendance metric. Auto-threshold: cohort mean − 1 SD.  
> **`high_es_lvl1`** — added for DDS2 Clinic team (2026-07). Fires if >X% of ES ratings are level 1 (not yet ready — below standard for DDS2 level). Default threshold: 20%.  
> **`high_fta`** and **`low_ts`** — remain in `FLAG_REGISTRY` but are excluded from `dds2_clinic` preset. Still available for other presets.

---

## 5. SHEET_REGISTRY

```python
SHEET_REGISTRY = {
    "summary":            _build_summary_sheet,
    "scale_trends":       _build_scale_trends_sheet,
    "level_distribution": _build_level_distribution_sheet,
    "comparison":         _build_comparison_sheet,        # "Item Comparison" or "Section Comparison"
    "count_pivot":        _build_count_pivot_sheet,       # "Item Code Count Pivot" or "Section Count Pivot"
    "gr_pivot":           _build_gr_pivot_sheet,          # "Item Code GR Pivot" or "Section GR Pivot"
    "clinical_incidents": _build_clinical_incidents_sheet,
    "legend":             _build_legend_sheet,
}
```

All builders share this signature:

```python
def _build_*(writer, flagDf, compDf, cohortDf, thresholds,
             cohort, formType, config, mappingFile=None):
    ...
```

Sheet names for `comparison`, `count_pivot`, `gr_pivot` are dynamic — they switch between "Item Code ..." and "Section ..." based on `formType`.

---

## 6. FlaggingConfig

```python
FlaggingConfig(
    flags,              # List[str] — keys from FLAG_REGISTRY
    sheets,             # List[str] — keys from SHEET_REGISTRY, in output order
    esThreshold=None,   # None = auto (cohort mean − 1 SD)
    grThreshold=None,
    tsThreshold=None,
    csThreshold=None,
    psThreshold=None,
    scoreThreshold=None,
    minForms=None,      # None = auto (cohort mean − 1 SD)
    slopeThreshold=0.0, # flag if slope < this (0 = any decline)
    improvementMargin=0.0,
    behindRatio=0.5,    # item/section flagged if count < cohort_avg * ratio
    minOperatorPct=50.0,
    maxFtaPct=30.0,
    # ── Added 2026-07 for DDS2 Clinic team ──
    info_flags=None,    # List[str] — flag keys shown in Excel but NOT counted in risk_score
                        #   e.g. info_flags=["low_cs"] → CS shown in blue, not red/green
    minPtSeen=None,     # None = auto (cohort mean − 1 SD); used by low_pt_seen
    maxEsLvl1Pct=20.0,  # used by high_es_lvl1: flag if es_lvl1_pct > this
)
```

### `info_flags` — info-only flags

Flags listed in `info_flags` must also appear in `flags`. They are:
- **Computed and written** to flagDf like any other flag
- **Shown in the Summary sheet** with blue cell styling (not red/green)
- **NOT counted** in `risk_score`
- **Listed** in the Legend sheet under "Info Flags (not counted in risk score)"

Use case: `low_cs` in `dds2_clinic` — visible to subject coordinators for context, but excluded from the overall at-risk score so it doesn't inflate a student's risk ranking.

### Methods

| Method | What it does |
|--------|-------------|
| `resolve_flags()` | Returns `List[FlagSpec\|CustomFlagSpec]` for active flags. Raises `KeyError` if a key isn't in `FLAG_REGISTRY`. |
| `resolve_sheets()` | Returns `List[Callable]` for active sheets. Raises `KeyError` if a key isn't in `SHEET_REGISTRY`. |
| `copy(**overrides)` | Returns a new `FlaggingConfig` with all settings inherited except what you override. |
| `describe()` | Prints all active flags, sheet order, and threshold values to stdout. |

---

## 7. Thresholds Dict

`getFlagDf` builds this and passes it to every sheet builder:

```python
thresholds = {
    "es":               float,   # ES avg threshold
    "gr":               float,   # GR avg threshold
    "ts":               float,
    "cs":               float,
    "ps":               float,
    "score":            float,
    "forms":            int,     # min form count
    "slope":            float,   # 0.0
    "improvement_margin": float, # 0.0
    "behind_ratio":     float,   # 0.5
    "min_operator_pct": float,   # e.g. 65.0
    "max_fta_pct":      float,   # e.g. 30.0
    # Added 2026-07
    "min_pt_seen":      float,   # auto = cohort mean − 1 SD if config.minPtSeen is None
    "max_es_lvl1_pct":  float,   # config.maxEsLvl1Pct, default 20.0
}
```

---

## 8. Presets

```python
PRESETS = {
    "clinic_full":   # All 17 flags, all 8 sheets. Clinic thresholds (ES 2.3, GR 2.5, minForms 12)
    "clinic_quick":  # 5 flags, 2 sheets (summary + legend). Fast triage.
    "sim_standard":  # 9 flags (no operator/FTA), 6 sheets. Sim-appropriate, minForms 8.
    "at_risk_only":  # All 17 flags, 1 sheet (summary only). Fastest at-risk list.
    "trends_only":   # 5 decline/improvement flags, 3 sheets. Trend-focused.
    "dds2_clinic":   # DDS2 Clinic team preset (added 2026-07 per team request).
}
```

### `dds2_clinic` preset — detail

Requested by DDS2 Clinic team (email, 2026-07). Changes from `clinic_full`:

| Change | Detail |
|--------|--------|
| `low_ts` **removed** | Not appropriate at DDS2 clinic level; flag definition kept in registry |
| `high_fta` **removed** | Replaced by `low_pt_seen` — more clinically meaningful |
| `low_pt_seen` **added** | Fires if patients seen < auto-threshold (cohort mean − 1 SD) |
| `high_es_lvl1` **added** | Fires if >20% of ES ratings are L1 (below standard for DDS2) |
| `low_cs` → **info flag** | Shown in Excel (blue) for subject coordinators, NOT counted in `risk_score` |

Usage:

```python
# Run with DDS2 preset
createFlaggingReport("DDS2", "Clinic", config=PRESETS["dds2_clinic"])

# Tighten the ES L1 threshold
cfg = PRESETS["dds2_clinic"].copy(maxEsLvl1Pct=15.0)
createFlaggingReport("DDS2", "Clinic", config=cfg)

# Remove info flag behaviour (count CS in risk_score)
cfg = PRESETS["dds2_clinic"].copy(info_flags=[])
createFlaggingReport("DDS2", "Clinic", config=cfg)
```

Access via `from flagging_utils import PRESETS` or directly if already in namespace.

---

## 9. flagDf Schema

One row per student. Key columns:

```
student_number, student_name
form_count, operator_count, support_count, pct_operator
patient_seen, patient_fta, pct_patient_seen, pct_fta
ci_count
avg_es, avg_gr, avg_ts, avg_cs, avg_ps, avg_score
es_slope, gr_slope, score_slope
first_third_es, last_third_es, first_third_gr, last_third_gr
es_lvl1_pct ... es_lvl4_pct
gr_lvl1_pct ... gr_lvl5_pct
ts_lvl1_pct ... ts_lvl4_pct
cs_lvl1_pct, cs_lvl2_pct
ps_lvl1_pct, ps_lvl2_pct
flag_low_es, flag_low_gr, ...   (bool — one per active flag)
risk_score                       (int — sum of all flag booleans)
flags_detail                     (str — comma-joined flag names that fired)
```

### compDf Schema

One row per (student, item_code) for Simulation or (student, section) for Clinic:

```
student_number, student_name
item_code  OR  section
student_count, cohort_avg_count, pct_of_cohort, behind
```

---

## 10. main.ipynb — Cell 22

```python
def createFlaggingReport(cohort, formType, config=None, filters=None):
    if config is None:
        config = PRESETS["clinic_full"]
    if filters is None:
        filters = {"type": formType}

    cohortDf = getDataDf(engine, cohort, filters=filters)
    # removes students in REMOVE_STUDENTS_DICT[cohort]
    cohortDf["scores"] = cohortDf.apply(lambda row: calcScore(row, SCORE_MAP), axis=1)

    flagDf, compDf, thresholds = getFlagDf(cohortDf, formType=formType, config=config)

    saveFlagDfToExcel2(
        flagDf, compDf, thresholds, cohortDf,
        filepath=f"{cohort}/{cohort} {formType} {clinic or ''}Flagging (2026).xlsx",
        formType=formType, cohort=cohort, config=config,
    )
```

`getDataDf`, `calcScore`, `SCORE_MAP`, `REMOVE_STUDENTS_DICT`, `engine` are defined in earlier notebook cells.

---

## 11. Usage Examples

### Run with a preset

```python
createFlaggingReport("DDS2", "Clinic")                                    # clinic_full default
createFlaggingReport("DDS2", "Clinic",      config=PRESETS["clinic_quick"])
createFlaggingReport("DDS2", "Simulation",  config=PRESETS["sim_standard"])
createFlaggingReport("BOH1", "Simulation",  config=PRESETS["sim_standard"])
createFlaggingReport("DDS3", "Clinic")
```

### Override one field from a preset

```python
# Stricter GR threshold, fewer min forms
cfg = PRESETS["clinic_full"].copy(grThreshold=2.3, minForms=8)
createFlaggingReport("BOH2", "Clinic", config=cfg)
```

### Filter by clinic sub-specialty

```python
createFlaggingReport("DDS3", "Clinic",
    filters={"type": "Clinic", "clinic": "Fixed Pros"})
createFlaggingReport("DDS3", "Clinic",
    filters={"type": "Clinic", "clinic": "Endo"})
```

### Select specific flags

```python
cfg = FlaggingConfig(
    flags=["low_es", "low_gr", "high_fta", "clinical_incident"],
    sheets=["summary", "legend"],
    esThreshold=2.3, grThreshold=2.5, minForms=12,
)
createFlaggingReport("DDS2", "Clinic", config=cfg)
```

### Select specific sheets

```python
cfg = PRESETS["clinic_full"].copy(
    sheets=["summary", "scale_trends", "legend"]   # skip pivots and CI sheet
)
createFlaggingReport("DDS2", "Clinic", config=cfg)
```

### Remove a flag or sheet from a preset

```python
cfg = PRESETS["clinic_full"].copy(
    flags=[f for f in PRESETS["clinic_full"].flags
           if f not in ("clinical_incident", "high_fta")],
    sheets=[s for s in PRESETS["clinic_full"].sheets
            if s != "clinical_incidents"],
)
```

### Inspect a config before running

```python
PRESETS["clinic_full"].describe()
cfg.describe()
```

---

## 12. How to Add a New Flag

**Step 1** — Add to `FLAG_REGISTRY` in `flagging_utils.py`:

```python
# Simple threshold comparison
"high_support_pct": FlagSpec(
    "flag_high_support_pct",   # name written to flagDf
    "pct_operator",            # column to compare
    "max_support_pct",         # key in thresholds dict (add this key too if new)
    "above",                   # direction
    "Hi Support%",             # short Excel label
    "Flag if too many forms as Support Operator",
),

# Custom function
"low_late_gr": CustomFlagSpec(
    "flag_low_late_gr",
    fn=lambda row, t: row["last_third_gr"] < t["gr"],
    label="Low Late GR",
    description="Flag if last-third GR is below threshold",
),
```

**Step 2** — If using a new `thresh_key`, add it to the `thresholds` dict inside `getFlagDf`.

**Step 3** — Add to a preset or pass via `config.copy(flags=[..., "high_support_pct"])`.

The new flag column automatically appears in the Summary sheet and Legend — no other changes needed.

---

## 13. How to Add a New Sheet

**Step 1** — Write the builder function in `flagging_utils.py`:

```python
def _build_my_sheet(writer, flagDf, compDf, cohortDf, thresholds,
                    cohort, formType, config, mappingFile=None):
    df = flagDf[["student_name", "risk_score"]].copy()
    df.to_excel(writer, sheet_name="My Sheet", index=False, startrow=2)
    ws = writer.sheets["My Sheet"]
    _styleHeader(ws, 1, 2, f"{cohort} {formType} — My Sheet")
    _styleColumnHeaders(ws, 3, ["student_name", "risk_score"])
    # ... body styling ...
```

**Step 2** — Register it:

```python
SHEET_REGISTRY["my_sheet"] = _build_my_sheet
```

**Step 3** — Add to a config:

```python
cfg = PRESETS["clinic_full"].copy(
    sheets=PRESETS["clinic_full"].sheets + ["my_sheet"]
)
```

---

## 14. Scale Reference

| Scale | Range | Notes |
|-------|-------|-------|
| ES (Entrustment) | 1–4 | 1=not ready, 2=direct supv, 3=periodic supv, 4=indirect supv |
| GR (Global Rating) | 1–5 | 1=Unsatisfactory, 2=Borderline, 3=Satisfactory, 4=Good, 5=Excellent |
| TS (Time Management) | 1–4 | 1=not completed, 2=safe to leave, 3=completed, 4=completed+records |
| CS (Communication) | 1–2 | 1=communicates, 2=matches style + active listening |
| PS (Professionalism) | 1–2 | 1=attends, 2=presents professionally |
| Score (Checklist) | 0–1 | Done well=1.0, Done=0.8, Mostly=0.6, Sometimes=0.4, Not done=0.0 |

---

## 15. Colour Logic Summary

| Colour | Trigger |
|--------|---------|
| Red | Below threshold / flag fired |
| Amber | Within 10% above threshold (warning zone) |
| Green | At or above threshold / flag clear |
| **Blue** | **Info flag fired** — shown for context, not counted in `risk_score` |
| White | Info flag not fired |
| Risk gradient | Summary sheet `risk_score` column: white→red as score rises |
| Pivot red | Bottom 25th percentile per column in count pivots |
| GR pivot: red/amber/green | `< 2.5` / `< 3.0` / `>= 4.0` |
| Level dist bad levels | `> 20%` = red, `> 10%` = amber (ES L1, GR L1–L2, TS L1, CS/PS L1) |
| Level dist good levels | `> 50%` = green (ES L3–L4, GR L4–L5, TS L3–L4) |

---

## 16. Dependencies

```python
# flagging_utils.py imports
import pandas as pd, numpy as np, matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import Callable, List, Optional
import variableUtils
from Utils import (_loadSectionMapping, _mergeSection, createTable,
                   addPlotImage, getBannerDrawer, getmodeArgs,
                   readDf, runDdl, toInt, autoFitColumns)
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side, GradientFill
from openpyxl.utils import get_column_letter
```

`item_section_mapping.xlsx` must be present in the working directory for Clinic formType (used by `_loadSectionMapping(None)`).

---

## 17. Known Gotchas

- `saveFlagDfToExcel2` signature changed — old calls passing explicit threshold kwargs will break. All thresholds now go through `FlaggingConfig`.
- `getFlagDf` no longer accepts `esThreshold=`, `grThreshold=` etc. as direct kwargs — pass a `config` object instead.
- The `comparison` sheet builder silently returns early if `compDf` is empty (e.g. no item codes in data).
- `count_pivot` and `gr_pivot` builders also return early if the pivot is empty.
- Sheet names for `comparison`, `count_pivot`, `gr_pivot` are dynamic strings — don't hardcode them when post-processing the workbook.
- `_ALL_FLAGS` and `_ALL_SHEETS` are computed at import time from the registries. If you add entries to `FLAG_REGISTRY` or `SHEET_REGISTRY` after module load, update any presets that use `_ALL_FLAGS` / `_ALL_SHEETS`.
- `info_flags` entries must also be present in `flags` — they are not auto-added. A flag only in `info_flags` but not `flags` is silently ignored.
- `low_pt_seen` requires column `patient_seen` in `flagDf`. If the data API doesn't return this column (e.g. for Simulation form type), the threshold computation falls back to `0.0` and the flag will never fire.
- `high_es_lvl1` requires column `es_lvl1_pct` in `flagDf` — this is always computed in `getFlagDf` regardless of active flags.
