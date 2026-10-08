# HANDOVER — OSCE student feedback PDFs (DDS4 2026)

**Date:** 2026-10-01
**Cohort:** DDS4 (2026 OSCE, Days 1 + 2). Code is cohort-generic: the station list comes from a metadata workbook filtered by cohort and year.
**Code files:** `osce_utils.py` (new section at the end of the file, "STUDENT OSCE FEEDBACK PDFs"), `main.ipynb` (new markdown and code cell straight after the station-wise BLR cell `b26eff7b`).
**New data file:** `OSCE/OSCE Station Metadata.xlsx`
**Inputs:** `OSCE/DDS4/DDS4 OSCE (2).xlsx` (cleaned feedback), `OSCE/DDS4/DDS4 BLR & Validity.xlsx` (applied cuts), `OSCE/OSCE Feedback Template.xlsx` (layout reference and logo).
**Output:** `OSCE/DDS4/Student Feedback Reports/<Name>_<StudentNo>.pdf`
**First run:** 7 students with an overall fail: 1113227 Yiyao Zhang, 1213093 YUE HENG XU, 1083399 James Phan, 916569 Henry Owuama, 1402031 Roman Prokopets, 1174040 Peikun Huang, 1383423 Warrick Edwards.

---

## 1. Why this exists

Coordinators asked for per-student OSCE feedback PDFs, like the 2025 DDS2 reports (sample: `Alisha_Dutt_1529549.pdf`, built with ReportLab on 28 Oct 2025). The team's new layout is `OSCE/OSCE Feedback Template.xlsx`, but the user wanted **PDFs**, and wanted the functions in `osce_utils.py` so the reports can be rebuilt from the notebook.

### 1a. Template vs 2025 sample: they did NOT match

| | 2025 DDS2 sample (PDF) | 2026 DDS4 template (xlsx) | **Built (2026)** |
|---|---|---|---|
| Header | "DDS2 OSCE Feedback" + name, green panel | navy band "DDS4 OSCE FEEDBACK" + name + UniMelb logo | template, plus the student number after the name |
| Summary | Rotation, Mark, Avg class mark, # passed, # failed, # < cutoff | Overall outcome, Mark %, Avg exam mark %, # passed, # failed, # 2 SDBM | Overall outcome, # passed, # failed, # 2 SDBM (Mark hidden for this run; avg exam mark removed) |
| Reassessment block | yes | no | no |
| Station header | Station N · Topic · Station type | Station N · Domain · Station type · Topic · "max = 30" | Station label · Domain · Station type · Topic |
| Station fields | Outcome, Score, Avg station score, Range, **Station cutoff** | Outcome, Score, **2 SDBM Y/N**, Cohort avg, Cohort range | template fields **+ Station cutoff** (user choice) |
| Max score | 100 | 30 | 100 (2026 scores are %) |

User decisions (2026-10-01): (1) 2026 template plus a cutoff field; (2) withhold the overall **mark** for these students (originally also the outcome, then the outcome cell was added back, see §6); (3) the user supplied the domain/type/topic mapping; (4) comments = cleaned Feedback, then Borderline/Fail Info.

---

## 2. Architecture

```
OSCE/DDS4/DDS4 OSCE (2).xlsx ──► loadFeedbackStations ──┐   (one sheet per checklist; cleaned Feedback)
                                   ▲                     │
OSCE/OSCE Station Metadata.xlsx ─► loadStationMeta ──────┤   (label/domain/type/topic, order, Include, Counts To Outcome)
                                                         ▼
OSCE/DDS4/DDS4 BLR & Validity.xlsx ─► loadAppliedCuts ─► computeFeedbackStats ─► buildStudentFeedbackPdf (×N)
   ('Student x Station' header +                         (cohort stats per station,     │
    'Standard Setting' APPLIED cut %)                     per-student outcomes/counts)   ▼
                                                                         OSCE/DDS4/Student Feedback Reports/*.pdf
OSCE/OSCE Feedback Template.xlsx ─► loadTemplateLogo (xl/media/image1.png) ─────────────┘
```

Orchestrator: `buildOsceFeedbackReports(...)`. Every public name has no leading underscore (the notebook uses `import *` in places; see the `import-star-underscore-rule`). ReportLab is imported **inside** the PDF function and aliased (`RlPara`, `RlTable`, …), so nothing collides with the module's openpyxl names (`Font`, `Image as XlImage`); see the `import-star-shadowing` rule.

### Design decisions
- **Read the cleaned station workbook, not the JSON.** `DDS4 OSCE (2).xlsx` holds the coordinator-cleaned Feedback (the "Feedback Cleaning" tracker sheet shows all 14 stations ticked for the 7 students). Scores there are the same dynamic per-item scores as the BLR workbook.
- **Cuts come from the BLR workbook's "Standard Setting → APPLIED cut %"**, so reports always agree with the official standard setting, including overrides (`PASS ALL`, BGM, −0.4pp, `excluded`).
- **Cohort stats come from every student on the sheet** (n = 104), not only the students being reported.
- **Station metadata lives in Excel** (user request), so non-coders can edit labels, order or inclusion. The dict `DDS4_FEEDBACK_STATION_META` is only a fallback when the workbook is missing.

---

## 3. Rules (load-bearing)

| Item | Rule |
|---|---|
| Station score | `Score (%)` from the station sheet (dynamic per-item, equal-weight; see `HANDOVER_osce_dds4_dynamic_item_scoring.md`) |
| Station FAIL | `round(score, 1) < APPLIED cut %` (same as `pct1`/`countBelow`) |
| PASS ALL station | Outcome PASS for everyone; **printed cutoff = lowest cohort score − `passAllCutOffset` (1)**. Oral Surgery 1.8: 48.08 → **47.1**; Ortho/Paeds 2.7: 54.17 → **53.2** |
| Not-counted station | Metadata `Counts To Outcome = N` (or `notCountedSheets=`): outcome **N/A**, cutoff **N/A**, left out of # passed / # failed and the overall outcome. Score, 2 SDBM, cohort avg/range and comments still shown. Note printed under the summary. DDS4: **Periodontics 2.11** (matches the official "Perio score counts to the average but not to the failure limit") |
| 2 SDBM | `score < mean − 2·SD` (sample SD, all students on that sheet). Agrees with "Mean-2SD %" in Standard Setting for every station |
| Overall outcome | `FAIL` if # stations failed > `maxStationFails` (4), else `PASS`; overridable per student via `overallOutcomes` |
| Excluded stations | Metadata `Include = N`: Diagnostics (`S1 diagnostics`) and Fixed Prosth (`S4 fixed-prosth`), removed by decision. Neither sheet is in `DDS4 OSCE (2).xlsx` anyway |
| Comments | Feedback, then Borderline/Fail Info. Heading "Borderline/Fail information:" only on **failed** stations (`bfHeading="failOnly"`); on passed stations the text runs on without a heading (`bfText="always"`) |

### Verification against the official outcome sheet (`DDS4 BLR & Validity.xlsx → OSCE Outcome`)
- Cohort average of the per-student average station score = **75.5%** (official "cohort mean = 75.5%") ✔
- Per-student averages: Yiyao 57.6, YUE HENG 57.9, James 64.2, Henry 66.7, Roman 68.4, Peikun 70.5, Warrick 70.9 ✔ (all equal to "Avg Score %")
- Failed-station counts with Perio not counted: 9 / 8 / 6 / 6 / 5 / 5 / 5 = official "Counted Fails" ✔. All 7 are overall FAIL.
- Mean−2SD per station equals Standard Setting "Mean-2SD %" (e.g. Ortho 13.2, Therapeutics 65.6, Rem Pros 15.6) ✔

---

## 4. Station metadata workbook: `OSCE/OSCE Station Metadata.xlsx`

Sheet **Stations** (plus a **Read Me** sheet). One row per checklist sheet in the station workbook. The loader filters on `Cohort` (and `Year` when given) and sorts by `Report Order`.

| Cohort | Year | Report Order | Station | Sheet Name | Domain | Station Type | Topic | Include | Counts To Outcome | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| DDS4 | 2026 | 1 | 1.1 | S1 Ortho | Orthodontics | Procedural | Assessment | Y | Y | |
| DDS4 | 2026 | 2 | 1.2 | S2 therapeutics | Therapeutics | Procedural | Script Writing | Y | Y | |
| DDS4 | 2026 | 3 | 1.5 | S5 removable-pr | Removable Prosthodontics | Procedural | Design Analysis | Y | Y | |
| DDS4 | 2026 | 4 | 1.7 | S7 special-need | Special Needs Dentistry | Consultation | Medical History | Y | Y | |
| DDS4 | 2026 | 5 | 1.8 | S8 oral-surgery | Oral Surgery | Consultation | Extractions | Y | Y | |
| DDS4 | 2026 | 6 | 1.10 | S10 health-promo | Health Promotion | Consultation | Dietary Advice | Y | Y | |
| DDS4 | 2026 | 7 | 1.11 | S11 paediactrics | Paediatrics | Procedural | Hand Hygiene & Separators | Y | Y | |
| DDS4 | 2026 | 8 | 2.2 | S2 sharps-manag | General Dentistry | Procedural | Sharps Management | Y | Y | |
| DDS4 | 2026 | 9 | 2.4 | S1 endodontics | Endodontics | Procedural | Trauma | Y | Y | |
| DDS4 | 2026 | 10 | 2.5 | S1+5 OralMed | Oral Medicine | Consultation | Ulcerations | Y | Y | |
| DDS4 | 2026 | 11 | 2.7 | S7 OrthoPaed | Paediatrics/Orthodontics | Consultation | Impacted Teeth | Y | Y | |
| DDS4 | 2026 | 12 | 2.8 | S8 medical-emer | General Dentistry | Procedural | Medical Emergencies | Y | Y | |
| DDS4 | 2026 | 13 | 2.10 | S10 extra-oral-e | General Dentistry | Procedural | Hand Hygiene & Examination | Y | Y | |
| DDS4 | 2026 | 14 | 2.11 | S11 Perio | Periodontics | Procedural | Hand Hygiene & Subgingival Scaling | Y | **N** | Outcome not counted |
| DDS4 | 2026 | | | S1 diagnostics | | | | **N** | N | Removed by decision |
| DDS4 | 2026 | | | S4 fixed-prosth | | | | **N** | N | Removed by decision |

The station label is the user's Day.Station numbering. It does **not** match the data's station number: the data files Endodontics under station 1, but it is **2.4** on the report, and Oral Medicine is the merged `S1+5 OralMed` = **2.5**. `Sheet Name` is the join key and must match the workbook tab exactly (watch the source typo `paediactrics`). "Removal" in the Domain column was corrected to "Removable".

---

## 5. API (`osce_utils.py`)

### Constants
| Name | Value / purpose |
|---|---|
| `DDS4_FEEDBACK_STATION_META` | OrderedDict, sheet → `{label, domain, type, topic[, counted]}`. Fallback when there's no metadata workbook; also the seed for `writeStationMetaWorkbook` |
| `FEEDBACK_EXCLUDE_SHEETS` | `{"S1 diagnostics", "S4 fixed-prosth"}` (fallback) |
| `STATION_META_PATH` / `STATION_META_SHEET` / `STATION_META_COLUMNS` | `"OSCE/OSCE Station Metadata.xlsx"` / `"Stations"` / column order |
| `FB_NAVY` `#000F46`, `FB_PANEL` `#D8E4BC`, `FB_FAIL` `#C00000` | template colours (header/bars, green panel, fail text) |
| `FB_LOGO_MEDIA` | `"xl/media/image1.png"`: the logo inside the template xlsx |

### Functions
| Function | Signature → returns | Notes |
|---|---|---|
| `loadStationMeta` | `(metaPath, cohort="DDS4", year=None, sheetName="Stations")` → `(meta OrderedDict, excluded set)` | `Include=N` → excluded; `Counts To Outcome=N` → `meta[s]["counted"]=False`; blank = Y |
| `writeStationMetaWorkbook` | `(metaPath, cohort, year, stationMeta=None, excludeSheets=None, overwrite=False)` → path | Seeds the workbook from the dict; refuses to overwrite unless `overwrite=True` |
| `readStationSheet` | `(ws)` → list of `{name, studentNo, score, gr, feedback, bfInfo}` | needs `Student Name`, `Student No`, `Score (%)` |
| `loadFeedbackStations` | `(stationPath, stationMeta=None, excludeSheets=None)` → `(stations, skipped)` | raises `KeyError` if a meta sheet is missing; `skipped` = scored sheets not reported |
| `loadAppliedCuts` | `(analysisPath)` → `{sheet: {checklist, cutPct, passAll, excluded, mean2sdPct}}` | zips "Student x Station" station headers (regex `^S[\d+]+ `) with "Standard Setting" rows; cross-checks the station number per row |
| `computeFeedbackStats` | `(stations, cuts, passAllCutOffset=1.0, notCountedSheets=None)` → `(stStats, students, examAvg)` | `stStats[s]`: n, mean, sd, min, max, sdbmPct, cutPct, passAll, displayCutPct, counted. `students[no]`: name, results, avg, nPass, nFail, nSdbm, complete |
| `loadTemplateLogo` | `(templatePath)` → bytes or None | |
| `fmtNum` / `commentHtml` | formatting helpers | 1 dp with ".0" dropped; XML-escape and keep newlines |
| `buildStudentFeedbackPdf` | `(outPath, student, stations, stStats, examAvg, cohortLabel="DDS4", hideOverall=False, logoBytes=None, showCutoff=True, maxScore=100, stationGapCm=0.9, bfHeading="failOnly", bfText="always")` | one A4 PDF |
| `buildOsceFeedbackReports` | see below | orchestrator |

```python
buildOsceFeedbackReports(
    stationPath, analysisPath, outDir,
    studentNumbers=None,          # None = everyone on the sheets
    cohortLabel="DDS4",           # title + metadata filter
    hideOverallFor=None,          # True | [studentNo,...] -> withhold overall MARK
    templatePath="OSCE/OSCE Feedback Template.xlsx",
    stationMeta=None, excludeSheets=None,          # explicit overrides
    showCutoff=True,
    overallOutcomes=None,         # {studentNo: "PASS"/"FAIL"} overrides the computed outcome
    metaPath=STATION_META_PATH, year=None,
    passAllCutOffset=1.0,         # PASS ALL cutoff = min - this
    maxStationFails=4,            # overall FAIL when # failed > this
    bfHeading="failOnly", bfText="always",         # "always" | "failOnly" | "never"
    stationGapCm=0.9,
    notCountedSheets=None)        # extra sheets whose pass/fail isn't counted
```
Returns
```python
{"metaSource": "OSCE/OSCE Station Metadata.xlsx",
 "files": ["OSCE/DDS4/Student Feedback Reports/Yiyao_Zhang_1113227.pdf", ...],
 "missing": [], "incomplete": {}, "skippedSheets": [],
 "examAvg": 75.49, "stationStats": {...},
 "summary": [{"name": "Yiyao Zhang", "studentNo": "1113227", "avg": 57.6, "passed": 4, "failed": 9,
              "sdbm": 3, "overallOutcome": "FAIL", "markHidden": True, "file": "..."}, ...]}
```

### Notebook cell (after `b26eff7b`, "DDS4 OSCE student feedback PDFs")
```python
fbCohort       = "DDS4"
fbStationPath  = "OSCE/DDS4/DDS4 OSCE (2).xlsx"
fbAnalysisPath = "OSCE/DDS4/DDS4 BLR & Validity.xlsx"
fbOutDir       = "OSCE/DDS4/Student Feedback Reports"
fbTemplate     = "OSCE/OSCE Feedback Template.xlsx"
fbMetaPath     = "OSCE/OSCE Station Metadata.xlsx"
fbYear         = 2026
fbStudents     = [1113227, 1213093, 1083399, 916569, 1402031, 1174040, 1383423]   # None = everyone
fbHideOverall  = True        # withhold overall MARK
fbMaxFails     = 4
fbBfHeading    = "failOnly"
fbBfText       = "always"
fbNotCounted   = None        # metadata already marks Perio
fbOutcomes     = None
```
It prints the PDF count, the metadata source, and any missing/incomplete students or unreported sheets, then displays the summary table.

---

## 6. PDF layout (A4, ReportLab)

```
┌──────────────────────────────────────────────── navy #000F46 ─┐
│ DDS4 OSCE FEEDBACK                                  [UniMelb] │
│ Yiyao Zhang (1113227)                                         │
├──────────────────────────────── green panel #D8E4BC, all pages┤
│ OVERALL EXAM OUTCOME [FAIL]   (MARK [x%] only if not hidden)  │
│ STATIONS PASSED [4]  STATIONS FAILED [9]  STATIONS 2 SDBM [3] │
│ Note: Station 2.11 (Periodontics) is not counted towards the  │
│   number of stations passed/failed; its outcome and cutoff    │
│   are shown as N/A.                                           │
│              maximum station score = 100 · 2 SDBM = …         │
│ ───────────────────────────────────────────────────────────── │
│ STATION 1.1  DOMAIN: … STATION TYPE: … TOPIC: …               │
│  OUTCOME [FAIL]   SCORE [5]           STATION CUTOFF [43.9]   │
│  2 SDBM  [YES]    COHORT AVERAGE [57.7]  COHORT RANGE [0-100] │
│ ┌──────────────── EXAMINER COMMENTS: (navy bar) ────────────┐ │
│ │ feedback …                                                │ │
│ │ Borderline/Fail information:  (failed stations only)      │ │
│ └───────────────────────────────────────────────────────────┘ │
│   (0.9 cm gap)                                                │
│ STATION 1.2 …                                                 │
└──────────────────────────────────────────── footer: name·no·p ┘
```
- FAIL / YES / failed counts are bold red. An empty comment shows *"No comments recorded."*
- The station header plus score grid are kept together with the comment box (`KeepTogether`). A block too tall for the space left moves to the next page, which can leave white space at the bottom of a page.

### Change log (all 2026-10-01, in order of request)
1. First build: template + cutoff, overall outcome and mark hidden, topic/domain/type from the user's mapping.
2. Station metadata moved to `OSCE/OSCE Station Metadata.xlsx` (`loadStationMeta`, `writeStationMetaWorkbook`); student number after the name; **average exam mark removed**; station heading reduced 15pt → 11pt (column 18% wide so "STATION 1.10" fits on one line); **green panel missing from page 3 on** fixed (see §7).
3. PASS ALL cutoff = lowest − 1.
4. Overall outcome cell added back (FAIL when > 4 stations failed); mark still withheld.
5. Gap between stations 0.35 → 0.9 cm (`stationGapCm`).
6. `bfHeading` / `bfText` options; heading only on failed stations.
7. Not-counted stations (`Counts To Outcome`, `notCountedSheets`): N/A outcome and cutoff, left out of counts and the overall outcome, note in the summary. Perio = N.
8. Note text shortened to "…not counted towards the number of stations passed/failed; …".

---

## 7. Gotchas

- **`SimpleDocTemplate` drops page decoration after page 2.** `SimpleDocTemplate.build()` appends its own "Later" template without `onPage`, so pages ≥ 3 lost the green panel. Fixed by using `BaseDocTemplate` with `PageTemplate("first", autoNextPageTemplate="rest")`. Don't switch back.
- **Variable shadowing in the PDF function:** `head` is the station-header table. An inner `head = "<b>Borderline…"` once replaced it with a string → `AttributeError: 'str' object has no attribute 'wrapOn'` inside `KeepTogether`. The B/F string is now `bfHead`.
- **Cut alignment is positional.** `loadAppliedCuts` zips the "Student x Station" station columns with the "Standard Setting" rows. Both are written in the same spec order by `buildOsceWorkbook`, and the station number is cross-checked, but a hand-edited BLR workbook (reordered rows) raises `ValueError` rather than mis-assigning a cut.
- **"Student x Station" has trailing non-station columns** (`Mean % (counted)`, `Fails`, `< M-2SD`, `Legend`); they are filtered with the regex `^S[\d+]+ `.
- **PASS ALL printed cutoff is cosmetic.** Outcomes still come from the PASS ALL flag; `min − 1` is just a number everyone is above.
- **The fail count is what's printed.** With Perio marked not-counted it equals the official "Counted Fails". If Perio is switched back to Y, the counts go up by one for students who failed Perio.
- **The overall-outcome rule is only "> 4 failed stations".** The official OSCE Outcome sheet also requires average ≥ average cut. For these 7 it doesn't matter (all fail on station count), but a student failing only on the average would show PASS here. Use `overallOutcomes={no: "FAIL"}` for such a case.
- **The mark is hidden by `fbHideOverall=True`.** For a normal run set it to `False`, and the MARK cell (student's average station score) appears next to the outcome.
- **Not run on the user's Windows Python.** The Cowork device shell has no scipy, and `osce_utils` imports scipy at module level. The PDFs were built in the cloud workspace from the same code and the same input files, then copied to the folder. Re-running the cell locally should reproduce them byte-for-byte except timestamps.
- `main.ipynb`: if it's open in Jupyter while the file is updated on disk, reload before saving or the new cell/settings are overwritten (happened once this session; the edit was re-applied on top of the user's saved version).

---

## 8. Files touched

| File | Change |
|---|---|
| `osce_utils.py` | +~520 lines at the end (feedback section). No existing function changed. 2,211 lines / 57 functions / 31 constants after |
| `main.ipynb` | +1 markdown + 1 code cell after `b26eff7b` |
| `OSCE/OSCE Station Metadata.xlsx` | new |
| `OSCE/DDS4/Student Feedback Reports/*.pdf` | 7 new PDFs |
| `_docs/osce_utils.md`, `_docs/INDEX.md` | dated amendments |
| Backups | `_bak/osce_utils.py.bak_20261001_*`, `_bak/main.ipynb.bak_20261001_*`, `_bak/OSCE Station Metadata.xlsx.bak_20261001_053246` |

---

## 9. Open items

- The 7 PDFs are built but **not yet emailed**. The BOH1 send cell (`send_email`, cell after the BOH1 OSCE PDFs) could be reused with `savefolder="OSCE/DDS4/Student Feedback Reports"` and filenames `<Name>_<No>.pdf`.
- Reports for the rest of the cohort (passing students): set `fbStudents=None`, `fbHideOverall=False`. Check the overall-outcome rule above first (the average ≥ cut condition isn't applied).
- The metadata workbook only has DDS4 2026 rows. Add DDS2 (and other cohorts/years) before using it for them.
- The old `osce_pdfs.py` (BOH1 checklist/GR PDF) is a separate generator and is untouched.
