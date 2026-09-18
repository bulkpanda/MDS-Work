# Rawforms v3 Form-Separation — Handover

**Date:** 2026-07-29
**Scope:** Migrating the form-separation pipelines to the **new `rawforms` JSON structure**.
**Status:** Both v3 separation tables built + wired. Downstream report rewiring **NOT done** — that is the job for the next session (see §7).

---

## 1. Context & why this exists

`rawforms` is the raw landing table (`assessmentid`, `student_number`, `datetimeutc`, `cohort`, `subject`, `type`, `completed`, **`forms` JSONB**, …). The `forms` blob is exploded into per-form rows by two "separation" pipelines:

- **`dds4_boh3_forms`** — final-year cohorts (DDS4, BOH3).
- **`rawform_forms`** — all other cohorts (BOH1, BOH2, DDS1, DDS2, DDS3).

The **shape of `forms` changed** (new DASH form engine). The old separation SQL read fields that no longer exist at the paths it expected, so it silently produced NULLs. We built **v3 versions of both tables** that read the new shape, keeping v2 column names so downstream reporting can be repointed with minimal churn.

**Architectural decision:** keep the *two-table* split (do **not** consolidate into one table). An earlier consolidated `rawform_forms_v3` attempt was scrapped because the two cohort families have genuinely different `form_context`/`assessor_data` shapes and different downstream consumers.

### Data flow

```
DASH API  ──fetch──►  rawforms (forms JSONB)
                          │
              ┌───────────┴────────────┐
              ▼                         ▼
   cohort ∈ {DDS4,BOH3}        cohort ∉ {DDS4,BOH3}
   getBoh3Dds4FormsV3ProcessSql   getInsertSqlRawform_forms_v3
   → dds4_boh3_forms_v3           → rawform_forms_v3
              │                         │
              ▼                         ▼
    boh3_dds4_utils.py reports   boh2_dds2_dds3_utils.py +
    (mostly new-shape ready)     general_utils.py reports (OLD flat shape — needs rewrite)
```

---

## 2. The new `rawforms.forms` structure

`forms` is a **JSON array** of form objects (legacy rows can be a JSON object keyed by form_key — both separation SQLs still handle both via a `jsonb_each ∪ jsonb_array_elements` lateral).

### 2a. Common form-object skeleton (all cohorts)

```json
{
  "id": 26133,
  "form_key": "PKrlA0",
  "version": 2,
  "assessor": 199,
  "assessor_name": "Test Assessor",
  "assessor_email": "test.assessor@unimelb.edu.au",
  "created_at": "2026-06-22T23:30:28+10:00",
  "updated_at": "2026-06-22T23:30:28+10:00",
  "form_context": { ... },          // shape differs by cohort family (see below)
  "student_data":  { "radio":{}, "texts":{}, "scales":{}, "checklists":{}, "multi-select":{} },
  "assessor_data": { "radio":{}, "texts":{}, "scales":{}, "checklists":{}, "multi-select":{} },
  "student_config": { ... },
  "assessor_config": { ... },
  "context_schema_snapshot": [ ... ],
  "submitted_by_student": true,
  "submitted_by_assessor": true
}
```

The `student_data`/`assessor_data` buckets are **nested**: `radio`, `texts`, `scales`, `checklists`, `multi-select`.

- **scales**: `{ "<scaleKey>": { "key": "...", "value": "..." } }`
  - Final-year (DDS4/BOH3) use **prefixed** keys: `scale-entrustment`, `scale-global-rating`, `scale-practice-readiness`, …
  - Other cohorts (BOH2 family) use **bare** keys: `entrustment`, `time_mgmt`, `communication`, `professionalism`, `patient_complexity`.
  - The graded level is under **`key`** (e.g. `"S3"` or `"3"`), **not** `scale`.
- **checklists**: `{ "<item_code>": { "MC1": { "key":"Yes","value":"Yes" }, ... } }` — values are `{key,value}` objects, not plain strings.
- **radio**: `{ "clinical-incident-occurred":"yes|no", "additional-concerns-occurred":"yes|no" }`
- **texts**: e.g. `reflection`, `additional-concerns`, `additional_comments`.
- **multi-select**: e.g. `clinical-incident`, `strengths`, `weakness-*` → arrays of `{key,value}`.

### 2b. Final-year `form_context` (DDS4 / BOH3)

```json
"form_context": {
  "patients": [
    { "item_codes":[{"code":"014","quantity":1}], "patient_age":"45",
      "visit_number":"1", "priority_group":[], "patient_attended":true, "priority_present":"no" }
  ],
  "placement": { "rotation":"Rotation 1", "external_clinic":"DTC" }
}
```
No `clinic_type`, no `role`, no single `patient`. Patients is an **array**.

### 2c. Other-cohorts `form_context` (BOH1/BOH2/DDS1/2/3)

```json
"form_context": {
  "role":"O",
  "patient": { "age":"41","drn":"...","details":"ISP","interpreter":false,"fta_substitute":null },
  "placement": { "rotation":"","external_clinic":"" },
  "clinic_type":"GP",
  "teeth_quadrant":""
}
```
Single `patient` object, has `role` and `clinic_type`.

---

## 3. Table A — `dds4_boh3_forms_v3` (final-year)

**Code:** `boh3_dds4_utils.py` → `_CREATE_TABLE_V3_SQL`, `getBoh3Dds4FormsV3ProcessSql(replace, tableName="dds4_boh3_forms_v3")`
**Wired in:** `main.ipynb` **cell 63** `processDds4BohForms()` (builds table, then runs `getClinicStandardizationSql(..., tableName="dds4_boh3_forms_v3")`).
**v2 equivalent (left intact):** `getBoh3Dds4FormsProcessSql` / `_CREATE_TABLE_SQL` → `dds4_boh3_forms`.

### Column mapping (v2 name kept; only source path changed)

| Column | New source | Note |
|---|---|---|
| assessmentId, form_code, cohort, subject, type, completed, datetimeUtc, student_number/name/email | `rawforms` row / `form_key` | unchanged |
| formId, version, assessorId, assessor_name, createdAt, updatedAt | form-level `id/version/assessor/assessor_name/created_at/updated_at` | unchanged |
| **assessor_email** | form-level `assessor_email` | **NEW** |
| student_data, assessor_data, student_config, assessor_config | form-level (raw, whole) | unchanged |
| **context_schema_snapshot** | form-level `context_schema_snapshot` | **NEW** |
| **clinic** | `form_context.placement.external_clinic` | was empty in v2; filled w/ external_clinic |
| **rotation** | `form_context.placement.rotation` | was top-level `rotation` |
| **external_clinic** | `form_context.placement.external_clinic` | was top-level |
| **patient_data** | `form_context.patients` (array) | was top-level `patient_data` |
| **additional_concerns** | `assessor_data.texts.additional-concerns` | was top-level `additional_concerns` |
| **additional_concerns_occurred** | `assessor_data.radio.additional-concerns-occurred` → bool | **NEW** |
| submitted_by_student, submitted_by_assessor, insertedAt | form-level / now() | unchanged |

`clinic` and `external_clinic` are intentionally identical (both = placement.external_clinic) so the existing clinic-standardization UPDATE keeps working on `external_clinic`.

### ON CONFLICT
`PRIMARY KEY (assessmentId, form_code)`. `replace=True` → `DO UPDATE SET` every column + `insertedAt=now()`; `replace=False` → `DO NOTHING`.

### Verification (done)
Simulated column extraction over **real** DDS4 + BOH3 rows (from `temp 2026 caf.json`). All columns resolve: e.g. BOH3 → `clinic=DTC`, `rotation=Rotation 1`, `patient_data`=1-element array, `additional_concerns="They wore tracksuit pants"`, `additional_concerns_occurred=true`, `assessor_email` present. **Not** run against live Postgres (none in sandbox).

---

## 4. Table B — `rawform_forms_v3` (other cohorts)

**Code:** `general_utils.py` → `CREATE_RAWFORM_FORMS_V3_TABLE_SQL`, `getInsertSqlRawform_forms_v3(replace)`, helper `_flattenChecklistsSqlExpr(rawExpr)`, constant `RAWFORM_FORMS_V3_EXCLUDE_COHORTS = ("DDS4","BOH3")`.
**Wired in:** `main.ipynb` **cell 6** `processForms()` (create table, insert with `replace=replaceExisting`, then `getDeleteSql(RAWFORM_FORMS_V3_NAME)`).
**Cohort filter:** `WHERE r.cohort NOT IN ('DDS4','BOH3')` — final-year go to Table A.

### Schema changes vs v2 `rawform_forms`
- **Collapsed** `patient_age`, `patient_drn`, `patient_details`, `patient_interpreter` → single **`patient_data JSONB`** = `form_context.patient`.
- **Added** `context_schema_snapshot JSONB`, `assessor_email TEXT`.
- All other v2 columns kept with same names: `student_data, assessor_data, student_reflection, assessor_reflection, clinical_incident, patient_complexity, role, clinic, scales, checklists, version, assessor_name, submitted_by_student, submitted_by_assessor, additional_checklists`.

### Column mapping

| Column | New source |
|---|---|
| clinic | `form_context.clinic_type` |
| role | `form_context.role` |
| patient_data | `form_context.patient` (single object JSONB) |
| patient_complexity | `assessor_data.scales.patient_complexity.key` (bare key) |
| student_reflection / assessor_reflection | `*_data.texts.reflection` |
| clinical_incident | joined `assessor_data.multi-select.clinical-incident[].value` via `string_agg(..., '; ')` (TEXT) |
| scales (col) | `assessor_data.scales` (nested, new shape) |
| checklists (col) | `assessor_data.checklists` (nested, new shape) |
| context_schema_snapshot | form-level `context_schema_snapshot` |
| assessor_email | form-level `assessor_email` |

### KEY architectural decision — `assessor_data` / `student_data` storage shape

Agreed hybrid (see §6 decision log):
- **scales** → stored in the **NEW nested shape** only (`*_data.scales.<bareKey>.{key,value}`).
- **checklists** → kept nested **AND** a **v2-style flattened copy is merged onto the top level** of `student_data`/`assessor_data`, so existing item-code/checklist reads keep working. Flattened entry: `"<item_code>": { "MC1": "<keyString>", "MC2": "<keyString>" }` (plain string = the `key` field, not the `{key,value}` object).

**Before (raw API) →**
```json
"assessor_data": {
  "scales":{"entrustment":{"key":"3","value":"Level 3..."}},
  "checklists":{"011":{"MC1":{"key":"Yes","value":"Yes"}}},
  "radio":{"clinical-incident-occurred":"no"}, "texts":{}, "multi-select":{}
}
```
**After (stored in rawform_forms_v3) →**
```json
"assessor_data": {
  "scales":{"entrustment":{"key":"3","value":"Level 3..."}},        // nested kept
  "checklists":{"011":{"MC1":{"key":"Yes","value":"Yes"}}},          // nested kept
  "radio":{...}, "texts":{}, "multi-select":{},
  "011":{"MC1":"Yes"}                                                // NEW flattened copy at top level
}
```

The flatten is done in SQL by `_flattenChecklistsSqlExpr()` → `raw || flat` (`jsonb ||` merge). It is robust to missing/non-object `checklists` (returns `{}`). Value coalesces `mc_val->>'key'` then `mc_val#>>'{}'` (handles a plain-string rubric if one ever appears).

### ON CONFLICT
`PRIMARY KEY (form_code, assessmentid)`. Same `DO UPDATE` (all columns) / `DO NOTHING` pattern.

### Verification (done)
Python simulation of the exact transform on the BOH2 sample → produces the intended shape: nested `scales`/`checklists` retained, flat `011/022/114-115/...` item codes at top level with `MC→"Yes"` strings; scalar columns correct (`role=O`, `clinic=GP`, `patient_complexity=non-complex`, `patient_data`=patient object). Rendered SQL checked: no stray `{}` placeholders, balanced parens. **Not** run against live Postgres.

---

## 5. Files touched this session

| File | Change |
|---|---|
| `boh3_dds4_utils.py` | **Added** `_CREATE_TABLE_V3_SQL`, `getBoh3Dds4FormsV3ProcessSql()`. v2 untouched. |
| `general_utils.py` | **Replaced** the scrapped consolidated block with the other-cohorts `CREATE_RAWFORM_FORMS_V3_TABLE_SQL`, `getInsertSqlRawform_forms_v3()`, `_flattenChecklistsSqlExpr()`, `RAWFORM_FORMS_V3_EXCLUDE_COHORTS`. |
| `main.ipynb` cell 6 | `getInsertSqlRawform_forms_v3(replace=replaceExisting)`. |
| `main.ipynb` cell 63 | calls `getBoh3Dds4FormsV3ProcessSql`, counts/standardizes on `dds4_boh3_forms_v3`. |

---

## 6. Architectural decision log

1. **Two tables, not one.** Consolidated `rawform_forms_v3` scrapped; separate final-year vs other-cohorts pipelines retained.
2. **v2 column names preserved** in both v3 tables → downstream repoint by changing `formsTable`, not query columns (where shapes allow).
3. **`clinic = external_clinic`** for final-year (no `clinic_type` in their context) — matches old dds4_boh3 intent.
4. **Patient info collapsed to `patient_data` JSONB** in `rawform_forms_v3` (user preference). Reporting will derive `patient_age`/`patient_details` from it inside `getDataDf` (see §7).
5. **`clinical_incident` stays a single TEXT** = joined multi-select values (no separate occurred bool for other cohorts).
6. **`additional_concerns` = TEXT + `additional_concerns_occurred` bool** for final-year.
7. **scales new-nested; checklists nested + flattened-to-top** for other cohorts (compat compromise so item-code reads survive without a full report rewrite of the checklist logic).
8. Optional new columns added: `assessor_email`, `context_schema_snapshot` (both tables).

---

## 7. REMAINING WORK — downstream rewiring (do this next)

### 7.1 Final-year reports — `boh3_dds4_utils.py` (LOW effort) — ✅ DONE (2026-07-29)
These were already updated for the new shape (read `patient_data` as an array via `jsonb_array_elements`, read `student_data->'checklists'->'checklist-caf-final-eval'`, read `assessor_data->'scales'->'scale-entrustment'`).

- **✅ Repoint defaults:** all **40** functions changed `formsTable="dds4_boh3_forms"` → `"dds4_boh3_forms_v3"` (chose in-utils default change over per-call-site; v2 table still reachable by passing the old name explicitly). 0 old defaults remain.
- **✅ Scale accessor path:** changed `->>'scale'` → `->>'key'` — **23** occurrences total, not just entrustment. The graded level is stored under `key` (verified in real `temp 2026 caf.json`: entrustment=`"S3"`, readiness=`"S4"`); the `CASE WHEN 'S1'..'S4'` labels already matched so only the accessor changed; config lookups `->'fields' -> (…->>'key')` now index correctly.
  - **⚠ Handover-list correction:** the original "affected lines" list named only `scale-entrustment` and missed `scale-practice-readiness` (**8** occurrences, incl. ~L1184, 1293, 1308, 1331–1332, 1905–1907, 1983–1984) plus entrustment occurrences at ~L1908–1998. The blanket `->>'scale'`→`->>'key'` replace caught all 23; do **not** treat the earlier line list as exhaustive. `scale-global-rating` is not used in this file.
- **Verification:** static only — `py_compile` OK, counts confirmed (40 v3 defaults / 0 old; 0 `->>'scale'` remaining / 23 `->>'key'`, 0 pre-existing), diff reviewed. **Not** run against live Postgres. Per §7.3, run cell 63 `processDds4BohForms()` on a small cohort and spot-check `dds4_boh3_forms_v3` before production.

### 7.2 Other-cohorts reports — `boh2_dds2_dds3_utils.py` + `general_utils.py` (HIGH effort)
These read the **OLD flat** `assessor_data` shape. Two classes of fix:

**(a) Scales — path change** (`->'scale-x'->>'scale'` → `->'scales'->'x'->>'key'`, bare keys):
- `boh2_dds2_dds3_utils.py`: **lines 252–269** (`getFullDf`/scale extraction), **386–402** (`getStudentScaleSummary`), **457–472** & **506–507** (`getFlaggedFormDetails`), **835–853** (`getDataDf`).
- `general_utils.py`: `getGlobalRatingSqlDDS2` (~L810 reads `key='scale-global-rating'` via `jsonb_each(assessor_data)` + `v->>'scale'`), `getWeeklySimDataSqlDDS2` (~L840 `MAX(CASE WHEN s.key='scale-global-rating' THEN ... ->>'scale')`). Both must target the nested `scales` sub-object and `->>'key'`.
- Note the graded value is now a **string** (`"3"`, `"S3"`), sometimes letter-prefixed → use `regexp_replace(x,'\D','','g')` before `::int` where an int is expected.

**(b) Checklists / item codes — use the flattened top-level copy we added.** Reads like `jsonb_each(assessor_data) WHERE key NOT LIKE 'scale-%'` (e.g. `boh2_dds2_dds3_utils.py` L859 item_codes in `getDataDf`; L165/218/405 `jsonb_each(f.checklists)`; `calcScore` iterating `assessor_data.items()`) will now also pick up the new top-level buckets `radio/texts/scales/checklists/multi-select`. **Exclude them**, e.g. `WHERE key NOT LIKE 'scale-%' AND key NOT IN ('radio','texts','scales','checklists','multi-select')`. The flattened `"011":{"MC1":"Yes"}` entries then behave exactly like the old v2 data, so `SCORE_MAP` logic works unchanged.

**(c) Patient fields — derive in `getDataDf`** (`boh2_dds2_dds3_utils.py` ~L828). Add to the SELECT:
```sql
patient_data->>'age'          AS patient_age,     -- cast ::int in pandas or NULLIF(...,'')::int
patient_data->>'details'      AS patient_details,
patient_data->>'drn'          AS patient_drn,
(patient_data->>'interpreter')::boolean AS patient_interpreter,
```
Consumers `adf["patient_age"]`, `adf["patient_details"]` are at `general_utils.py`-side report ~L1112–1127 (age-band chart, patient-details counts) — they keep working once `getDataDf` exposes the columns.

**(d) `getChecklistBank`** (`general_utils.py`, reads `FROM {RAWFORM_FORMS_NAME}` + `jsonb_each(checklists)->'fields'`): the `checklists` **column** now holds the nested **data** (no `'fields'`). The checklist definitions (`{name, fields:{MC:desc}}`) now live in **`assessor_config->'checklists'->'selected'`** / `student_config->'checklists'->'selected'`. Repoint this function to read the config, not the data column.

**(e) Repoint `formsTable` default:** 16 functions in `boh2_dds2_dds3_utils.py` default `formsTable="rawform_forms"` → `"rawform_forms_v3"`.

### 7.3 Cleanup / gotchas
- **Name collision:** `general_utils.py` **L23** `RAWFORM_FORMS_NAME = "rawform_forms_v3"`. The **dead** v2 `CREATE_RAWFORM_FORMS_TABLE_SQL` (L49) and `getInsertSqlRawform_forms` (L256) reference this constant, so they'd target the v3 name with the v2 schema if ever called. They are currently unused. Recommend: delete the dead v2 funcs, and set `RAWFORM_FORMS_NAME` intentionally (it's still used by `getChecklistBank` at ~L1179). 6 `rawform_forms` refs remain in `general_utils.py`.
- **Other readers of `rawform_forms`:** `boh1_utils.py`, `assessor_analysis.py`, `webapp/var.py` also reference it — audit when repointing.
- **No live Postgres test** was possible in the build sandbox. Before trusting production runs, execute both `main.ipynb` cells against the real DB on a small cohort and spot-check the two tables.

---

## 8. How to run / test

1. Ensure `rawforms` is populated (cell 4 `main()` fetches API → inserts).
2. **Other cohorts:** run cell 6 `processForms()` → builds/fills `rawform_forms_v3` (excludes DDS4/BOH3).
3. **Final year:** set `includeCohorts=["DDS4","BOH3"]`, `targetCohorts` accordingly, run cell 63 `processDds4BohForms()` → builds/fills `dds4_boh3_forms_v3`.
4. Spot-check:
```sql
SELECT cohort, count(*) FROM rawform_forms_v3 GROUP BY cohort;         -- no DDS4/BOH3
SELECT cohort, count(*) FROM dds4_boh3_forms_v3 GROUP BY cohort;        -- only DDS4/BOH3
-- flattened checklist present at top level of assessor_data:
SELECT assessor_data->'011' FROM rawform_forms_v3 WHERE assessor_data ? '011' LIMIT 1;
-- nested scales preserved:
SELECT assessor_data->'scales' FROM rawform_forms_v3 LIMIT 1;
```

## 9. Quick reference — function/constant index

| Symbol | File | Purpose |
|---|---|---|
| `getBoh3Dds4FormsV3ProcessSql` | boh3_dds4_utils.py | build `dds4_boh3_forms_v3` (create+upsert) |
| `_CREATE_TABLE_V3_SQL` | boh3_dds4_utils.py | final-year v3 DDL |
| `getInsertSqlRawform_forms_v3` | general_utils.py | build `rawform_forms_v3` insert |
| `CREATE_RAWFORM_FORMS_V3_TABLE_SQL` | general_utils.py | other-cohorts v3 DDL |
| `_flattenChecklistsSqlExpr` | general_utils.py | nested→flat checklist SQL expr |
| `RAWFORM_FORMS_V3_EXCLUDE_COHORTS` | general_utils.py | `("DDS4","BOH3")` |
| `getClinicStandardizationSql` | boh3_dds4_utils.py | clinic-name cleanup (pass `tableName`) |
