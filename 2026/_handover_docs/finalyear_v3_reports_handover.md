# Final-Year (DDS4 / BOH3) v3 Reports Rewiring — Handover

**Date:** 2026-07-31
**File primarily touched:** `boh3_dds4_utils.py` (+ `main.ipynb` cell 63 `processDds4BohForms`)
**Predecessor doc:** `_handover_docs/rawforms_v3_separation_handover.md` (the table-build work; this doc continues its §7.1)
**Status:** Cohort-summary PDF pipeline (`buildCohortSummaryPdf`) fully migrated to the v3 shape and runs on **BOH3** (live). Student-level report functions **NOT** done — see §7. DDS4 summary not yet run this session (call was commented out).

---

## 1. Context — where we are

The v3 separation produced `dds4_boh3_forms_v3` (final-year) with **v2 column names kept but new JSON shapes inside** the `patient_data / student_data / assessor_data / *_config / context_schema_snapshot` blobs. This session rewired the *reporting* code in `boh3_dds4_utils.py` from the old (v2) shape to the new (v3) shape, cohort-summary-PDF first.

Pipeline reached working state for **BOH3 cohort summary PDF**. The **per-student report** functions (`getStudent*`, `getAssessorRollup`, the big report/rollup SQL ~L1900–2160) still contain v2-shape reads and are the next job.

```
dds4_boh3_forms_v3  ──►  boh3_dds4_utils.py
                          ├── cohort-level fns (age/patients/clinic/items/entrustment/CAF)  ✅ v3-ready
                          ├── buildFrontPage / getFrontPageSummaryTable / buildCohortSummaryPdf ✅ v3-ready, runs
                          └── student-level fns (getStudent*, getAssessorRollup, rollup SQL)   ❌ still v2-shape
```

---

## 2. The v3 data shape (final-year) — quick reference

`dds4_boh3_forms_v3` columns unchanged from v2 **plus** `assessor_email`, `context_schema_snapshot`, `additional_concerns_occurred`.

### 2a. `patient_data` — JSON **array** of patient objects (v3)
```json
[{"item_codes":[{"code":"577","quantity":1},{"code":"LA1","quantity":1}],
  "patient_age":"82","visit_number":"4","priority_group":null,
  "patient_attended":true,"priority_present":"no"}]
```
- `item_codes` elements carry ONLY `{code, quantity}` — **no `description`, no `category`** (v2 had them inline).
- Keys are **snake_case**: `patient_age`, `visit_number`, `patient_attended`, `priority_present`, `priority_group`.
- May be JSON `null`/scalar on some rows → must guard with `jsonb_typeof(...)='array'` before `jsonb_array_elements`.

### 2b. `assessor_data` / `student_data` (v3) — nested buckets `radio/texts/scales/checklists/multi-select`
- **scales** (level under **`key`**, full text under `value`):
  ```json
  "scales": {"scale-entrustment": {"key":"S3","value":"Level 3: ..."}}
  ```
- **checklists** (values are **objects**):
  ```json
  "checklists": {"checklist-caf-final-eval": {"MC1": {"key":"O1","value":"Done well"}, ...}}
  ```
  Option map: `O1`=Done well(1.0), `O2`=Done(0.8), `O3`=Mostly done(0.6), `O4`=Sometimes done(0.4), `O5`=Not done(0.0).
- **multi-select** (items keyed by **`key`** in v3; v2 used `name`):
  ```json
  "multi-select": {"strengths": [{"key":"STR3","value":"Person-Centered Care: ..."}]}
  ```

### 2c. `context_schema_snapshot` — the source of truth for label maps
Array of field descriptors. Contains the `item_code_picker` `options` (category → `[{code, description}]`) for **every** item code, plus `placement.rotation` options (`R6`→`Rotation 6`) and clinic options (`EC02`→`Cobram District CHC`).

### v2 → v3 field mapping (final-year)
| Area | v2 (last year) | v3 (new) |
|---|---|---|
| clinic / external_clinic | name (`MDC`) | **code** (`EC02`) |
| rotation | text (`Rotation 1`) | **code** (`R6`) in raw upsert |
| patient keys | `patientAge`,`patientAttended`,`itemCodes`,`visitNumber`,`priorityGroup`,`priorityGroupOptions` | `patient_age`,`patient_attended`,`item_codes`,`visit_number`,`priority_present`,`priority_group` |
| item element | `{code,category,quantity,description}` | `{code,quantity}` only |
| scale leaf | `->>'scale'` (`{"scale":"S3"}`) | `->>'key'` (`{"key":"S3","value":...}`) |
| checklist value | plain string `"Mostly done"` | object `{"key":"O3","value":"Mostly done"}` |
| multi-select item code | `->>'name'` (`{"name":"STR3"}`) | `->>'key'` (`{"key":"STR3"}`) |
| new columns | — | `assessor_email`, `context_schema_snapshot`, `additional_concerns_occurred` |

---

## 3. Changes made THIS session (all in `boh3_dds4_utils.py` unless noted)

### 3.1 Scale accessor + formsTable defaults (§7.1 of predecessor doc) — DONE
- **40** functions: default `formsTable="dds4_boh3_forms"` → `"dds4_boh3_forms_v3"`.
- **23** occurrences: `->>'scale'` → `->>'key'` — covers `scale-entrustment` (15) **and** `scale-practice-readiness` (8). Verified vs real data: level stored under `key` (`"S3"`,`"S4"`); config lookups `->'fields' -> (…->>'key')` now index correctly; `CASE WHEN 'S1'..'S4'` labels already matched. `scale-global-rating` not used in this file.

### 3.2 Patient-data camelCase → snake_case — DONE (whole file, one pass)
`patientAge`→`patient_age`, `patientAttended`→`patient_attended`, `'itemCodes'`→`'item_codes'`. Python identifiers (`itemCodesDf`, column `"itemcode"`) intentionally left untouched. Affected: `getAgeCounts(Batch)`, `getAgeList`, `getAvgAge`, `getPatientsPerStudentStats`, `getPatientPerStudent`, `getPatientCountPerRow`, `getClinicPatientCounts`, `getTopItemCodes`, `getItemCodesPerStudentBatch`, plus student-level fns.

### 3.3 Scalar guard on all patient_data / item_codes array-expansions — DONE
`COALESCE(x,'[]'::jsonb)` only guards SQL NULL, not JSON `null`/scalar (some rows store patients/item_codes as JSON `null`), causing `InvalidParameterValue: cannot extract elements from a scalar`. Replaced **19** occurrences with:
```sql
jsonb_array_elements(CASE WHEN jsonb_typeof(<expr>)='array' THEN <expr> ELSE '[]'::jsonb END)
```
for `<expr>` in {`patient_data`, `f.patient_data`, `pd->'item_codes'`}.

### 3.4 CAF final-eval scoring for v3 object shape — DONE (cohort-level only)
`getCafFinalEvalScoreStudent` (L756). v2 stored plain strings, v3 stores `{key,value}` objects. Changed `jsonb_each_text` → `jsonb_each` and matched on `COALESCE(kv.value->>'value', kv.value#>>'{}')` (robust to both shapes). Verified: v3 row → 0.9714, legacy v2 string row → 0.8000.

### 3.5 Item-code Description sourced from schema snapshot — DONE
New helper **`getItemCodeDescriptionMap(engine, cohort, formsTable)`** (L686): reads one recent `context_schema_snapshot`, recursively harvests the `item_code_picker` `options` into `{code: description}`. `getItemCodesPerStudentBatch` (L727) drops the (now-NULL) SQL `MAX(ic->>'description')` and re-inserts the Description column (position 3) via `df["Item Code"].map(descMap)`. (The `item_section_mapping.xlsx` file has only `Item Code, Section, Sub-section` — no descriptions — hence the snapshot source.)

### 3.6 Top item codes weighted by quantity — DONE
`getTopItemCodes` (L662): `COUNT(*)::bigint AS freq` → `SUM(COALESCE(NULLIF(ic->>'quantity','')::int,1))::bigint AS freq`. Now consistent with the per-student "Total Qty" and section pivot (both already SUM quantity). **Quantity audit:** every place that *counts/totals* item codes now uses quantity (section pivot, per-student totals, top-item charts, student-report top items + cohort avg). The two `string_agg` code-listings (`getClinicalIncidentSummary`, `getSelfReflections`) list distinct codes as text — quantity N/A there.

### 3.7 Clinic code→name + Title-Case (in `main.ipynb` cell 63 `processDds4BohForms`) — DONE
- New helper **`getClinicCodeStandardizationSql(clinicDict=CLINIC_DICT, tableName, columns=("external_clinic","clinic"))`** (L157): single `UPDATE` with one independent `CASE` per column mapping EC-codes → names; unknown values left via `ELSE`. Example output maps `EC02`→`Cobram District CHC` in both columns.
- New helper **`smartTitleCaseClinic(name)`** (L193): title-cases each word but **preserves all-caps acronyms** (≥2 letters: `DTC`,`CHC`,`GV`,`VAHS`,`IPC`,`EACH`,`MDC`,`PC`). Applied to `external_clinic` as the final step (distinct-value loop in the cell).
- Cell 63 order: build/upsert v3 → **code→name map** → existing free-text standardization UPDATEs → **Title-Case external_clinic**.
- (Also bumped `getClinicStandardizationSql` default `tableName` to `_v3`; always called with explicit `tableName` so no behavior change.)

### 3.8 Professional banner: rotation range + generation date — DONE
- New **`getRotationRange(engine, cohort, formsTable, filters=None, minForms=20)`** (L1076): returns `(minNum, maxNum)` rotation numbers. **Max is gated to rotations backed by ≥ `minForms` (20) forms** so a one-off entry (e.g. a single form logged against a far rotation) doesn't inflate the range; falls back to raw max if none qualify. Min is earliest present, clamped ≤ max. Extracts the number via `regexp_replace(rotation,'[^0-9]','','g')` → robust to `Rotation 6` **or** `R6`.
- New **`buildBannerSubtitle(engine, cohort, formsTable)`** (L1112): `"Rotations 1 to 6   •   Generated 31 July 2026"` (collapses to `"Rotation 3"` if single; `"Generated <date>"` if none).
- `buildCohortSummaryPdf` now calls `getBannerDrawer(bannerTitle, buildBannerSubtitle(engine, cohort))` (was `""`). `getBannerDrawer(firstline, secondline)` lives in `Utils.py` L530 — unchanged, 2-line banner.

### 3.9 Entrustment NaN crash — DONE
`getEntrustmentSummary` (L847): the old `WHERE …->>'key' IS NOT NULL` let ungraded rows (blank/empty key) through the `CASE`'s implicit `ELSE NULL`, producing a NaN bucket that crashed `int(row.entrustment)` in `getFrontPageSummaryTable`. Fixed: `WHERE …->>'key' IN ('S1','S2','S3','S4')`. Also hardened the consumer (L~1019) to skip `pd.notna(row.entrustment)`.

**BOH3 entrustment reality (from live data):** S3=2173, S2=1045, S4=511, S1=39, plus **142 ungraded** (141 no entrustment object, 1 empty `{'key':'','value':''}`) ≈ 3.6%. No old-shape (`scale`) rows — BOH3 fully v3. Ungraded ≈ forms not yet submitted by assessor (entrustment is assessor-graded). Optional TODO: surface an "Ungraded: N" line instead of silently dropping.

---

## 4. New / changed symbols index (line numbers as of 2026-07-31, will drift)

| Symbol | Line | Purpose |
|---|---|---|
| `getClinicCodeStandardizationSql` | 157 | EC-code → clinic name UPDATE (both cols) |
| `smartTitleCaseClinic` | 193 | Title-case clinic name, keep acronyms |
| `getTopItemCodes` | 662 | top codes, now SUM(quantity) |
| `getItemCodeDescriptionMap` | 686 | `{code:description}` from context_schema_snapshot |
| `getItemCodesPerStudentBatch` | 727 | per-student totals; Description via map |
| `getCafFinalEvalScoreStudent` | 756 | CAF score, v3 object-aware |
| `getEntrustmentSummary` | 847 | entrustment counts, gated to S1–S4 |
| `getRotationRange` | 1076 | rotation min/max, ≥20-form gate on max |
| `buildBannerSubtitle` | 1112 | banner subtitle string |
| `buildCohortSummaryPdf` | 1123 | cohort PDF (uses subtitle) |
| `CLINIC_DICT` | 40 | EC01–EC17 → names |

---

## 5. Architectural decisions this session
1. **Clinic remap both `external_clinic` and `clinic`**, each via its own `CASE` (no cross-column mismatch). Runs BEFORE free-text standardization so typed variants converge on canonical names.
2. **Title-case preserves acronyms** and runs LAST, so curated `CLINIC_DICT` names (already correct casing) pass through unharmed.
3. **Descriptions from `context_schema_snapshot`** (not the data rows, not the mapping xlsx) — it's the only complete source in v3.
4. **CAF score reads `value->>'value'` with `#>>'{}'` fallback** — one code path handles both v3 objects and any legacy strings.
5. **Scalar guard via `jsonb_typeof='array'`** everywhere patients/item_codes are expanded — defends against JSON `null`/scalar rows.
6. **Rotation range gates the MAX at ≥20 forms** (min left as true earliest, per instruction) — "genuine" range, no one-off inflation.
7. **Entrustment restricted to S1–S4** at the SQL level; ungraded simply excluded.

---

## 6. Verify / how to run
- Cohort summary (works): `main.ipynb` cell 70 → `buildCohortSummaryPdf(cohort="BOH3", …)`. **DDS4 call is currently commented out — uncomment and run it too.**
- Table rebuild: cell 63 `processDds4BohForms()` (builds `dds4_boh3_forms_v3`, maps clinic codes, title-cases).
- Handy diagnostics (run in a notebook cell against live `engine`):
  ```python
  # entrustment value distribution
  readDf(engine, """SELECT assessor_data->'scales'->'scale-entrustment'->>'key' k,
                    COUNT(*) n FROM dds4_boh3_forms_v3 WHERE cohort=:c GROUP BY 1 ORDER BY n DESC""",
         {"c":"DDS4"})
  ```

---

## 7. REMAINING WORK (next chat) — prioritized

### 7.1 Student-level report functions — HIGH (this is the next cell)
These power the per-student PDFs (`getStudent*`, `getAssessorRollup`, big rollup SQL ~L1900–2160). Scales + patient keys are already fixed (global passes), but two v3 issues remain:

**(a) CAF checklist object shape — same bug as §3.4, still present at:**
- **L1384** and **L1506** — `jsonb_each_text(COALESCE(b.caf,'{}'::jsonb)) kv` + `CASE kv.value WHEN 'Done well' …`. In v3 `b.caf` values are objects → no match → NULL scores.
- Fix pattern: `jsonb_each(...)` + `CASE COALESCE(kv.value->>'value', kv.value#>>'{}')`. Note L1384's function also exposes `kv.value AS ratingText` — change that to `COALESCE(kv.value->>'value', kv.value#>>'{}')` too, else it shows the raw JSON blob.

**(b) multi-select "Other" filter reads `->>'name'` (v2 key) — at L2003 and L2117:**
- `WHERE COALESCE(e->>'name','') <> 'Other'`. In v3 items are keyed by `key`, so `e->>'name'` is NULL and the "Other" exclusion no-ops. Change to `e->>'key'` (confirm how v3 encodes the free-text "Other" entry first — check a real row's `multi-select.strengths`/`weakness-*`).
- Value labels elsewhere use `e->>'value'` / `x->>'value'` which is **unchanged** between v2/v3 (safe).

**(c) General:** spot-run each `getStudent*` for the sample students in `main.ipynb` and eyeball the per-student PDF, since these weren't executed this session.

### 7.2 Rotation column persistence — LOW
The v3 **upsert** (`getBoh3Dds4FormsV3ProcessSql`, L433) still stores `form_context.placement.rotation` **raw** (`R6`). User currently maps it to `Rotation 6` outside the upsert; if `processDds4BohForms` is re-run with `replace=True`, the column reverts to `R6`. Banner is robust either way (regex). If persistence is wanted, add a rotation code→label step in cell 63 mirroring `getClinicCodeStandardizationSql` (source: `context_schema_snapshot` → `placement.rotation.options`). **User said they already handle this — confirm before adding.**

### 7.3 Other-cohorts reports (§7.2 of predecessor doc) — HIGH, separate effort
`boh2_dds2_dds3_utils.py` + `general_utils.py` for `rawform_forms_v3` (BOH1/2, DDS1/2/3). Entirely pending. See predecessor handover §7.2 for the detailed plan (scales path, flattened checklists, patient_data derivation, `getChecklistBank` config repoint, 16 formsTable defaults).

### 7.4 Testing gaps
- Only **BOH3** cohort summary was run live this session; **DDS4 not run**. Uncomment and run it.
- Nothing validated against DDS4 student PDFs.

---

## 8. Gotchas / reusable patterns
- **`grep` for `->>` needs `-F --`** in bash (the leading `-` and `>` trip it up).
- **Array expansion must be guarded** — always `CASE WHEN jsonb_typeof(x)='array' THEN x ELSE '[]'::jsonb END`, never bare `COALESCE(x,'[]')`.
- **`jsonb_each` vs `jsonb_each_text`** — use `jsonb_each` when values are objects (`{key,value}`), then `->>'value'`; `_text` stringifies objects and breaks label matching.
- **scales:** level is under `->>'key'` (`"S3"`), config labels under `->'fields'->'S3'`.
- **item descriptions:** only in `context_schema_snapshot` in v3 (use `getItemCodeDescriptionMap`).
- Backups from this session (sandbox tmp, ephemeral): `/tmp/boh3_dds4_utils.*.bak.py`.
