# BOH2 Clinic Flagging — Summary Columns, Low+Declining Flag, Item-Code Pivot

**Date:** 2026-08-19
**File touched:** `flagging_utils.py` (only)
**Cohort:** BOH2 Clinic (`PRESETS["boh2_clinic"]`) — the two new Summary columns compute cohort-wide but are additive
**Backup:** `flagging_utils.py.bak_20260819_011822` (pre-session)
**Notebook:** no change — re-run `main.ipynb` cell 15 (`createFlaggingReport("BOH2", "Clinic", config=PRESETS["boh2_clinic"])`); the preset carries every change.

**Read this first if:** a BOH2 workbook shows new "Checklists"/"Classes" columns, a `Low+↓…` flag you don't recognise, or a second "Item Code Score Pivot" sheet.

Builds directly on the 2026-08-18 work — see `HANDOVER_dds2_clinic_flagging_fhy.md`. The Pt-Seen-Operator gate, `scoreWeighting`, inclusive thresholds and the Section Score Pivot are all from that session and unchanged here.

---

## 0. Summary

Four changes, all requested against BOH2 and all scoped to `boh2_clinic` (bar the two additive Summary columns):

| # | Change | Scope | Behaviour change on other presets? |
|---|---|---|---|
| 1 | **Two new Summary columns** — Checklists (config total/unique) + Classes (distinct dates) | `flagDf` cohort-wide; shown on every Summary sheet | Additive columns only; no flag/threshold moves |
| 2 | **Low+Declining flags** replace the standalone declining flags | `boh2_clinic` only | **No** — kept out of `_ALL_FLAGS`, so `clinic_full`/`at_risk_only`/`dds2_clinic` are byte-identical |
| 3 | **Pt Seen = Operator only** | already cohort-wide since 2026-08-18 | No change — verified only |
| 4 | **Item Code Score Pivot** sheet for Clinic | `boh2_clinic` only | **No** — kept out of `_ALL_SHEETS`, added explicitly to boh2 |

**Follow-up (2026-08-19, same session).** The **Simulation** Summary now hides the seven
Clinic-only stat columns — `Operator`, `Support`, `% Oper`, `Pt Seen (Op)`, `Pt Seen (any)`,
`Pt FTA`, `% FTA` — because a sim form has no operator role and no patient, so they were all
zero/meaningless. Gated on `formType == "Simulation"` in `_build_summary_sheet` (`_opCols = []`),
so it applies to every sim preset (`sim_standard`, `boh2_sim`); Clinic is unchanged and still shows
all seven. The cross-highlight blocks all guard on `in SUM_COLS`, so they simply no-op. Checklists
and Classes still show in sim. Backup `flagging_utils.py.bak_20260819_*` (second one of the day).

**Follow-up 2 (2026-08-19, same session).** The Operator gate now also applies to **patient FTA**,
not just patient seen. An FTA logged while the student was only the Support Operator double-counts
the chair the same way, so `patient_fta` / `pct_fta` are now Operator-gated via the same
`requireOperatorForPtSeen` switch (cohort-wide, default True; `False` restores the old any-role
count). New `patientFtaMask(grp, requireOperator=True)` helper and a `patient_fta_any_role` audit
column; Summary shows `Pt FTA (Op)` + `Pt FTA (any)`, mirroring `Pt Seen (Op)/(any)`. Forms with no
role field (final-year templates) stay exempt and still count. The Legend "Pt Seen / FTA counts" row
covers both. Affects any preset using `high_fta` (clinic_full, clinic_quick, dds3_clinic) — the FTA
percentage they flag on is now Operator-only. Verified: Operator FTA counts, Support-Operator FTA
excluded from the gated count but kept in `(any)`, no-role FTA exempt, `requireOperator=False`
reproduces the old total.

**Follow-up 3 (2026-08-19, same session).** The ungated **`Pt Seen (any)` and `Pt FTA (any)`
columns were removed from the Summary** — with the Operator gate in place they were noise. Both
`patient_seen_any_role` / `patient_fta_any_role` are still computed on `flagDf` (available for audit
or a future sheet) but no longer shown; the Summary carries only `Pt Seen (Op)` and `Pt FTA (Op)`,
and `% FTA` is the Operator-gated count over all forms. (Supersedes the "shows both columns" wording
in Follow-ups 1 and 2 above.)

**Follow-up 4 (2026-08-19, same session).** Added an **Item Code Count Pivot** sheet for Clinic — the
count twin of the Item Code Score Pivot, so Clinic now has per-item-code counts as well as
per-section (`Section Count Pivot`). Same pattern: `_buildCountPivot(..., groupBy="item_code")` (new
arg), a new `_build_item_code_count_pivot_sheet`, and the shared `_writeCountPivotSheet` renderer
extracted from `_build_count_pivot_sheet` so the two count sheets can't drift. Registered as
`item_code_count_pivot`, kept out of `_ALL_SHEETS` (now via `_BOH2_ONLY_SHEETS`), added to
`boh2_clinic` next to the Item Code Score Pivot. Skipped for Simulation (the normal Count Pivot is
already named "Item Code Count Pivot" there — running it too would duplicate the sheet).

**Follow-up 5 (2026-08-19, same session).** Added **`low_checklist_count` and `low_class_count`
flags** (both `FlagSpec`, `below`) for the two Summary counts, **high tier**, on the **Sim** preset
`boh2_sim` only (user: "only for Sim"). `low_checklist_count` tests `checklist_count` (the resolved
count the Summary shows, per `checklistCountMode`) against `min_checklists`; `low_class_count` tests
`n_classes` against `min_classes`. Both thresholds are auto = cohort mean − `sdMultiplier`·SD via
`_auto` (rounded, so no single-student `int()` crash), overridable with new config fields
`minChecklists` / `minClasses`. getFlagDf now writes a resolved `checklist_count` column (mode-aware)
and Summary shows/flags/cross-highlights that single column (red when flagged). Kept out of
`_ALL_FLAGS` (`_OPT_IN_FLAGS`), so no other preset changes — `sim_standard` (DDS2 sim), all clinic
presets and `clinic_full` are untouched. Verified: fires on a 1-checklist/1-class student, quiet for
a high-volume one, counts into `high_risk_flag_count`, both flags resolve into the high tier with zero
unclassified across all presets.

**Design rule for this session: zero blast radius outside BOH2.** New flags and the new sheet are registered (so they are usable) but deliberately excluded from the "all flags"/"all sheets" lists, then opted into by `boh2_clinic` alone. Verified by a no-op regression on every other preset.

---

## 1. Two new Summary columns — Checklists and Classes

### What they mean

- **Checklists** — how many *checklists* (scored item-codes) the student completed. A "checklist" is one scored item-code on a form, the same unit the Item Code Score Pivot and `_itemCodeCounts` use. Two counts are always computed:
  - `checklist_total` — every item-code assessment, **repeats included**;
  - `checklist_unique` — **distinct** item-codes.
  Which one Summary shows is `config.checklistCountMode` (`"total"` default, or `"unique"`). Header reads `Checklists (tot)` / `Checklists (uniq)` accordingly.
- **Classes** (`n_classes`) — number of **distinct session dates**, i.e. how many classes/clinic sessions the student attended. Two forms on the same day count once.

### Implementation (`getFlagDf`, per-student loop)

```python
# A "checklist" is one scored item-code on a form (repeats included in _total,
# distinct in _unique). Scale rows ("scale…") are excluded — same rule as
# _itemCodeCounts. "Classes" = distinct session dates on the MELBOURNE-LOCAL date.
_codeList = []
if "item_codes" in grp.columns:
    for _codes in grp["item_codes"]:
        if isinstance(_codes, str):
            try: _codes = json.loads(_codes)
            except Exception: _codes = None
        if isinstance(_codes, (list, set)):
            _codeList.extend(str(c) for c in _codes
                             if c and not str(c).startswith("scale"))
checklist_total  = len(_codeList)
checklist_unique = len(set(_codeList))
_localDates = (pd.to_datetime(grp["datetimeutc"], utc=True, errors="coerce")
               .dt.tz_convert("Australia/Melbourne").dt.date)
n_classes = int(_localDates.dropna().nunique())
```

`rec` gains `checklist_total`, `checklist_unique`, `n_classes`. Both counts live in `flagDf` regardless of the mode, so switching the config never re-runs the aggregation.

> **TRAP — Classes uses the MELBOURNE-LOCAL date, not the raw UTC one.** DASH stores UTC; a late-afternoon Melbourne session sits on the previous UTC day, so a naive `.dt.date` would split one class into two (or merge a boundary pair). Same trap called out for the FHY/SHY selector and the weekly-sim `datetimeutc::date` note. Verified: two forms at 09:00 and 14:00 Melbourne on 1 Apr collapse to one class.

### Rendering (`_build_summary_sheet`)

```python
_ckMode  = str(getattr(config, "checklistCountMode", "total")).strip().lower()
_ckCol   = "checklist_unique" if _ckMode == "unique" else "checklist_total"
_ckExtra = [c for c in (_ckCol, "n_classes") if c in flagDf.columns]   # guarded
SUM_COLS = _ID_COLS + ["form_count"] + _ckExtra + ["operator_count", ...]
```

The columns sit immediately after **Forms**. `_ckExtra` is guarded on column presence, so an older `flagDf` still builds.

> **Architectural decision — checklist = item-code, not form.** `form_count` ("Forms") already counts forms, so a form-level "checklists" column would duplicate it and "unique forms" would be meaningless. Item-code is the non-redundant unit and makes total-vs-unique meaningful (the same procedure repeated vs distinct procedures). Confirmed with the user before building.

### API

```python
FlaggingConfig(..., checklistCountMode="total")   # "total" | "unique"; RAISES on anything else
config.checklistCountMode                          # normalised lower-case
PRESETS["boh2_clinic"].copy(checklistCountMode="unique")   # switch per run
```

`flagDf` columns: `checklist_total`, `checklist_unique`, `n_classes`.

---

## 2. Low+Declining flags — fire only when BOTH low AND declining

### The problem with the standalone declining flags

`declining_es` / `declining_gr` / `declining_score` fire on **any** negative slope. A strong student who dips slightly still lights up, which is noise — a high performer trending down is not an at-risk student. The BOH2 request: flag a declining trend **only** when the student is also below the metric threshold. *"A high score declining shouldn't flag."*

### The three new registry flags

Custom flags (`CustomFlagSpec`), so the "low" and "declining" tests read from the **same** `thresholds` dict the standalone flags use — no new thresholds, no drift:

```python
"low_declining_es": CustomFlagSpec(
    "flag_low_declining_es",
    fn=lambda row, t: bool(pd.notna(row.get("avg_es")) and row["avg_es"] < t["es"]
                           and pd.notna(row.get("es_slope")) and row["es_slope"] < t["slope"]),
    label="Low+↓ES",
    description="Flag if ES avg is below threshold AND the ES trend is declining "
                "(a high-but-declining student does not flag)",
),
# low_declining_gr  -> avg_gr < t["gr"]      and gr_slope    < t["slope"]
# low_declining_score-> avg_score < t["score"] and score_slope < t["slope"]
```

- **Low** reuses the same `es`/`gr`/`score` thresholds as `low_es`/`low_gr`/`low_score` (Score follows `scoreWeighting`, since `avg_score` does). Strict `<` — boh2 is not in `inclusiveFlags`.
- **Declining** reuses `t["slope"]` (default `0.0` → any strictly-negative slope).
- **NaN slope counts as not declining** — a one-form student has no trend, so `pd.notna(...slope)` guards it. Verified: single-form low-ES student does **not** flag.

### Truth table (verified end-to-end)

| Student | avg_es | es trend | `low_declining_es` |
|---|---|---|---|
| Alice | 1.23 (< 2) | declining | **fires** |
| Bob | 3.5 (≥ 2) | declining | no — high-but-declining |
| Cara | 1.23 (< 2) | improving | no — not declining |
| Dan | 1.0 (< 2) | single form, NaN slope | no — no trend |

### Preset swap (`boh2_clinic` only)

`declining_es`/`gr`/`score` → `low_declining_es`/`gr`/`score` in **both** `flags` and `lowTierFlags`. They stay low-tier (early-warning), so `low_risk_flag_count` behaviour is preserved. The standalone flags remain in the registry for every other preset.

### Keeping it BOH2-only

```python
# low_declining_* are BOH2-opt-in: keep them out of the "all flags" presets
_ALL_FLAGS = [k for k in FLAG_REGISTRY.keys() if not k.startswith("low_declining_")]
```

So `clinic_full` and `at_risk_only` (which use `_ALL_FLAGS`) keep the standalone `declining_*` behaviour and gain nothing. `dds2_clinic`/`dds3_clinic` have explicit flag lists and are untouched.

> **Architectural decision — combined flag, not two AND-ed columns.** A single boolean per metric keeps the Summary readable and the risk count honest (one concern = one flag). The two inputs stay visible on the Scale Trends sheet (`ES Avg`, `ES Slope`), so a coordinator can still see *why* it fired.

---

## 3. Pt Seen = Operator only — already done (verified)

No code change. `requireOperatorForPtSeen` defaults `True` on `FlaggingConfig`, and `boh2_clinic` does not override it, so a "patient seen" form counts only when the student was the **Operator** (forms with no role field are exempt — final-year templates). Confirmed:

```python
PRESETS["boh2_clinic"].requireOperatorForPtSeen        # True
getFlagDf(...)[2]["pt_seen_operator_only"]             # True (recorded on the Legend)
```

Summary carries both `Pt Seen (Op)` and `Pt Seen (any)`; the gap is the "logged a patient while Support Operator" volume. See §2 of the 2026-08-18 handover for the full mechanism.

---

## 4. Item Code Score Pivot — the per-item view for Clinic

### What it is

The Section Score Pivot groups the 0–1 checklist score by **Section** for Clinic and by **item_code** for Simulation. BOH2 wanted the item-code granularity for Clinic too — *"an item code pivot sheet for clinic as well, we are doing only for sim."* This adds a second sheet, **Item Code Score Pivot**, that groups by `item_code` even in Clinic mode. It sits right after the Section Score Pivot.

### `buildSectionScorePivot` gained a `groupBy` override

```python
buildSectionScorePivot(cohortDf, formType="Clinic", mappingFile=None, groupBy=None)
#   groupBy="item_code" -> force item-code grouping (even for Clinic)
#   groupBy="section"   -> force Section grouping
#   groupBy=None        -> historical default (Section for Clinic, item_code otherwise)

useSection = (groupBy == "section") or (groupBy is None and formType == "Clinic")
```

### New builder + shared renderer

The rendering body (cohort-average row, red/amber/green/grey cells, `<3`-item italics, the two Overall columns, the notes) was extracted verbatim into `_writeScorePivotSheet(...)` so the Section and Item-Code sheets **cannot drift**:

```python
def _build_section_score_pivot_sheet(...):      # Section (or item_code for Sim), unchanged output
    pivot, groupCol, counts = buildSectionScorePivot(cohortDf, formType, mappingFile)
    if pivot.empty: return
    sheet = f"{'Item Code' if formType=='Simulation' else 'Section'} Score Pivot"
    _writeScorePivotSheet(writer, pivot, groupCol, counts, thresholds, cohort, formType, config, sheet)

def _build_item_code_score_pivot_sheet(...):    # NEW — always item_code
    if formType == "Simulation":                # Sim's Section pivot already IS item_code
        print("[item_code_score_pivot] skipped — Simulation already groups by item_code"); return
    pivot, groupCol, counts = buildSectionScorePivot(cohortDf, formType, mappingFile, groupBy="item_code")
    if pivot.empty: return
    _writeScorePivotSheet(writer, pivot, groupCol, counts, thresholds, cohort, formType, config, "Item Code Score Pivot")
```

Registered as `SHEET_REGISTRY["item_code_score_pivot"]`.

### Keeping it BOH2-only + placement

```python
# item_code_score_pivot kept out of _ALL_SHEETS so clinic_full / dds2_clinic are unchanged.
_ALL_SHEETS = [k for k in SHEET_REGISTRY.keys() if k != "item_code_score_pivot"]

def _sheetsWith(exclude=(), insertAfter=None, insert=()):
    """Drop `exclude` from _ALL_SHEETS and slot `insert` right after `insertAfter`."""
    ...

# boh2_clinic:
sheets = _sheetsWith(exclude=["reportable_items_pivot","item_scale_dist","operator_by_clinic"],
                     insertAfter="section_score_pivot", insert=["item_code_score_pivot"])
```

Result order: `… Section Score Pivot, Item Code Score Pivot, Clinical Incidents, …`.

> **Architectural decisions.**
> - **Shared renderer, not a copy** — the memory note about `risk_report.py` duplicating a header map and breaking is the cautionary tale; one renderer means the two pivots always agree.
> - **Skipped for Simulation** — the Section pivot already produces an "Item Code Score Pivot" there, so running the new builder too would collide on the sheet name. Guarded with an early return.
> - **`_sheetsWith` helper** rather than string concatenation, so the sheet lands next to its twin instead of at the end of the workbook.

---

## 5. API changes — quick reference

```python
# FlaggingConfig
FlaggingConfig(..., checklistCountMode="total")   # "total" | "unique"; validated, RAISES otherwise
config.checklistCountMode                          # normalised
# carried through .copy()

# flagDf new columns
checklist_total, checklist_unique, n_classes

# FLAG_REGISTRY new keys (BOH2-opt-in, out of _ALL_FLAGS)
low_declining_es, low_declining_gr, low_declining_score   # cols flag_low_declining_*

# Sheet
SHEET_REGISTRY["item_code_score_pivot"] = _build_item_code_score_pivot_sheet   # out of _ALL_SHEETS
buildSectionScorePivot(..., groupBy="item_code"|"section"|None)
_writeScorePivotSheet(writer, pivot, groupCol, counts, thresholds, cohort, formType, config, sheet)
_sheetsWith(exclude, insertAfter, insert)
```

All public names have no leading underscore where `main.ipynb` calls them (`buildSectionScorePivot`); the pure-internal helpers (`_writeScorePivotSheet`, `_sheetsWith`, the sheet builders) keep the underscore because they are only reached through the registry / other module code, never a notebook cell.

---

## 6. What changes on a BOH2 workbook re-run today

1. **Summary gains two columns** after Forms: `Checklists (tot)` and `Classes`.
2. **The three `↓ES` / `↓GR` / `↓Score` flag columns are replaced** by `Low+↓ES` / `Low+↓GR` / `Low+↓Score`. A student who was flagged only for a mild decline while scoring well **will no longer flag**, so expect **fewer** low-risk flags than the previous BOH2 run.
3. **A new "Item Code Score Pivot" sheet** appears after "Section Score Pivot".
4. Everything else — thresholds, Pt Seen, all other sheets, and every non-BOH2 preset — is unchanged.

To count checklists as distinct codes instead of total: `PRESETS["boh2_clinic"].copy(checklistCountMode="unique")`.

---

## 7. Verification

No live database (the user's Postgres is localhost). Verified against synthetic frames carrying the exact `getDataDf` column set, driving the **real** `getFlagDf` / `saveFlagDfToExcel2` and reading the workbooks back with `openpyxl` — **28 assertions, all passing**:

- **Low+declining (item 2):** the four-student truth table above (low+declining fires; high+declining, low+improving, and single-form/NaN-slope all no-fire); the standalone `flag_declining_es` is absent from the BOH2 `flagDf`; `flag_low_declining_es` resolves into the low-risk tier.
- **Checklists + Classes (item 1):** exact counts on hand-built students — total (repeats in, `scale…` out), unique (distinct), and same-day forms collapsing to one class across a Melbourne-vs-UTC boundary; the config total→unique switch flips the Summary header and value; an invalid `checklistCountMode` raises.
- **Item Code pivot (item 4):** the sheet is present and distinct from Section Score Pivot; its header carries item codes (`101`) while the Section sheet carries sections (`Restorative`); a full BOH2 workbook builds every sheet without a swallowed per-sheet exception.
- **Pt Seen (item 3):** `requireOperatorForPtSeen is True`; `thresholds["pt_seen_operator_only"] is True`.
- **No-op regression:** `clinic_full` and `at_risk_only` carry **no** `low_declining_*` and **no** `item_code_score_pivot`; `dds2_clinic` still has `declining_es` and neither new feature. Every one of the nine presets passes `resolve_flags` / `resolve_sheets` / `resolve_tiers` with **zero unclassified flags**.
- **Static:** `py_compile` clean; full diff against the pre-session file reviewed hunk-by-hunk — every change maps to one of the four items, no stray edits.

---

## 8. Gotchas / Open

- **`Classes` is on the Melbourne-local date.** If a future puller stores local time instead of UTC, drop the `tz_convert` — otherwise it would double-shift.
- **Checklist counts exclude `scale…` codes**, matching `_itemCodeCounts`. A future scale prefix change must update both.
- **The Item Code pivot is skipped for Simulation** (the Section pivot already is item-code there). If BOH2 ever runs this preset in Simulation mode, that is why the sheet is absent — by design, not a bug.
- **BOH2-only by request.** DDS2/DDS3 still use the standalone `declining_*` flags and have no Item Code Score Pivot. Mirroring to DDS2 is a two-line change per item (swap the flag keys in `flags`/`lowTierFlags`; add `item_code_score_pivot` via the same `_sheetsWith` call) if the team asks.
- **Not run against live Postgres** — re-run `main.ipynb` cell 15 and sanity-check §6.
- Pre-existing, not touched: `getFlagDf`'s `forms` threshold `int(mean - std)` still raises on a single-student cohort; `saveFlagDfToExcel2` still prints rather than raises per-sheet exceptions.
