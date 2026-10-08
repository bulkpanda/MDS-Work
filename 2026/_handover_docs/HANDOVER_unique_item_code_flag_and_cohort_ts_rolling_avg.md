# HANDOVER — Unique Item Code risk flag, Count-Pivot highlight modes, and cohort time-series score-graph parity (rolling avg + Sim stream colours)

**Date:** 2026-09-22
**Author session scope:** DDS2 Sim weekly flagging tweaks that grew into a cross-preset flag + two parity fixes on the cohort time-series PDF.
**Files changed:** `flagging_utils.py`, `boh2_dds2_dds3_utils.py`. **`main.ipynb` NOT edited** — every change is a default or a new opt-in field, so the existing notebook cells pick it up on re-run (flagging = cell 16, cohort time-series = cell 11).

**Backups (all in `_bak/`):**
- `flagging_utils.py.bak_20260922_004904` — before ALL flagging changes this session.
- `flagging_utils.py.bak_iccflags_20260922_015515` — before the cross-preset flag roll-out.
- `boh2_dds2_dds3_utils.py.bak_cohortts_20260922_010528` — before the cohort time-series changes.

**Verification:** static (`py_compile` on both files) + synthetic end-to-end runs on the Cowork VM (no live DB — the user's Postgres is on the UniMelb network and unreachable here). The VM cannot import the modules as-is (`win32com`, `arial.ttf`, `sklearn`, `psycopg`, `scipy`, `PyPDF2` absent); tests stubbed the Windows/ML-only imports, installed `scipy`/`psycopg[binary]`/`PyPDF2`/`sqlalchemy`, and pointed `variableUtils.itemSectionMappingFile` at the real `item_section_mapping.xlsx`. **Not yet run on the live DB / Windows — Kunal runs the cells.**

---

## PART A — Count-Pivot highlight modes: `zeros` and `column_gradient` (`flagging_utils.py`)

### Why
The **Item Code Count Pivot** sheet (Simulation → `count_pivot`, grouped by `item_code`) highlights "low" cells. For weekly sim each item code is a *different week*, so almost every count is **1** — a per-column percentile is degenerate (bottom-25% lands on the common value). The only meaningful signal is a **0** (a week the student missed). Kunal asked for (1) highlight only 0s, and (2) a percentile-based option that colours the whole column.

### What changed
`COUNT_HIGHLIGHT_MODES` gained two members; the dispatcher `_colorPivotByMode` gained two branches; two new render helpers + one colour helper were added. No existing mode changed.

```
COUNT_HIGHLIGHT_MODES = ("percentile", "mean_fraction", "mean_fraction_expected",
                         "mean_sd", "zeros", "column_gradient")
```

**New helpers** (module-level, near `_colorPivotBelowMeanFraction`):
- `_gradientHex(t)` → ARGB hex on a 3-stop **red→yellow→green** scale for `t∈[0,1]` (0 = worst/red `F8696B`, 0.5 = `FFEB84`, 1 = best/green `63BE7B`).
- `_colorPivotZeros(ws, pivotDf, data_start_col, data_start_row)` → red-fills **only** cells whose count `== 0`. Columns of all-1s show nothing.
- `_colorPivotColumnGradient(ws, pivotDf, data_start_col, data_start_row)` → per-column **heatmap**: every cell shaded by its **within-column percentile rank** (`col_vals.rank(method="average", pct=True)`), low→red … high→green, black text. A column where all values tie gets one mid colour (rank = 1.0).

**Dispatcher** (`_colorPivotByMode`) now:
```
if mode == "zeros":           _colorPivotZeros(...);          return
if mode == "column_gradient": _colorPivotColumnGradient(...); return
```
`resolveCountHighlightMode` validates against the tuple, so a typo still raises rather than silently falling back.

### Config / preset wiring
Both modes are selectable via the existing `FlaggingConfig.countHighlightMode`. **`dds2_sim` now defaults to `countHighlightMode="zeros"`** (its comment points at `"column_gradient"` and `"percentile"` as the alternatives). Every other preset is unchanged (`boh2_sim`/`boh2_clinic` keep `mean_fraction`, others `percentile`). The Section Count Pivot (Clinic) is untouched — it always uses `mean_fraction` × `behindRatio`.

Switch per run:
```python
PRESETS["dds2_sim"].copy(countHighlightMode="column_gradient")   # full heatmap
PRESETS["dds2_sim"].copy(countHighlightMode="percentile")        # old behaviour
```

### Verified
`zeros` reddens exactly the 0-cells and nothing else (all-1s columns clean); `column_gradient` shades every cell (12/12 in the test); `_gradientHex(0/0.5/1)` = `FFF8696B / FFFFEB84 / FF63BE7B`; bad mode raises; existing modes intact.

---

## PART B — "Unique Item Codes" Summary column + `low_item_code_count` risk flag (`flagging_utils.py`)

### Why
Kunal wanted a Summary risk column for the number of **distinct item codes** a student was assessed on (for weekly sim ≈ weeks attended), mirroring the existing Checklists/Classes columns and their flags.

### The value it uses
`getFlagDf` already computes, per student:
- `checklist_total` = every item-code assessment (repeats counted) — the plain "item code count".
- **`checklist_unique = len(set(_codeList))`** = **distinct** item codes, `scale…` rows excluded — this is the "unique item codes" value.

The new column/flag/threshold all read **`checklist_unique`**, NOT `checklist_total`. (These look near-identical for weekly sim because each week is a distinct code sat once; they diverge only when a code repeats.)

### What changed
1. **FlagSpec** (registry):
```python
"low_item_code_count": FlagSpec(
    "flag_low_item_code_count", "checklist_unique", "min_item_codes", "below",
    "Low IC", "Flag if fewer unique item codes (distinct checklists sat) than the minimum"),
```
2. **Threshold** (in `getFlagDf`'s `thresholds` dict): `"min_item_codes": _auto("checklist_unique", getattr(config, "minItemCodes", None))` — auto = cohort mean − `sdMultiplier`·SD (rounded; NaN-safe for a single-student cohort), overridden by `config.minItemCodes`.
3. **Config field** `FlaggingConfig.minItemCodes = None` (signature, `self.`, `copy()` passthrough, `describe()` row) — same pattern as `minChecklists`/`minClasses`.
4. **Summary column**: `checklist_unique` added to `_ckExtra` (so it appears right after Checklists, before Classes) and to `FRIENDLY` as **"Unique Item Codes"** (originally "Item Codes" — renamed 2026-09-22 to remove the count/unique ambiguity Kunal flagged).
5. **Cross-highlight**: when `flag_low_item_code_count` fires, the student's `checklist_unique` cell gets the red fill (same block as `low_checklist_count`/`low_class_count`).
6. **Opt-in registry**: added to `_OPT_IN_FLAGS` so it stays out of `_ALL_FLAGS` (clinic_full / at_risk_only unaffected); presets opt in explicitly.
7. **Legend**: automatic (the Legend sheet iterates the resolved FlagSpecs).

### Preset roll-out (2026-09-22)
Added `low_item_code_count` to **both `flags` and `highTierFlags`** (so it fires AND counts as high-risk) in:

| Preset | Cohort/context | minItemCodes |
|---|---|---|
| `dds2_sim` | DDS2 Simulation (cell 16) | **27** (Kunal-set, matches `minClasses`) |
| `boh2_sim` | BOH2 Simulation **and BOH1 Simulation** (BOH1 runs on `boh2_sim`) | None → auto |
| `boh2_clinic` | BOH2 Clinic | None → auto |
| `dds2_clinic` | DDS2 Clinic | None → auto |
| `dds3_clinic` | DDS3 Clinic | None → auto |

Untouched: `clinic_full`, `clinic_quick`, `sim_standard`, `at_risk_only`, `trends_only`.

**BOH1 note:** there is no `boh1`/`boh1_sim` preset; the notebook builds BOH1 Sim with `PRESETS["boh2_sim"].copy(...)`, so it inherits the flag automatically.

### How to enable it elsewhere / tune it
```python
base = PRESETS["boh2_sim"]
createFlaggingReport("BOH2", "Simulation",
    config=base.copy(
        flags         = base.flags + ["low_item_code_count"],       # already present now
        highTierFlags = base.highTierFlags + ["low_item_code_count"],# high-risk (drop for low-risk)
        minItemCodes  = 10),                                          # optional; None = auto
    period="SHY")
```
The **Unique Item Codes** column shows whenever `checklist_unique` is present (all cohorts); the *flag* is what makes it a red risk column and adds to the High Risk Flags count.

### Verified
Synthetic DDS2 Sim cohort: `checklist_unique` = {Dan:2, others:5}; with `minItemCodes=3`, `flag_low_item_code_count` fires for Dan only, his high-risk count increments, the "Unique Item Codes" cell is red (`FFC7CE`), others white; Legend documents it. All five presets resolve with the flag in `flags`+`highTierFlags`; `clinic_full`/`sim_standard` exclude it.

---

## PART C — Cohort time-series score-graph parity (`boh2_dds2_dds3_utils.py`, `buildCohortTimeSeriesPdf`)

Goal: make the **score scatter** in the cohort time-series PDF (cell 11) match the per-student V2 report's score graph. Only the score scatter changed; the 5 rubric panels, the Item Code counts table, purple missing-session dots, half-year divider and categorical x-axis are all kept.

### C1 — Rolling-average(3) line (Sim **and** Clinic)
New helper mirroring `_addTimeSeriesPageV2`'s "only addition":
```python
def _addRollingAvgToScatter(ax, df, xCategories, streamCohort=None):
    perDate = _v2SessionMeanByDate(df)          # per-date mean of assessed item scores (0-100)
    ...  reindex(xCategories) → rolling(3, min_periods=1).mean()
    ax.plot(xi, yi, "-", color=variableUtils.uniColor, linewidth=1.4, alpha=0.5,
            zorder=5, label="Rolling avg (3)")
    ax.legend(...)   # re-run so the new key joins the existing scatter legend
```
Called in **both** `buildCohortTimeSeriesPdf` layouts:
- combined branch: after `_drawScoresScatter(axes[0], …)`, before the rubric loop.
- split branch: on `scoreFig.axes[0]`, before `addPlotImage`.

Uses `_v2SessionMeanByDate(studentDataDf)` (same per-date session mean the V2 student report uses), so the cohort and per-student rolling lines are computed identically.

### C2 — Sim stream colour-coding / legend / labels
`buildCohortTimeSeriesPdf` previously called the scatter **without** `streamCohort`, so DDS2 Sim points were plain blue with 3-digit code labels. Now:
```python
simStreamCohort = cohort if (formType and str(formType).strip().lower().startswith("sim")) else None
```
is computed once and threaded into the combined `_drawScoresScatter(...)`, the split `plotStudentScoresTimeSeries(...)`, and both `_addRollingAvgToScatter(...)` calls. This activates the existing `streamCohort` path in `_drawScoresScatter` → `SIM_STREAM_COLORS` + `_shortStreamItemCode` + the stream legend proxies.

Result for DDS2 Sim (matches the student report exactly): points coloured by stream, labels `CD1/P1/FP1/E1`, legend `CD — Semester 1 Sim`, `P — Paediatric Dentistry Sim`, `FP — Fixed Prosthodontics Sim`, `E — Endodontics Sim`, plus `Rolling avg (3)`. Non-Sim runs and single-stream date-routed cohorts (BOH2/BOH1, `codePatterns=None`) fall through to plain colouring unchanged.

**Stream source** (`general_utils.SIM_STREAMS["DDS2"]`): `SEM1`→`2026-Week-*` (CD, blue `#0072B2`), `PAEDS`→`Paeds*` (P, green `#009E73`), `FP`→`FP-Week-*` (FP, vermilion `#D55E00`), `ENDO`→`Week-*` (E, purple `#CC79A7`). `SIM_STREAM_ABBREV = {"SEM1":"CD","PAEDS":"P","FP":"FP","ENDO":"E"}`.

### Decision (from Kunal, via question)
- Port scope: **rolling-avg line only** (NOT the FHY/SHY split, NOT dropping code labels). Keep item-code table etc.
- Rolling avg applies to **Sim + Clinic**; stream colours apply to **Sim** only.

### Traps
- `_streamForCode`/`_cohortStreamsSafe` are wrapped in try/except and degrade to plain colouring if `general_utils` can't import — so on a broken environment the scatter silently loses stream colours (this is why the Cowork VM test showed plain colours until `psycopg` etc. were installed). On Windows with all deps it colours correctly.
- The rolling line re-runs `ax.legend(...)`; the helper reproduces `_drawScoresScatter`'s own legend placement (stream vs non-stream) so keys aren't dropped.
- `addPlotImage`'s `pageSize` default is import-bound — the function already passes `pageSize=chartPageSize` explicitly; unchanged.

### Verified
With a real `general_utils`: stream map correct (SEM1/PAEDS/FP/ENDO), legend text exactly matches the student report screenshot, point labels `CD1/P1/FP1/E1`, rolling line drawn; `py_compile` OK for both layouts.

---

## Run notes
- Flagging: re-run **cell 16** — `createFlaggingReport("DDS2","Simulation", config=PRESETS["dds2_sim"], period="SHY")` now emits the zeros-highlighted Item Code Count Pivot and the Unique Item Codes risk column; the four other presets carry the flag too.
- Cohort time-series: re-run **cell 11** — Sim PDFs gain stream colours + rolling avg; Clinic PDFs gain the rolling avg.
- No `main.ipynb` edit required.

## Open / not done
- Not run on live Postgres / Windows (Cowork VM can't reach the DB). Kunal to confirm numbers and the rendered PDFs.
- `minItemCodes` left at auto for boh2_sim/boh2_clinic/dds2_clinic/dds3_clinic — tune per cohort once seen against live data.
- FHY/SHY split and label-free clean scatter were deliberately NOT ported to the cohort PDF (Kunal chose rolling-avg-only).
