# BOH1/BOH2/DDS2/DDS3 Cohort Reports — Rawforms v3 Migration Handover

**Date:** 2026-08-04
**Scope:** Rewiring the **cohort-report chain** in `boh2_dds2_dds3_utils.py` to the new `rawform_forms_v3` shape (BOH1, BOH2, DDS2, DDS3).
**Status:** Cohort reports (`getCohortReports`, `main.ipynb` cell 10) **DONE + statically verified**. Not yet run against live Postgres. Several adjacent pieces deferred (see §8).
**Predecessor:** [`rawforms_v3_separation_handover.md`](rawforms_v3_separation_handover.md) (built the v3 tables) and the final-year migration in `boh3_dds4_utils.py` (already done).

> ⚠️ **Correction to the predecessor handover.** `rawforms_v3_separation_handover.md` §2a/§7.2(a) claims other-cohort scales use **bare** keys (`entrustment`, `time_mgmt`, …). This is **WRONG** — verified against real DDS2/DDS3/BOH1 rows on 2026-08-04. They use the **same prefixed keys as final-year** (`scale-entrustment`, `scale-global-rating`, …), nested under `assessor_data->'scales'`, with the graded level under `->>'key'`. This handover supersedes that claim.

---

## 1. Context & why this exists

The DASH form engine changed the shape of `rawforms.forms`. The v3 separation pipelines (`rawform_forms_v3` for non-final-year, `dds4_boh3_forms_v3` for final-year) were built to read the new shape while keeping v2 column names. The **downstream reports** in `boh2_dds2_dds3_utils.py` still read the OLD flat shape and silently produced NULLs. This session repointed the cohort-report chain to the new shape.

### Data flow (this file's part)

```
rawforms (forms JSONB)
      │  getInsertSqlRawform_forms_v3()  [general_utils.py, cohort NOT IN (DDS4,BOH3)]
      ▼
rawform_forms_v3  ──►  boh2_dds2_dds3_utils.py
                         getCohortReports()            (cell 10)  ← MIGRATED
                         getCohortReportsPerClinic()              ← MIGRATED (chain)
                         buildCohortTimeSeriesPdf()    (cell 11)  ← default flipped, see §8
```

---

## 2. The v3 data structure (non-final-year cohorts)

### 2a. `rawform_forms_v3` columns (as consumed here)

| Column | Type | Source (v3 insert) | Notes |
|---|---|---|---|
| `form_code`, `assessmentid` | text / int | `form_key` / row | PK = (form_code, assessmentid) |
| `student_number`, `student_name`, `student_email` | text | row | |
| `datetimeutc` | timestamptz | row | |
| `cohort`, `subject`, `type` | text | row | `type` ∈ {Simulation, Clinic} |
| `student_data`, `assessor_data` | jsonb | form-level, **nested + flattened** | see §2b |
| `student_reflection`, `assessor_reflection` | text | `*_data->'texts'->>'reflection'` | ⚠ NULL when a form uses multi-reflection keys (see §2d) |
| `clinical_incident` | text | joined `assessor_data->'multi-select'->'clinical-incident'` | `; `-joined values |
| `patient_complexity` | text | `assessor_data->'scales'->'patient_complexity'->>'key'` | ⚠ **bug**: should be `scale-patient-complexity` → currently NULL |
| `role` | text | `form_context->>'role'` | `O`=Operator, `OB`, `SO` |
| `clinic` | text | `form_context->>'clinic_type'` | e.g. GP, EN, RP, PE, SS |
| `scales` | jsonb | `assessor_data->'scales'` | nested, prefixed keys (see §2c) |
| `checklists` | jsonb | `assessor_data->'checklists'` | nested item-code map (see §2c) |
| `patient_data` | jsonb | `form_context->'patient'` | single object; `age/drn/details/interpreter/fta_substitute` |
| `context_schema_snapshot` | jsonb | form-level | field definitions (select options, conditions) |
| `assessor_name`, `assessor_email` | text | form-level | |
| `submitted_by_student`, `submitted_by_assessor` | bool | form-level | |
| `version` | int | form-level | |

### 2b. `assessor_data` / `student_data` shape (the important bit)

Each is a JSON object with **five standard buckets** PLUS **flattened item-code entries merged onto the top level**:

```jsonc
{
  "radio":        { "clinical-incident-occurred": "no" },
  "texts":        { "reflection": "Developing very good skills" },
  "scales":       { "scale-global-rating": {"key":"4","value":"Good"}, ... },   // nested, prefixed
  "checklists":   { "222": { "MC1": {"key":"O2","value":"Done"}, ... } },        // nested item-code map
  "multi-select": {},
  // ---- flattened v2-style copy merged on top (compat shim) ----
  "222":    { "MC1":"O2", "MC2":"O2", "MC3":"O6", ... },   // item code -> {MC: keyString}
  "114 H/S":{ "MC1":"O2", "MC2":"O6", ... }
}
```

Two consequences the reports must handle:
1. **Scales moved down** one level (`assessor_data->'scales'->...`) with the graded value under `key`, not `scale`.
2. **`jsonb_each(assessor_data)` now yields the 5 buckets** as well as real item codes. Any item-code enumeration must exclude `radio/texts/scales/checklists/multi-select` **and** `scale-%`.

### 2c. Scales — prefixed keys, value under `key`

Observed keys across DDS2/DDS3/BOH1 (superset; not every form has all):

```
scale-global-rating        (3=Satisfactory, 4=Good — a RATING, counted separately)
scale-practice-readiness   (== "entrustment" for these cohorts; "Level 2/3/4…")
scale-professionalism
scale-communication
scale-time-mgmt
scale-position-ergonomics
scale-preparedness
scale-record-keeping
scale-infection-control
scale-safe-not-safe        (key = "safe" — text, not int)
scale-patient-complexity   (key = "non-complex" — text, not int)
```

Value example: `"scale-global-rating": {"key": "4", "value": "Good"}` → the graded level is `"4"`.
Level scales are plain integer strings; `scale-safe-not-safe` and `scale-patient-complexity` are text.

**Correct read pattern:**
```sql
NULLIF(assessor_data->'scales'->'scale-practice-readiness'->>'key', '')::int   -- entrustment
```

### 2d. Reflection keys vary by form

Standard forms use `texts.reflection`. Some subjects use multiple named keys, e.g. DDS2 `DENT90146` clinic:
- student: `reflection-how-prepare`, `reflection-what-did-well`, `reflection-what-differently`
- assessor: `reflection-student-improve`, `reflection-student-did-well`

The v3 insert only maps `texts->>'reflection'`, so `student_reflection`/`assessor_reflection` are **NULL** for these forms. Not fixed this session (affects flagging comment columns, not the scale/pivot cohort reports).

### 2e. Real example payload (DDS2 Sim, trimmed)

```json
{
  "cohort": "DDS2", "subject": "DENT90148", "type": "Simulation",
  "role": null, "clinic": "EN",
  "assessor_data": {
    "radio": {}, "multi-select": {},
    "texts": {"reflection": "Slob rule"},
    "scales": {
      "scale-time-mgmt":        {"key":"2","value":"Level 2: Completes… in allocated timeframe"},
      "scale-communication":    {"key":"2","value":"Level 2: Matches verbal and non-verbal…"},
      "scale-global-rating":    {"key":"3","value":"Satisfactory"},
      "scale-professionalism":  {"key":"2","value":"Level 2: Presents as a professional…"},
      "scale-practice-readiness":{"key":"3","value":"Level 3 – … periodic direct supervision."},
      "scale-position-ergonomics":{"key":"2","value":"Level 2: Adjusts clinician chair…"}
    },
    "checklists": {"Week-05": {"MC1":{"key":"O2","value":"Done well"}, "MC2":{"key":"O3","value":"Mostly done"}, "…":"…"}},
    "Week-05": {"MC1":"O2","MC2":"O3","MC3":"O4","…":"…"}
  },
  "patient_data": {"age":"", "drn":"", "details":"", "interpreter":false, "fta_substitute":null},
  "version": 3
}
```

---

## 3. What was migrated (this session)

All in `boh2_dds2_dds3_utils.py`. **Backup:** `boh2_dds2_dds3_utils.py.bak_20260804_132525`.

### 3a. Scale-path rewrites (before → after)

| Function | Old (v2 flat) | New (v3 nested) |
|---|---|---|
| `getStudentScaleSummary` | `assessor_data->'scale-practice-readiness'->>'scale'` (+ bare COALESCE fallbacks) | `assessor_data->'scales'->'scale-practice-readiness'->>'key'` |
| `getStudentItemCodeDf` | `f.assessor_data->'scale-global-rating'->>'scale'` etc. | `f.assessor_data->'scales'->'scale-global-rating'->>'key'` etc. |
| `getFlaggedFormDetails` | `assessor_data->'scale-global-rating'->>'scale'` (triggers, labels, columns) | `assessor_data->'scales'->'scale-global-rating'->>'key'` |
| `getDataDf` | same flat pattern (×5 scales) | nested `->'scales'->…->>'key'` |

Concrete example (`getStudentScaleSummary`):
```sql
-- BEFORE
COALESCE(
  NULLIF(assessor_data->'scale-practice-readiness'->>'scale','')::int,
  NULLIF(assessor_data->'entrustment'->>'scale','')::int,
  NULLIF(assessor_data->'practice-readiness'->>'scale','')::int
) AS entrustment,

-- AFTER
NULLIF(assessor_data->'scales'->'scale-practice-readiness'->>'key','')::int AS entrustment,
```

`entrustment = scale-practice-readiness` for these cohorts (there is no separate `scale-entrustment` in the samples). **Global rating is deliberately NOT part of the scale summary** — it is a satisfactory/good rating and is surfaced separately (its own pivot in `getCohortReports`, its own column in `getStudentItemCodeDf`, and its own flag trigger).

### 3b. Item-code enumeration — bucket exclusion

`getDataDf`'s lateral and `calcScore` iterate `assessor_data`, which now contains the 5 buckets. Added exclusions:

```sql
-- getDataDf lateral
WHERE ic.key NOT LIKE 'scale-%'
  AND ic.key NOT IN ('radio','texts','scales','checklists','multi-select')
```
```python
# calcScore
if itemCode in ("radio","texts","scales","checklists","multi-select"):
    continue
```

The item-code pivots (`getStudentItemCodeDf` → `pivotItemCodes`) read the **`checklists` column** (`jsonb_each(f.checklists)`), which contains only item codes as keys, so those needed **no** exclusion — only the scale columns beside them were fixed. Note `cl.value->>'name'` (the "Description" column) is now NULL because the nested checklist data has no `name`; it is not used by any pivot.

### 3c. `formsTable` default flip

`formsTable="rawform_forms"` → `"rawform_forms_v3"` across the whole file **except** `getChecklistMcTexts` and `getChecklistItems` (they still read the v2 `checklists->'fields'/'name'` shape — see §8). The v2 table stays reachable by passing the old name explicitly.

---

## 4. Column / concept mapping (v2 report expectation → v3 source)

| Report concept | v2 read | v3 read |
|---|---|---|
| Entrustment | `assessor_data->'scale-practice-readiness'->>'scale'` | `assessor_data->'scales'->'scale-practice-readiness'->>'key'` |
| Professionalism / Communication / Time mgmt | `assessor_data->'scale-x'->>'scale'` | `assessor_data->'scales'->'scale-x'->>'key'` |
| Global rating (separate) | `assessor_data->'scale-global-rating'->>'scale'` | `assessor_data->'scales'->'scale-global-rating'->>'key'` |
| Item codes (pivots) | `jsonb_each(checklists)` keys | `jsonb_each(checklists)` keys (unchanged; column now nested) |
| Item codes (getDataDf) | `jsonb_each(assessor_data) WHERE key NOT LIKE 'scale-%'` | + `AND key NOT IN (5 buckets)` |
| Critical incident | `clinical_incident` column | unchanged (v3 populates it) |
| Clinic | `clinic` column | unchanged (v3 = `form_context.clinic_type`) |
| Submission flags | `submitted_by_*` columns | unchanged |

---

## 5. Architectural decisions

1. **Trust the data, not the predecessor handover.** Keys are prefixed+nested (§2c), confirmed against real rows. The "bare keys" spec was discarded.
2. **Read scales from `assessor_data->'scales'`**, not the separate `scales` column — keeps every report reading a single JSON blob and matches the final-year approach.
3. **Global rating stays separate** from the level-scale summary (it is a rating, per user), preserving existing report layout.
4. **Minimal churn:** kept v2 column names and function signatures; only SQL paths + the `formsTable` default changed. v2 table remains reachable via explicit arg.
5. **Bucket exclusion centralised** at the two enumeration points (`getDataDf` lateral, `calcScore`) rather than restructuring the JSON.
6. **`getDataDf` migrated even though it belongs to student reports** — the scale substring is shared with the cohort chain, so completing it avoided a half-migrated function. Its downstream `calcScore` was fixed to match.

---

## 6. Verification (done — static only)

- `python -m py_compile boh2_dds2_dds3_utils.py` → clean.
- `grep` confirms **0** remaining `scale-…->>'scale'` reads; only the 2 checklist explorers retain the old default.
- **Path simulation** on the 4 real sample rows (DDS3 clinic, DDS2 sim, DDS2 clinic, BOH1 sim):

| Sample | entrustment | prof | comm | time | GR | item codes | calcScore |
|---|---|---|---|---|---|---|---|
| DDS3 (Roya) | 3 | — | — | — | 3 | 799-DPI | {799-DPI: 1.0} |
| DDS2 sim (Kera) | 3 | 2 | 2 | 2 | 3 | Week-05 | {Week-05: 0.75} |
| DDS2 clinic (Yechan) | 2 | 2 | 2 | 3 | 3 | 721 | {721: 0.66} |
| BOH1 sim (Vanessa) | 3 | 2 | 2 | 2 | 4 | 114 H/S, 222 | {…: 1.0} |

Nulls for Roya's prof/comm/time are correct — that form only recorded global-rating + practice-readiness. Buckets correctly excluded from item codes; `O6` (Not applicable) correctly skipped in scoring.

**NOT done:** no live Postgres in the build environment. **Before production, run `main.ipynb` cell 10 `getCohortReports(engine, "DDS2", today)` (then BOH1/BOH2/DDS3) against the real DB and spot-check the output workbooks.**

---

## 7. How to run

```python
# main.ipynb cell 10
getCohortReports(engine, "DDS2", today)                       # Sim + Clinic
getCohortReports(engine, "BOH2", today)
getCohortReports(engine, "BOH1", today)
getCohortReports(engine, "DDS3", today, type_=["Clinic"])
getCohortReportsPerClinic(engine, "DDS3", today)
```
Outputs (per cohort, in `<cohort>/`): `Scale Information …xlsx`, `Item Code Pivot …xlsx`, `Submission Info …xlsx`. Returns `(flaggedSimDf, flaggedClinicDf)`.

Spot-check SQL:
```sql
SELECT cohort, count(*) FROM rawform_forms_v3 GROUP BY cohort;                 -- no DDS4/BOH3
SELECT assessor_data->'scales'->'scale-global-rating'->>'key'
  FROM rawform_forms_v3 WHERE cohort='DDS2' LIMIT 5;                           -- returns 3/4/…
SELECT assessor_data ? '222' FROM rawform_forms_v3 WHERE cohort='BOH1' LIMIT 1;-- flattened item code present
```

---

## 8. Remaining work (deferred)

| Item | Where | Action |
|---|---|---|
| **Checklist explorers** | `getChecklistItems`, `getChecklistMcTexts` (cell 9) | Still read `checklists->'fields'/'name'` (v2). Definitions now live in `assessor_config`/`student_config`->'checklists'->'selected'. Repoint to config; then flip their default to v3. |
| **Patient fields** | student reports (`buildStudentReport`, general_utils ~L1112) | Derive `patient_age/details/drn/interpreter` from `patient_data` JSONB (in `getDataDf` SELECT). §7.2(c) of predecessor doc. |
| **BOH1 student-only checklists** | Config.xlsx note | Some BOH1 checklists filled by students only → read `student_data`. Deferred per user. |
| **BOH2 Smile Squad** | Config.xlsx note | Smile Squad clinic has only `student_data` → swap student/assessor (logic already exists in `buildCohortTimeSeriesPdf`; verify for `getCohortReports`). |
| **DDS2 general_utils SQL** | `getGlobalRatingSqlDDS2`, `getWeeklySimDataSqlDDS2` | Still old shape (`key='scale-global-rating'` + `v->>'scale'`). Repoint to nested `scales` + `->>'key'`. |
| **`patient_complexity` insert bug** | `general_utils.py` L519 | Reads bare `scales->'patient_complexity'` → NULL. Fix to `scale-patient-complexity`. |
| **Reflection multi-keys** | v3 insert, `general_utils.py` | Only `texts->>'reflection'` mapped; multi-reflection subjects (e.g. DENT90146) lose reflections. |
| **`buildCohortTimeSeriesPdf`** | cell 11 | Default flipped to v3; depends on migrated `getDataDf`/`calcScore`. Patient-field usage unverified — run once and check. |
| **DENT90148 15/07/2026** | Config.xlsx note | AM session had technical problems → don't penalise AM students (reporting-time filter, not a code change). |

---

## 9. Function / symbol index (this file)

| Symbol | Role in cohort reports | v3 status |
|---|---|---|
| `getCohortReports` | Orchestrates Scale/Pivot/Submission workbooks (cell 10) | ✅ chain migrated |
| `getCohortReportsPerClinic` | Per-clinic breakdown | ✅ chain migrated |
| `getStudentScaleSummary` | Level counts + averages per student | ✅ scales migrated |
| `getStudentItemCodeDf` / `getStudentItemCodePivot` / `pivotItemCodes` | Item-code & GR/Entrustment pivots | ✅ scales migrated; checklists col unchanged |
| `getFlaggedFormDetails` | Low GR / low entrustment flags | ✅ scales migrated |
| `getCriticalIncidentDf` | Critical incidents | ✅ column-only (v3 safe) |
| `getStudentFormCountDf` / `getSubmissionInfo` / `getClinicList` | Counts / submission / clinics | ✅ column-only (v3 safe) |
| `getDataDf` | Per-form data + item codes (student reports) | ✅ SQL migrated; consumers deferred |
| `calcScore` | Per-item normalised score | ✅ bucket-excluded |
| `getChecklistItems` / `getChecklistMcTexts` | Checklist definitions (cell 9) | ❌ needs config repoint (§8) |

---

*End of handover.*
