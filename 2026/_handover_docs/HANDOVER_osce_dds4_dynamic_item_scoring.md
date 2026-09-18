# HANDOVER — DDS4 OSCE dynamic per-item scoring

**Date:** 2026-09-09
**Cohort:** DDS4 (2026 OSCE Day 1)
**Code files:** `osce_utils.py`, `osce_metrics.py` (station/analysis workbook builders); driven from `main.ipynb` cell ~35 (`osce_utils.buildOsceWorkbook`).
**Data:** `temp 2026 osce.json` (624 records, all `2026 DDS4 OSCE Day 1`).

---

## 1. Why this change

DDS4 OSCE introduced a new checklist shape: **different MC items can offer a different
number of response options, even within the same checklist.** The previous OSCE engine
(built for DDS2) assumed one scale per checklist and hard-coded 10 items, so it was wrong
for DDS4 in three ways:

1. **Hard-coded `range(1, 11)`** silently dropped MC11–MC14 (Paediatrics has 14 items,
   Oral Surgery 13, Removable Prosth 12).
2. **One scale per checklist** could not represent Fixed Prosth (2- and 4-level items
   mixed) or Removable Prosth (2- and 3-level mixed).
3. **Label-based points were unreliable** for DDS4: Oral Surgery has the label typo
   `"Unsatifactory"`; DDS4 uses `"Very Good"` (capital G) where the old map had
   `"Very good"`; and Removable Prosth's 3-level map has `O1 = Satisfactory` as its *best*
   option (label-based scoring would have marked it 1 instead of top).

## 2. DDS4 data shape (what the JSON actually contains)

Per checklist, `form_config.checklists[<ck>]` has:
- `fields`: `{ "MC1": "...", ... }` — the item list (MC1..MCn, n up to 14).
- `extra_config.options`: checklist-level `O-key -> label` map (varies per checklist).
- `extra_config.rubric[MCi]`: **per-item** `O-key -> description` (+ a `label` sub-heading
  key to ignore). **The number of O-keys in an item's rubric = that item's level.**

`form_data.checklists[<ck>][MCi]` = `{ "key": "O2", "value": "Satisfactory" }`.

Observed levels (all data clean: 0 answer keys outside the item rubric):

| Checklist | Items | Level mix | O-key sets |
|---|---|---|---|
| Fixed Prosthodontics | 10 | 2-level ×4 + 4-level ×6 | 2-lvl `{O2,O4}`, 4-lvl `{O1..O4}` |
| Removable Prosthodontics | 12 | 2-level ×3 + 3-level ×9 | 2-lvl `{O1,O3}`, 3-lvl `{O1,O2,O3}` |
| Special Needs Dentistry | 12 | 4-level | `{O1..O4}` |
| Oral Surgery | 13 | 4-level | `{O1..O4}` (label typo "Unsatifactory") |
| Health Promotion | 12 | 4-level | `{O1..O4}` |
| Paediatrics | 14 | 2-level | `{O2,O4}` |

O-keys within a checklist are always ordered best→worst (`O1` best); verified contiguous.

## 3. Scoring model (new)

**Per-item, by rank (best→worst), never by label:**

| Level | Points (best→worst) | Item max |
|---|---|---|
| 4-level | 4, 3, 2, 0 | 4 |
| 3-level | 2, 1, 0 | 2 |
| 2-level | 1, 0 | 1 |

(Unexpected level counts fall back to a linear best→worst scale so a new template never
crashes; a 1-option item scores 1/1.)

**Equal weight via normalisation:** each item → `frac = points / itemMax` (so a 2-level
item and a 4-level item both span 0..1). **Checklist score = mean of the answered items'
fractions × 100.** A blank item is excluded from that mean.

Scoring is **by the answer `key`** looked up in the item's rank map — immune to label
typos/case and to O-key→label maps differing across checklists.

### Config keys / constants (in `osce_utils.py`)
```python
LEVEL_POINTS = {4: [4, 3, 2, 0], 3: [2, 1, 0], 2: [1, 0]}   # index 0 = best option
LEVEL_MAX    = {4: 4, 3: 2, 2: 1}
```

### New / changed functions (`osce_utils.py`)
- `_okeyNum(k)` — numeric part of an O-key for ordering (`O3`→3).
- `checklistItems(cfg)` — ordered MC indices from `fields` (fixes the 10-item cap).
- `itemOptionOrder(rubItem)` — an item's O-keys best→worst (ignores `label`).
- `itemScale(rubItem)` → `(keyPoints, maxPts, level, order)` — the per-item rank map.
- `checklistItemScales(cfg)` → `{i: (keyPoints, maxPts, level, order)}`.
- `checklistOptionLabels(cfg)` — checklist O-key→label map (display only).
- `levelsText(itemLevel)` — `"4-level"` / `"mixed 2/4"` etc.
- `checklistScale(...)` — **removed** (replaced by the per-item helpers above).
- `buildStationSpecs` — now attaches `items`, `itemLevel`, `itemMax`, `scales`,
  `optLabels`, `levels` (text) and `maxPerItem` (the single item max, or `None` if mixed).
  Each row now carries `points[i]` (rank points, display), `frac[i]` (0..1, scoring/stats)
  and `labels[i]`; `score` = mean of answered `frac`.
- `cronbachAlpha(rows, items)` and `itemTotalCorrs(rows, items)` — now take the dynamic
  item list and compute on the **normalised fractions** (so mixed-level items are
  comparable), instead of the old raw-integer points over `range(1,11)`.
- `buildBlrFigure` — item-analysis panel uses per-item mean fractions and the dynamic
  item list; title shows the level summary.
- Workbook sheets updated: **Read Me** (new scoring note), **detail sheets** (dynamic MC
  columns; MC cells now coloured by a red→green gradient on the item fraction instead of
  by label), **MC Item Stats** (per-item `Level`, best→worst option counts, `Avg Points`,
  `Max`, `Avg %`), **Checklist Legend** (per-item `Item Level`).

### Changed (`osce_metrics.py`)
- `interGradeDiscrimination(spec)` — for a uniform-level checklist keeps the raw-mark scale
  (`maxMark = 10 × per-item max`, unchanged); for a **mixed** checklist uses the normalised
  percentage scale (`maxMark = 100`, guideline 10 %/grade) so the metric stays defined.
- `buildStationMetricsSheet` — `cronbachAlpha` / `itemTotalCorrs` calls pass `sp["items"]`.

## 4. Verification

- **Hand-check** (Fixed Prosth, first record): keys
  `MC1..MC10 = O2,O2,O2,O1,O4,O4,O4,O2,O1,O2` → fracs
  `1,1,0.75,1,0,0,0,1,1,0.75` → **65.0%** ✓
- **Uniform-level equivalence:** for a uniform 4-level checklist, the new mean-of-fractions
  equals the old `sum(points)/(n×max)` for **every** row (diff = 0) — so uniform checklists
  (the DDS2 case) are numerically unchanged.
- **Rank vs label:** 0 mismatches on a standard 4-level checklist (rank-based = old
  label-based for standard labels).
- 3-level item → `1.0 / 0.5 / 0.0`; 2-level item → `1.0 / 0.0` (both verified).
- Both workbooks open in openpyxl; 12 BLR/harshness PNGs render.

DDS4 station BLR cuts (equal-weighted): see §4b for the corrected figures (the values first
computed here used GR wrongly reversed; §4b lists the fixed cuts).

## 4a. Cohort filter (2026-09-09, follow-up)

Records carry **no `cohort` field** — the only cohort marker is the `session` string (e.g.
`"2026 DDS4 OSCE Day 1"`). The API pull (`main.ipynb` cell 31) already scopes the fetch with
`cohort=`, so each `temp … osce.json` is normally single-cohort. As a guard for a mixed-cohort
JSON, `loadOsceRecords(..., cohort=None)` now keeps only records whose `session` contains the
cohort token (case-insensitive); `buildOsceWorkbook(..., cohort=None)` defaults it to the
`cohortLabel` already passed (so `cohortLabel="DDS4"` also filters to DDS4). Pass `cohort=""` to
disable. It is a no-op on a single-cohort file (DDS4: 583 → 583 records, cuts unchanged).

## 4b. Global Rating direction (2026-09-09, follow-up)

**DDS4's GR key is already in standard order** — the scale config is `1=Fail, 2=Borderline, 3=Pass,
4=Very Good, 5=Excellent`. DDS2 stored it reversed (`1=Excellent..5=Fail`), which is why the old
code did `6 - key`. Applying that reversal to DDS4 flips Excellent↔Fail and makes the BLR slope
**negative** (the bug: fixed-prosth slope was −0.141; correct is +0.141, R²=0.676).

`reverseGr` (True/False/`"auto"`, default `"auto"`) on `buildStationSpecs` / `buildOsceWorkbook`
controls it. `"auto"` decides from the scale's own labels via `GRADE_RANK` (reverse only when the
lowest key is the better grade); helpers `grScaleFields` / `shouldReverseGr` / `resolveReverseGr`.
Reversal uses `maxGr+1-key` (not hard-coded 6). 12 DDS4 records have a corrupt `[object Object]`
GR — non-numeric, so already excluded from BLR.

**Corrected DDS4 BLR cuts** (GR not reversed): Fixed 59.1, Removable 47.5, Special Needs 60.4,
Oral Surgery 53.8, Health Promotion 60.4, Paediatrics 80.6%. (The earlier 87.3/79.3/… figures in
§4 were computed with GR wrongly reversed — superseded by these.)

## 4c. Empty-BLR guard + submitted-only (2026-09-10, follow-up)

The full DDS4 re-pull (`temp 2026 osce.json`, 1352 records, 14 checklists) added station types that
can't support BLR and crashed cell 35 with `ValueError: Inputs must not be empty` (empty
`linregress`):
- **`diagnostics`** — 21 scored MC items but **no Global Rating** → can't regress.
- **`endodontics`** — has a GR but **no scored MC items** → nothing to score.

Fixes (all in `osce_utils.py`):
- `computeBlr` now returns `valid=False` with NaN stats (and `cutPct=None`) when there are `<2`
  paired GR+score points or `<2` distinct GR values, instead of calling `linregress` on empty input.
- `buildOsceWorkbook` splits `analysisSpecs = [valid]` from `skippedAnalysis`. **All** stations still
  get station-workbook sheets (detail, MC Item Stats, Legend, Station Summary — cut shown as `-`);
  the analysis workbook (BLR Analysis, Station Metrics, BLR-per-Circuit, Assessor Analysis, Standard
  Setting, Student×Station, Assessor Grid) is built from `analysisSpecs` only, with a red note on the
  BLR Analysis sheet listing what was excluded and why.
- Guarded the empty cases: Station-Summary stats skip when a station has no scores; the detail-sheet
  `mc0` handles a station with no MC items.
- **Submitted-only** is enforced in `loadOsceRecords` (`if not r.get("submitted"): continue`) — 569 of
  1352 were unsubmitted and dropped; 783 used. The summary dict returns `recordsUsed` and
  `skippedAnalysis`, and cell 35 prints both.

Current DDS4 (submitted only, GR not reversed): 11 stations with BLR cuts (Fixed 59.7, Removable 47.7,
Special Needs 60.1, Oral Surgery 54.3, Health Promotion 60.8, Paediatrics 80.7, Oral Medicine 71.6,
Ortho-Paeds 66.8, Medical Emergencies 67.1, Extra-oral Exam 63.7, Periodontics 74.7); diagnostics and
endodontics skipped from analysis.

## 4d. Student numbers alongside names (2026-09-13, follow-up)

**2026-09-14 update:** the DASH pull now includes `student_number` on each record, so that is the
primary source — `buildStationSpecs` sets `r["studentNo"] = str(r["student_number"])`, and
`loadOsceRecords` excludes ignored students by that number directly. The roster lookup below is now
just a fallback for any record missing the field (100% present in the current pull). This resolved the
DDS2 name gaps automatically (Yong (Miranda) Wang, Karan Nahal, Gloria Xu all carry correct numbers),
so `STUDENT_NUMBER_OVERRIDES` / `nameToNumberMap` / `studentNumberFor` are retained only as fallback.

Original (roster) approach — Records carry only the student **name**; numbers come from `studentEmailList.csv`
(`student_number, student_name, ...`). New helper `nameToNumberMap(rosterPath)` inverts the roster to
`{name(lower): number}`; `buildOsceWorkbook` attaches `r["studentNo"]` to every row (all 104 DDS4
students matched). Surfaced as a dedicated **"Student No"** column (separate from "Student Name") in the per-station detail
sheets, the BLR "Students below cut" table, the **Student×Station pivot** (`ST0=3`, freeze `C2`) and the
**Assessor Grid** (`AST0=3`, freeze `C2`) — both station-indexed sheets were reindexed so stations start
at column C. (Fixed a latent Assessor-Grid bug in passing: its cell loop iterated all `specs` instead of
`analysisSpecs`, which could write extra unlabelled columns.) This is a roster lookup — if the DASH API
later returns the number on the record, switch `studentNo` to read it directly.

Matching (2026-09-13): the OSCE `student` field uses preferred/English names that the roster (legal
names) may not carry, so exact match misses some. `studentNumberFor(name, nameToNum)` resolves in
order: `STUDENT_NUMBER_OVERRIDES` (manual map) → exact normalised match → name with any
`(parenthetical)` removed. Known DDS2 gaps handled via overrides: `Yong (Miranda) Wang`→1361370
(roster `Yong Wang`), `Karan Nahal`→1677856 (roster `Karanvir Nahal`), `Gloria Xu`→1351773 (roster
`Nuo Xu`). Add new gaps to `STUDENT_NUMBER_OVERRIDES`. DDS2 must be re-run to pick these up (the
DDS2 records JSON was overwritten by the DDS4 pull, so it can't be regenerated retroactively here).

## 4e. Grouping by checklist + excluded stations (2026-09-14, follow-up)

`buildStationSpecs` now groups by **checklist key only** (was `(station, checklist)`). A checklist run
across several station numbers/circuits is therefore merged into ONE station group — DDS4
`oral-medicine` runs at S1 (35 students) and S5 (69), now a single `S1+5 OralMed` sheet with n=104 and
one BLR. (This also fixed a latent bug: the `blr` dict and other downstream maps are keyed by `ck`, so
two same-`ck` specs were colliding.) Verified no student has the same checklist submitted at two
stations, so no double-counting. `spec["st"]` is the single station int, or `"1+5"` when merged (used
in sheet titles — `+` is a legal sheet-name char); `spec["stations"]` holds the list.

`EXCLUDE_CHECKLISTS = {"orthodontics", "endodontics"}` drops incomplete/not-run stations from the whole
OSCE output (DDS4 stray `orthodontics` n=1, partial `endodontics` n=53 — NOT the full
`orthodontics-paediatrics` n=104, which stays). Override per run via `buildOsceWorkbook(...,
excludeChecklists={...})`. Added abbreviations `oral-medicine→OralMed`, `orthodontics-paediatrics→
OrthoPaed` so sheet names are clear. DDS2 is unaffected (its checklists are each single-station and not
excluded — output identical).

## 4f. Derived GR for the no-GR diagnostics station (2026-09-14, follow-up)

DDS4 **Day 2 Station 1 = Diagnostics** was unobserved / marked post-task, so **no examiner Global
Rating was entered on any of its 103 forms** (the `global-rating` field is absent, not blank). It was
the only GR gap anywhere (verified across DDS4 + DDS2). The examiners agreed to derive the GR from the
raw checklist total.

The raw total is the **label-value sum** (Very Good=4, Satisfactory=3, Borderline=2, Unsatisfactory=0),
summed over the 21 items — **max = 66** (12 two-level items best=Sat=3 → 36, 6 three-level best=Sat=3 →
18, 3 four-level best=VG=4 → 12). This is the OLD label-based scheme, distinct from the report's
equal-weight `Score%`. Examiner bands → GR: **Excellent 63-66, Very good 50-62, Pass 44-49, Borderline
36-43, Fail 0-35**. Result on the data: 101 Fail + 2 Borderline (the cohort picked Unsatisfactory on
64.6% of items — genuinely low, confirmed with the user).

Config in `osce_utils.py`: `GR_LABEL_VALUES` (label→value), `GR_SCORE_BANDS = {"diagnostics": [...] }`,
helper `grFromBands`. In `buildStationSpecs`, when a record has no numeric GR **and** its checklist is
in `grScoreBands`, `gr` is derived from the label-value total; the row carries `grDerived`/`grRaw`, and
the spec carries `grDerived`. This makes diagnostics analysable (it now gets a BLR instead of being
skipped). Both Read Me sheets carry a NOTE that the GR was derived. Override via
`buildOsceWorkbook(..., grScoreBands={...})`; pass `{}` to disable. A per-student list for entry back
into DASH is `OSCE/DDS4/DDS4 Diagnostics Derived GR.xlsx` (student no, name, circuit, assessor, raw/66,
derived GR).

## 4g. Item options = options map − disabled_options (2026-09-16, IMPORTANT FIX)

**Bug:** item level/options were read from `extra_config.rubric[MCn]` (per-item descriptions), which is
often EMPTY or PARTIAL. Items with a blank rubric were detected as 0-level and every answer on them was
dropped → **missing MC values** in the sheets (oral-medicine 624, extra-oral 1456, periodontics 1040,
medical-emergencies some). The rubric is descriptions only, not the option set.

**Fix:** an item's available options come from the checklist's **`extra_config.options` map MINUS that
item's `extra_config.row_config[MCn].disabled_options`** — `itemAvailableKeys(cfg, i)` (falls back to
rubric keys only when there is no options map). `checklistItemScales` now builds each item's scale from
those keys via `itemScaleFromKeys`. Points/levels unchanged in method (rank best→worst, 4/3/2/0 etc.),
only the SET of options per item is now correct.

**Effect:** 0 answers dropped now (was thousands). Corrected checklists: oral-medicine (now 4-level,
n=104 mean 80%, cut 66.2), extra-oral (2/4, cut 73.1), medical-emergencies (2/3/4, cut 67.4),
periodontics (**15 items, options O1/O2/O3 only — no Unsatisfactory**, cut 78.2), removable MC4 (3→2).
Checklists with `options−disabled == rubric` are unchanged (diagnostics, fixed-prosth, special-needs,
oral-surgery, health-promotion, paediatrics, etc. — verified 0 diffs), so diagnostics' derived GR is
identical. NOTE: DDS2 and DDS4 both have a "periodontics" checklist but they are DIFFERENT (DDS2 = 10
items O1-O4; DDS4 = 15 items O1-O3) — always cohort-filter before inspecting a checklist config.

## 5. Traps / notes

- **Score by `key`, not `value`.** O-key→label maps differ per checklist and contain a typo
  (`"Unsatifactory"`); `Very Good` vs `Very good` casing differs from the legacy map.
- **`label` is a rubric sub-key**, not an option — always excluded from the O-key set.
- **`maxPerItem` is now `None` for mixed checklists.** Any new consumer must handle that (it
  is only used by `interGradeDiscrimination`, which does).
- **Points are read by rank position**, so the *relative spacing* matters: 4-level is
  `4,3,2,0` (Borderline→2, i.e. 0.5 normalised), not linear.

## 6. Open items

- **DDS2 now builds from the same JSON** (2026-09-14): the re-pull holds both `2026 DDS4 OSCE Day 1`
  and `2026 DDS2 OSCE` (plus Test sessions), so `buildOsceWorkbook(cohortLabel="DDS2")` regenerates
  the DDS2 workbooks — done and committed. DDS2 auto-detects `reverseGr=True` (its scale is
  `1=Excellent..5=Fail`); the cohort filter keeps the sessions apart. The only residual caveat vs the
  *old* DDS2 output is a partial item that offered a **middle** option (e.g. an Occlusal item defined
  with only `O1`/`O3`=Borderline), which the new engine treats as a genuine 2-level item; extreme-only
  partial items are unaffected.
