# Handover — DDS3 role-code normalisation in flagging sheet builders

**Date:** 2026-08-28
**Code file touched:** `flagging_utils.py`
**Docs touched:** `_docs/flagging_utils.md` (§0), `_handover_docs/INDEX.md`
**Cohorts affected:** DDS3 Clinic (visible symptom); fix is cohort-generic
**Status:** Applied, `py_compile` clean, smoke-tested against real DDS3 CAF rows. Not yet run end-to-end through `main.ipynb` against live Postgres.

---

## 1. Symptom

For **DDS3 Clinic**, the `Item Scale Distribution` and `Item Scale Donuts` sheets came out empty — a
table of reportable items with every O1–O6 count at 0 (dist) and a grid of blank donut cells (donuts).

DDS3 is the only preset that renders these two sheets: `dds2_clinic` and `boh2_clinic` explicitly
exclude `item_scale_dist`, `item_scale_donuts`, `operator_by_clinic`, and `reportable_items_pivot`
from their `sheets` lists, so the latent bug never surfaced until DDS3's `sheets` list turned them on.

## 2. Root cause — role CODE vs LABEL, again

Four sheet builders filter to **Operator forms** by testing the *label* `"Operator"`, but the v3 CAF
stores role as the *code* `"O"` (Support Operator = `"SO"`, Observer = `"OB"`). Every Operator form
therefore failed the filter and was dropped, so the builders saw zero rows.

This is the same CODE-vs-LABEL bug class that was fixed in the patient-count masks on 2026-08-18
(`normalizeRole` folds `O`/`SO`/`OB` → `Operator`/`Support Operator`/`Observation`). The masks were
fixed; these four sheet builders were missed because they run on `cohortDf` *after* `getFlagDf`, and
**`cohortDf["role"]` is never normalised in place** — `normalizeRole` was only ever applied locally
inside the masks (lines 115, 132) and inside `getFlagDf`'s per-group summary counts (line 3263).

### Data evidence (from `fetched_rows 2026 caf.xlsx`, DDS3 rows)

- `form_context.role` values across 600 DDS3 forms: `{"O": 567, "SO": 33}` — no `"Operator"` label anywhere.
- The v3 loader (`general_utils._flattenChecklistsSqlExpr`) already flattens the checklist scores to the
  top level of `assessor_data` in the old v2 shape `{item_code: {MCk: "O4"}}`, merged onto the raw
  nested `radio/texts/scales/checklists/multi-select` keys:
  `assessor_data = (adr.raw || assessorFlat)`. So the scale data and item codes are present and
  correctly shaped; **the only thing breaking the sheets was the role filter.**

Payload shape reaching a builder (one form, abridged):

```json
{
  "student_number": 1387xxx,
  "role": "O",
  "assessor_data": {
    "radio": {"clinical-incident-occurred": "no"},
    "scales": {"scale-global-rating": {"key": "3", "value": "..."}, "...": "..."},
    "checklists": {"011": {"MC1": {"key": "O4", "value": "Sometimes done"}, "...": "..."}},
    "011": {"MC1": "O4", "MC2": "O5", "MC6": "O2"},   // <- v2-flat copy the builders read
    "511": {"MC1": "O1", "...": "..."}
  }
}
```

## 3. The fix

All edits in `flagging_utils.py`. Each builder now folds role through `normalizeRole` before testing
it, instead of comparing the raw string to the label `"Operator"`.

| # | Builder / sheet | Line (pre-edit) | Before | After |
|---|---|---|---|---|
| 1 | `_buildItemCountPivot` → `reportable_items_pivot` | ~1634 | `if str(row.get("role","")).strip() not in ("", "Operator"): continue` | `if normalizeRole(row.get("role")) not in (None, ROLE_OPERATOR): continue` |
| 2 | `_buildItemScaleDist` → `item_scale_dist` | ~1699 | same as #1 | same as #1 |
| 3 | `_build_operator_by_clinic_sheet` → `operator_by_clinic` | ~1948 | `role_counts` built from raw `df["role"]`, then `.get("Operator")` / `.get("Support Operator")` | inserted `df["role"] = df["role"].map(normalizeRole)` right after `df["clinic"].fillna(...)`, so the `.get("Operator")` / `.get("Support Operator")` lookups now match |
| 4 | `_build_item_scale_donut_sheet` → `item_scale_donuts` | ~2085 | `cohortDf["role"].str.strip().str.lower() == "operator"` | `cohortDf["role"].map(normalizeRole).eq(ROLE_OPERATOR)` |
| 5 | `_build_clinical_incidents_sheet` → `clinical_incidents` (display only) | ~1369 | showed raw `role` code in the "Role" column | inserted `ciDf["role"] = ciDf["role"].map(normalizeRole)` so the column shows `Operator`/`Support Operator`, not `O`/`SO` |

### Why per-builder rather than one central normalise

`getFlagDf(cohortDf, …)` returns `flagDf/compDf/thresholds`; the **sheet builders are dispatched by the
caller** (`createFlaggingReport` in `main.ipynb`), each receiving `cohortDf` as a parameter.
Normalising inside `getFlagDf` would touch a copy the builders never see. Normalising per builder is
also correct for the standalone call sites (`_buildItemScaleDist` is called directly at ~line 3707).
`normalizeRole` is idempotent on labels, so this is safe even if a future central normalise is added.

### Semantic equivalence

The rewrite preserves the original branch behaviour for every role except the one that was broken:

| raw role | `normalizeRole` | old test skips? | new test skips? |
|---|---|---|---|
| `""` / None (final-year, no role) | `None` | no (included) | no (included) |
| `"O"` (v3 operator) | `Operator` | **yes (BUG — dropped)** | **no (included — fixed)** |
| `"Operator"` (legacy label) | `Operator` | no | no |
| `"SO"` / `"Support Operator"` | `Support Operator` | yes | yes |
| `"OB"` / `"Observation"` | `Observation` | yes | yes |

Only the `"O"` row changes — exactly the intended fix.

## 4. Verification

Ran the two parsing helpers against 600 real DDS3 CAF forms (flattened the same way the v3 loader
does), comparing old label test vs new:

```
raw role values: {'O': 567, 'SO': 33}
OLD (label test) total responses : 0            <- reproduces the empty-sheet bug
NEW item_scale_dist              : 7789 responses across 21 items
NEW item_scale_donuts op_df rows : 567 / 600    <- 33 SO forms correctly excluded
NEW reportable_items_pivot rows  : 92 students
```

`python3 -m py_compile flagging_utils.py` clean. Import-level end-to-end run through `main.ipynb` not
done here (the flag report needs live Postgres / the Windows environment).

## 5. What to do next / open items

- **Re-run `main.ipynb` for DDS3 Clinic** (`createFlaggingReport("DDS3","Clinic", config=PRESETS["dds3_clinic"])`)
  and confirm `Item Scale Distribution`, `Item Scale Donuts`, and `Reportable Items Pivot` now populate,
  and that `Clinical Incidents` shows `Operator`/`Support Operator` instead of `O`/`SO`.
- **`operator_by_clinic`** is currently commented out of the `dds3_clinic` sheet list; it is now fixed
  and safe to re-enable if the team wants it.
- The role→label / patient-detail→label maps remain duplicated in `flagging_utils.py` and
  `boh2_dds2_dds3_utils.py` (pre-existing note): a new DASH code must be added to both.
- Optional hardening: a single `cohortDf["role"] = cohortDf["role"].map(normalizeRole)` at the point
  `createFlaggingReport` assembles `cohortDf` would make every current and future builder code-safe;
  the per-builder guards make this unnecessary but it would remove the footgun for good.
