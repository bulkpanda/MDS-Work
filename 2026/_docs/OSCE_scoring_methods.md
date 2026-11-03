# OSCE scoring & overall-score methods — reference

One place to look up how an OSCE mark is built. All logic lives in `osce_utils.py`;
this file just documents it. Selected in the `buildOsceWorkbook(...)` call in `main.ipynb`.

---

## 1. Item scoring mode (how each MC item becomes a 0–1 fraction)

Set via `scoreConfig` (exposed in `main.ipynb` as `scoringMethod = "new" | "old"`).
Every item is normalised to its own max FIRST, then a checklist's **Score % = mean of its
items' fractions × 100** (equal weight per item). This is `aggregate="normalize"` (the default);
`aggregate="total"` would instead do `Σpoints / Σmax`.

| Mode | `scoreConfig` | How an option scores | 3-level middle |
|---|---|---|---|
| **new** (rank) | `None` → `{"mode":"rank"}` | by POSITION: best/middle/worst → 2/1/0 (max 2); 4-level 4/3/2/0; 2-level 1/0 | always 0.5 |
| **old** (label) | `{"mode":"label"}` | by LABEL value: Very good=4, Satisfactory=3, Borderline=2, Unsatisfactory=0, normalised by best **available** label | Satisfactory=3/4=0.75, Borderline=2/4=0.5 |

Only 3-level items differ between the two; 4-level and 2-level items are identical.
DDS4 = rank. DDS2 current = rank (legacy DDS2 = label). GR is normalised to 5=Excellent..1=Fail
(`reverseGr`); the BLR cut is the score predicted at GR=Borderline(2).

---

## 2. Overall-score scalings (one /100 Outcome column each)

Pass as `finalScoreMethods=[...]` to `buildOsceWorkbook`. Each is a cohort-level function
`f(students, ctx) -> {student: /100 mark}`, registered in `osce_utils.FINAL_SCORE_SCALINGS`
(display label in `FINAL_SCORE_HEADERS`). All marks clipped to [0,100].

Notation, per student over the counted stations i: `xᵢ`=station %, `cᵢ`=station raw BLR cut %,
`meanᵢ`/`sdᵢ`=cohort mean/SD of station i, `raw`=(1/n)Σxᵢ.
Cohort constants: `meanCut`=mean cᵢ, `grandMean`=mean of raw across students, `rawSD`=SD of raw.

| Name | Column | Formula | Family / represents |
|---|---|---|---|
| `rawMean` | Avg % (raw) | `raw = (1/n)Σxᵢ` | plain average; ignores difficulty |
| `cutAnchored50` | Cut-anchored /100 | `sl=(grandMean-50)/(grandMean-meanCut)`; `50+(raw-meanCut)·sl` | criterion; aggregate cut→50, cohort mean kept |
| `cutAnchoredFull` | Cut->50/100 | `raw≥meanCut: 50+50(raw-meanCut)/(100-meanCut)`; else `50·raw/meanCut` | criterion; cut→50, 100→100 (compresses) |
| `perStationCutRaw` | Per-stn cut (raw) | base = mean of `g(xᵢ,cᵢ)`, where `g=50+50(x-c)/(100-c)` if x≥c else `50x/c` | criterion per station; pass=50, mean sits low |
| `perStationCut` | Per-stn cut /100 | `k=(grandMean-50)/(bmean-50)`; `50+(base-50)·k` (bmean=cohort mean of base) | as above, level-restored to cohort mean |
| `perStationWeighted` | Wtd 100/cut | `Σ(xᵢ·100/cᵢ)/Σ(100/cᵢ)` | weighted avg; harder (low cut) station weighs more |
| `difficultyWeighted` | Difficulty-wtd /100 | `Σ(xᵢ·wᵢ)/Σwᵢ`, default `wᵢ=1/cᵢ` (configurable) | configurable twin of perStationWeighted (see §3) |
| `meanCutWeighted` | Wtd mean/cut | `Σ(xᵢ·meanᵢ/cᵢ)/Σ(meanᵢ/cᵢ)` | weighted avg by cohort **headroom** (meanᵢ/cᵢ); up-weights easy/lenient stations, down-weights hard ones |
| `z70` | Std 70/10 | `70+10(raw-grandMean)/rawSD` | norm-referenced; mean 70, SD 10 |
| `perStationZ` | Per-stn z /100 | zᵢ=(xᵢ-meanᵢ)/sdᵢ; `grandMean+rawSD·mean(zᵢ)` | norm-referenced per station; removes difficulty + spread |
| `perStationZ50` | Std 50/10 | zᵢ=(xᵢ-meanᵢ)/sdᵢ; `50+10·(z̄-μ)/σ` | standardised per-station z on a fixed 50±10 scale; norm-referenced, within-cohort ranking only |

Two axes: **aggregate vs per-station**, and **criterion** (50 pegged to the pass cut) vs
**norm-referenced** (relative to the cohort). Only the per-station / weighted ones can change a
student's rank versus their plain average.

---

## 3. Configurable weighted average — `difficultyWeightedScaling`

`osce_utils.difficultyWeightedScaling(weights="invcut", label="Difficulty-wtd /100") -> (label, func)`.
Mark = `clip( Σ(xᵢ·wᵢ) / Σwᵢ )`. A constant factor in w cancels, so `"invcut"` (1/cut) is identical
to `perStationWeighted` (100/cut).

| `weights` | wᵢ |
|---|---|
| `"invcut"` (default) | 1/cutᵢ — lower cut = harder = higher weight |
| `"invmean"` | 1/meanᵢ |
| `"inv_sd"` | 1/sdᵢ |
| `callable(cut, mean, sd, ck)` | your formula (return a constant for flat weights) |
| `dict {ck or sheet-title: w}` | hard per-station weights; stations not listed → 1/cut |

Standardised z aggregate (fixed scale, e.g. 50±10): `"perStationZ50"` by name, or
`osce_utils.perStationZScaled(mean=50, sd=10, restandardize=True, label="Std 50/10")`.
`restandardize=True` forces the output to exactly mean/sd; `False` just shifts/scales mean-z.

Examples (in the `finalScoreMethods` list):
```python
finalScoreMethods = ["rawMean", "difficultyWeighted", "meanCutWeighted"]           # by name
finalScoreMethods = ["rawMean", osce_utils.difficultyWeightedScaling(
    lambda cut, mean, sd, ck: 100 - cut, "Wtd (100-cut)")]                          # custom formula
finalScoreMethods = ["rawMean", osce_utils.difficultyWeightedScaling(
    {"S4 Referral": 3.0, "S2 LA": 2.0}, "Wtd (manual)")]                            # hard weights
```

---

## Where this is defined in code
- Item scoring: `resolveScoreConfig`, `itemScaleFromKeys`, `buildStationSpecs` (`osce_utils.py`).
- Scalings: `FINAL_SCORE_SCALINGS`, `FINAL_SCORE_HEADERS`, `_sc*` functions, `difficultyWeightedScaling`, `resolveFinalScoreMethods`.
- Applied in `buildOsceWorkbook` → "OSCE Outcome" sheet (prints the scaling constants used).
