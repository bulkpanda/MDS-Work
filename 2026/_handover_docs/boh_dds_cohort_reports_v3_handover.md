# BOH1/BOH2/DDS2/DDS3 Cohort Reports → rawforms v3 — Handover

**Date:** 2026-08-04
**Scope:** Migrating the non-final-year **cohort reports** (and their shared query chain) in `boh2_dds2_dds3_utils.py` + `general_utils.py` to the new `rawform_forms_v3` shape.
**Status:** `getCohortReports` (main.ipynb **cell 10**) **works well — confirmed by user**. All secondary fixes (checklist definition readers, DDS2 weekly SQL, patient fields, BOH1/BOH2 student-data fallback) are implemented and statically verified. Final-year (DDS4/BOH3) was already migrated in a prior session (`boh3_dds4_utils.py`).

> This continues from `rawforms_v3_separation_handover.md` (§7.2 "Other-cohorts reports — HIGH effort"). **Important correction to that doc is in §2 below.**

---

## 1. TL;DR — what to know before touching anything

- Reports for BOH1/BOH2/DDS2/DDS3 read from the **`rawform_forms_v3`** table (built by `main.ipynb` cell 6 `processForms()`), **not** `rawform_forms`.
- **Scale keys are PREFIXED and NESTED**, graded level under `key`:
  `assessor_data->'scales'->'scale-global-rating'->>'key'`. (The separation handover's "bare keys" claim was **wrong** — see §2.)
- Checklist **definitions** (item name + MC descriptions) are **not** in the data columns anymore — they live in **`assessor_config`/`student_config`** (added this session).
- `getCohortReports(engine, cohort, today)` is the entry point and is verified working.
- **Action required after pulling this code:** re-run cell 6 with `replaceExisting=True` to backfill the two new config columns (see §7).

---

## 2. ⚠ Correction to the separation handover — the actual v3 data shape

`rawforms_v3_separation_handover.md` §2a/§7.2(a) said other-cohort scales use **bare keys** (`entrustment`, `time_mgmt`, …). **This is wrong.** Verified against real DDS2/DDS3/BOH1 rows from `rawform_forms_v3` (2026-08-04): non-final-year cohorts use the **same prefixed keys as final-year**, nested under `assessor_data->'scales'`, with the graded level under **`key`** (not `scale`).

### Real `assessor_data` (DDS2 Simulation, abbreviated)
```json
{
  "radio": {},
  "texts": { "reflection": "Slob rule" },
  "scales": {
    "scale-time-mgmt":          { "key": "2", "value": "Level 2: ..." },
    "scale-communication":      { "key": "2", "value": "Level 2: ..." },
    "scale-global-rating":      { "key": "3", "value": "Satisfactory" },
    "scale-professionalism":    { "key": "2", "value": "Level 2: ..." },
    "scale-practice-readiness": { "key": "3", "value": "Level 3 – ..." },
    "scale-position-ergonomics":{ "key": "2", "value": "Level 2: ..." }
  },
  "Week-05":    { "MC1": "O2", "MC2": "O3", "MC3": "O4" },      // flattened item code (top level)
  "checklists": { "Week-05": { "MC1": {"key":"O2","value":"Done well"}, "MC2": {"key":"O3","value":"Mostly done"} } },
  "multi-select": {}
}
```

### Scale key reference (non-final-year)
| Report concept | JSON key (under `scales`) | Notes |
|---|---|---|
| Entrustment | `scale-practice-readiness` | entrustment == practice-readiness for these cohorts; int 1–4 |
| Professionalism | `scale-professionalism` | int |
| Communication | `scale-communication` | int |
| Time management | `scale-time-mgmt` | int |
| **Global rating** | `scale-global-rating` | int 1–5 (3=Satisfactory, 4=Good). **Counted separately** — own column/pivot/trigger, NOT in the level-scale summary |
| Patient complexity | `scale-patient-complexity` | **text** (`non-complex`/`complex`), never cast to int |
| (others present) | `scale-preparedness`, `scale-safe-not-safe`, `scale-record-keeping`, `scale-infection-control`, `scale-position-ergonomics` | not used by cohort reports |

Values are plain integer strings for level scales (`"2"`,`"3"`,`"4"`) and text for complexity/safe. Read as `NULLIF(<scales>->'scale-x'->>'key','')::int`.

### assessor_data top-level buckets (critical gotcha)
In v3, `assessor_data` (and `student_data`) top level holds the **5 standard buckets** (`radio`, `texts`, `scales`, `checklists`, `multi-select`) **plus flattened item-code entries** (`"Week-05": {"MC1":"O2"}`). Any code that iterates `jsonb_each(assessor_data)` to find item codes **must exclude** those 5 buckets and `scale-%`:
```sql
WHERE key NOT LIKE 'scale-%'
  AND key NOT IN ('radio','texts','scales','checklists','multi-select')
```

---

## 3. The v3 table (`rawform_forms_v3`)

Built by `general_utils.py` → `CREATE_RAWFORM_FORMS_V3_TABLE_SQL` + `getInsertSqlRawform_forms_v3(replace)`, wired at `main.ipynb` cell 6. PK `(form_code, assessmentid)`.

**Columns added this session:** `student_config JSONB`, `assessor_config JSONB`.

Relevant columns for reporting:
| Column | Source | Shape / use |
|---|---|---|
| `assessor_data` / `student_data` | raw nested + flattened checklist copy merged on top | see §2 |
| `scales` | `assessor_data->'scales'` | nested, prefixed keys |
| `checklists` | `assessor_data->'checklists'` | `{item_code: {MC: {key,value}}}` (assessor's) |
| `patient_data` | `form_context.patient` | `{age,drn,details,interpreter,fta_substitute}` |
| `patient_complexity` | `scales->'scale-patient-complexity'->>'key'` | text |
| `clinical_incident` | joined `multi-select.clinical-incident[].value` | TEXT |
| `student_reflection`/`assessor_reflection` | `texts->>'reflection'` | ⚠ null when a form uses multi-reflection keys (see §8) |
| `clinic` | `form_context.clinic_type` | code e.g. `GP`, `RP`, `SS` |
| `role` | `form_context.role` | `O`/`OB`/`SO` |
| **`assessor_config`/`student_config`** | form-level `*_config` | checklist **definitions** live here (§4) |

### Checklist definition shape (config)
```json
"assessor_config": { "checklists": { "mode": "student_select", "selected": {
  "Consent":     { "name": "Consent Checklist",  "fields": { "MC1": "Obtains informed consent ..." } },
  "positioning": { "name": "Positioning and Ergonomics Checklist",
                   "fields": { "MC1": "Adjusts clinician chair correctly", "MC2": "Maintains good posture ..." } }
} } }
```
This is identical to the old v2 `checklists` column shape (`name` + `fields:{MC:desc}`), which is why repointing the readers to the config keeps `->>'name'` / `->'fields'` working.

---

## 4. Cohort report chain — functions & data flow

Entry point (`main.ipynb` cell 10):
```python
getCohortReports(engine, "DDS2", today)                       # Simulation + Clinic
getCohortReports(engine, "DDS3", today, type_=["Clinic"])     # Clinic only
getCohortReportsPerClinic(engine, "DDS3", today)              # per-clinic breakdown
```

`getCohortReports` (`boh2_dds2_dds3_utils.py`) orchestrates and writes 3 workbooks per cohort into `{cohort}/`:
- `Scale Information {cohort} ({today}).xlsx`
- `Item Code Pivot {cohort} ({today}).xlsx`
- `Submission Info {cohort} ({today}).xlsx`

```
getCohortReports
├─ getStudentScaleSummary   → scales (level counts + averages)   [v3 nested scales]
├─ getCriticalIncidentDf    → clinical_incident TEXT column      [unchanged]
├─ getStudentFormCountDf    → COUNT(*)                            [unchanged]
├─ getStudentItemCodePivot → getStudentItemCodeDf → pivotItemCodes
│                             item codes + GR/Entrustment pivots  [v3 nested scales + nested checklists]
├─ getSubmissionInfo        → submitted flags                     [unchanged]
├─ getClinicList            → distinct clinic                     [unchanged]
└─ getFlaggedFormDetails    → low GR / low entrustment forms      [v3 nested scales]
```

**Default `formsTable` for the whole chain is now `"rawform_forms_v3"`.** Pass the old table name explicitly only if you must hit v2.

---

## 5. What changed this session (implementation detail)

### 5.1 `boh2_dds2_dds3_utils.py`
- **Scale path migration** in `getStudentScaleSummary`, `getStudentItemCodeDf`, `getFlaggedFormDetails`, `getDataDf`:
  `assessor_data->'scale-x'->>'scale'` → `assessor_data->'scales'->'scale-x'->>'key'`.
- **`formsTable` default** `rawform_forms` → `rawform_forms_v3` across the file.
- **Item-code lateral / `calcScore`** now exclude the 5 buckets (see §2 gotcha).
- **`getChecklistItems` / `getChecklistMcTexts`** repointed to config:
  ```sql
  CROSS JOIN LATERAL jsonb_each(
      COALESCE(f.assessor_config->'checklists'->'selected',
               f.student_config->'checklists'->'selected', '{}'::jsonb)
  ) AS item(item_code, item_data)
  ```
- **Patient fields** derived in `getDataDf`:
  ```sql
  NULLIF(regexp_replace(f.patient_data->>'age','[^0-9]','','g'),'')::int AS patient_age,
  f.patient_data->>'details'      AS patient_details,
  f.patient_data->>'drn'          AS patient_drn,
  f.patient_data->>'interpreter'  AS patient_interpreter,
  ```
- **`plotStudentScoresTimeSeries`** complexity read fixed to `assessor_data['scales']['scale-patient-complexity']['key']`.
- **NEW helpers** `_effScalesSrc(cohort, prefix)` / `_effChecklistsSrc(cohort, prefix)` + `STUDENT_FALLBACK_COHORTS = ("BOH1","BOH2")` — see §6.

### 5.2 `general_utils.py`
- `CREATE_RAWFORM_FORMS_V3_TABLE_SQL`: added `student_config JSONB`, `assessor_config JSONB`.
- `getInsertSqlRawform_forms_v3`: insert list + SELECT (`f.form_value->'student_config'`, `->'assessor_config'`) + ON CONFLICT DO UPDATE. **Fixed** `patient_complexity` to `scales->'scale-patient-complexity'->>'key'` (was bare `patient_complexity` → always NULL).
- `getGlobalRatingSqlDDS2`, `getWeeklySimDataSqlDDS2`: repointed to `RAWFORM_FORMS_NAME` (=`rawform_forms_v3`), iterate `assessor_data->'scales'` with `->>'key'`, added bucket exclusion to the checklist CTEs.
- `getChecklistBank`: reads `COALESCE(assessor_config, student_config)->'checklists'->'selected'` instead of the data column.

---

## 6. Architectural decisions

1. **Prefixed nested scales confirmed authoritative** (§2) — overrides the separation handover.
2. **Global rating counted separately** from level scales (own column/pivot/trigger) — matches assessment design and user instruction.
3. **Checklist definitions come from config, not data.** The v3 separation intentionally stores only response data in `checklists`; definitions were added as `student_config`/`assessor_config` columns rather than re-parsing raw `rawforms`.
4. **BOH1/BOH2 student-data fallback** implemented generically and **cohort-gated** (only `STUDENT_FALLBACK_COHORTS`), so DDS2/DDS3 behaviour is byte-for-byte unchanged:
   - `_effScalesSrc` → `COALESCE(NULLIF(assessor_data->'scales','{}'), student_data->'scales', '{}')` (Smile Squad BOH2 has only student_data; empty-assessor falls back).
   - `_effChecklistsSrc` → `(student_data->'checklists' || assessor_data checklists)` — **UNION** so BOH1 student-only item codes appear (assessor wins on key conflict).
5. **`getFlaggedFormDetails` deliberately reads assessor_data only** (no student fallback) — flagging low assessor grades.
6. **`formsTable` default flipped in-utils** (not per call-site), mirroring the final-year migration.

---

## 7. How to run / test

1. **Pull code**, ensure `rawforms` is populated (cell 4 `main()`).
2. **⚠ Backfill config columns (one-time):** run `main.ipynb` **cell 6** `processForms()` with `replaceExisting=True` so `student_config`/`assessor_config` get populated. Until then, cell 9 checklist explorers return empty.
3. **Cohort reports:** run **cell 10**:
   ```python
   getCohortReports(engine, "DDS2", today)
   getCohortReports(engine, "BOH2", today)
   getCohortReports(engine, "BOH1", today)
   getCohortReports(engine, "DDS3", today, type_=["Clinic"])
   getCohortReportsPerClinic(engine, "DDS3", today)
   ```
4. Spot-check SQL:
   ```sql
   SELECT assessor_config->'checklists'->'selected' FROM rawform_forms_v3
   WHERE assessor_config IS NOT NULL LIMIT 1;                        -- definitions present
   SELECT assessor_data->'scales'->'scale-global-rating'->>'key'
   FROM rawform_forms_v3 WHERE cohort='DDS2' LIMIT 5;               -- global rating
   SELECT patient_data->>'age' FROM rawform_forms_v3 WHERE cohort='DDS3' LIMIT 5;
   ```

### Verification done this session
- `py_compile` clean on both files.
- Simulated every migrated extraction against **4 real v3 rows** (DDS2 sim/clinic, DDS3 clinic, BOH1 sim): scales, item-code counting (bucket-excluded), `calcScore` (O2=1.0/O3=0.66/O4=0.33/O6=NaN), config→definitions, patient-field derivation, and the effective-source exprs all resolve correctly.
- **Not** run against live Postgres in the build environment. **User confirmed `getCohortReports` works well against the real DB.**

---

## 8. Remaining / open items (next session)

- **Multi-reflection forms** (e.g. DDS2 `DENT90146`): use keys like `reflection-student-improve`, `reflection-what-did-well` instead of `reflection`. The v3 insert only extracts `texts->>'reflection'`, so `student_reflection`/`assessor_reflection` are **NULL** for these. Affects `getFlaggedFormDetails` comment filter and any reflection display. Fix: coalesce/aggregate the `reflection-*` text keys in the insert (or in `getDataDf`).
- **Dead v2 funcs** `getInsertSqlRawform_forms` (general_utils L~258) and `CREATE_RAWFORM_FORMS_TABLE_SQL` (L~50): unused but target the v3 table **name** with v2 columns (`patient_age`, …) that don't exist → would error if ever called. Recommend delete (separation handover §7.3 agrees). Left in place pending sign-off.
- **Student PDF reports** (`buildStudentReport`, `buildEntireCohortStudentReports`) and **`buildCohortTimeSeriesPdf`** (cell 11): defaults flipped to v3 and they consume the migrated `getDataDf`/`calcScore`, but end-to-end PDF output not user-verified. `buildCohortTimeSeriesPdf` already contains BOH2 Smile Squad swap logic — re-check it against the new `_eff*` helpers to avoid double-handling.
- **Other `rawform_forms` readers** to audit when convenient: `boh1_utils.py`, `assessor_analysis.py`, `webapp/var.py`.

## 9. Quick reference — symbol index
| Symbol | File | Purpose |
|---|---|---|
| `getCohortReports` / `getCohortReportsPerClinic` | boh2_dds2_dds3_utils.py | cohort report orchestrators (cell 10) |
| `getStudentScaleSummary` | boh2_dds2_dds3_utils.py | level-scale counts/averages |
| `getStudentItemCodeDf` / `getStudentItemCodePivot` / `pivotItemCodes` | boh2_dds2_dds3_utils.py | item-code + GR/entrustment pivots |
| `getFlaggedFormDetails` | boh2_dds2_dds3_utils.py | low-GR / low-entrustment flags |
| `getDataDf` / `calcScore` | boh2_dds2_dds3_utils.py | per-student form data + item scores |
| `getChecklistItems` / `getChecklistMcTexts` | boh2_dds2_dds3_utils.py | checklist definitions (from config) |
| `_effScalesSrc` / `_effChecklistsSrc` / `STUDENT_FALLBACK_COHORTS` | boh2_dds2_dds3_utils.py | BOH1/BOH2 student-data fallback |
| `getInsertSqlRawform_forms_v3` / `CREATE_RAWFORM_FORMS_V3_TABLE_SQL` | general_utils.py | build/fill rawform_forms_v3 (+config cols) |
| `getGlobalRatingSqlDDS2` / `getWeeklySimDataSqlDDS2` | general_utils.py | DDS2 weekly SQL (v3) |
| `getChecklistBank` | general_utils.py | checklist bank (from config) |

**Backups:** `boh2_dds2_dds3_utils.py.bak_20260804_132525`, `general_utils.py.bak_20260804_*`.
