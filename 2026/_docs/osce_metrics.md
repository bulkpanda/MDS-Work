# `osce_metrics.py`

> Rigorous OSCE quality metrics per **AMEE Guide No. 49** (Pell et al., *Medical Teacher* 2010; 32:802-811). Adds three sheets to the analysis workbook built by `osce_utils.buildOsceWorkbook`.

| | |
|---|---|
| **Lines** | 285 |
| **Deps** | numpy, scipy (`stats`), openpyxl; `import osce_utils as ou` |
| **Imported by** | `osce_utils.buildOsceWorkbook` (lazy import, to avoid a circular import) |
| **Handover** | `_handover_docs/HANDOVER_osce_stationwise_blr_analysis.md` |

---

## 1. Purpose

Turns the per-station BLR output into the AMEE Guide 49 "Table 2" family of quality metrics and an assessor hawks-&-doves analysis. Consumes the same `specs` / `blr` objects `osce_utils` already computed.

---

## 2. Computation functions

| Function | Returns / meaning |
|---|---|
| `studentStationMatrix(specs)` | `(colKeys, students, M)` where `M[student][ck] = Score%`. |
| `testAlpha(colKeys, students, M, dropCk=None)` | Cronbach α treating each **station as an item** (complete cases). `dropCk` gives **α-if-station-deleted** (leave-one-out). |
| `interGradeDiscrimination(spec)` | Regression slope of checklist marks on GR; `{slope, maxMark, guideline=maxMark/10, ratio}`. **2026-09-09:** for a uniform checklist keeps raw-mark scale (`maxMark = 10×per-item max`, unchanged); for a **mixed-level** checklist uses the normalised % scale (`maxMark = 100`) since there is no single per-item max. Guards against <2 grades. |
| `betweenGroupVariation(spec, groupField)` | One-way ANOVA of `Score%` by `'circuit'` or `'assessor'`: `{eta2 (%), F, p, k}`. Each circuit = one assessor here, so circuit var ≈ assessor var. |
| `betweenGroupVerdict(eta2, p)` | "Hawks & doves (concern)" if η²>40 or (p<.05 & η²>30); "Watch" >30; else "Consistent". |

Thresholds (from the guide): R² > 0.5 acceptable; discrimination ≈ maxMark/10; between-group η² < 30% good, 30–40% watch, > 40% concern.

---

## 3. Sheet builders

| Function | Sheet |
|---|---|
| `buildStationMetricsSheet(awb, specs, blr)` | **Station Metrics (AMEE)** — header shows overall test α; per station: BLR cut %, Mean-2SD %, R², inter-grade discrimination, max mark, failures, circuit var % (η²), assessor var % (η²), α-if-deleted, item α, mean item-total r, **grade counts (Excellent…Fail)**, flags; concern cells shaded; **column-averages row** at the bottom. |
| `buildCircuitCutSheet(awb, specs, blr, borderlineGr=2)` | **BLR Cut per Circuit** — station × circuit matrix of within-circuit BLR cuts + "All". `-` when a circuit's assessor used a single GR (no regression possible). |
| `buildAssessorAnalysisSheet(awb, specs, blr, imgDir)` | **Assessor Analysis (AMEE)** — per station: ANOVA F/p/η² + hawks-&-doves verdict, per-assessor stringency table (Δ% / ΔGR vs station, BLR residual, flag), embedded harshness bar. |

`_styles()` returns the shared openpyxl fonts/fills/borders so the three builders match `osce_utils`'s look.

---

## 4. Gotchas

- Imports `osce_utils` at module top; `osce_utils` imports **this** module lazily inside `buildOsceWorkbook` — do not add a top-level import the other way (circular).
- `testAlpha` uses complete cases only (105 students did all 13 stations); overall test α is low (~0.46) because OSCE stations measure distinct constructs — expected, not a bug.
- Uses `ou.countBelow` / `ou.GR_LABELS` / `ou.stationTitle` / `ou.computeBlr` — keep those stable.
- **2026-09-09:** `cronbachAlpha` / `itemTotalCorrs` now take a second arg `sp["items"]` (dynamic item list) and run on normalised fractions — the calls in `buildStationMetricsSheet` were updated to match. See `_handover_docs/HANDOVER_osce_dds4_dynamic_item_scoring.md`.
