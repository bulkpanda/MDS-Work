# DDS2 Clinic Flagging — FHY Review Changes

**Date:** 2026-08-18
**Files touched:** `flagging_utils.py`, `boh2_dds2_dds3_utils.py`, `general_utils.py`, `main.ipynb` (cell 15)
**Cohorts:** DDS2 Clinic is the requester; three of the seven changes are cohort-wide bug fixes
**Backups:** `flagging_utils.py.bak_20260818_062600` (pre-session), `…_064500`, `…_071500`, `…_090000` (the three same-day revisions), `boh2_dds2_dds3_utils.py.bak_20260818_064500`, `general_utils.py.bak_20260818_064500`, `main.ipynb.bak13_20260818_062600`, `main.ipynb.bak14_20260818_090000`

**Read this first if:** a flagging workbook shows a number you don't recognise (Pt Seen, Score,
clinical incidents), or you need to know why two "score" columns disagree.

---

## 0. Summary

Seven changes, in the order they were requested:

| # | Change | Scope | Behaviour change without opt-in? |
|---|---|---|---|
| 1 | **Role / patient-detail codes** (`O`/`SO`/`OB`, `ISP`/`FTA`) now recognised | all cohorts | **Yes — bug fix.** v3-coded forms were counted as neither operator nor patient-seen |
| 2 | **Pt Seen requires role = Operator** | all cohorts (`requireOperatorForPtSeen`, default `True`) | **Yes.** Support-Operator sessions no longer count |
| 3 | **Inclusive (`<=`) thresholds** + new DDS2 numbers | `dds2_clinic` preset only | Yes, for that preset only |
| 4 | **Section Score Pivot** sheet | every preset built from `_ALL_SHEETS` | Additive (new sheet) |
| 5 | **FHY / SHY semester selector** | opt-in per run | No — default `period="ALL"` is byte-identical |
| 6 | **`ignoreDates`** — drop whole sessions | opt-in per run | No |
| 7 | **Clinical incidents actually populate** | all cohorts | **Yes — bug fix.** Every CI report was empty |
| 8 | **`scoreWeighting`** — switch the Score definition | opt-in per config, default unchanged | No |

Three of these (1, 2, 7) change numbers on a workbook nobody asked to change, because they are
fixes to things that were silently wrong. §9 lists exactly what to expect.

---

## 1. Role and patient-detail codes — the bug behind changes 1 and 2

### The two storage shapes

DASH stores `role` and `patient_data.details` as **codes** on the v3 form template and as full
**labels** on the older one. Both shapes are live in the 2026 data.

```jsonc
// v3 template — form_context
{ "role": "O",                 // O | SO | OB
  "patient": { "details": "ISP" } }   // ISP | FTA | PCW | NPB | UBP

// older template
{ "role": "Operator",
  "patient": { "details": "I saw a patient" } }
```

`getFlagDf` tested only the label spelling:

```python
role_counts    = grp["role"].fillna("Unknown").value_counts()
operator_count = int(role_counts.get("Operator", 0))          # never matches "O"
pd_counts      = grp["patient_details"].fillna("Unknown").value_counts()
patient_seen   = int(pd_counts.get("I saw a patient", 0))     # never matches "ISP"
```

So on a code-shaped pull `operator_count`, `pct_operator` and `patient_seen` were **undercounted
to zero**, and `low_pt_seen` fired on the wrong students. `patient_fta` was accidentally safe
because it matched on the substring `"FTA"`, which appears in both spellings. The July 2026
workbook looks right only because that particular pull happened to be label-shaped.

### The fix

`flagging_utils` now folds both spellings to the label form before anything is counted:

```python
ROLE_CODE_TO_LABEL = {"O": "Operator", "OPERATOR": "Operator",
                      "SO": "Support Operator", "SUPPORT OPERATOR": "Support Operator", …}
PATIENT_DETAIL_CODE_TO_LABEL = {"ISP": "I saw a patient", "FTA": "Failed to attend (FTA)", …}

normalizeRole(value)            # -> 'Operator' | 'Support Operator' | 'Observation' | None
normalizePatientDetail(value)   # -> 'I saw a patient' | 'Failed to attend (FTA)' | … | None
```

An **unrecognised** value is returned stripped and unchanged rather than dropped, so a future
code shows up in the counts as itself instead of vanishing.

> **Architectural decision.** These constants duplicate
> `boh2_dds2_dds3_utils.ROLE_LABELS_FALLBACK` / `PATIENT_DETAIL_LABELS_FALLBACK` rather than
> importing them, to keep `flagging_utils` free of a dependency on the report module. The
> authoritative source for both maps is each form's `context_schema_snapshot` (read dynamically by
> `_labelMapFromSnapshots`); these are the same static fallback. **If a new code appears, both
> copies need it.**

---

## 2. Pt Seen requires role = Operator

`Config.xlsx`, the **All** row:

> *For cohorts, student are putting Support Operator and Patient Attended together. So for patient
> count, we need to count where role is Operator as well as Patient Attended, not valid for final
> year forms since they don't have Operator/Support Operator field.*

```python
def patientSeenMask(grp, requireOperator=True):
    seen = grp["patient_details"].map(normalizePatientDetail).eq(PATIENT_SEEN_LABEL)
    if not requireOperator or "role" not in grp.columns:
        return seen
    role = grp["role"].map(normalizeRole)
    return seen & (role.isna() | role.eq(ROLE_OPERATOR))
```

**The final-year exemption is per FORM, not per cohort.** A form carrying no role value at all —
the DDS4/BOH3 template, which has no Operator/Support field — is exempt from the role half of the
test and counts on the patient detail alone. That means a mixed-template cohort works correctly
without any cohort-specific branching.

`FlaggingConfig(requireOperatorForPtSeen=False)` restores the old any-role count.

**Summary sheet** now carries both numbers, so the gate is auditable:

| Header | flagDf column | Meaning |
|---|---|---|
| `Pt Seen (Op)` | `patient_seen` | gated — feeds `low_pt_seen` and `pct_patient_seen` |
| `Pt Seen (any)` | `patient_seen_any_role` | ungated — the old number |

The gap between the two columns is exactly the "logged a patient while Support Operator" volume.

---

## 3. Inclusive thresholds — `<=` instead of `<`

The DDS2 team fixed four cutoffs and asked for a student sitting **exactly** on the number to be
flagged. `FlagSpec.direction` gained two values, and a config can promote a strict registry flag
to its inclusive form **per run** — so one cohort asking for `<= 2` does not move every other
cohort's cutoff.

```python
# direction: "below" | "below_eq" | "above" | "above_eq"
_INCLUSIVE_DIRECTION = {"below": "below_eq", "above": "above_eq", …}
DIRECTION_SYMBOL     = {"below": "<", "below_eq": "<=", "above": ">", "above_eq": ">="}

config.direction_for("low_es")   # registry direction, promoted if the key is in inclusiveFlags
```

`getFlagDf` iterates `zip(config.flags, specs)` (it needs the KEY, not just the spec) and branches
on `direction_for`.

### `PRESETS["dds2_clinic"]` — what changed

| Field | Was | Now |
|---|---|---|
| `esThreshold` | `None` (borderline-GR auto) | `2` |
| `grThreshold` | `2.5` | `3` |
| `psThreshold` | `None` (borderline-GR auto) | `1.5` |
| `minPtSeen` | `None` (mean − 1.5 SD) | `11` |
| `inclusiveFlags` | — | `["low_es", "low_gr", "low_ps", "low_pt_seen"]` |

> **Architectural decision.** ES/PS were cohort-**relative** (mean of the borderline-GR peer group)
> and are now **absolute** standards. GR moved 2.5 → 3. Expect materially more students flagged
> than the July run — that is the intent, not a regression. Every other preset is untouched and
> stays strict `<`.

The Legend sheet prints the **actual operator** — `ES avg | <= 2` rather than a bare `2` — so a
workbook always states whether a student on the cutoff was flagged.

---

## 4. Section Score Pivot — the new sheet

Sheet key `section_score_pivot`, title *"Section Score Pivot"* (Clinic) / *"Item Code Score Pivot"*
(Simulation). It is the **score twin** of the existing *Section GR Pivot*: that sheet answers
"how were they rated overall in Restorative", this one answers "how well did they do the
Restorative items themselves", using the 0–1 checklist score from `calcScore`.

```python
pivot, groupCol, counts = buildSectionScorePivot(cohortDf, formType="Clinic", mappingFile=None)
```

| Return | Contents |
|---|---|
| `pivot` | `student_number, student_name, <Section…>, Overall (per item), Overall (per form)` |
| `groupCol` | `"Section"` (Clinic) or `"Item Code"` (Simulation) |
| `counts` | same shape — scored **items** behind each section cell, **forms** behind the per-form column |

`calcScore` already returns `{}` for Observation/Support-Operator forms, so these are the student's
own operating scores with no extra filtering.

**Cell rules.** Red `<=` the score threshold · amber = below the cohort average for that section ·
green = at/above · grey = not assessed (coloured *after*, so "no data" never reads as "scored
badly") · *italic* = fewer than 3 scored items behind the average, so a 1.00 off one item is not
read as settled. Cohort-average row at the bottom, computed over the students actually assessed in
that section (blank ≠ zero).

Because `_ALL_SHEETS = list(SHEET_REGISTRY.keys())`, the sheet appears automatically in
`clinic_full`, `dds2_clinic` and `boh2_clinic`. **`dds3_clinic` has an explicit sheet list and was
deliberately left alone** — add `"section_score_pivot"` to it if DDS3 wants it.

---

## 5. The two Overall columns, and `scoreWeighting`

The user's question — *"section overall doesn't even match average of all sections, so where is
this coming from?"* — has a real answer, and it applies to Summary's `Score` too.

### The three numbers

| Number | What it averages | Weighting |
|---|---|---|
| Section cells | every scored (form, item) pair in that section | item |
| `Overall (per item)` | every scored (form, item) pair, all sections | **item** |
| `Overall (per form)` / Summary `Score` | each form's own item mean, then averaged across forms | **form** |

`Overall (per item)` is therefore the section means **weighted by their own item counts** — not the
plain average of the section cells, which would give a two-item section the same say as a
forty-item one.

### Measured on the real FHY workbook (106 students)

- Rebuilding `Overall (per item)` as the item-count-weighted mean of the section cells matches to
  **mean 0.0009 / max 0.031**. (Residual only because the Section Count Pivot counts every item
  code on a form, including ones with no scoreable answer.) The **unweighted** mean of sections is
  off by up to **0.107**. That is the proof of the mechanism.
- per item − per form: mean **+0.021**, max **+0.064**, higher for 95 of 106.
- Spearman 0.945, but **one student moves 43 rank places**.
- At the 0.63 cutoff: **8 flagged per form, 6 per item** — Matthew Huang 0.615/0.632 and Morris Man
  0.620/0.642 straddle it.
- Items per form: mean 1.44 (min 0.77, max 2.77). The gap does **not** correlate with items-per-form
  (r = −0.07) or form count (r = 0.05).

### The switch

```python
SCORE_PER_FORM = "per_form"     # default — the historical behaviour, what July 2026 used
SCORE_PER_ITEM = "per_item"
resolveScoreWeighting(value)    # accepts 'item', 'per item', 'PER-FORM'; RAISES on a typo

createFlaggingReport("DDS2", "Clinic",
    config=PRESETS["dds2_clinic"].copy(scoreWeighting="per_item"))
```

Implementation — both are derived from the same per-form item lists, so they cannot drift:

```python
_vals = df["scores"].apply(_scoreVals)          # every non-null item score on one form
df["_mean_score"] = …                            # per-form mean
df["_score_sum"], df["_score_n"] = …             # item sum / count per form

avg_score = (grp["_mean_score"].mean()                       if per_form
             else grp["_score_sum"].sum() / grp["_score_n"].sum())
```

| Follows the switch | Does **not** |
|---|---|
| `avg_score` | `score_slope`, `first_third_*`, `last_third_*` |
| `low_score` flag | the Section Score Pivot (always shows both) |
| the auto/borderline score threshold | |
| Summary header `Score (per form)` / `Score (per item)` | |
| Scale Trends `Score Avg (…)` | |

> **Architectural decision.** Slopes stay per form because a **form** is the natural point on a time
> series. The Scale Trends header says `Score Slope (per form)` explicitly, so when you run
> per-item the two headers deliberately disagree — that is documentation, not drift.

> **Architectural decision.** Only the **active** Score column is written to Summary (the user's
> choice), so there is never ambiguity about which number the flag used. The comparison lives on
> the Section Score Pivot, which marks the active column in its banner and footnote — **rendered
> from the config at write time**, not baked into a header that would go stale the moment the
> switch is flipped.

---

## 6. Semester selector (FHY / SHY) and excluded dates

### Period

```python
filterCohortDfByPeriod(cohortDf, period="FHY", minDate=None, maxDate=None,
                       dateCol="datetimeutc", tz="Australia/Melbourne")
# -> (filteredDf, label, (minDate, maxDate))
```

Reuses `general_utils.resolvePeriod` / `periodSuffixPath` / `SEMESTER_SPLIT_DATE`, so clinic
flagging and the weekly-sim chain split the year on the **same constant** (2026-06-15) and can
never drift apart. `flagging_utils` now imports from `general_utils`; this is **not** circular —
`general_utils` does not import `flagging_utils`.

Applied in `createFlaggingReport` **before** `calcScore`/`getFlagDf`, so every threshold, cohort
average and pivot on the sheet describes that half year only. Output filename is suffixed:
`DDS2 Clinic Flagging (2026) (FHY).xlsx`. `period="ALL"` (the default) keeps the plain filename and
is byte-identical to the old behaviour.

> **TRAP — the comparison is on the MELBOURNE-LOCAL date, not the raw UTC one.** DASH stores UTC;
> a late-afternoon Melbourne session sits on the previous UTC day and a naive `.dt.date` would drop
> it into the wrong semester at the 15 June boundary. Same trap as the weekly-sim
> `datetimeutc::date` note.

### Excluded session dates

```python
DDS2_CLINIC_IGNORE_DATES = ["2026-01-21", "2026-01-29", "2026-02-03", "2026-02-10",
                            "2026-02-26", "2026-03-02", "2026-03-05", "2026-03-16"]

parseIgnoreDates(values, defaultYear=None)   # -> sorted unique 'YYYY-MM-DD'
dropIgnoredDates(cohortDf, ignoreDates, …)   # -> (df, parsedDates)
```

Those eight 2026 days are **student-on-student activities** — the "patient" was a classmate, so the
forms are not evidence of clinical performance. All eight fall in FHY. The mechanism is generic;
the constant is a documented default passed on the run line, not an automatic cohort rule.

Parsing accepts ISO, day-first slash/dash, written (`26 Feb 2026`) and date objects. **Day-first is
assumed for ambiguous slash dates** — `03/02/2026` is 3 February. A bare `16/03` needs
`defaultYear`.

Two deliberate loudness choices:

- an **unparseable** entry raises, rather than being skipped — silently ignoring a typo leaves the
  session in the analysis;
- a date matching **no forms** prints a `WARNING` — a silently-ineffective exclusion is worse than
  none, because the workbook looks like it was applied.

Rows are dropped before scoring, so they touch no average, threshold, count or pivot. The Legend
lists every excluded date.

---

## 7. Clinical incidents — why every CI report was empty

### The bug

`rawform_forms_v3.clinical_incident` was built from **one** storage shape:

```sql
(SELECT string_agg(x->>'value', '; ' ORDER BY x->>'value')
   FROM jsonb_array_elements(COALESCE(adr.raw->'multi-select'->'clinical-incident','[]'::jsonb)) x)
   AS clinical_incident
```

The DDS2/BOH2/BOH1/DDS1 2026 templates don't use it. They record an incident as a **radio plus a
text field**:

```jsonc
"assessor_data": {
  "radio": { "clinical-incident-occurred": "yes" },     // no | yes
  "texts": { "reflection": "Needs improvement in some fields",
             "clinical-incident": "Infection isssues" }
}
```

So the column came back NULL and **everything downstream showed zero** — flagging `ci_count`,
`flag_clinical_incident`, the Clinical Incidents sheet, and the cohort report's Critical Incident
sheet (`getCriticalIncidentDf`).

Counted directly in `temp 2026 caf.json` (495 MB — too big for `json.load`; `grep`/`awk` on the
device handles it):

| | yes | no |
|---|---|---|
| DDS2 Simulation | 40 | |
| DDS2 Clinic | 35 | |
| BOH2 Clinic | 32 | |
| BOH1 Simulation | 23 | |
| DDS1 Simulation | 20 | |
| BOH2 Simulation | 9 | |
| **Total** | **159** | 8 503 |

The multi-select shape is real too — 87 rows carry it — so the fix must read **both**. Only 93 of
the 159 have detail text, so **~66 are "yes" with nothing typed**.

> `clinical-incidents` (plural) and `heading-clinical-incidents` appear in the payload but are only
> a `group_key` and a heading on the **config**, never data fields. Don't chase them.

### The fix — one expression, used in three places

```python
# boh2_dds2_dds3_utils.py
CLINICAL_INCIDENT_NO_DETAILS = "Yes (no details recorded)"

def clinicalIncidentSqlExpr(alias="f"):
    """COALESCE(stored column, radio+text, multi-select). alias='' when the query has none."""
```

```sql
COALESCE(
    NULLIF(TRIM(COALESCE(f.clinical_incident, '')), ''),
    CASE WHEN lower(COALESCE(f.assessor_data->'radio'->>'clinical-incident-occurred','')) = 'yes'
         THEN COALESCE(NULLIF(TRIM(f.assessor_data->'texts'->>'clinical-incident'), ''),
                       'Yes (no details recorded)')
    END,
    (SELECT string_agg(x->>'value', '; ' ORDER BY x->>'value')
       FROM jsonb_array_elements(
            COALESCE(f.assessor_data->'multi-select'->'clinical-incident','[]'::jsonb)) x)
)
```

| Where | How |
|---|---|
| `getDataDf` | aliased `f`, selected as `clinical_incident_resolved`, then swapped over the raw column **in Python** (because `SELECT f.*` already returns the real one) |
| `getCriticalIncidentDf` | unaliased, in **both** the SELECT and the WHERE |
| `general_utils.getInsertSqlRawform_forms_v3` | the same COALESCE, so the stored column is right going forward |

> **Architectural decision — belt and braces.** The read-time path **repairs the current table with
> no reload**, because the raw JSON is still sitting in `assessor_data`. The loader fix keeps the
> stored column correct from the next load onward. Precedence is stored-column-first, so a
> correctly-loaded row is never overwritten. Existing rows keep their NULL until the table is
> reloaded — which is optional.

**A "yes" with no text counts**, carrying `CLINICAL_INCIDENT_NO_DETAILS`. An empty string there
would read as "no incident", which is the failure this whole section is about.

### Second fix, found in passing

`_build_clinical_incidents_sheet` did an unguarded
`cohortDf[[…, "assessor_name", "role", "clinic"]]`. **One** missing context column raised
`KeyError`, `saveFlagDfToExcel2` swallowed it, and the workbook arrived with no incident sheet at
all and nothing saying why. Context columns are now optional, the omission is printed, and the
builder reports the incident count it found.

---

## 8. API changes — quick reference

### New public names in `flagging_utils`

```
Role / patient      ROLE_OPERATOR, ROLE_SUPPORT, ROLE_OBSERVATION, PATIENT_SEEN_LABEL,
                    ROLE_CODE_TO_LABEL, PATIENT_DETAIL_CODE_TO_LABEL,
                    normalizeRole(), normalizePatientDetail(), patientSeenMask()
Period              filterCohortDfByPeriod()          (+ re-exports SEMESTER_SPLIT_DATE,
                                                       PERIOD_FHY/SHY/ALL, resolvePeriod,
                                                       periodSuffixPath from general_utils)
Ignored dates       DDS2_CLINIC_IGNORE_DATES, parseIgnoreDates(), dropIgnoredDates()
Score pivot         buildSectionScorePivot(), OVERALL_PER_ITEM, OVERALL_PER_FORM,
                    OVERALL_BY_WEIGHTING
Score weighting     SCORE_PER_FORM, SCORE_PER_ITEM, SCORE_WEIGHTINGS,
                    SCORE_WEIGHTING_LABELS, resolveScoreWeighting()
Flag directions     DIRECTION_SYMBOL
```

All are public (no leading underscore) because `main.ipynb` uses `from flagging_utils import *`,
which skips `_name`.

### Changed signatures

```python
getFlagDf(cohortDf, formType, config, mappingFile=None,
          periodInfo=None,      # (label, minDate, maxDate) — Legend documentation only
          ignoredDates=None)    # list of 'YYYY-MM-DD'      — Legend documentation only

FlaggingConfig(..., inclusiveFlags=None,
                    requireOperatorForPtSeen=True,
                    scoreWeighting="per_form")
config.direction_for(key)       # NEW — the comparison actually used this run

createFlaggingReport(cohort, formType, config=None, filters=None,
                     period="ALL", minDate=None, maxDate=None, ignoreDates=None)
```

`periodInfo` / `ignoredDates` are **documentation only** — the rows must already be filtered out.

### New `thresholds` keys (documentation only, never compared against)

`inclusive_flags`, `pt_seen_operator_only`, `score_weighting`, and — when a period or exclusions
were applied — `period_label`, `period_min`, `period_max`, `ignored_dates`.

---

## 9. What changes on a workbook you re-run today

Even with no new arguments:

1. **`Pt Seen` drops** wherever students logged a patient as Support Operator, and gains a
   companion `Pt Seen (any)` column. `low_pt_seen` fires differently.
2. **`Operator` / `Support` / `% Oper` change** on any code-shaped pull (they were previously 0).
3. **Clinical incidents appear** — 35 DDS2 Clinic forms in the 2026 data. `ci_count`,
   `flag_clinical_incident`, `high_risk_flag_count` and the Clinical Incidents sheet all move.
4. **A new sheet** appears (Section Score Pivot) on every `_ALL_SHEETS` preset.
5. **`dds2_clinic` only:** ES/GR/PS/Pt Seen cutoffs are the new absolute numbers, inclusive.

Everything else — including all other presets — is unchanged, and that was verified rather than
assumed (§10).

---

## 10. Verification

No database was reachable (the user's Postgres is localhost), so nothing here was run against live
data. What *was* done:

**Behaviour — 136 assertions across four suites**, driving the real `getFlagDf` /
`saveFlagDfToExcel2` over synthetic frames carrying the exact column set `getDataDf` returns:

- *Role/gate/thresholds/period* (52): both role spellings plus a no-role student; exact-on-cutoff
  boundary cases for all four inclusive flags; FHY + SHY partition ALL, disjoint and complete; the
  Melbourne-midnight edge case; item-weighted `Overall`; a full workbook read back with `openpyxl`.
- *Incidents + ignoreDates* (47): the four real payload shapes replayed through a Python port of
  the COALESCE precedence; date parsing in every accepted format; the unmatched-date warning; an
  end-to-end run where the excluded days move ES 1.857 → 3.0 and clear the flag.
- *The two Overall columns* (9): per-form matches `avg_score` cell-for-cell **in the written
  workbook**; per-item reconciles with the section cells weighted by item count; the two collapse
  onto each other when every form has the same number of items — the cleanest confirmation that the
  gap is weighting and nothing else.
- *`scoreWeighting`* (28): aliases and typo-raising; `copy()` carrying the setting; `avg_score`
  matching the corresponding pivot column exactly under each setting; threshold and flag following;
  slopes provably **not** moving; every sheet header and marker consistent in both modes.

**No-op regression.** With `requireOperatorForPtSeen=False, inclusiveFlags=[]` (and `dds2_clinic`'s
four numbers reverted), **all nine presets reproduce the pre-session module's `flagDf` and
`thresholds` exactly**, on label-spelled data — `assert_frame_equal` over 49–62 columns. The only
new column is `patient_seen_any_role`.

**SQL.** Every modified query was parsed as PostgreSQL with `sqlglot`: the read-time expression in
both alias forms, the full `getDataDf` and `getCriticalIncidentDf` queries as actually built
(captured through a patched `readDf`), and the whole v3 INSERT for `replace=True/False`.

**Static.** `py_compile` on all three modules; `ast` parse of notebook cell 15.

---

## 11. Gotchas

- **Two copies of the role/patient code maps** now exist (`flagging_utils` and
  `boh2_dds2_dds3_utils`). A new DASH code needs adding to both.
- **`dds3_clinic` has an explicit sheet list** — it did not pick up `section_score_pivot`.
- **The pivot's per-form/per-item headers are plain names.** Which one Summary uses is rendered
  from the config at write time. Don't reintroduce `= Summary Score` into a header.
- **Test tolerance:** with equal items per form the two Overall columns are mathematically identical
  but reach the value by different float paths, so they can land either side of the 3-dp rounding
  line. Assert to one rounding unit (0.0011), not 0.
- **Test fixtures:** don't test the score-weighting flag difference with an arbitrary cutoff — pick
  one *between* the two values of the student with the largest gap, or a random cohort gets flagged
  identically under both definitions and the test passes vacuously.
- **`ignoreDates` drops a WHOLE day**, AM and PM.
- **`getFlagDf`'s `forms` threshold** does `int(mean - std)`, which raises
  `ValueError: cannot convert float NaN to integer` on a **single-student** cohort — reachable via a
  narrow `filters={"clinic": …}`. Pre-existing; not fixed.
- **`saveFlagDfToExcel2` swallows per-sheet exceptions** and prints them. A missing sheet in the
  output means a printed line you may have scrolled past — this is how the Clinical Incidents
  `KeyError` hid.

---

## 12. Open

- Nothing here has been run against the live Postgres. Re-run cell 15 and sanity-check §9.
- `Config.xlsx`'s DDS2 note — *"DENT90148 On 15/07/2026 there was technical problems leading to AM
  session being not complete, will need to not penalize AM students"* — is **still not handled**.
  `ignoreDates` would drop the whole day; a half-day exclusion needs a time-of-day filter that
  doesn't exist.
- The stored `rawform_forms_v3.clinical_incident` column stays NULL for radio+text rows until the
  table is reloaded. Reports are correct without it, so this is optional.
- `dds3_clinic` / `boh2_clinic` still use strict `<` and the old auto thresholds — deliberate; the
  team only specified DDS2.
- Whether **per item** should become the default Score definition is unresolved. It is arguably the
  better measure (each assessed item is one observation), but it moves `low_score` for every cohort
  and breaks comparability with the July workbook. Run both once before deciding — on FHY it is 8
  flagged versus 6.
