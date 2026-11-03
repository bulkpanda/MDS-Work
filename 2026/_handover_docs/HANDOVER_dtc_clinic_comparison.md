# Handover — DTC vs placement-site clinical-exposure comparison + PDF item-code totals (DDS4/BOH3)

**Date:** 2026-10-15 (revised 2026-10-16 — scope narrowed to clinical exposure only)
**Cohorts:** DDS4, BOH3 (final-year external placements)
**Main code files:** `boh3_dds4_utils.py` (new section 11 + edits to `plotItemCodeFrequencies`/`buildFrontPage`/`buildCohortSummaryPdf`), `main.ipynb` (one new call cell)
**Request:** Compare the average student **clinical exposure** at DTC against the other placement sites — avg patients, avg total item codes, avg unique item codes **per student**. Plus, in the DDS4/BOH3 cohort summary PDF, show the overall **total** on the item-code bar charts and drop the extra sections after the patient-count table.

---

## 1. Clinical-exposure workbook — `BOH3_DDS4/Clinical Exposure <cohort> <today>.xlsx`

**One sheet, "Clinical Exposure"** (deliberately minimal — earlier multi-sheet/rotation version was dropped as too much):
- **DTC vs other sites (per student)** table — Metric · DTC · Other sites (avg) · Difference · % vs others, for: avg patients/student, avg total item codes/student, avg unique item codes/student.
- **All sites (per student)** table — Site · Students · Avg Patients/Student · Avg Total Codes/Student · Avg Unique Codes/Student (sorted by patients desc).
- **Three bar charts** across sites with DTC and MDC bars recoloured orange: avg patients, avg total codes, avg unique codes per student.

### Functions (section 11, `boh3_dds4_utils.py`, all public)
| Function | Returns | Purpose |
|---|---|---|
| `getClinicStudentExposure(engine, cohort, formsTable="dds4_boh3_forms_v3", attended=True, filters=None)` | `external_clinic, student_name, patients, total_codes, unique_codes` | One row per (clinic, student); metrics aggregated across the student's whole time at that site. **Unique = distinct codes at site level** (computed in SQL, NOT a sum of per-rotation varieties). |
| `summariseClinicExposure(exposureDf, minStudents=1)` | per-site DF | Mean of each metric across students; `Site, Students, Avg Patients/Student, Avg Total Codes/Student, Avg Unique Codes/Student`. |
| `dtcVsOthersExposure(exposureDf, dtcName="DTC")` | DF | DTC vs pooled-others, 3 metrics, abs + % difference. |
| `buildClinicComparisonWorkbook(engine, cohort, outPath, *, dtcName="DTC", attended=True, minStudents=1, today=None)` | outPath | The one-sheet workbook. |
| `_xlClinicBar`, `_xlHighlightPoints` | — | Private chart helpers (single-series column chart, DTC/MDC recoloured). |

**SQL shape** (`getClinicStudentExposure`): unnest `patient_data` WITH filter `patient_attended=:attended` → `pat`; unnest `pat.patient->item_codes` → `codes(code, qty=COALESCE(quantity,1))`; `codeAgg = SUM(qty) total_codes, COUNT(DISTINCT code) unique_codes GROUP BY clinic,student`; `patAgg = COUNT(*) patients GROUP BY clinic,student`; `patAgg LEFT JOIN codeAgg`.

**`main.ipynb`** — one call cell after `createPatientStatsPerClinicPerRotation`, looping `targetCohorts`.

---

## 2. Cohort summary PDF changes (`buildCohortSummaryPdf`)
- **Item-code totals on the bar charts.** New `getItemCodeTotal(engine, cohort, filters=None)` = grand total of item-code quantity for a filter (same WHERE/age logic as `getTopItemCodes`). `plotItemCodeFrequencies` gained a `total=None` arg → title becomes `Top Item Codes (Total: N)`. Front-page chart (`buildFrontPage`) passes the cohort/clinic total; each **by-age** panel title now reads `Age 0-6 (Total: N)` etc.
- **Removed the extra sections after the patient-count table.** The `addGenericCharts` kwarg + block and the `addCohortGenericCharts` function (total-by-section / per-student histograms, added 2026-10-15) were removed; the PDF again ends at the patient-count table.

---

## 3. Decisions / data
- **Per student** (not per rotation) — user narrowed scope 2026-10-16. Each student's totals aggregated across their whole time at a site.
- **Unique codes** must be distinct at site level → computed with `COUNT(DISTINCT code)` in SQL; cannot be derived by summing rotation-level varieties.
- Attended patients counted directly (`patient_attended`); final-year forms have no Operator field, so the Config.xlsx Operator-as-patient rule is N/A.
- `external_clinic` holds readable site names (DTC/MDC/community sites); new sites handled automatically.
- **Rotation 8 excluded by default** (incomplete) via `excludeRotations=(8,)` on `getClinicStudentExposure`/`buildClinicComparisonWorkbook` — filtered by rotation NUMBER (robust to label/trailing-space variants); NULL-rotation forms kept. Sheet shows an "Excludes: Rotation 8 (incomplete)" note.
- Old per-clinic functions (`createPatientStatsPerClinic*`, `clinic_metrics_<cohort>.xlsx`) untouched.

## 4. Verification
- `py_compile` OK after every edit.
- Offline (live Postgres is localhost, unreachable from the VM): `summariseClinicExposure`, `dtcVsOthersExposure`, `buildClinicComparisonWorkbook` run clean on synthetic + JSON-derived data; workbook loads back with 1 sheet + 3 charts; empty inputs return correctly-shaped empties. PDF chart/total edits `py_compile` clean.
- **Not yet run on the live DB** — first run should sanity-check per-student numbers.

## 5. How to run
1. Refresh the `dds4_boh3` v3 table as usual.
2. Run the DDS4/BOH3 section (`targetCohorts = ["DDS4","BOH3"]`).
3. Re-run `buildCohortSummaryPdf` → item-code bars now show totals; no sections after the patient table.
4. Run the `buildClinicComparisonWorkbook` cell → `BOH3_DDS4/Clinical Exposure DDS4 <today>.xlsx` + `... BOH3 ...`.

## 6. Gotchas / open
- `targetCohorts`/`today` must be defined (they are).
- `(unknown)` site bucket = forms with a missing `external_clinic`.
- Not yet validated on the live DB (patient/code numbers).
