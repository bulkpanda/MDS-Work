# Handover — OSCE station-wise reports + BLR / AMEE analysis

**Date:** 2026-09-09
**Cohort:** DDS2 (2026 OSCE); code is cohort-generic and auto-adapts to new checklists/levels
**New code files:** `osce_utils.py`, `osce_metrics.py`
**Touched:** `main.ipynb` (one new cell, ~idx 34), reads `studentEmailList.csv` (roster)
**Reference used:** AMEE Guide No. 49 — Pell, Fuller, Homer & Roberts, *Medical Teacher* 2010; 32:802-811 (“How to measure the quality of the OSCE”)

---

## 1. What this delivers

From a single DASH OSCE JSON dump (`temp 2026 osce.json`), one function builds **two Excel workbooks**:

- **Station workbook** — `OSCE/DDS2/DDS2 OSCE.xlsx` — the per-station results people read.
- **Analysis workbook** — `OSCE/DDS2/DDS2 BLR/DDS2 BLR & Validity.xlsx` — standard-setting (BLR), reliability/validity (AMEE Guide 49), assessor harshness, and cross-tab views.
- **Figures** — 4-panel BLR PNGs + assessor-harshness bar PNGs saved to `OSCE/DDS2/DDS2 BLR/` and embedded in the analysis workbook.

Everything is produced by `osce_utils.buildOsceWorkbook(...)`; the rigorous AMEE sheets live in `osce_metrics.py` and are called from inside it.

---

## 2. How to run

`main.ipynb` cell (~idx 34, after the OSCE PDF/email cells):

```python
import importlib, osce_utils
importlib.reload(osce_utils)                 # picks up edits to osce_utils.py (which reloads osce_metrics)

osceSummary = osce_utils.buildOsceWorkbook(
    srcPath="temp 2026 osce.json",
    stationPath="OSCE/DDS2/DDS2 OSCE.xlsx",
    analysisPath="OSCE/DDS2/DDS2 BLR/DDS2 BLR & Validity.xlsx",
    imgDir="OSCE/DDS2/DDS2 BLR",
    cohortLabel="DDS2",
    borderlineGr=2,
    ignoreStudentNumbers={"1357773"},        # or None -> osce_utils.IGNORE_STUDENT_NUMBERS
)
```

`scipy` must be installed (used for `linregress`, `f_oneway`, `pearsonr`, `spearmanr`) — `pip install scipy` if missing.

### API

```python
buildOsceWorkbook(srcPath, stationPath, analysisPath, imgDir,
                  cohortLabel="", borderlineGr=2,
                  ignoreStudentNumbers=None, rosterPath="studentEmailList.csv") -> dict
```

Returns:
```python
{
 "stations": [{"station","checklist","sheet","levels","n","blrCut"}, ...],
 "stationWorkbook": <path>, "analysisWorkbook": <path>, "imgDir": <path>,
 "ignored": ["1357773", ...],
}
```

---

## 3. Input data shape (DASH OSCE v3 JSON)

The source is a plain `list` of assessment records. One record:

```jsonc
{
  "id": 123, "circuit": 3, "station": 4,
  "assessor": "Fammy Liem", "student": "Henry Chen",
  "submitted": true, "visible": false,
  "form_config": {
    "scales":   { "global-rating": { "name": "Global Rating",
                    "fields": { "1":"Excellent","2":"Very good","3":"Pass","4":"Borderline","5":"Fail" } } },
    "checklists": { "<ck-key>": { "name":"Occlusal Assessment...", "order":1,
                    "fields": { "MC1":"...", ... "MC10":"..." },
                    "extra_config": { "rubric": { "MC1": {"O1":"...","O2":"...","O3":"...","label":"..."} } } } }
  },
  "form_data": {
    "scales":     { "global-rating": { "key":"4", "value":"Borderline" } },
    "checklists": { "<ck-key>": { "MC1": {"key":"O1","value":"Very good"}, ... "MC10": {...} } },
    "texts": {
       "feedback-on-student-performance": "...",
       "comments-on-the-osce": "...",
       "if-you-have-awarded-a-global-rating-of-borderline-or-fail-please-provide-additional-information": "..."
    }
  }
}
```

**Two things that bit us (architectural constraints):**

1. **Score by the response LABEL, never the O-key.** `key` (`O1..O4`) is *inconsistent across checklists* — e.g. `O3` = "Borderline" in infection-control but "Unsatisfactory" in occlusal; occlusal items sometimes only have `O1/O3`. Only `value` (the label) is reliable.
2. **A station number carries MULTIPLE checklists.** In the current DDS2 pull there are **13** station-checklist combinations across 5 stations (most stations have 3 checklists), each with 105 students. Always key by **(station, checklist)**, never station alone. `buildStationSpecs` groups by the checklist actually filled in `form_data`.

---

## 4. Scoring model (integer points, per-checklist level)

Scale is chosen per checklist by `checklistScale(cfg, usedLabels)` — 4-level if the rubric defines 4 distinct O-keys OR the label "Borderline" was used, else 3-level:

| Level | Very good | Satisfactory | Borderline | Unsatisfactory | Max/item |
|---|---|---|---|---|---|
| 4-level | **4** | **3** | **2** | **0** | 4 |
| 3-level | **2** | **1** | — | **0** | 2 |

- In the current data **only Occlusal Assessment is 3-level**; all other checklists are 4-level.
- `Score (%) = total points / (n_items × max_per_item) × 100`.
- MC cells in the detail sheets show the **integer points**, coloured **by label** (green = Very good, blue = Satisfactory, amber = Borderline, red = Unsatisfactory) — colour is by label because the integer `2` is ambiguous (Borderline in 4-level, Very good in 3-level).

**Global Rating reversed to the standard direction.** Data key is `1=Excellent..5=Fail`; the workbooks store `num = 6 - key` so **5=Excellent .. 1=Fail** (higher = better). Consequently the BLR regression slope is **positive** and the cut is taken at `GR = Borderline = 2`.

**Rounding rule (important):** cutoffs and scores are rounded to **1 dp** and pass/fail is decided on the rounded values. Helpers: `pct1(x)=round(x*100,1)`, `countBelow(scs, cutFrac)` counts `pct1(score) < round(cutFrac*100,1)`. A student **fails** a station when `pct1(score) < cutPct`.

---

## 5. Standard setting

- **BLR (Borderline Regression)** — `computeBlr(rows, borderlineGr=2)`: `linregress(score ~ GR)`; `cut = slope*2 + intercept`. Returns `cut`, `cutPct` (1 dp), `mean`, `sd`, `mean2sd`, `mean2sdPct`, `r2`, `p`, and the aligned `grs`/`scs` arrays.
- **Mean − 2SD** — a low-outlier candidate cut (`mean − 2·SD` of the checklist score).
- **BGM** (Borderline Group Method) = mean score of students graded exactly Borderline.
- **Cohen** = 0.6 × 95th-percentile score.
- **Fixed** 50 / 60.

The **Standard Setting** sheet shows the cut per method, then a second table of **number of students failing (< cut)** under each method (counts, not pass %).

---

## 6. AMEE Guide 49 metrics (`osce_metrics.py`)

- **Overall test Cronbach α** — each station's `Score%` treated as an item across the 105 complete cases (`studentStationMatrix` + `testAlpha`).
- **α if station deleted** — leave-one-station-out; if it *exceeds* the overall α, that station detracts from reliability.
- **R²** — `Pearson(score, GR)²` (= BLR R²); > 0.5 = reasonable grade/checklist relationship.
- **Inter-grade discrimination** — regression slope in **raw checklist marks per grade** (`interGradeDiscrimination`); guideline ≈ max-mark/10.
- **Number of failures** — reality check (`countBelow`).
- **Between-group variation %** — one-way ANOVA **η²** of `Score%` by group (`betweenGroupVariation(spec,'circuit'|'assessor')`): < 30% good, 30–40% watch, > 40% concern. Each circuit = one assessor here, so circuit var ≈ assessor var; the assessor ANOVA (F, p, η²) drives the hawks-&-doves verdict (`betweenGroupVerdict`).

---

## 7. Sheet inventory

### Station workbook (`DDS2 OSCE.xlsx`)
| Sheet | Contents |
|---|---|
| Read Me | Scope, scoring key, GR direction |
| Station Summary | Per station: N, mean/SD/median %, GR mean, **grade counts (Excellent…Fail)**, Pass+ %, **Fails (BLR)**, BLR Cut % |
| S# detail (×13, abbreviated names e.g. `S1 IC`) | One row per assessment: Circuit, Student, Assessor, MC1–10 (coloured points), Score (%), GR (number only), Feedback, **Borderline/Fail Info** (last). Sorted by Score **descending** |
| MC Item Stats | Per item: label counts, avg points, avg % |
| Checklist Legend | Sheet↔checklist map + MC descriptions + level |
| Assessors | 50 unique assessors, # stations, assessments (n), stations covered |

Detail sheet abbreviations (`CHECKLIST_ABBR`): S1 IC / S1 Rad / S1 CommStaff · S2 Comm / S2 LA / S2 RiskRecall · S4 MedHx / S4 Occl / S4 Referral · S5 ConsDent / S5 Consent / S5 MedEmerg · S6 Perio.

### Analysis workbook (`DDS2 BLR & Validity.xlsx`)
| Sheet | Contents |
|---|---|
| Read Me | Method notes |
| Student x Station | Score% matrix; **3-colour fail coding** — red = below BLR cut, orange = below Mean−2SD, purple = below both, grey = not attempted — with a **legend top-right**; +Mean %, +Fails (BLR), +< M-2SD columns; per-station fails totals row |
| BLR Analysis | One panel per station, separated by a **full-width navy banner**: metrics grid (BLR cut, Mean−2SD, α, slope/intercept, R², p, Students < cut), per-GR group table, "Students below BLR cut" list, and the embedded 4-panel figure |
| Station Metrics (AMEE) | Overall test α header; per station: BLR cut %, Mean-2SD %, R², discrimination, failures, circuit var %, assessor var %, α-if-deleted, item α, mean item-total r, **grade counts (Excellent…Fail)**, flags; **column-averages row** at the bottom |
| BLR Cut per Circuit | Station × circuit matrix of within-circuit BLR cuts + "All" column |
| Assessor Analysis (AMEE) | Per station: ANOVA F/p/η² + hawks-&-doves verdict, per-assessor stringency table (Δ% / ΔGR vs station, BLR residual, flag), embedded harshness bar |
| Standard Setting | Cut by BLR / Mean-2SD / BGM / Cohen / fixed 50 & 60, then **counts failing** under each |
| Assessor Grid | Student × station filled with **assessor names**, cell fill = **red→green gradient by the assessor's mean %** at that station (global scale; legend top-right) |

---

## 8. Key functions

`osce_utils.py` (865 lines): `loadOsceRecords`, `loadRoster`/`resolveIgnoreNames`, `checklistScale`, `buildStationSpecs`, `computeBlr`, `pct1`/`countBelow`/`gradientHex`, `cronbachAlpha`, `itemTotalCorrs`, `buildBlrFigure`, `computeAssessorHarshness`, `buildHarshnessFigure`, `stationTitle`, `buildOsceWorkbook`.

`osce_metrics.py` (285 lines): `studentStationMatrix`, `testAlpha`, `interGradeDiscrimination`, `betweenGroupVariation`, `betweenGroupVerdict`, `buildStationMetricsSheet`, `buildCircuitCutSheet`, `buildAssessorAnalysisSheet`. It `import osce_utils as ou`; `buildOsceWorkbook` imports `osce_metrics` lazily to avoid a circular import.

---

## 9. Ignore list

`IGNORE_STUDENT_NUMBERS = {"1357773"}` (= Nethmini Nanayakkara, DDS2). OSCE records are **name-keyed** (no student_number field), so numbers are resolved to names via `studentEmailList.csv` (`student_number,student_name`) in `resolveIgnoreNames`, then excluded alongside test/dummy/model placeholders. Her 2 records (Occlusal, Conservative) were removed. Add more numbers to the set as needed.

---

## 10. Traps & decisions (read before editing)

- **O-key inconsistency** → always score by label (§3).
- **Two+ checklists per station** → key by (station, checklist); sheets are abbreviated to fit the 31-char sheet-name limit.
- **Single-grade circuit → null per-circuit cut.** In *BLR Cut per Circuit*, a `-` means that circuit's assessor gave **one global grade to all ~18 students**, so the regression has no x-variation and no cut is computable (e.g. S5 Consent / Circuit 1 — Asmono Truong gave GR 4 to all 18). Guarded by `len(distinct GR) >= 2`.
- **Compensatory check:** no student's *average* station score (min 69.6%) falls below the *average* BLR cut (66.4%). Students only fail per-station.
- **File locks.** The output `.xlsx` is often open in Excel (`~$…` lock). The notebook/run pattern: on `PermissionError`, write to a `…(refreshed).xlsx` sibling and copy over once closed. `device_bash` cannot delete on the mounted drive — move stale copies into `_to_delete/`.
- **Colour choices:** MC cells colour **by label**, not integer, because `2` is ambiguous across levels. Assessor Grid uses a global red→yellow→green scale of assessor mean % (`gradientHex`).

---

## 11. Open items / next steps

- **Assessor Grid gradient is global** (absolute mean %), so a red cell can reflect a *hard station* as much as a *harsh assessor*. Option offered but not built: a **per-station** normalised gradient to isolate the assessor effect.
- **`-` in BLR Cut per Circuit**: could add a footnote / "single-grade" flag (offered, not yet added).
- No student-ability-adjusted harshness (mixed model / residual-after-cohort) — current harshness assumes ~random allocation of students to assessors within a station (true here: one assessor per station-circuit).
- Round 1 only (all 13 combos are treated as round 1 since all are fully submitted). If a later pull carries a round marker, add a filter in `loadOsceRecords`.
