# Handover — BOH2 Item-Code Year Summary (PDF) + `context_checklists` ingest

**Date:** 2026-10-08
**Cohorts:** BOH2 (the new util is cohort-generic; ingest change covers all non-final cohorts BOH1/BOH2/DDS1/DDS2/DDS3)
**Main code files:** `boh2_dds2_dds3_utils.py` (new report + counts), `general_utils.py` (ingest: new `context_checklists` column), `main.ipynb` (new call cell), `general_utils.EXCLUDED_STUDENT_NUMBERS` (ingest-time student exclusion, unchanged)

---

## 1. Scope / what was built

A colleague asked for the whole-year BOH2 numbers on a set of clinical item codes (012, 114, 141, 221,
022/024, 521/531) for an end-of-year whole-student brief. There was no dedicated per-code yearly summary
(only the per-student `Item Code Pivot` workbook from `getCohortReports`). Built a new PDF report plus the
supporting cohort-count function, and — after discovering that the real procedure **quantity** was being
dropped at ingest — carried it into the DB and made the count quantity-aware.

**Deliverable:** `BOH2/BOH2 Item Code Year Summary ({today}).pdf`
- Per **form type** (Clinic and Simulation, reported **separately**):
  - *Requested item codes* table — `Item Code · Section · Sub-section · Count · Students` (a requested code
    not seen is listed as "not assessed", 0/0).
  - *Top N item codes for the year* table + a bar chart.
- Embedded PDF metadata (Title/Author/Subject/Creator/Keywords).

---

## 2. New / changed APIs

### `boh2_dds2_dds3_utils.py`

- `getItemCodeCohortCounts(engine, cohort, formsTable="rawform_forms_v3", filters=None) -> DataFrame`
  Columns `Item Code · Count · Students`, sorted by Count desc. Loads forms with `getDataDf` (so the
  assessor-side + Smile-Squad-swap form selection is identical to the rest of the pipeline), explodes
  `getDataDf.item_codes`, reduces each raw label to its real 3-digit code(s) via `_shortItemCode` and splits
  multi-code labels, then **weights each code by quantity** from the form's `context_checklists` where present
  (else 1). Drops `REMOVE_STUDENTS_DICT[cohort]`. Year window from `_where` (`datetimeutc >= 2026-01-01`).

- `_codeQuantityMap(contextChecklists) -> {cleanCode: summedQty}` (helper)
  Parses a form's `context_checklists` list `[{"code","quantity"}, ...]`; cleans codes with `_shortItemCode`
  and splits; sums quantity per resulting 3-digit code. Returns `{}` when the form has no list.

- `plotItemCodeBars(countsDf, uniColor=None, title=..., figWidth=11, figHeight=4.5) -> Figure`
  Navy bar chart of `Count` by `Item Code` (expects a pre-sorted/truncated frame).

- `buildItemCodeYearSummaryPdf(engine, cohort, outPath, requestedCodes, today, formsTable="rawform_forms_v3",
   types=("Clinic","Simulation"), topN=20, mappingFile=None, uniColor=None, subheadingStyle=None,
   requestedBy=None, bannerTitle=None, year="2026", author="Kunal Patel") -> {formType: {"requested","top","all"}}`
  Builds the PDF (headings only, no meta paragraph block), one page/section per form type, tables via
  `Utils.createTable`, bar via `plotItemCodeBars` + `Utils.addPlotImage`. Sections/sub-sections via
  `Utils._mergeSection` on `variableUtils.itemSectionMappingFile`. Writes PDF `/Info` metadata by passing
  title/author/subject/creator/keywords to `SimpleDocTemplate` **and** setting `doc.*` (belt-and-braces).

Defaults: `uniColor=variableUtils.uniColor`, `subheadingStyle=variableUtils.subheadingStyle`,
`mappingFile=variableUtils.itemSectionMappingFile`. All names are public (no leading underscore) because a
`main.ipynb` cell calls them (`from … import *` skips underscored names — see `import-star-underscore-rule`).

### `general_utils.py` (ingest change)

- `rawform_forms_v3` gained a nullable `context_checklists JSONB` column.
  - DDL `CREATE_RAWFORM_FORMS_V3_TABLE_SQL`: an idempotent
    `ALTER TABLE rawform_forms_v3 ADD COLUMN IF NOT EXISTS context_checklists JSONB;` was appended after the
    GIN indexes, so **existing** tables gain the column when `runDdl` runs inside `processForms` (the
    `CREATE TABLE IF NOT EXISTS` alone never alters an existing table).
  - `getInsertSqlRawform_forms_v3`: added `context_checklists` to the INSERT column list, the SELECT
    projection `fc.ctx->'checklists' AS context_checklists`, and the `ON CONFLICT … DO UPDATE SET …
    context_checklists = EXCLUDED.context_checklists`.
  - Additive only — no existing column touched. `context_checklists` is NULL for cohorts/forms that have no
    `form_context.checklists`.

### `main.ipynb`

- New **code cell inserted directly below the `getCohortReports` cell** (the "BOH1 BOH2 DDS2 DDS3 general"
  section). It calls `buildItemCodeYearSummaryPdf(engine, "BOH2", …, requestedCodes=["012","114","141",
  "221","022","024","521","531"], types=("Clinic","Simulation"), topN=20, requestedBy="colleague request …")`
  and has commented BOH1/DDS2 variants. Utils live in `boh2_dds2_dds3_utils.py`; only the call sits in the
  notebook (per the house rule).

---

## 3. Data structures — how BOH2 checklist/item-code storage changed over 2026

Discovered by streaming `temp 2026 caf.json` (the BOH1–DDS3 CAF pull; 4,795 BOH2 records / 6,204 forms).
There are **three distinct places** item codes can live, and the structure shifted mid-year:

1. **`*_data.checklists` (rubric responses).** Always present. An object. Two sub-shapes:
   - early: keyed by **checklist/template name** — e.g. `"DDS2-MAR-31": {"MC1": {"key","value"}, …}`.
   - newer: keyed by **item code or composite procedure label** — e.g.
     `"533": {"MC1": …}`, `"LA": {…}`, `"14MODB (534 577) (restoration)": {…}`.
   This is what the DB flattens onto the top level of `student_data`/`assessor_data`
   (`general_utils._flattenChecklistsSqlExpr`, `(raw || flattened)`), and what `getDataDf.item_codes`
   (= `array_agg(DISTINCT key)` over `assessor_data`, buckets/`scale-*` excluded) reads.

2. **`form_context.checklists` (the procedure list WITH quantity).** **New, added ~June 2026**, partial
   adoption. A list: `[{"code":"533","quantity":1}, {"code":"LA","quantity":1}]`. This is the only place a
   **quantity** exists. Coverage on BOH2: ~1,358/4,796 Clinic forms and ~622/1,408 Sim forms carry it
   (Jan–May: none; Jun onward: growing but never universal). `quantity > 1` in only ~45 entries.

3. **top-level `additional_checklists`** (API field, mapped to the DB `additional_checklists` column) — **not
   present on BOH2 forms** (always null here); do not confuse with (2).

**Example payload (abridged, real BOH2 Clinic form, 2026-10-05, student-submitted):**
```json
{ "type":"Clinic", "cohort":"BOH2",
  "forms":[{
    "form_context": { "role":"O", "clinic_type":"GP",
      "checklists": [ {"code":"533","quantity":1}, {"code":"LA","quantity":1} ] },
    "student_data": { "checklists": { "LA":{"MC1":{"key":"O2"}…}, "533":{"MC1":{"key":"O2"}…} } },
    "assessor_data": {},                       // empty: submitted_by_assessor=false
    "submitted_by_student": true, "submitted_by_assessor": false }]}
```

---

## 4. Counting rules (as implemented)

- **Form inclusion / side:** unchanged from the pipeline. Codes come from `getDataDf.item_codes`
  = the **assessor** side (with the Smile Squad `student_data↔assessor_data` swap already applied by
  `applySmileSquadSwap`). So only assessor-filled forms (and swapped Smile Squad forms) contribute. A
  student-only form with empty `assessor_data` (e.g. the example above) contributes **0** — deliberate,
  confirmed with Kunal.
- **Label cleaning:** every raw label → `_shortItemCode` (pulls each `\b\d{3}\b`, de-duped), then split on
  `,`. So `14MODB (534 577) (restoration)` → `534`,`577`; `26O (531) & 64DO 65MO (532)` → `531`,`532`;
  variants `114` / `114-US` / `114-HS` / `BOH2 S2 114` all fold to `114`; `011-COE` → `011`.
- **Quantity weighting:** for each included code on a form, `Count += context_checklists[code].quantity`
  if the form has a `context_checklists` entry for that code, else `+= 1`. Pre-June forms (no list) are
  therefore identical to a plain occurrence count; only genuine multiples (qty > 1) now count as >1.
- **`Count`** = total quantity performed across the cohort; **`Students`** = distinct students with the code.
- Codes with no 3-digit form (`LA`, tooth numbers like `22`, `BOH-DD`, `reflection`) pass through as their
  own labels (fallback) — they can appear in Top-N; not filtered (open item).

---

## 5. Verification (report vs raw JSON)

Independent recompute from `temp 2026 caf.json` (BOH2), mirroring the report logic (assessor side + SS swap,
`_shortItemCode` split, pre-quantity i.e. occurrence counts), vs the regenerated PDF:

| | Clinic total | Sim total |
|---|---|---|
| PDF (DB) | 5169 | 2799 |
| JSON (Oct-5 snapshot) | 5384 | 2819 |

Several codes matched exactly (521 = 22/17; Sim 221 = 49/49; Sim 531 = 149/149; Clinic 012 count = 93); the
rest within ~2–3%. The PDF is consistently *slightly lower* and the gap concentrates in high-volume codes and
in student counts (PDF caps ~49 students, JSON ~55) → **the DB was last loaded before the Oct-5 pull**, so the
JSON snapshot has a few more recent (late-Sep/Oct) forms. Logic verified; residual is data freshness, closed
by re-running `processForms`.

`form_context`-only quantity sums (where present) for requested codes were much lower than the full counts
(e.g. Clinic 114 = 321 vs 494), confirming `form_context.checklists` alone is **not** a full-year source
(~28% coverage) — hence the hybrid (quantity where present, occurrence fallback otherwise).

---

## 6. How to run

1. **Re-run `main.ipynb` cell 6 `processForms()` with `replaceExisting = True`.** This runs the `ALTER`
   (adds `context_checklists`) and repopulates it for every form. Without this the column is absent/NULL and
   quantity is not used.
2. **Re-run the new cell** (below `getCohortReports`) to write `BOH2/BOH2 Item Code Year Summary (…).pdf`.

Backups of the edited files are in `_bak/` (`general_utils.py.bak_*`, `boh2_dds2_dds3_utils.py.bak_*`,
`main.ipynb.bak_*`).

---

## 7. Gotchas

- **Two-step run.** Quantity does nothing until `processForms(replaceExisting=True)` has repopulated
  `context_checklists`. `getDataDf` returns `f.*`, so it picks the new column up automatically once it exists.
- **Quantity is sparse on BOH2** (~28% of forms; qty>1 in ~45 entries). Most counts are unchanged vs the
  previous occurrence count; the feature mainly matters for other cohorts / future forms.
- **Assessor-only gating retained by choice** — procedures logged only in a student-submitted form's
  `form_context.checklists` (empty `assessor_data`, non-SS) are **not** counted. Revisit if "effective side"
  (student fallback when assessor empty) is ever wanted.
- **Non-ADA labels** (`LA`, tooth numbers, `BOH-DD`, `reflection`) are not real item codes but survive as
  fallback labels; they can clutter Top-N. Filter to `^\d{3}$` if a clean procedures-only brief is wanted.
- **Clinic Flagging total MATCHES this PDF (both 5169).** Verified per student (e.g. 1775573 = 141 in both)
  and in grand total; both sit on the same `getDataDf` (assessor side + Smile Squad swap, `period="ALL"`,
  same `REMOVE_STUDENTS_DICT`). The flagging `Item Code Count Pivot` differs only in PRESENTATION:
  `flagging_utils._itemCodeCounts` counts the raw labels, so variant spellings stay separate columns
  (`114` / `114-US` / `BOH2 S2 114`) and non-ADA labels (`LA`, tooth numbers, `BOH-DD`, `reflection`) show as
  columns; the year-summary folds variants via `_shortItemCode`. Folding preserves the total and clinic
  assessor labels have no multi-code composites to split, so the grand totals coincide. Flagging left
  unchanged (Kunal's scope decision: year-summary only).
  NOTE: an earlier analysis in this session mis-reported the flagging total as 10,338 — that was a parsing
  double-count (per-code columns 5169 + the per-student `Total` column 5169); the real total is 5169.
- **Sandbox can't reach the DB or import the module** (`win32com`, `arial.ttf`, Postgres on the user's
  localhost). Everything was validated by `py_compile`, star-import name resolution, a synthetic
  `getDataDf`→PDF build (metadata + both tables + charts), and the JSON recompute above — **not** a live DB run.

---

## 8. Open items

- Not run against live Postgres / on Windows. Re-run cell 6 then the new cell; confirm the PDF numbers and
  that `context_checklists` is populated (e.g. a `quantity > 1` form reflects in the Count).
- Decide whether to filter Top-N / tables to real 3-digit codes (drop `LA`, tooth numbers, etc.).
- If a true "procedures performed" number is ever wanted regardless of who submitted, add an effective-side
  (student-fallback) option to `getItemCodeCohortCounts`.
- Optional: align the Clinic Flagging `Item Code Count Pivot` to the same clean 3-digit + quantity basis
  (off by default, so existing flag thresholds don't shift).
