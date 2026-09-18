# Handover — `boh2_dds2_dds3_utils.py`: v3 report suitability + time-series rework

**Date:** 2026-08-10
**File:** `boh2_dds2_dds3_utils.py` (BOH1 / BOH2 / DDS2 / DDS3 reports; final-year BOH3/DDS4 live in `boh3_dds4_utils.py`)
**Scope of this session:** (1) reworked the per-student **cohort** time-series page (`buildCohortTimeSeriesPdf`, notebook cell 11), (2) applied the same rework to the per-student **report** time-series page (`_addTimeSeriesPage`, cell 12/13), (3) audited the **entire** per-student report chain for `rawform_forms_v3` suitability and verified against real data.
**Backups on disk (device, `…/MDS Work/2026/`):**
`boh2_dds2_dds3_utils.py.bak_20260810_080552` (pre-time-series), `boh2_dds2_dds3_utils.py.bak_pretimeseries` (session workspace copy), `boh2_dds2_dds3_utils.py.bak_20260804_132525` (pre-v3-migration), `general_utils.py.bak_20260810_160648`.

---

## 1. TL;DR / current state

- The per-student report and the cohort time-series PDF are **v3-suitable**. No schema-shape bugs remain.
- The original "scatter only shows July" symptom was a **role-gate bug** in `calcScore` (detailed in §4.1), now fixed.
- Charts now use **categorical (equidistant) date ticks**, **matched figure widths**, **3-digit item-code labels**, and a **`combined=` layout toggle** (two figures vs one stacked figure).
- The report's data loader (`getDataDf`) and cohort helpers were migrated to v3 on 2026-08-04; every report component is a **consumer of derived columns**, so v3-correctness is centralised in the loader.
- Verified role/scale-key structure against the real raw pull `fetched_rows 2026 caf.xlsx` (19,197 BOH/DDS forms) — see §6.

---

## 2. Architecture: how the report is assembled

### 2.1 Data-flow schematic

```
buildEntireCohortStudentReports(engine, cohort, formsTable="rawform_forms_v3", combined=None)
  │
  ├── getStudentsInCohort(engine, cohort, formsTable)            → student list
  ├── getCohortItemCodeAverages(engine, cohort, formType, …)     → {item_code: avg_count}  (class baseline)
  │       └── getStudentItemCodeDf(…)   [v3 scale paths + bucket exclusion]
  │
  └── for each student:
        studentDataDf = getDataDf(engine, cohort, formsTable, {"student_number": id})   ← THE v3 LOADER
        elements = buildStudentReport(studentDataDf, …, cohort=cohort,
                                      classAvgItemCounts=…, combined=combined)
        doc.build(elements, onFirstPage=getBannerDrawer(…))

buildStudentReport(studentDataDf, …, combined=None)
  │  # datetimeutc → Australia/Melbourne; split Simulation / Clinic
  ├── _computeSummaryMetrics(df, patientInfo, isSimulation)      → Summary table
  ├── createTable(…)                                            (generic reportlab)
  ├── _makeRatingsFigure(simDf, clinicDf, …)                    → entrustment + GR pies
  │       ├── _plotEntrustmentPie(ax, df, title)
  │       └── _plotGlobalRatingPie(ax, df, title)
  │  # filter submitted_by_assessor; scores = calcScore(row)
  ├── explodeScoresToLong(studentDataDf)  → longDf(Item Code, Score, Entrustment, Global Rating, Type)
  ├── _mergeSection(longDf)               (item_section_mapping.xlsx → Section)   [from Utils.py]
  ├── _addItemCodeCountsBarChart(elements, adf, classAvg, type, …)  → procedures-performed bars
  ├── _addSectionPerformance(elements, longDf, typePages, …)        → spider charts + section tables
  ├── _addTimeSeriesPage(elements, typeDf, type, …, combined)       → scatter + rubric (see §5)
  └── _addReflectionsTable(elements, typeDf, type, …)               → reflections table
```

### 2.2 Key architectural decision — "loader derives, components consume"

`getDataDf` performs **all** v3 JSON extraction in SQL and returns a flat DataFrame. Every downstream component reads **already-derived DataFrame columns** (`entrustment`, `global_rating`, `role`, `clinical_incident`, `patient_age`, `item_codes`, `student_reflection`, `assessor_reflection`, `scores`) and never re-parses `assessor_data` — **except**:
- `calcScore(row)` — reads `assessor_data` (item scores) + `row["role"]` (gate).
- `_drawScoresScatter` — reads `assessor_data->'scales'->'scale-patient-complexity'->>'key'` for the complex/non-complex marker colour.

**Consequence:** v3-correctness is centralised. If a column looks wrong, fix it in `getDataDf`'s SQL, not in the plotting/table helpers.

---

## 3. `rawform_forms_v3` schema + the loader (`getDataDf`)

### 3.1 Real columns in `rawform_forms_v3` (from `general_utils.py`, `CREATE_RAWFORM_FORMS_V3_TABLE_SQL`)

```
form_code, assessmentid, student_number, student_name, student_email,
datetimeutc, cohort, subject, type, completed,
student_data JSONB, assessor_data JSONB,
student_reflection TEXT, assessor_reflection TEXT, clinical_incident TEXT,
patient_complexity TEXT, role TEXT, clinic TEXT,
scales JSONB, checklists JSONB, version INTEGER,
patient_data JSONB, context_schema_snapshot JSONB,
student_config JSONB, assessor_config JSONB,
assessor_name TEXT, assessor_email TEXT,
submitted_by_student BOOLEAN, submitted_by_assessor BOOLEAN,
additional_checklists JSONB, insertedat TIMESTAMPTZ
```

So `role`, `clinical_incident`, `student_reflection`, `assessor_reflection`, `type`, `submitted_by_*` are **top-level columns** — `SELECT f.*` supplies them directly (no derivation needed).

### 3.2 `getDataDf` — the SQL that makes the report v3-correct

```python
def getDataDf(engine, cohort, formsTable="rawform_forms_v3", filters=None):
    whereClause, params = _where(cohort, filters=filters)
    sql = f"""
      SELECT f.*,
      -- v3: scales NESTED under assessor_data->'scales', PREFIXED keys, level under ->>'key'
      NULLIF(f.assessor_data->'scales'->'scale-practice-readiness'->>'key', '')::int AS entrustment,
      NULLIF(f.assessor_data->'scales'->'scale-professionalism'->>'key', '')::int    AS professionalism,
      NULLIF(f.assessor_data->'scales'->'scale-communication'->>'key', '')::int      AS communication,
      NULLIF(f.assessor_data->'scales'->'scale-time-mgmt'->>'key', '')::int          AS time_management,
      f.assessor_data->'scales'->'scale-global-rating'->>'key'                       AS global_rating,
      -- v3: patient fields collapsed into patient_data JSONB
      NULLIF(regexp_replace(f.patient_data->>'age', '[^0-9]', '', 'g'), '')::int AS patient_age,
      f.patient_data->>'details'     AS patient_details,
      f.patient_data->>'drn'         AS patient_drn,
      f.patient_data->>'interpreter' AS patient_interpreter,
      ic.item_codes AS item_codes
        FROM {formsTable} f
        LEFT JOIN LATERAL (
            -- v3: assessor_data top level holds the 5 buckets alongside flattened item-code
            -- entries; exclude buckets + scale-% so only real item codes remain.
            SELECT array_agg(DISTINCT ic.key) AS item_codes
            FROM jsonb_each(COALESCE(f.assessor_data,'{{}}'::jsonb)) ic
            WHERE ic.key NOT LIKE 'scale-%%'
              AND ic.key NOT IN ('radio','texts','scales','checklists','multi-select')
        ) ic ON true
      WHERE {whereClause}
    """
    if filters: params.update(filters)
    return readDf(engine, sql, params)
```

**Scale-path rules (critical, easy to get wrong):**
- Scales are **nested** under `assessor_data->'scales'`, keys are **prefixed** `scale-*`, graded level is under `->>'key'` (NOT `->>'scale'`).
- `entrustment` = `scale-practice-readiness` for these cohorts (there is no bare `entrustment` key in the prefixed template).
- `global_rating` = `scale-global-rating`, kept as text `->>'key'` (integer-castable string "1".."5"); counted **separately** from the level scales.
- Patient-complexity value is text (`"non-complex"`/`"complex"`), not an integer level.

### 3.3 Example v3 `assessor_data` payload (prefixed template — the dominant shape)

```json
{
  "radio":  { "clinical-incident-occurred": "no" },
  "texts":  { "reflection": "Good handling of the extraction..." },
  "scales": {
    "scale-practice-readiness": { "key": "3" },
    "scale-global-rating":      { "key": "4" },
    "scale-communication":      { "key": "2" },
    "scale-professionalism":    { "key": "2" },
    "scale-time-mgmt":          { "key": "3" },
    "scale-patient-complexity": { "key": "non-complex" }
  },
  "checklists": { "36MO (532)": { "MC1": {"key": "O2"} } },
  "multi-select": {},

  "36MO (532)": { "MC1": "O2" },
  "BOH2 S2 531": { "MC1": "O3" }
}
```

Note the **flattened item-code entries** (`"36MO (532)"`, `"BOH2 S2 531"`) at the top level, added by the separation process (`getInsertSqlRawform_forms_v3` → `_flattenChecklistsSqlExpr`). These are what `getDataDf`'s lateral and `calcScore` read; the 5 buckets and `scale-*` keys are excluded.

---

## 4. `calcScore` — scoring + the role-gate fix

### 4.1 The bug (root cause of "scatter only shows July")

Old gate: `if role not in (None, "Operator"): return {}`. DASH stores `role` as `"O"` (operator), `"OB"`/`"SO"` (observer / second operator), or `None` — **never** the string `"Operator"`. So the gate silently dropped **every** `role="O"` form (most of Feb–June). `role` happened to be null on many July forms, so only July survived → the scatter looked empty until July.

### 4.2 Current code

```python
def calcScore(row, scoreMap=None):
    if scoreMap is None:
        scoreMap = SCORE_MAP
    assessorData = row["assessor_data"]
    # Score the operator's own forms only; exclude observer ("OB") / second-operator ("SO").
    # role ∈ {"O", "OB", "SO", None, ""}. Operator side = O / None / "".
    if assessorData is None or (row.get("role") in ("OB", "SO")):
        return {}
    scores = {}
    for itemCode, itemData in assessorData.items():
        if "scale" in itemCode:
            continue
        if itemCode in ("radio", "texts", "scales", "checklists", "multi-select"):
            continue                       # v3 buckets
        if not isinstance(itemData, dict):
            continue
        itemScore, validLength = 0, 0
        for k, v in itemData.items():
            if v in scoreMap:
                if pd.isna(scoreMap[v]):   # O6 = "Not observed" → NaN → skip
                    continue
                itemScore += scoreMap[v]
                validLength += 1
        scores[itemCode] = {"score": round(itemScore / validLength, 2) if validLength else np.nan}
    return scores
```

`SCORE_MAP = {"O1":1.0,"O2":0.8,"O3":0.6,"O4":0.4,"O5":0.0,"O6":NaN,"Yes":1.0,"No":0.0}` — `O6` ("Not observed") maps to `NaN` and is dropped from averages and from the scatter.

---

## 5. Time-series charts (cohort **and** student report)

Two builders share the same helpers: `buildCohortTimeSeriesPdf` (cell 11, 5 rubric panels) and `_addTimeSeriesPage` (per-student report, 2 rubric panels: Entrustment + Global Rating).

### 5.1 Categorical (equidistant) x-axis — decision + mechanism

Dates are treated as **strings** so ticks are **equidistant** (a 3-month gap becomes an adjacent column, not empty space). A shared ordered category list is built once per student and passed to both the scatter and every rubric panel so their columns line up:

```python
xCategories = sorted(df["datetimeutc"].dt.strftime("%Y-%m-%d").unique())
```

Each series maps its date-string → integer index; axes use `set_xticks(range(n))`, `set_xticklabels(xCategories, rotation=45)`, `set_xlim(-0.5, n-0.5)`.

Signatures:
```python
_drawScoresScatter(ax, df, dateCol="Date", scoreDictCol="scores", scoreKey="score",
                   fallbackKey=None, xCategories=None, showXTickLabels=True) -> bool
plotStudentScoresTimeSeries(df, …, xCategories=None, marginFractions=None) -> Figure|None   # wrapper, standalone fig
rubricPlot(ax, studentDf, label, color, xLabelRotation=45, maxY=None, xCategories=None)
```

### 5.2 Layout toggle `combined=` — decision + mechanism

Module default constant (near `SCORE_MAP`):
```python
COMBINE_TIMESERIES_PANELS = False   # flip globally, or override per call with combined=
```
Threaded through `buildCohortTimeSeriesPdf(…, combined=None)`, `buildStudentReport(…, combined=None)`, `buildEntireCohortStudentReports(…, combined=None)`, and `_addTimeSeriesPage(…, combined=None)` (None → use the constant).

- **`combined=False` (default):** two separate figures with **matched widths** — same figure width (14), identical `subplots_adjust(left=0.09, right=0.985, …)`, same `addPlotImage(fig, 0.9)` scaling → both images render at identical width so ticks align vertically. (Verified: axes x-fraction `0.0900..0.9850` on both; PNG widths equal.)
- **`combined=True`:** one figure, `sharex=True`, taller scatter on top.
  - Cohort: `subplots(6,1, figsize=(16,22), height_ratios=[5,1,1,1,1,1])`.
  - Student: `subplots(3,1, figsize=(16,14), height_ratios=[5,1,1])`.
  (Larger canvas + 5:1 score-panel share was an explicit request.)

Example call from the notebook:
```python
buildEntireCohortStudentReports(engine, "BOH2", combined=True)   # single stacked figure per page
buildCohortTimeSeriesPdf(engine=engine, cohort="BOH2", outPath=…, bannerTitle=…, combined=False)
```

### 5.3 Point labels — 3-digit item codes (`_shortItemCode`)

Crowded labels are reduced to their 3-digit item code(s). Pulls every standalone `\b\d{3}\b` (inside parentheses or not), de-duplicated in order; falls back to the full label when there is no 3-digit code:

| Raw item label | Displayed |
|---|---|
| `36MO (532)` | `532` |
| `14MODB (534 577) (preparation)` | `534, 577` |
| `26O (531) & 64DO 65MO (532)` | `531, 532` |
| `BOH2 S2 531` | `531` |
| `pe-scaling` | `pe-scaling` |

```python
def _shortItemCode(item):
    codes = []
    for c in re.findall(r"\b\d{3}\b", str(item)):
        if c not in codes:
            codes.append(c)
    return ", ".join(codes) if codes else str(item)
```
Smile Squad forms still append `" SS"` to the label.

### 5.4 Other behaviours
- Null / Not-Observed (`O6`→`NaN`) item scores draw **no marker** (the old off-chart `y=-500` "All NA" grey dot + its legend entry were removed).
- Marker colour: red = complex patient (`scale-patient-complexity` key == `"complex"`), else blue. Legend shows only "Complex".

---

## 6. v3 data verification (against real raw pull)

Source: `fetched_rows 2026 caf.xlsx` (raw pre-separation DASH pull; `forms` column = JSON). **19,197** BOH1/BOH2/DDS1/2/3 forms parsed from `form_context.role` + `assessor_data.scales`.

**Scale-key style** (confirms `getDataDf`'s prefixed reads):

| Style | Count | Notes |
|---|---|---|
| prefixed (`scale-*`) | 14,130 | the live template — what `getDataDf` reads ✅ |
| empty | 5,059 | forms with no scales (observers, comment-only, etc.) |
| bare (`entrustment`, `time_mgmt`) | 8 | legacy/old template, different semantics — **intentionally not** given a fallback (negligible; would conflate scale meanings) |

**`role` values:**

| role | count | meaning |
|---|---|---|
| `O` | 9,329 | operator (scored) |
| `''` | 3,796 | operator-side (scored) |
| `None` | 3,026 | operator-side (scored) |
| `SO` | 2,787 | second operator (excluded from scoring) |
| `OB` | 259 | observer (excluded from scoring) |

**OB/SO content** — they carry comments, not ratings:
- SO: scales present in **52 / 2,787** (2,735 none); reflection present in 1,930.
- OB: scales present in **37 / 259** (222 none); reflection present in 59.

**Architectural implication (decision):** because OB/SO forms almost never have scales, their `global_rating`/`entrustment` are null and are **already excluded** from Avg Global Rating, the rating pies, and the rubric lines via `.dropna()`. Therefore **no extra role filter was added** to those metrics (only item-code *scoring* excludes OB/SO, via the `calcScore` gate). This was an explicit decision confirmed with the data owner on 2026-08-10 ("SO forms only fill in comments").

---

## 7. Component-by-component v3 status

| Component | Reads | v3 status |
|---|---|---|
| `getDataDf` | `assessor_data`/`patient_data` JSON → derived cols | ✅ prefixed scale paths, patient_data, bucket-excluded item-code lateral |
| `calcScore` | `assessor_data`, `row["role"]` | ✅ bucket/scale exclusion + OB/SO gate |
| `explodeScoresToLong` | `scores`, `entrustment`, `global_rating`, `type` | ✅ consumer |
| `_computeSummaryMetrics` | `entrustment`, `global_rating`, `clinical_incident`, `role`, `patient_age`, `patient_details` | ✅ consumer (all cols supplied by `getDataDf` / `f.*`) |
| `_makeRatingsFigure` + pies | `entrustment`, `global_rating` | ✅ consumer |
| `_addItemCodeCountsBarChart` | `item_codes` (list) | ✅ consumer |
| `_addSectionPerformance` | `longDf` (Score/GR/ES/Section/Type) | ✅ consumer |
| `_addReflectionsTable` | `item_codes`, `student_reflection`, `assessor_reflection` | ✅ consumer (all real v3 cols) |
| `_addTimeSeriesPage` | `scores`, rubric cols | ✅ reworked this session (§5) |
| `getStudentItemCodeDf`, `getCohortItemCodeAverages`, `getFlaggedFormDetails` | v3 scale paths + bucket exclusion | ✅ migrated 2026-08-04 |
| `_mergeSection` / `_loadSectionMapping` (Utils.py) | item-code label → Section | ⚠️ schema-independent, but keyed on item-code *label*; see §8 |

**Verification performed:** `py_compile` clean; a synthetic v3-shaped record run end-to-end through `calcScore` (O/None/'' scored, OB/SO empty), `explodeScoresToLong`, `_computeSummaryMetrics` (sim + clinic, `patientInfo=True`), and `_makeRatingsFigure` — all ran without error and produced correct values. Time-series alignment verified (identical axis fractions + PNG widths, 5:1 combined ratio). **Not** run against live Postgres — the notebook operator runs cells 11/12.

---

## 8. Open items / watch-outs

1. **Section mapping is label-keyed.** `_mergeSection` (in `Utils.py`) maps item-code *labels* → sections via `item_section_mapping.xlsx`. If v3 item-code labels differ from the mapping's keys, those items fall to `Unmapped` → `Miscellaneous` (no crash, just categorisation). Spot-check the mapping against the live item-code list if section spiders look sparse.
2. **8 legacy bare-key forms** are not scored on scales (different template). Left intentionally unhandled; revisit only if a specific cohort depends on them.
3. **`getInsertSqlRawform_forms_v3` (general_utils.py ~L519)** extracts `scales->'patient_complexity'->>'key'` (bare) which returns NULL in the prefixed template — should be `scale-patient-complexity`. Separate from this file; noted for the insert path.
4. **Dead v2 DDL/insert** (`getInsertSqlRawform_forms` / `CREATE_RAWFORM_FORMS_TABLE_SQL` in general_utils.py) target the v3 table name with v2 columns — unused landmine if ever called.
5. **`combined=` default** is `False` (two matched-width figures). Set `COMBINE_TIMESERIES_PANELS = True` or pass `combined=True` for the single stacked layout.

---

## 9. Files touched this session

- `boh2_dds2_dds3_utils.py` — all changes in §4–§5 + `combined=` passthrough on `buildStudentReport` / `buildEntireCohortStudentReports`. Deployed to `…/MDS Work/2026/`.
- Read-only references pulled: `general_utils.py` (v3 DDL / insert), `fetched_rows 2026 caf.xlsx` (verification), `schema.yaml`.
- Project memory notes updated: `rawforms-v3-scale-keys.md`, `boh2-cohort-timeseries-v3.md`, `boh2-dds2-dds3-cohort-reports-v3.md`.
