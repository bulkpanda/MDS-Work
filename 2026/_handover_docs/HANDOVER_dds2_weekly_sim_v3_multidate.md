# Handover — Weekly Sim reports (DDS2 + BOH2): v3 audit, date discovery, streams, flagging

**Date:** 2026-08-12, last updated 2026-08-18
**Cohorts:** DDS2 and BOH2 (`type = 'Simulation'`) — the chain is cohort-generic as of 2026-08-17
**Files changed:** `general_utils.py`, `main.ipynb` (cells 36, 37, 39, 40, 41), `risk_report.py`
**Backups:** `general_utils.py.bak_20260812_162331`, `general_utils.py.bak_20260818_012522`
(pre-column-layout), `main.ipynb.bak_20260812_162331`,
`main.ipynb.bak2_*` (pre-period), `main.ipynb.bak3_*` (pre-ignore-list),
`main.ipynb.bak4_*` (pre-streams), `main.ipynb.bak5_*` (pre-flagging/styling), `bak6_*` (pre-GR-levels), `bak7_*` (pre-assessor-sheet), `bak8_*` (pre-cohort-generic),
`general_utils.py.bak_20260818_014728` (pre-attendance),
`general_utils.py` / `risk_report.py` / `main.ipynb` `.bak*_20260818_020907` (pre-combined-relabel)
**Status:** verified end-to-end against a real PostgreSQL 16 instance loaded with the actual
2026 DDS2 Simulation payloads (see §8). Not yet run against the user's own Postgres.

**Latest changes (18 Aug 2026):** the weekly sheet's column layout — dropped columns, MC block
moved before `Assessor Score`, Title Case headers (**§6e**) — and an attendance layer: a greyed
blank row for every roster student with no data, an amber student number where someone has more
than one form, and a Session Summary sheet
(**§6f**), and the same relabelling applied to the combined workbook, with a compat shim in
`risk_report.py` (**§6g**). §6 updated. No database work, no schema change; every number in every
sheet is unchanged.

---

## 1. What this session was for

The DDS2 Weekly Sim workbooks (`DDS2/Weekly Sim/dds2 <date> assessment_data.xlsx`) were built one
date at a time from a notebook cell that carried a hand-maintained list of dates as commented-out
calls:

```python
# createDateReport('2026-02-02') # Week 01
# createDateReport('2026-02-09') # Week 02
...
# createDateReport('2026-05-25') # Week 15
```

Three things were asked for:

1. **Confirm/complete the v3 migration** of the data pull, in line with the rest of the
   BOH1/BOH2/DDS1/DDS2/DDS3 chain already moved to `rawform_forms_v3`.
2. **Read the assessment dates from the database** rather than maintaining them by hand, and
   **accept a list of dates** so many workbooks can be built in one call.
3. **A minimum-date cutoff**, defaulting to **15 June 2026** — the semester 1 / semester 2
   boundary — so already-built semester 1 workbooks are never reconsidered, and splitting
   sem 1 / sem 2 workbooks is just a matter of which bound you pass.
4. *(added later in the same session)* **An FHY / SHY / ALL selector for the downstream analyses**
   — BLR, combined notebook and risk report — which all glob the shared folder and were therefore
   pooling both semesters. See §7.
5. *(also added later)* **An `ignoreCodeList` (+ optional `minItemCount`)** so the combined
   notebook and BLR can exclude specific item codes — January test forms, semester-1 catch-ups
   leaking into semester 2, and single-student codes whose percentile threshold is computed over
   n = 1. See §7.6.
6. **A stream model.** Semester 2 is not one weekly sim but three parallel subjects
   on three weekdays (Paediatrics / Fixed Prosthodontics / Endodontics), each with its own
   checklist family and its own subfolder, plus a pooled view. Forms are routed by item code
   because the subject code students enter is wrong ~4% of the time. See §6b.
7. *(and finally)* **Flagging.** A `borderline` method alongside `percentile` and `blr`, a fix for
   BLR silently flagging nobody, best-attempt aggregation made explicit, and a styled combined
   workbook with a Description sheet. See §6c.

Why (2) matters more in semester 2 than it did in semester 1: **semester 1 ran one sim session a
week (Mondays only, 15 dates). Semester 2 runs three a week** — Monday (Paeds), Tuesday (FP) and
Wednesday (the unprefixed `Week-xx` family) — so by 12 Aug there were already 20 sem-2 dates to
build instead of 15 across a whole semester.

---

## 2. Data shape — what is actually in `rawform_forms_v3` for DDS2 Simulation

Verified against the raw pull `fetched_rows 2026 caf.xlsx` (20,312 assessments; 3,583 DDS2
Simulation forms, 3,474 with `submitted_by_assessor = true`).

### 2.1 A representative `assessor_data` payload (2026-07-13, Paeds)

```jsonc
{
  "radio":  { "clinical-incident-occurred": ... },
  "texts":  { "reflection": "both preps completed, 54 restoration incomplete. ..." },
  "scales": {
    "scale-time-mgmt":           { "key": "1", "value": "Level 1: Work not completed ..." },
    "scale-communication":       { "key": "2", "value": "Level 2: Matches verbal and ..." },
    "scale-global-rating":       { "key": "2", "value": "Borderline" },
    "scale-professionalism":     { "key": "2", "value": "Level 2: Presents as a professional ..." },
    "scale-practice-readiness":  { "key": "1", "value": "Level 1 - Student is not ready ..." },
    "scale-position-ergonomics": { "key": "2", "value": "Level 2: Adjusts clinician chair ..." }
  },
  "checklists": {
    "Paeds 2026-Week-1": {
      "MC1":  { "key": "O2", "value": "Done well" },
      "MC2":  { "key": "O3", "value": "Mostly done" },
      "MC13": { "key": "O1", "value": "Outstanding" }
    }
  },
  "multi-select": {},

  // merged on top by getInsertSqlRawform_forms_v3 — the v2-style FLAT copy:
  "Paeds 2026-Week-1": { "MC1": "O2", "MC2": "O3", "MC13": "O1" }
}
```

Two consequences the SQL depends on:

- **Scales are nested and prefixed**, level under `->>'key'`, i.e.
  `assessor_data->'scales'->'scale-global-rating'->>'key'`. The `rawforms_v3_separation_handover.md`
  claim of *bare* keys (`entrustment`, `time_mgmt`) is wrong for these cohorts — only 8 legacy
  forms in the whole year use it. Do not add a bare-key fallback.
- **The item-code entries sit at the TOP LEVEL of `assessor_data`** alongside the five standard
  buckets, because the separation layer merges a flattened `{item_code: {MCk: "<key>"}}` copy on
  top. Any `jsonb_each(assessor_data)` that harvests item codes must therefore exclude
  `radio / texts / scales / checklists / multi-select` **and** `scale-%`.

### 2.2 `form_context` carries no `role` for DDS2 sim

```json
{ "checklists": [{"code": "Paeds 2026-Week-1", "quantity": 1}],
  "clinic_type": "PA", "teeth_quadrant": "54, 55" }
```

No `role` key → `role` is NULL for these forms. There is essentially one form per assessment
(3,583 forms / 3,546 assessments), so the OB/SO observer-role gate used by the cohort reports is
not relevant here and no role filter was added.

### 2.3 The date column is a Melbourne-midnight timestamp — **this is a real trap**

Every DDS2 sim `datetimeutc` is exactly `13:00Z` (AEDT months) or `14:00Z` (AEST months), i.e.
local midnight:

| stored `datetimeutc` | `::date` under Australia/Melbourne | `::date` under UTC |
|---|---|---|
| `2026-02-01 13:00+00` | **2026-02-02** ✅ (workbook name) | 2026-02-01 ❌ |
| `2026-07-14 14:00+00` | **2026-07-15** ✅ | 2026-07-14 ❌ |

Cross-checked against `Config.xlsx`, which records *"DENT90148 On 15/07/2026 there was technical
problems leading to AM session being not complete"* — and `2026-07-14 14:00Z` is the only partial
day in the data (57 forms instead of ~105). Confirms the Melbourne reading.

**Therefore: every weekly-sim query must use the identical `datetimeutc::date` expression, and the
Postgres session `TimeZone` must be `Australia/Melbourne`.** If the session TZ ever changes, every
workbook silently shifts one day. This is why date discovery and data extraction now share one
WHERE-clause builder rather than each writing their own comparison.

### 2.4 Checklist families and the key-format mess

Item codes used by DDS2 Simulation in 2026 (counts are forms):

| Family | Codes seen | Where |
|---|---|---|
| sem 1 | `2026-Week-1` … `2026-Week-3` (unpadded), `2026-Week-02` … `2026-Week-15` (padded) | Mondays |
| sem 2 Mon | `Paeds 2026-Week-1` (**space**), `Paeds-2026-Week-2/3/4` (**hyphen**), `Paeds 2026-Week-5` (**space again**) | Mondays |
| sem 2 Tue | `FP-Week-01` … `FP-Week-07` | Tuesdays |
| sem 2 Wed | `Week-01` … `Week-08` | Wednesdays |
| non-week | `positioning`, `DDS2-MAR-31`, `19-Jan-SIM` | January test forms |

The Paeds family alternates between a space and a hyphen after `Paeds`, and the week number is
sometimes unpadded. Left alone, one checklist splits into up to three distinct keys in every pivot
and sorts `Week-10` before `Week-2`. `standardizeWeekFormat` was generalised to fix both (§3.3).

---

## 3. Implementation

All new code lives in the `# DDS2 Weekly Sim` section of `general_utils.py`
(after `insertOsceRows`, before `# ------ Weekly Analysis utilities`).

### 3.1 New module constants

```python
DDS2_SEMESTER_SPLIT_DATE = "2026-06-15"   # sem1 | sem2 boundary; default minDate everywhere

WEEKLY_SIM_SCORE_MAP = {"O1":1.00,"O2":0.80,"O3":0.60,"O4":0.40,"O5":0.00,"Yes":1.00,"No":0.00}
```

`WEEKLY_SIM_SCORE_MAP` deliberately mirrors the `CASE it.value WHEN 'O1' THEN 1.00 …` expression
inside `getWeeklySimDataSqlDDS2`, so the python-side MC columns and the SQL-side
`Assessor Score` / `Student Score` can never drift apart. The notebook's global `scoreMap` is no
longer required by the builder (it is still accepted via the `scoreMap=` parameter).

### 3.2 `createwhereStatementDDS2` — now range-capable

```python
def createwhereStatementDDS2(prefix, date=None, minDate=None, maxDate=None,
                             cohort="DDS2", type_="Simulation"): ...
```

Emits, e.g.:

```sql
-- createwhereStatementDDS2('f', '2026-08-10')
where f.datetimeutc::date = DATE '2026-08-10'
and f.cohort = 'DDS2' and f.submitted_by_assessor and f.type = 'Simulation'

-- createwhereStatementDDS2('f', None, '2026-06-15', None)
where f.cohort = 'DDS2' and f.submitted_by_assessor and f.type = 'Simulation'
and f.datetimeutc::date >= DATE '2026-06-15'
```

Backwards compatible in effect — the previous signature `('f', date)` produces the same clause set
— but note `date` is now **keyword-optional and defaults to `None`** instead of `'2026-04-13'`.
Nothing outside `general_utils.py` calls it (checked repo-wide).

### 3.3 `standardizeWeekFormat` — generalised

```python
_WEEK_KEY_RE = re.compile(r'^(?P<prefix>.*?)[-\s]*Week[-\s]*(?P<num>\d{1,2})$', re.IGNORECASE)

def standardizeWeekFormat(itemCode):
    if not isinstance(itemCode, str): return itemCode
    m = _WEEK_KEY_RE.match(itemCode.strip())
    if not m: return itemCode
    prefix = re.sub(r'[\s-]+', '-', m.group('prefix').strip()).strip('-')
    num = m.group('num').zfill(2)
    return f"{prefix}-Week-{num}" if prefix else f"Week-{num}"
```

| input | old output | new output |
|---|---|---|
| `2026-Week-1` | `2026-Week-01` | `2026-Week-01` |
| `2026-Week-15` | `2026-Week-15` | `2026-Week-15` |
| `Week-1` | `Week-1` ❌ | `Week-01` |
| `FP-Week-3` | `FP-Week-3` ❌ | `FP-Week-03` |
| `Paeds 2026-Week-1` | `Paeds 2026-Week-1` ❌ | `Paeds-2026-Week-01` |
| `Paeds-2026-Week-2` | `Paeds-2026-Week-2` ❌ | `Paeds-2026-Week-02` |
| `positioning` / `DDS2-MAR-31` / `19-Jan-SIM` | unchanged | unchanged |

**This function is shared with `getChecklistBank`** (`df["week_key"] = df["week_key"].apply(...)`),
which is the point: the checklist *bank* and the checklist *data* are normalised by the same rule,
so a join on the key cannot half-match. Existing sem-1 outputs are unaffected — every sem-1 code
already round-trips to the same value.

Also added: `_sortMcColumns` so MC columns come out `MC1, MC2, … MC10, MC25` rather than lexically.

### 3.4 `getGlobalRatingSqlDDS2(date, minDate=None, maxDate=None)`

Now uses the shared WHERE builder and qualifies the lateral alias (`k.key`). Passing
`date=None, minDate=DDS2_SEMESTER_SPLIT_DATE` gives a whole-semester GR distribution.

### 3.5 `getWeeklySimDatesSqlDDS2(...)` — the date-discovery query

```sql
WITH forms AS (
    SELECT f.form_code, f.assessmentid, f.student_number,
           f.datetimeutc::date AS date, f.assessor_data
    FROM rawform_forms_v3 f
    where f.cohort = 'DDS2' and f.submitted_by_assessor and f.type = 'Simulation'
    and f.datetimeutc::date >= DATE '2026-06-15'
),
weekkeys AS (                       -- item codes actually used that day
    SELECT DISTINCT b.date, ck.ckey AS item_code
    FROM forms b
    CROSS JOIN LATERAL jsonb_each(COALESCE(b.assessor_data,'{}'::jsonb)) ck(ckey, cval)
    WHERE NOT ck.ckey LIKE 'scale-%%'
      AND ck.ckey NOT IN ('radio','texts','scales','checklists','multi-select')
      AND jsonb_typeof(ck.cval) = 'object'
      AND NOT (ck.cval ? 'scale')
)
SELECT b.date,
       COUNT(*)                         AS n_forms,
       COUNT(DISTINCT b.student_number) AS n_students,
       (SELECT string_agg(k.item_code, ', ' ORDER BY k.item_code)
          FROM weekkeys k WHERE k.date = b.date) AS week_keys
FROM forms b GROUP BY b.date ORDER BY b.date
```

The bucket-exclusion predicate is copied verbatim from the two checklist CTEs in
`getWeeklySimDataSqlDDS2` so discovery and extraction agree on what counts as an item code.
The CTE is named `weekkeys`, not `keys`, to stay clear of anything reserved-ish.

### 3.6 Public API

```python
getWeeklySimDatesDDS2(engine, minDate=DDS2_SEMESTER_SPLIT_DATE, maxDate=None,
                      cohort="DDS2", type_="Simulation", minForms=1) -> DataFrame
#   date (str 'YYYY-MM-DD') | n_forms | n_students | week_keys (normalised, comma-joined)

buildWeeklySimWorkbookDDS2(engine, date, folder="DDS2/Weekly Sim", scoreMap=None,
                           fileTemplate="dds2 {date} assessment_data.xlsx",
                           blrFilter="BLR", sheet1Name="Sheet1", chartSheetName="Charts",
                           returnDf=False) -> path | (path, DataFrame) | None

buildWeeklySimReportsDDS2(engine, folder="DDS2/Weekly Sim", dates=None,
                          minDate=DDS2_SEMESTER_SPLIT_DATE, maxDate=None,
                          skipExisting=True, minForms=1, dryRun=False,
                          scoreMap=None, fileTemplate="dds2 {date} assessment_data.xlsx",
                          blrFilter="BLR", cohort="DDS2", type_="Simulation") -> DataFrame
```

`buildWeeklySimWorkbookDDS2` is the old notebook `createDateReport`, lifted out unchanged in
behaviour except for the added week-key normalisation and numeric MC ordering. It still writes
`Sheet1`, autofits, then calls `addAssessmentChartsDDS2(...)` to add the three-chart `Charts` sheet.

`buildWeeklySimReportsDDS2` returns a summary frame
`date | n_forms | n_students | week_keys | status | path`, where `status` is one of:

| status | meaning |
|---|---|
| `built` | workbook written |
| `skipped-exists` | file already on disk and `skipExisting=True` |
| `skipped-low-volume` | fewer than `minForms` forms that day |
| `skipped-out-of-range` | explicit date outside `minDate`/`maxDate` |
| `no-rows` | date has forms but no checklist rows (comments-only day) |
| `planned` | `dryRun=True` |
| `error: <Type>: <msg>` | that date failed; the batch continued |

Design decisions worth knowing:

- **A failing date does not abort the batch.** Each build is wrapped; the error text lands in the
  summary row so a 20-date run still produces 19 workbooks.
- **An explicit `dates=[...]` list is still filtered by `minDate`/`maxDate`.** This is deliberate —
  it is the guard that stops a stray semester-1 date being rebuilt by a typo. Pass `minDate=None`
  to disable it.
- **Counts come from discovery even when `dates` is explicit**, so the summary always carries
  `n_forms` / `week_keys` and can classify `no-rows` without a wasted extraction query.
- `skipExisting=True` is the default because the intended weekly usage is "re-run the cell, build
  only what is new".

### 3.7 `main.ipynb` — cells 36 and 37 rewritten

Cell 36 now lists the dates and then shows the GR distribution for the most recent one:

```python
folder = 'DDS2/Weekly Sim'
datesDf = getWeeklySimDatesDDS2(engine, minDate=DDS2_SEMESTER_SPLIT_DATE)
display(datesDf)

date = datesDf["date"].iloc[-1] if not datesDf.empty else '2026-02-02'
ratingDist = readDf(engine, getGlobalRatingSqlDDS2(date))
display(ratingDist)
print(f"Total assessments with global rating on {date}: {ratingDist['n'].sum()}")
```

Cell 37 replaces the commented per-date list entirely:

```python
DRY_RUN = False

summary = buildWeeklySimReportsDDS2(
    engine, folder=folder,
    minDate=DDS2_SEMESTER_SPLIT_DATE,   # inclusive; None = no lower bound
    maxDate=None,                       # inclusive; e.g. '2026-06-14' for sem 1
    skipExisting=True,
    minForms=20,
    dryRun=DRY_RUN,
)
display(summary)
```

with commented recipes below it for an explicit date list, a forced rebuild, a semester-1 rebuild,
and a single workbook with the DataFrame returned.

---

## 4. Recipes

```python
# every new semester-2 date, real sessions only
buildWeeklySimReportsDDS2(engine, folder='DDS2/Weekly Sim', minForms=20)

# preview first, write nothing
buildWeeklySimReportsDDS2(engine, folder='DDS2/Weekly Sim', dryRun=True)

# just these three days
buildWeeklySimReportsDDS2(engine, folder='DDS2/Weekly Sim',
                          dates=['2026-08-03', '2026-08-04', '2026-08-05'])

# force one date to rebuild
buildWeeklySimReportsDDS2(engine, folder='DDS2/Weekly Sim',
                          dates=['2026-08-10'], skipExisting=False)

# semester 1 (into a separate folder if you want them side by side)
buildWeeklySimReportsDDS2(engine, folder='DDS2/Weekly Sim Sem1',
                          minDate=None, maxDate='2026-06-14', minForms=20)

# one workbook + the frame for ad-hoc work
path, dataDf = buildWeeklySimWorkbookDDS2(engine, '2026-08-10',
                                          folder='DDS2/Weekly Sim', returnDf=True)

# whole-semester global rating distribution
readDf(engine, getGlobalRatingSqlDDS2(date=None, minDate=DDS2_SEMESTER_SPLIT_DATE))
```

Downstream analyses, per half year and with item codes excluded (§7):

```python
# all three set once in the DDS2 Weekly config cell (36)
PERIOD         = 'SHY'          # 'FHY' | 'SHY' | 'ALL'
IGNORE_CODES   = ['2026-Week-*', 'positioning']
MIN_ITEM_COUNT = 5              # 0 = off

runBlrAnalysisForAllFiles(folderPath=folder, borderlineGr=2, period=PERIOD,
                          ignoreCodeList=IGNORE_CODES, minItemCount=MIN_ITEM_COUNT)
exportCombinedNotebook(folder_path=folder, out_path=..., period=PERIOD,
                       ignore_code_list=IGNORE_CODES, min_item_count=MIN_ITEM_COUNT)
generate(periodSuffixPath(combined, PERIOD), periodSuffixPath(risk, PERIOD), cohort="DDS2")

# an arbitrary window instead of a half year
runBlrAnalysisForAllFiles(folderPath=folder, minDate='2026-07-01', maxDate='2026-07-31')

# what would be dropped, without running anything
loadWeeklyFiles(folder, period='SHY', ignoreCodeList=['2026-Week-*'], minItemCount=5)
```

Per stream (§6b):

```python
# build every stream into its own subfolder; each stream's own dates apply
buildWeeklySimReportsDDS2(engine, folder=folder, stream='ALL', minDate=None, minForms=1)

# just Endodontics
buildWeeklySimReportsDDS2(engine, folder=folder, stream='ENDO', minDate=None, minForms=1)

# what the DB holds for one stream, with off-weekday catch-ups flagged
getWeeklySimDatesDDS2(engine, minDate=None, stream='PAEDS')

# which forms have the wrong subject code
getSubjectMismatchesDDS2(engine, minDate=DDS2_SEMESTER_SPLIT_DATE)

# analyses: one folder per stream in, collision-free path out
runBlrAnalysisForAllFiles(folderPath=weeklySimFolders(folder, 'FP'), borderlineGr=2)
exportCombinedNotebook(folder_path=weeklySimFolders(folder, 'ALL'),
                       out_path=weeklySimOutPath(folder, "dds2 combined scores and ratings.xlsx", 'ALL'))
```

BOH2 weekly sheets, styled, 1-5 MC, last-name order (§6d.6):

```python
buildWeeklySimReports(engine, folder=weeklySimBaseFolder('BOH2'), cohort='BOH2', stream='SHY',
                      minDate=None, mcScale='1-5', roster=loadRoster('BOH2'), styleSheet=True)

# same but keep the historical 0-1 MC values and no styling
buildWeeklySimReports(engine, folder=..., cohort='BOH2', stream='SHY', minDate=None)

# does the DB agree with the published session schedule?
compareSessionsToSchedule(getWeeklySimDates(engine, cohort='BOH2', stream='SHY', minDate=None),
                          loadSessionSchedule('BOH2'))

# wrong subject codes — date-routed cohorts now answer this correctly
getSubjectMismatches(engine, cohort='BOH2')

# --- sheet layout (§6e) ---------------------------------------------------
# rebuild ONE stream with the new column layout (the default since 18 Aug 2026)
buildWeeklySimReports(engine, folder=folder, cohort=COHORT, stream='PAEDS',
                      minDate=None, skipExisting=False)

# build with the pre-18-Aug layout instead
buildWeeklySimReports(engine, folder=folder, cohort=COHORT, stream='PAEDS',
                      minDate=None, dropCols=[], labels={}, mcBefore=False)

# keep student_email this once, and drop subject as well
buildWeeklySimReports(engine, folder=folder, cohort=COHORT,
                      dropCols=['date', 'assessmentid', 'form_code', 'subject'])

# what would the sheet look like? (no DB write, no file)
formatWeeklySheet(someWeeklyFrame).columns.tolist()

# --- attendance (§6f) ------------------------------------------------------
# default: greyed absentee rows (needs a roster) + amber duplicates + Session Summary
buildWeeklySimReports(engine, folder=folder, cohort='BOH2', stream='SHY', minDate=None,
                      skipExisting=False, roster=loadRoster('BOH2'))

# bring back the per-row Forms column (§6f.8)
buildWeeklySimReports(engine, folder=folder, cohort=COHORT, addForms=True)

# no absentee rows even if a roster is passed
buildWeeklySimReports(engine, folder=folder, cohort=COHORT, addAbsent=False)

# none of it: byte-identical to the §6e-only sheet
buildWeeklySimReports(engine, folder=folder, cohort=COHORT,
                      addAbsent=False, summarySheet=False)

# who missed which session, without building anything
for date in getWeeklySimDates(engine, cohort='BOH2', stream='SHY', minDate=None)['date']:
    _, df = buildWeeklySimWorkbook(engine, date, cohort='BOH2', stream='SHY',
                                   folder=weeklySimFolder(folder, 'SHY', cohort='BOH2'),
                                   roster=loadRoster('BOH2'), returnDf=True)
    print(date, df.loc[df['Item Code'].isna(), 'Student Name'].tolist())
```

---

## 5. What the discovery query returns today (12 Aug 2026)

Semester 2, `minDate='2026-06-15'` — 20 dates:

```
      date  n_forms  n_students  week_keys
2026-06-30      105         103  FP-Week-01, FP-Week-03, Week-01
2026-07-01      104         104  Week-01
2026-07-07      108         106  FP-Week-02, Week-02
2026-07-08      102         102  Week-02
2026-07-13      107         106  FP-Week-03, Paeds-2026-Week-01
2026-07-14      105         105  FP-Week-02, FP-Week-03, FP-Week-04
2026-07-15       52          52  Week-02, Week-03        <- the 15/07 technical-problem AM session
2026-07-17       13           7  2026-Week-08, 2026-Week-15   <- sem-1 catch-ups
2026-07-20      107         106  FP-Week-04, Paeds-2026-Week-02
2026-07-21      105         105  FP-Week-03, FP-Week-04
2026-07-22      106         106  Week-04
2026-07-27      107         106  2026-Week-03, FP-Week-05, Paeds-2026-Week-03
2026-07-28      103         103  FP-Week-04, FP-Week-05
2026-07-29      106         106  Week-05, Week-08
2026-08-03      105         104  Paeds-2026-Week-04, Paeds-2026-Week-05
2026-08-04      106         106  FP-Week-05, FP-Week-06
2026-08-05      103         103  Week-03, Week-06
2026-08-10      106         105  2026-Week-06, FP-Week-07, Paeds-2026-Week-05
2026-08-11      104         104  FP-Week-06, FP-Week-07
2026-08-12        5           5  Week-07                 <- today, session in progress
```

Note the Mon/Tue/Wed rhythm, and that a handful of students each week are catching up on a
different week's checklist — hence `week_keys` listing more than one family per date.
With `minForms=20`, 2026-07-17 (13 forms) and 2026-08-12 (5 forms, in progress) are skipped.

Semester 1 (`minDate=None, maxDate='2026-06-14'`) returns the 15 known Mondays plus five junk
dates: 2026-01-12 / 01-19 (2 forms, `positioning` + `DDS2-MAR-31` / `19-Jan-SIM` test forms),
2026-01-29 and 2026-03-17 (1-2 forms, **no checklist at all** → `week_keys` NULL → `no-rows`),
and 2026-01-30 (2 forms). All excluded by `minForms=20`.

---

## 6. Workbook layout

> **Changed 18 Aug 2026 — see §6e.** The block below is the *current* layout. The original is
> kept underneath because every workbook built before 18 Aug still has that shape, and both
> load correctly through `loadWeeklyFiles`.

`Sheet1`, one row per (form × item code):

```
Student Number | [Last Name | First Name] | Student Name | Assessor Name | Subject |
Item Code | GR | TS | CS | PS | PR | PEC | MC1 … MCn | Assessor Score | Student Score |
Clinical Incident | Assessor Reflection | Student Reflection
```

`Last Name` / `First Name` appear only when the build was given a `roster=` (§6d.5). The blank,
greyed absentee rows come from the attendance layer (§6f) and switch off with `addAbsent=False`;
`addForms=True` adds a per-row `Forms` column that is off by default (§6f.8).

Sheets in the workbook: `Sheet1 | Session Summary | Charts` (§6f.4).

Original layout, up to and including 17 Aug 2026:

```
student_number | student_name | student_email | assessor_name | subject | item_code | date |
GR | TS | CS | PS | PR | PEC | Assessor Score | Student Score |
clinical_incident | assessor_reflection | student_reflection | assessmentid | form_code |
MC1 … MCn
```

`GR/TS/CS/PS/PR/PEC` = global-rating / time-management / communication / professionalism /
practice-readiness / position-ergonomics, each the integer `->>'key'` of the matching
`scale-*` entry. `Assessor Score` / `Student Score` are the mean of the O-code→0..1 mapping across
that item's MCs, rounded to 2dp, computed in SQL. MC columns are the same mapping per item.

`Charts` sheet (from the untouched `addAssessmentChartsDDS2`): (1) Student vs Assessor scatter with
a dashed y=x reference line, (2) GR distribution bar with value labels, (3) Assessor Score vs GR
scatter with a linear trendline showing equation and R².

---

## 6b. Streams — three parallel subjects from semester 2

### 6b.1 What actually runs

From semester 2 DDS2 sim is not one weekly session but **three parallel subjects, one per
weekday**, each with its own checklist family:

| Stream | Subject | Day | From | Checklist codes | Folder |
|---|---|---|---|---|---|
| `PAEDS` | Paediatric Dentistry Sim, DENT90146 | Mon | 13 Jul 2026 | `Paeds 2026-Week-1`, `Paeds-2026-Week-2…7` | `Weekly Sim/Paediatrics` |
| `FP` | Fixed Prosthodontics Sim, DENT90148 | Tue | 30 Jun 2026 | `FP-Week-01…15` | `Weekly Sim/Fixed Prosthodontics` |
| `ENDO` | Endodontics Sim, DENT90148 | Wed | 30 Jun 2026 | `Week-01…15` (no `Week-11`) | `Weekly Sim/Endodontics` |
| `SEM1` | Semester 1 Sim, DENT90146 | Mon | — | `2026-Week-01…15` | `Weekly Sim` (base, unchanged) |

Note FP and Endo **share a subject code** (DENT90148), so subject alone cannot separate them
even when it is correct.

### 6b.2 Classification is by item code, never by subject

Students choose the subject themselves and get it wrong often. Measured on the 2026 data,
**76 of 1,859 semester-2 forms carry the wrong subject** (95 across the whole year):

```
stream   subject     expected     n
ENDO     DENT90146   DENT90148   16
FP       DENT90146   DENT90148   37
PAEDS    DENT90148   DENT90146   23
SEM1     DENT90115   DENT90146    8      <- an entirely unrelated subject code
SEM1     DENT90148   DENT90146    3
(none)   DENT90115   —            4      <- item code belongs to no stream
(none)   DENT90146   —            4
```

The **item code** is reliable, because it comes from the checklist the assessor actually
opened, and it agrees with the weekday almost perfectly:

```
stream   Mon  Tue  Wed  Fri
PAEDS    526    0    0    0
FP         4  733    0    0
ENDO       0    3  578    0
SEM1       2    0    0   13
```

The handful of off-weekday rows are catch-ups, not misclassifications. So: **route on item
code, record subject and weekday for reporting only.**

`codePatterns` are fnmatch globs matched as **full** matches, which is exactly what keeps
the families disjoint — `Week-*` matches `Week-01` but not `FP-Week-01` or
`Paeds-2026-Week-01`. That property is doing real work here; a substring match would put
every stream in ENDO.

### 6b.3 API

```python
DDS2_SIM_STREAMS                      # the registry above: name, folder, subject, weekday,
                                      # startDate, endDate, codePatterns
resolveStreams(stream) -> [(key,cfg)] # 'ALL' | 'PAEDS' | ['FP','ENDO'] | 'Endodontics Sim'
streamForItemCode(code) -> key|None
weeklySimFolder(base, key)            # one stream's folder ('' -> the base folder)
weeklySimFolders(base, stream)        # LIST of folders — a pooled read spans subfolders
weeklySimOutFolder(base, stream)      # where a scoped analysis writes
weeklySimOutPath(base, filename, stream, period)   # collision-free full output path
getSubjectMismatchesDDS2(engine, …)   # the report above, as a DataFrame
```

`loadWeeklyFiles` now accepts **a list of folders** as well as one, concatenating workbooks
that share a date — that is what makes a pooled all-streams combined report possible
without moving a single file.

### 6b.4 Building

```python
buildWeeklySimReportsDDS2(engine, folder, stream='ALL', minDate=None, minForms=1)
```

- `stream=None` — the original unsplit behaviour, one workbook per date in the base folder.
- `stream='ALL'` — every stream into its own subfolder.
- `stream='PAEDS'` / `['FP','ENDO']` — just those.
- `useStreamDates=True` (default) intersects each stream's own `startDate`/`endDate` with
  `minDate`/`maxDate`, so `stream='ALL'` needs no dates at all.

Each stream's workbook contains **only its own item codes** (the SQL carries an `ILIKE`
filter built from `codePatterns`), so a catch-up FP form filled on a Paeds Monday is written
into `Fixed Prosthodontics/dds2 2026-07-13 assessment_data.xlsx` — its real date, its real
stream. Every form is counted exactly once. Those days are flagged `*off-day` in the build
log, and `getWeeklySimDatesDDS2` returns an `offWeekday` column for a single-stream query.

**`minForms` should be 1 for a split build** (the notebook default). Within a stream a
one-form day *is* a real catch-up, not junk — the junk codes (`positioning`, `DDS2-MAR-31`,
`19-Jan-SIM`) belong to no stream and are excluded automatically. A split run prints what it
left behind:

```
NOTE: 3 item code(s) belong to no stream and were not built: 19-Jan-SIM, DDS2-MAR-31, positioning
```

`SEM1` deliberately has **no `endDate`**: students still complete semester-1 checklists as
catch-ups during semester 2 (15 forms by 12 Aug), and that work belongs to the semester-1
record rather than to whichever stream owned the day. Set an `endDate` in the registry if you
ever want semester 1 frozen.

Also added: a `subject` column in every workbook, and a `minRows` guard (default 3) on
`runBlrAnalysisForAllFiles`, because the split creates genuine 1–2 form days and scipy
returns an all-NaN regression row for those rather than failing — saying so is better.

### 6b.5 What gets produced

`STREAM = 'ALL'`, `POOLED = True` on the real data gives 44 workbooks and 15 analysis files:

```
Weekly Sim/                              16 workbooks (semester 1)   + combined / BLR / risk
Weekly Sim/Paediatrics/                   5 workbooks                + combined / BLR / risk
Weekly Sim/Fixed Prosthodontics/         11 workbooks                + combined / BLR / risk
Weekly Sim/Endodontics/                   9 workbooks                + combined / BLR / risk
Weekly Sim/…(All streams).xlsx           pooled combined / BLR / risk
Weekly Sim/DDS2 subject code mismatches.xlsx
```

The `(All streams)` suffix is **not cosmetic**: semester 1's folder *is* the base folder, so
without it the pooled combined workbook silently overwrites the semester-1 one. That bug was
caught during verification; `weeklySimOutPath` is what prevents it.

Per-stream flagging is far more informative than the pooled view:

| scope | dates | item codes | students | Fail | risk High/Mod/Watch/OK |
|---|---|---|---|---|---|
| SEM1 | 16 | 15 | 107 | 44 | 8 / 19 / 29 / 51 |
| PAEDS | 5 | 5 | 106 | 4 | 19 / 56 / 31 / 0 |
| FP | 11 | 7 | 106 | 11 | 7 / 38 / 30 / 31 |
| ENDO | 9 | 8 | 106 | 11 | 50 / 41 / 15 / 0 |
| pooled | 35 | 35 | 107 | 81 | 20 / 78 / 9 / 0 |

Endodontics is visibly the harshest-scored stream and Paeds the least discriminating — a
distinction the pooled number cannot show. As with periods, **risk bands are comparable only
within a scope**, since they are computed relative to that scope's own thresholds.

### 6b.6 Notebook wiring

Cell 36 sets `STREAM` and `POOLED` alongside `folder`, `PERIOD`, `IGNORE_CODES`,
`MIN_ITEM_COUNT`, then prints a per-stream date table. Cell 37 builds and writes the subject
mismatch report. Cells 39/40/41 loop `resolveStreams(STREAM)` and, when `POOLED` and more
than one stream is selected, add a pooled run. `exportCombinedNotebook` also emits a
`subject_mismatches` sheet when the workbooks carry `subject`.

---

---

## 6c. Flagging — the BLR bug, three methods, and the styled workbook

### 6c.1 BLR was flagging nobody (fixed)

`_flag_by_blr` built its cutoffs keyed by **date**, taken from the workbook filename, while
`exportCombinedNotebook` pivots the wide score table on **item code** (`pivotCol = ITEM_CODE_COL`).
The `reindex(date_cols)` therefore never matched a single key, every threshold came out `NaN`,
and `_count_low` returned 0 for every student. Demonstrated on a two-code corpus:

```
method=percentile   thresholds: {'W-01': 0.407, 'W-02': 0.3755}   Fail: 8/40
method=blr          thresholds: {'W-01': nan,   'W-02': nan}      Fail: 0/40
```

Percentile was unaffected because its thresholds come from the pivoted columns directly.
This was live at the point the user switched to BLR, so the combined workbooks produced with
`method='blr'` before 2026-08-17 passed everybody and should be regenerated.

**Fix:** cutoffs are computed **per item code**, pooling that code's rows across every date.
That matches the pivot, and gives a code sat on several dates (catch-ups) one consistent cutoff.
Codes that cannot be fitted (fewer than 3 rows, or a single distinct GR value) are reported and
left out of the count rather than silently becoming NaN:

```
  no cutoff for 2 item code(s) (too few rows or a single GR value): Week-07, Week-08
```

### 6c.2 Three methods, all keyed per item code

| `FlagMethod` | Cutoff for an item code | Notes |
|---|---|---|
| `PERCENTILE` | the `percentile` quantile (default 0.15) of the cohort's scores for that code | purely relative — a fixed share is always below |
| `BLR` | fit `assessor_score ~ GR` over that code's forms, read the fitted score at `GR = borderline_gr` | anchored to the assessors' own global ratings |
| `BORDERLINE` *(new)* | mean `assessor_score` of the forms rated `GR = borderline_gr` for that code | classic borderline-group average; no linearity assumption, noisier when few sit on the borderline |

A student Fails when they are at or below the cutoff in at least `min_low_count` codes.
On the real Fixed Prosthodontics stream the three give genuinely different pictures:

| method | cutoffs (FP-Week-01 … 07) | Fail |
|---|---|---|
| percentile | 0.496, 0.550, 0.500, 0.580, 0.623, 0.670, … | 11 |
| blr | 0.490, 0.568, 0.518, 0.606, 0.579, 0.626, … | 5 |
| borderline | 0.440, 0.572, 0.494, 0.583, 0.581, 0.630, … | 3 |

Set them in notebook cell 36: `FLAG_METHOD`, `MIN_LOW_COUNT`, `PERCENTILE`, `BORDERLINE_GR`.

### 6c.3 Repeated item codes take the BEST attempt

`buildWideDf` pivots with `aggfunc="max"`, so a student who sits the same code twice is scored on
their better attempt — now an explicit `agg` parameter (`AGG` in cell 36) rather than a hard-coded
string, and stated on the Description sheet. Verified against the real FP data: 14 repeated
(student, code) pairs, every one of them showing the max in the workbook (e.g. student 1082382
FP-Week-04, attempts 0.48 and 0.57 → 0.57). `Avg Score` is then the mean across those best
attempts. Every repeat is still listed on the `repeated_attempts` sheet.

### 6c.4 Styling

New helpers in `general_utils.py`, using the same palette as `flagging_utils.py` so the two
families of workbook look like one system:

```python
cwFill(hex) / cwBorder()
styleHeaderRow(ws, nCols)          # navy, white bold, wrapped, centred
freezeAfter(ws, nIdCols)           # freeze header row + identity columns
fillEmptyCells(...)                # grey = not assessed
applyGrColorScale(...)             # FIXED 1-5 red -> amber -> green
highlightBelowThreshold(...)       # red at/below cutoff, optional amber margin
styleCombinedSheet(ws, df, idCols, kind, thresholds, amberMargin)
writeDescriptionSheet(wb, lines)   # inserted at position 0
```

Per sheet:

| sheet | `kind` | colouring |
|---|---|---|
| `scores` | `score` | red **only** where the value is at or below that item code's cutoff |
| `global_ratings` | `gr` | only the levels in `GR_HIGHLIGHT` (default 1 red, 2 amber) |
| `practice_readiness` | `gr` | only the levels in `PR_HIGHLIGHT` |
| `scores_flagged` | `flagged` | as `scores`, plus Pass/Fail green/red |
| others | header + freeze only | |

**GR / PR highlighting is level-based, not a gradient.** The first version put a full 1-5
red→green colour scale across every GR cell, which saturated the sheet — 848 of 848 cells
coloured, so nothing stood out. Now only the levels worth looking at are filled: on the same
sheet that is 15 red (level 1) + 81 amber (level 2) = 96 cells, and the rest are left plain.

Configured in cell 36 and fully flexible:

```python
GR_HIGHLIGHT = {1: 'red', 2: 'amber'}              # default — just the low end
GR_HIGHLIGHT = {1: 'red', 2: 'amber', 5: 'green'}  # also mark the top level
GR_HIGHLIGHT = [1, 2]                              # shorthand, all red
GR_HIGHLIGHT = 'scale'                             # the old full 1-5 gradient
GR_HIGHLIGHT = None                                # no colouring
PR_HIGHLIGHT = {1: 'red', 2: 'amber'}              # set independently
```

Colours are named (`red` / `amber` / `green` / `grey` from `CW_LEVEL_PALETTE`) or an explicit
`(bg, text)` hex pair; an unknown name raises rather than silently doing nothing. Levels are keyed
as floats so `2`, `2.0` and `'2'` all match. `resolveLevelColors` normalises the spec and
`highlightLevelCells` applies it; `applyGrColorScale` is still there for the `'scale'` option.

Two other deliberate choices. Empty cells are greyed **after** the colour work, so "not assessed"
can never be mistaken for "scored badly" — the two look different at a glance. And
`AMBER_MARGIN` (default 0) adds an amber band just above the score cutoff if wanted.

The Description sheet's colour key is generated **from the active spec** — change
`GR_HIGHLIGHT` and the workbook's own documentation follows, rather than describing a gradient
that is no longer there.

Because the low-score colouring uses the **active** method's thresholds, the red cells are
literally the ones counted in `low_count` — the sheet and the Pass/Fail column tell one story.

### 6c.5 The `assessors` sheet

A student × item-code grid filled with **assessor names**, so a student who keeps drawing the same
assessor is visible at a glance. Built by `buildAssessorPivot(longDf, idCols)`, which returns the
grid plus a `{(student, assessor): timesSeen}` map that drives the colouring.

- A repeated item code shows **both** names joined by `' | '` — a repeat is exactly where a second
  exposure to the same assessor turns up, so dropping one would defeat the point.
- Summary columns: `n_forms`, `n_assessors`, `most_seen_assessor`, `most_seen_count`.
- `highlightRepeatAssessors` colours a cell when that student has seen that assessor at least N
  times, highest matching threshold winning. Configured by `ASSESSOR_REPEAT_HIGHLIGHT` in cell 36.
- The run also prints the worst pairing, e.g. *"most repeated pairing is Ahmad Mekkawy with
  Kaitlyn Tze Ning Wong (4 forms)"*.

**Pick the threshold deliberately — the default is loud.** With 7 FP codes and ~4 assessors each,
seeing an assessor twice is routine, so `{2: 'amber', 3: 'red'}` colours **49%** of the grid:

| setting | cells coloured (of 742) |
|---|---|
| `{2: 'amber', 3: 'red'}` (default) | 361 — 49% (291 amber, 70 red) |
| `{3: 'red'}` | 70 — 9% |
| `None` | 0 — summary columns only |

Note `None` genuinely means off. The first cut had `levelColors=None` fall back to the default
inside the function, so passing None silently kept the colouring; the default now lives in the
signature instead. Same shape of bug as any "None means unset" fallback — worth remembering.

`buildWideDf`'s default `extraCols` is now `("subject", "assessor_name")` so the long frame carries
the assessor through; a workbook without the column just skips the sheet.

### 6c.6 Description sheet

Every combined workbook now opens on a `Description` sheet covering: scope and source folders,
period and dates, item codes and student count, generation time; the flagging method with its
plain-English definition, cutoff granularity, the actual cutoffs used, how many codes had none,
and the resulting Fail count; the repeat-attempt rule, `Avg Score`, the 0-1 score scale with the
O-code mapping, what GR and PR are, and the ignore/min-count filters; the colour key; and a
one-line description of every sheet.

### 6c.7 `repeated_attempts` crashed a whole build when a stream had no repeats

`printDuplicateItemStudents` ended with a bare `return` when no student had sat the same item
code twice, handing back `None`; `exportCombinedNotebook` then called `duplicates.to_excel(...)`
and the run died with `AttributeError: 'NoneType' object has no attribute 'to_excel'`. It takes
down the scope it hits **and every scope after it** in the loop, and leaves a truncated `.xlsx`
behind because the `ExcelWriter` context exits mid-write.

Scope-dependent, so it lay hidden: a stream simply may have no repeats, and `MIN_ITEM_COUNT`
makes it likelier by dropping exactly the low-count catch-up codes the repeats live on. Fixed at
source — the function now always returns a DataFrame (empty when there are no repeats), so the
sheet is just written empty. The other bare `return`s in `general_utils` were checked: all in
void styling helpers whose return value is never used.

### 6c.8 `import *` skips underscore names

`describeLevelColors` and `describeRepeatColors` were first written as `_describe…`. The notebook
does `from general_utils import *`, which **does not import names beginning with an underscore**,
so cell 40 died with `NameError: name '_describeLevelColors' is not defined` — at workbook-write
time, after all the analysis had already run. Both are public now, with a docstring saying why.

The rule for this codebase: **anything a notebook cell calls must not start with an underscore.**
Checked repo-wide — no other private `general_utils` helper is called from a cell. A `star`-import
simulation was added to the verification pass so this class of error surfaces in testing rather
than in the notebook.

### 6c.9 One more filename bug caught

Cell 40 had been edited to put the scope label in the combined filename, but cell 41 still read
the unlabelled name — so the risk report silently skipped every stream
(`no combined workbook at … — skipped`). Scope naming now lives in **one** place in cell 36:

```python
streamScopes()                       # -> [(scope, KEY, label), …]  KEY goes in filenames
scopedPath(name, scope, key, period) # -> '<stream folder>/<name> <KEY>.xlsx' (+ period suffix)
```

Cells 39, 40 and 41 all build paths through `scopedPath`, so a writer and a reader cannot drift
again. Outputs are now `… SEM1.xlsx`, `… PAEDS.xlsx`, `… FP.xlsx`, `… ENDO.xlsx`, `… POOLED.xlsx`.

---

---

## 6d. Cohort-generic: BOH2 joins the weekly chain

### 6d.1 Verification first — is the switch viable?

BOH2 moved to weekly sim sessions in semester 2. Checked against the DB before touching
any code, and the answer is yes, cleanly. Every SHY session in the data is a **Tuesday**
carrying **exactly one checklist**, and the DASH item codes ARE the task names from the
schedule:

```
2026-06-30 Tue n=44  36MO (532) x28, 41MIBL (524 578) x12  (+4 FHY strays)   <- choice week
2026-07-07 Tue n=49  14MODB (534 577) (preparation)
2026-07-14 Tue n=48  14MODB (534 577) (restoration)
2026-07-21 Tue n=48  16MODB (534 577)
2026-07-28 Tue n=49  26O (531) & 64DO 65MO (532)
2026-08-04 Tue n=49  51B DP (525)
2026-08-11 Tue n=49  85 (587) & 75O (414 531)
```

Cross-checked against the supplied schedule: **7 matched, 9 missing (all future dates),
1 unplanned** (a stray single form on Wed 2026-06-24). Three discrepancies worth recording:

- **Jackie Tran's student number is transposed.** The supplied roster says `1745117`;
  DASH has `1475117`. A join on student number would have silently dropped her. The
  roster file uses the DASH value and keeps the supplied one in `supplied_student_number`.
- `1234567 Test1 Student1` appears in BOH2 sim data and is not on the roster. The existing
  `excludeNames` doesn't catch "Test1 Student1".
- **The choice weeks are 27 and 38, not 30 and 38** — the covering note said 30, but the
  schedule table and the data both say Week 27 (30 June). Week 30 is a normal single week.

Also worth knowing: `fetched_rows 2026 caf.xlsx` **truncates** 3 BOH2 rows, because a
`forms` JSON blob exceeds Excel's 32,767-character cell limit. Fine for analysis at this
scale, but that pull is not a faithful mirror of the DB — go to Postgres for anything exact.

### 6d.2 Two ways to define a stream

`DDS2_SIM_STREAMS` became `SIM_STREAMS`, **keyed by cohort**, and a stream may now route
either way:

| `codePatterns` | routing | used by |
|---|---|---|
| `[...]` globs | by ITEM CODE | DDS2 — three subjects share a day-space, so a catch-up on any weekday must be attributable |
| `None` | by DATE RANGE alone | BOH2 — one weekly session whose code is a free-text task name, so there is no pattern to match and nothing to disambiguate |

```python
SIM_STREAMS["BOH2"] = {
  "FHY": {..., "weekday": "Tue", "startDate": None,         "endDate": "2026-06-14", "codePatterns": None},
  "SHY": {..., "weekday": "Tue", "startDate": "2026-06-15", "endDate": None,         "codePatterns": None,
          "folder": "Weekly SHY"},
}
```

`_streamCodeSqlFilter` returns `TRUE` for a date-range stream, and the unclassified-code
check is skipped for cohorts that have no pattern-routed stream at all (there is no such
thing as an orphan code when nothing routes on codes).

### 6d.3 Renames, with aliases

Cohort-neutral names, plus thin aliases so nothing already written breaks:

```
createwhereStatementDDS2 -> createWeeklySimWhere      getWeeklySimDatesDDS2      -> getWeeklySimDates
getGlobalRatingSqlDDS2   -> getGlobalRatingSql        getSubjectMismatchesDDS2   -> getSubjectMismatches
getWeeklySimDatesSqlDDS2 -> getWeeklySimDatesSql      buildWeeklySimWorkbookDDS2 -> buildWeeklySimWorkbook
getWeeklySimDataSqlDDS2  -> getWeeklySimDataSql       buildWeeklySimReportsDDS2  -> buildWeeklySimReports
addAssessmentChartsDDS2  -> addAssessmentCharts       DDS2_SEMESTER_SPLIT_DATE   -> SEMESTER_SPLIT_DATE
```

New: `cohortStreams(cohort)`, `weeklySimBaseFolder(cohort)` → `'<COHORT>/Weekly Sim'`,
`weeklySimFileTemplate(cohort)` → `'boh2 {date} assessment_data.xlsx'`. Every folder,
filename and SQL where-clause now derives from `COHORT`, set once at the top of cell 36.

**A trap worth recording:** `getWeeklySimDataSql` builds three CTEs, each with its own
where-clause. Threading `cohort` into only one of them produced a query that found dates
but returned zero rows — the `base` CTE was still filtering `cohort = 'DDS2'`. When a
generated query has repeated boilerplate, change all of it or none.

### 6d.4 Reference data: sessions and roster

Excel in the cohort folder, so staff can edit without touching code:

```
BOH2/BOH2 Sim Sessions 2026.xlsx    week_no, date, weekday, task, is_choice_week,
                                    choice_options, counts_toward_total, notes
BOH2/BOH2 Roster 2026.xlsx          sort_order, student_number, first_name, last_name,
                                    status, supplied_student_number, notes
```

Loaders `loadSessionSchedule(cohort)` / `loadRoster(cohort)` return an EMPTY frame when the
file is absent — the schedule is a cross-check, not a dependency, and a cohort without one
must still run. `compareSessionsToSchedule(datesDf, schedule)` produces the
matched / missing / unplanned table in §6d.1. Choice weeks are highlighted amber in the
sessions file; the 15 counting sessions reconcile with the stated year-end target.

### 6d.5 Roster ordering, not deidentified

`applyRosterOrder(df, roster)` sorts every student sheet by **last name**, inserts
`last_name` / `first_name` after the student number, and returns both directions of
mismatch. Students in the data but not on the roster are **appended, never dropped** —
silently losing a student is worse than showing an unexpected one — and both lists go on
the Description sheet:

```
Student order        Alphabetical by LAST NAME, from the roster file.
Not on roster        Test1 Student1
On roster, no data   none
```

On the real BOH2 SHY data that gives Aktam Anjrini → Zeki with Test1 Student1 at the end,
and "no data: none" confirms all 49 roster students matched once Jackie Tran's ID was
corrected.

### 6d.6 Weekly sheets: MC scale, ordering and styling

Everything up to here concerned the *combined* workbook. The **per-date weekly sheets** got
the same treatment on 17 Aug 2026, driven off cell 36 so it can be switched off entirely.

**MC scale.** The MC columns historically carried 1.00 / 0.80 / 0.60 / 0.40 / 0.00. A 1-5
scale reads better next to GR, so both now exist:

```python
WEEKLY_MC_SCALES = {
    "0-1": {"O1":1.00, "O2":0.80, "O3":0.60, "O4":0.40, "O5":0.00, "Yes":1.00, "No":0.00},
    "1-5": {"O1":5,    "O2":4,    "O3":3,    "O4":2,    "O5":1,    "Yes":5,    "No":1},
}
resolveMcScale(scale=None) -> (scoreMap, label)   # None = 0-1, i.e. nothing changes
```

`buildWeeklySimWorkbook` / `buildWeeklySimReports` take `mcScale='1-5'`; an explicit
`scoreMap=` still wins. **These are not linear rescales of each other** — O5 is `0.00` on
0-1 but `1` on 1-5. The only thing that moves is `runBlrAnalysis`'s per-item statistics and
Cronbach's alpha, which are computed from the MC columns. Every flagging decision reads
`Assessor Score`, which comes from SQL and is always 0-1, so **Pass/Fail is identical on
either scale**. Do not mix scales inside one folder: BLR pools the workbooks it globs.

**Ordering.** `roster=loadRoster(cohort)` passed to the builders runs `applyRosterOrder`
on each weekly sheet too, so a weekly sheet is alphabetical by last name with
`last_name` / `first_name` inserted after `student_number` — the same ordering as the
combined workbook, which is the point (the sheet is read side by side with a paper list).
Unknown students are appended, never dropped.

**Styling.** `styleWeeklySheet(ws, df, grLevels=None, mcLevels=None, grCols=("GR",), freezeAfterCols=None, greyEmpty=True)`
— navy bold header, freeze panes after the last identity column present
(`WEEKLY_FREEZE_AFTER = ["student_number","last_name","first_name","student_name"]`, so
`E2` once last/first are inserted), level colouring, and grey fill on empty MC cells.
Defaults:

```python
WEEKLY_GR_HIGHLIGHT          = {1:"red", 2:"amber", 5:"green"}
WEEKLY_MC_HIGHLIGHT_BY_SCALE = {"1-5": {1:"red", 2:"amber"},
                                "0-1": {0.0:"red", 0.4:"amber"}}
```

The MC map is keyed **by scale on purpose**: `1` is the worst value on 1-5 and the best on
0-1, so a single fixed map would invert the meaning the moment the scale changed. The
builder picks the right one from the resolved scale label unless `mcLevels=` is given.
Only GR is colour-graded among the 1-5 scales — TS/CS/PS/PR/PEC are left plain, as asked;
add them to `grCols` to include them.

Notebook wiring (cell 36), all off by default so DDS2 output is unchanged:

```python
WEEKLY_MC_SCALE        = '1-5' if COHORT == 'BOH2' else None
WEEKLY_STYLE           = COHORT == 'BOH2'
WEEKLY_ORDER_BY_ROSTER = COHORT == 'BOH2'
WEEKLY_GR_LEVELS       = None      # None -> WEEKLY_GR_HIGHLIGHT
WEEKLY_MC_LEVELS       = None      # None -> the map for the active scale
```

Verified on the real BOH2 SHY data: order Aktam Anjrini → Zeki, MC distinct values
`[1,2,3,4,5]` with `Assessor Score` still 0.4–1.0, `freeze_panes = E2`, header fill
`00010D44` bold, GR column 4 red / 11 amber / 1 green, MC block 28 red / 33 amber.

### 6d.7 Subject mismatch: 337 false positives on BOH2 (fixed)

`getSubjectMismatches` classified every row with `streamForItemCode`, then flagged
`stream.isna() | subject != expected_subject`. A **date-range stream carries nothing in the
item code** — BOH2 item codes are free-text task names like `14MODB (534 577)` — so
`streamForItemCode` returned `None` for all 337 SHY forms and the report flagged the lot.

Fix: `streamForDate(date, streams=None, cohort=DEFAULT_COHORT)` resolves a stream from the
date window, narrowest window winning (a bounded stream beats a catch-all with no dates),
and `getSubjectMismatches` chooses the axis from the stream definitions:

```python
usesCodes = any(c.get("codePatterns") for c in streams.values())
if usesCodes:
    df["stream"] = df["item_code"].apply(lambda c: streamForItemCode(c, streams, cohort))
else:
    df["stream"] = df["date"].apply(lambda d: streamForDate(d, streams, cohort))
```

BOH2 SHY now reports **8 rows, all real** — `ORAL20003` filed against sessions that expect
`ORAL20005`, one per date from 30 Jun to 11 Aug. DDS2 is untouched at 76, since it has code
patterns and takes the first branch. Note the axis is chosen per *cohort*, not per stream:
a cohort mixing code-routed and date-routed streams would take the code branch and go back
to flagging the date-routed ones. Nothing does that today.

### 6d.8 What does NOT work for BOH2 yet

`risk_report.generate` selects its per-session columns by substring (`weekColKeyword`,
default `'Week'`). DDS2 codes all contain "Week"; BOH2 task names share no keyword, so the
risk report raises `No columns containing 'Week' found`. Rather than hack it, cell 41 now
skips with an explanation and `RISK_WEEK_KEYWORD` is exposed in cell 36 (`None` for BOH2).
Passing `'('` would match every BOH2 SHY task name but also drop the bare-numeric FHY codes
(522/531/532), so it is left as an experiment rather than a default. Making `risk_report`
take an explicit column list is the proper fix and is not done.

---

## 6e. Weekly-sheet presentation layer (18 Aug 2026)

### 6e.1 What was asked for

The per-date weekly sheet is printed and read next to a paper list, so it was carrying five
columns nobody reads and a set of database identifiers as headers. Three changes:

1. drop `student_email`, `date`, `assessmentid` and `form_code`;
2. move the whole `MC1 … MCn` block from the far right to sit **immediately before
   `Assessor Score`**, so the per-item marks read straight into the score they roll up into;
3. relabel the remaining columns to reader vocabulary — `student_number` → `Student Number`,
   `student_name` → `Student Name`, and so on.

`subject` was on the original drop list and was **deliberately kept** — see §6e.5.

### 6e.2 Where it happens — one function, at the very end

Everything inside the pipeline stays `snake_case`. The change is a presentation step applied
to a copy of the frame *after* roster ordering and *immediately before* `to_excel`:

```python
# general_utils.py, just under resolveMcScale
WEEKLY_SHEET_DROP_COLS  = ["student_email", "date", "assessmentid", "form_code"]
WEEKLY_SHEET_MC_BEFORE  = "Assessor Score"     # None -> leave the MC block at the end
WEEKLY_SHEET_COLUMN_LABELS = {
    "student_number":      "Student Number",
    "last_name":           "Last Name",
    "first_name":          "First Name",
    "student_name":        "Student Name",
    "student_email":       "Student Email",
    "assessor_name":       "Assessor Name",
    "subject":             "Subject",
    "item_code":           "Item Code",
    "date":                "Date",
    "clinical_incident":   "Clinical Incident",
    "assessor_reflection": "Assessor Reflection",
    "student_reflection":  "Student Reflection",
    "assessmentid":        "Assessment ID",
    "form_code":           "Form Code",
}
WEEKLY_SHEET_COLUMN_LABELS_INVERSE = {v: k for k, v in WEEKLY_SHEET_COLUMN_LABELS.items()}

formatWeeklySheet(df, dropCols=None, labels=None, mcBefore=None) -> new DataFrame
```

`formatWeeklySheet` returns a **new** frame; the caller's is never mutated (asserted in the
verification). Each of the three steps switches off independently — `dropCols=[]`, `labels={}`,
`mcBefore=False`.

Anything not in the label map passes through untouched. That is what keeps `MC1…MCn`,
`Assessor Score` and `Student Score` as they were, and it is why a column added to
`getWeeklySimDataSql` later will appear in the sheet under its raw name rather than vanishing.

The MC move is **positional, not a rewritten column list**: the MC columns are pulled out,
`_sortMcColumns`'d (so `MC10` sorts after `MC3`, not after `MC1`), and spliced back in at the
index of the anchor. Every other column keeps its relative order, whatever the stream's column
set happens to be. If the anchor is absent the MC block is left at the end rather than dropped
(regression-tested — §6e.6 check 8).

`mcBefore` is matched against **both** the final label and its `snake_case` original, because
`formatWeeklySheet` runs before the rename but is configured with the name you see in the
sheet. `"Assessor Score"` happens to be identical either way; `mcBefore="Item Code"` and
`mcBefore="item_code"` both work.

### 6e.3 Call path

```python
buildWeeklySimReports(..., dropCols=None, labels=None, mcBefore=None)
  -> _buildWeeklySimForOneStream(..., dropCols, labels, mcBefore)
    -> buildWeeklySimWorkbook(..., dropCols=None, labels=None, mcBefore=None)
```

Inside `buildWeeklySimWorkbook`:

```python
if roster is not None and not roster.empty:
    dataDf, _notOnRoster, _noData = applyRosterOrder(dataDf, roster)

# Presentation last: applyRosterOrder still works on snake_case, and everything from
# here down (styling, charts) sees exactly what lands in the file.
sheetDf = formatWeeklySheet(dataDf, dropCols=dropCols, labels=labels, mcBefore=mcBefore)

sheetDf.to_excel(filePath, index=False)
...
    styleWeeklySheet(ws, sheetDf, ...)
addAssessmentCharts(filePath, ...)
return (filePath, sheetDf) if returnDf else filePath
```

Ordering matters in both directions:

- **After `applyRosterOrder`**, because it looks up `idCol="student_number"` /
  `nameCol="student_name"` and inserts `last_name` / `first_name`. Relabelling first would
  break it.
- **Before `styleWeeklySheet`**, because that function locates the GR and MC columns by
  `df.columns` and must be handed the frame that is actually in the sheet.

**`returnDf=True` now returns the WRITTEN frame** (dropped, reordered, relabelled) rather than
the raw pull, so it matches the file. Only a commented example in cell 37 uses it. Call
`readDf(engine, getWeeklySimDataSql(...))` if you want the raw shape.

### 6e.4 Reading it back — the compat shim

`loadWeeklyFiles` is the single funnel feeding `buildWideDf`, `runBlrAnalysisForAllFiles`,
`flag_low_students` and the combined notebook (§7.2). One rename there covers all of them:

```python
df = pd.read_excel(filePath, engine="openpyxl")
# Undo the sheet's presentation labels so everything downstream keeps working in
# snake_case. A workbook written before 2026-08-18 has no labels to undo, so the same
# call handles both layouts and the two can sit in one folder.
df.rename(columns={**WEEKLY_SHEET_COLUMN_LABELS_INVERSE,
                   'Assessor Score': 'assessor_score'}, inplace=True)
```

Consequences, all verified:

- **Nothing downstream changed.** `DEFAULT_ID_COLS = ["student_number"]`, `ITEM_CODE_COL =
  "item_code"`, `runBlrAnalysis`'s `grCol="GR"` and cell 39's
  `id_cols=["student_number","student_name"]` all still resolve.
- **Old and new workbooks coexist in one folder** and produce identical long frames. This is
  what makes "rebuild whenever you feel like it" safe — the folder does not have to be
  consistent.
- **Nothing needs rebuilding.** Rebuild a date with `skipExisting=False` (cell 37's
  `REBUILD = True`) when you want the new look; leave it and the old sheet keeps working.
- The rename is `inplace` on a fresh read, so a workbook carrying *both* spellings (impossible
  today) would collapse them — not a real case, but do not add a label whose value equals
  another column's snake name.

`WEEKLY_FREEZE_AFTER` gained the four display names alongside the four snake ones:

```python
WEEKLY_FREEZE_AFTER = ["student_number", "last_name", "first_name", "student_name",
                       "Student Number", "Last Name", "First Name", "Student Name"]
```

`styleWeeklySheet` filters this list by `c in df.columns`, so listing both spellings costs
nothing and keeps the function callable on a raw frame. Freeze panes still land at `E2` on a
rostered sheet.

### 6e.5 Why GR/TS/CS/PS/PR/PEC and `subject` were left alone

**The scale acronyms stay acronyms.** Three places key off the literal string `GR`:
`addAssessmentCharts` looks headers up by text (`headers['GR']`, `headers['Assessor Score']`,
`headers['Student Score']`), `styleWeeklySheet` defaults to `grCols=("GR",)`, and
`runBlrAnalysis` takes `grCol="GR"`. Expanding them means editing all three plus every
`WEEKLY_GR_HIGHLIGHT` call site, for headers that are already documented on the sheet's own
Description block. Offered and declined. If it is ever wanted, add the six entries to
`WEEKLY_SHEET_COLUMN_LABELS` **and** change those three defaults together.

**`subject` stays in the sheet.** It was on the original drop list, but cell 39's
`exportCombinedNotebook` guards on `if "subject" in score_long_df.columns` to emit the combined
workbook's `subject_mismatches` sheet — dropping the column would have made that sheet silently
disappear rather than fail. It is a one-word change if you want it gone:

```python
WEEKLY_SHEET_DROP_COLS = ["student_email", "subject", "date", "assessmentid", "form_code"]
```

Note that cell 37 already writes a DB-driven `<COHORT> subject code mismatches.xlsx` via
`getSubjectMismatches` (§6d.7), which is the authoritative version — the in-workbook sheet is a
convenience duplicate. Nothing *routes* on subject either way (§6b.2).

**`date` was safe to drop** because no reader takes the date from the sheet: `loadWeeklyFiles`
parses it out of the FILENAME via `DEFAULT_DATE_REGEX`, and `buildWideDf` then sets
`tmp["date"] = dateStr` itself. The in-sheet column was redundant with the filename and, being
a `datetimeutc::date`, was the column most likely to be misread under a UTC session (§2.3).

### 6e.6 Verification

No database was needed: a synthetic frame with exactly `getWeeklySimDataSql`'s column set (in
its `SELECT` order, MC block appended last, mixed week-key spellings) was pushed through the
same calls `buildWeeklySimWorkbook` makes. Eight checks, all passing:

| # | Check | Result |
|---|-------|--------|
| 1 | Column order and labels equal the target list exactly; caller's frame unmutated | pass |
| 2 | `last_name` / `first_name` from `applyRosterOrder` relabel and stay in position 2–3 | pass |
| 3 | `to_excel` → `styleWeeklySheet` → `addAssessmentCharts` all succeed; `freeze_panes == E2`; `Charts` sheet present; `MC1` index < `Assessor Score` index; none of the five dropped headers present | pass |
| 4 | `loadWeeklyFiles` on the new sheet yields `student_number`, `student_name`, `assessor_name`, `item_code`, `assessor_score`, `subject`, `GR`, `MC1` | pass |
| 5 | An old-layout workbook written into the same folder loads alongside it; both dates found | pass |
| 6 | `buildWideDf` long frames from the old and new sheets are `assert_frame_equal` identical (date column aside); `Avg Score` identical; `subject` survives | pass |
| 7 | `formatWeeklySheet(df, dropCols=[], labels={}, mcBefore=False)` reproduces the pre-change column list exactly | pass |
| 8 | With `Assessor Score` absent, the MC block stays at the end in `_sortMcColumns` order instead of disappearing | pass |

Plus `runBlrAnalysisForAllFiles` over the mixed-layout folder (2 dates, no error) and
`flag_low_students` with `id_cols=["student_number","student_name"]` (6 × 10 flag frame), and
`py_compile general_utils.py`.

Header actually written, with a roster:

```
Student Number | Last Name | First Name | Student Name | Assessor Name | Subject | Item Code |
GR | TS | CS | PS | PR | PEC | MC1 | MC2 | MC3 | MC10 | Assessor Score | Student Score |
Clinical Incident | Assessor Reflection | Student Reflection
```

Note `MC3` before `MC10` — `_sortMcColumns` is applied inside `formatWeeklySheet` as well as at
build time, so the reordering cannot reintroduce lexical MC ordering.

**Not verified:** no run against the user's live Postgres, and no rebuild of the workbooks
already on disk. Both are safe to defer — see §6e.4.

---

## 6f. Attendance: the `Forms` count, absentee rows and the Session Summary sheet (18 Aug 2026)

### 6f.1 What was asked for

Two questions the weekly sheet could not answer:

1. **"Did every student get exactly one form this session?"** From semester 2 every SHY session
   is one form per student, so anything other than 1 is worth a look. (This first shipped as a
   per-row `Forms` column and was cut the same day — see §6f.8. The signal survives as an amber
   student number and a line on the Session Summary.)
2. **"Who was not assessed at all?"** An absent student simply had no row, so a missed session
   was invisible — you could only find it by diffing the sheet against a class list. Staff want
   to see the name, then check it against a leave application.

Explicitly scoped: the names come from **the reference student sheet if there is one, otherwise
ignore it**. Only BOH2 has `BOH2/BOH2 Roster 2026.xlsx`; DDS2 has none and gets the count only.

### 6f.2 `addWeeklyAttendance`

```python
WEEKLY_FORMS_COL       = "Forms"
WEEKLY_FORMS_HIGHLIGHT = {0: "grey", 2: "amber", 3: "red"}

addWeeklyAttendance(df, roster=None, formsCol="Forms", idCol="student_number",
                    nameCol="student_name", countCol="assessmentid",
                    addForms=True, addAbsent=True) -> (out, stats)
```

**The count is of DISTINCT `assessmentid` per student, not rows.** This matters on DDS2, where one
form can carry several checklists and therefore several rows — all of them belong to one form. It
also matters on BOH2: on 2026-06-30 there are 44 rows for 42 students and 43 forms, so a naive row
count would report two anomalies where there is one. It falls back to a row count only if
`assessmentid` is absent — which over-counts multi-checklist forms, so keep `assessmentid` in the
frame until after this call.

The count is **always computed** — `duplicate` and `duplicateIds` are built from it — but since
§6f.8 it is only written into the sheet as a column when `addForms=True`. `duplicateIds` is what
`styleWeeklySheet` colours from.

The count is computed **before** any placeholder row exists, so an absentee cannot dilute it.

**Absentee rows** are one blank row per roster student with no data, carrying `student_number`,
`student_name` (built as `first_name + " " + last_name` from the roster) and `Forms = 0` — and
nothing else. They are appended unsorted, because `applyRosterOrder` runs next and folds them
into the alphabetical run; `last_name` / `first_name` come free from that merge.

When `addForms=True`, `Forms` is placed immediately after `student_name`, with the identity block
rather than the scores.

`stats` carries `expected` / `assessed` / `missing` / `duplicate` / `extra` plus the frames behind
each (`absentDf`, `duplicateDf`, `extraDf`), `duplicateIds` for the styling, the item codes
present, and `hasRoster`.

### 6f.3 Call order — this is the whole design

```python
dataDf, sessionStats = addWeeklyAttendance(dataDf, roster if addAbsent else None, …)
if roster is not None and not roster.empty:
    dataDf, _notOnRoster, _noData = applyRosterOrder(dataDf, roster)
sheetDf = formatWeeklySheet(dataDf, …)
```

Attendance → order → present. Each step depends on the one before:

- **Attendance before ordering** so absentees sort in with everyone else and the sheet is one
  alphabetical register. Appending them afterwards would leave a block at the bottom, which was
  offered and not taken.
- **Ordering before presentation** because `applyRosterOrder` keys off `student_number` /
  `student_name` (§6e.3).

`buildWeeklySimWorkbook` / `buildWeeklySimReports` take `addForms=False`, `addAbsent=True`,
`summarySheet=True`, `summarySheetName="Session Summary"`. `addAbsent=False, summarySheet=False`
reproduces the §6e-only sheet exactly (verified by `assert_frame_equal`).

### 6f.4 The Session Summary sheet

`sessionSummaryLines(stats, date, cohort, stream)` produces the `(label, value)` rows;
`writeDescriptionSheet` renders them with the same navy styling as the combined workbook's
Description sheet. It gained an `index` parameter for this — `index=0` (default) puts a sheet
first, which is what the combined workbook wants; the weekly workbook passes `index=None` so the
summary is **appended**, leaving `Sheet1` as the sheet that opens. Final order is
`Sheet1 | Session Summary | Charts`.

Real output, BOH2 SHY 2026-06-30:

```
Session
  Date          2026-06-30
  Cohort        BOH2
  Stream        SHY
  Item code(s)  36MO (532), 41MIBL (524 578), 522, 531, 532

Attendance
  Expected (roster)               49
  Assessed                        42
  No data (Forms = 0)              7
  More than one form (Forms > 1)   1

Not assessed this session
  Students   1608030 Zipei Cheng; 1760557 Elizabeth Puthumana; 1757029 Rem Said;
             1634242 James Segalla; 1758179 Anda Sudampanthorn; 1606301 Lea Tabbara;
             1452737 Nina Tran

More than one form
  Students   1535538 Qiwen Xue (2)
```

A roster `notes` value is appended in brackets after the student's name, so a note already
recorded against a student travels onto the sheet. When no roster is found the Attendance block
drops the roster lines and says so explicitly rather than reporting `expected = 0`.

### 6f.5 Styling

`styleWeeklySheet` gained `absentCol` / `greyAbsentRows` / `duplicateIds` / `idCol` /
`duplicateColor` (plus `formsCol` / `formsLevels`, used only when the sheet still has a `Forms`
column). Two signals, both read off the data rather than a helper column:

- the **whole row** is filled `CW_LIGHT_GREY` where `absentCol` is blank. An absentee placeholder
  is precisely "a row with no item code", so `absentCol` defaults to the item-code column under
  either spelling. A real row can never have a blank item code — the extraction query inner-joins
  the checklist CTE (§9, `no-rows`), which is what makes this safe as an identifier;
- the **student-number cell** goes `WEEKLY_DUPLICATE_COLOR` (amber) for every row of a student in
  `duplicateIds`.

Row fills go on **first** so the per-cell colours survive them.

`duplicateIds` is **passed in, not recomputed**: by styling time the sheet has been through
`formatWeeklySheet`, which drops `assessmentid` — the only thing it is correct to count. Counting
rows here would call a two-checklist form a duplicate.

Ids are compared **as strings**, because the frame's id column is `Int64` (the placeholder concat
forces a nullable dtype) while `duplicateIds` comes from a groupby index that may be plain
`int64`.

Both row loops are **positional** (`enumerate`), matching `highlightLevelCells`, because the
frame's index is no longer a clean `RangeIndex` after the concat that added the placeholder rows.

`WEEKLY_FORMS_HIGHLIGHT` still applies when `addForms=True`. `highlightLevelCells` matches
**exact values**, so `{3: "red"}` catches exactly three forms, not "three or more".

### 6f.6 Downstream: placeholders never leave the sheet

A placeholder row deliberately has **no `item_code`**, and that is how `loadWeeklyFiles`
recognises it:

```python
if ITEM_CODE_COL in df.columns:
    df = df[df[ITEM_CODE_COL].notna()].copy()
    df[ITEM_CODE_COL] = df[ITEM_CODE_COL].apply(standardizeWeekFormat)
df = df.drop(columns=[c for c in (WEEKLY_FORMS_COL,) if c in df.columns])
```

Both lines matter. Without the first, a student who missed a session would appear in the combined
workbook with all-blank scores and be scored **Pass** by the flagging — `low_count` counts scores
at or below a cutoff, and `NaN` is never below one. The second is kept even though the column is
off by default (§6f.8), so a workbook built while it was on, or with `addForms=True`, still loads
clean. The sheet answers "who was here"; the combined workbook answers "who is at risk"; they are
different questions and the placeholder belongs only to the first.

### 6f.7 Verification — real BOH2 data, not a simulation

All seven BOH2 SHY workbooks on disk were replayed through the new path with the real roster
(49 active students). The workbooks are the pre-18-Aug output, i.e. exactly the frame
`buildWeeklySimWorkbook` holds just before writing, so this is the genuine call path minus SQL.

| date | rows before | rows after | expected | assessed | missing | >1 form | not on roster |
|---|---|---|---|---|---|---|---|
| 2026-06-30 | 44 | 51 | 49 | 42 | 7 | 1 | 0 |
| 2026-07-07 | 49 | 49 | 49 | 49 | 0 | 0 | 0 |
| 2026-07-14 | 48 | 49 | 49 | 48 | 1 | 0 | 0 |
| 2026-07-21 | 48 | 49 | 49 | 48 | 1 | 0 | 0 |
| 2026-07-28 | 49 | 49 | 49 | 49 | 0 | 0 | 0 |
| 2026-08-04 | 49 | 49 | 49 | 49 | 0 | 0 | 0 |
| 2026-08-11 | 49 | 49 | 49 | 49 | 0 | 0 | 0 |

**The data answers the "x1 per student" question directly:** six of the seven sessions are exactly
one form for every one of the 49 students. Only 2026-06-30, the first SHY session, is not —
7 students with no data and Qiwen Xue (1535538) with two forms. Whether those seven are leave or
a first-week teething problem is the check this column exists to enable.

Note 2026-06-30 has 44 rows for 42 students but only 43 forms: one student's single form carries
two item codes. `Forms` reads `1` for them, which is the point of counting `assessmentid` rather
than rows.

Per-workbook invariants asserted on every date: `rows_after == rows_before + missing`; distinct
students == roster size; every `Forms == 0` row has a name and no item code; sheet order is
`Sheet1 | Session Summary | Charts`. Styling checked on 2026-06-30 — 7 rows greyed, 2 amber
`Forms` cells (the duplicate student's two rows), `freeze_panes = E2`.

**Downstream proven unchanged on the same corpus:**

- `loadWeeklyFiles` — all 7 date frames `assert_frame_equal` identical to the originals across
  the 33 shared columns, with `Forms` asserted absent;
- `buildWideDf` — identical, 49 students × 11 item codes;
- `flag_low_students(method='percentile', min_low_count=3)` — identical flag frame.

Plus the §6e synthetic suite re-run (8/8), `import *` name survival for every new public name,
and `py_compile`.

**Not verified:** not run against the live database; `getSubjectMismatches` and the risk report
were not re-run (neither reads the weekly sheet's new columns).

### 6f.8 The `Forms` column was removed the same day

Seen in the sheet, the column read as noise: it holds the same number down every row of a
student, and for the six clean sessions that number is `1` forty-nine times. Everything it was
carrying is available elsewhere, so **`addForms` now defaults to `False`** and the column is not
written.

What replaced it, with nothing lost:

| was | is now |
|---|---|
| `Forms = 0` marked an absentee | the row is greyed; it is identifiable by a blank `Item Code` |
| `Forms >= 2` marked a duplicate | that student's number cell goes amber |
| the counts, per row | the Session Summary's `Assessed` / `Not assessed` / `More than one form`, with names |

The count itself is **still computed on every build** — `stats['duplicate']` and
`stats['duplicateIds']` come from it, and both feed the summary and the highlighting. Only the
column is optional. `addForms=True` brings it back and `WEEKLY_FORMS_HIGHLIGHT` still colours it;
`loadWeeklyFiles` still strips `Forms` on read, so a workbook built either way loads clean.

The Session Summary's wording moved with it: `No data (Forms = 0)` became `Not assessed`,
`More than one form (Forms > 1)` became `More than one form`, and the how-to-read block now
describes the grey row and the amber student number instead of a column. It also states outright
that the count is of forms, not rows — the one thing the column's name used to imply and no
longer can.

**Verified:** the same 7-workbook BOH2 replay, re-run — 7 greyed rows and 2 amber student-number
cells on 2026-06-30 (Qiwen Xue's two rows), `Forms` asserted absent from both the sheet and the
loaded frame, absentee rows asserted to carry nothing but a number and a name, and
`loadWeeklyFiles` / `buildWideDf` / `flag_low_students` still identical. `addForms=True` was
re-checked as an escape hatch (counts 0×7, 1×42, 2×2) and a workbook written with the column was
confirmed to load clean. §6e and §6g suites re-run and passing.

---

## 6g. The combined workbook's headers, and the `risk_report` dependency (18 Aug 2026)

### 6g.1 Nothing was broken — but the two workbooks stopped matching

The first question after §6e/§6f was whether the weekly-sheet renames break the combined
report. **They do not**, and this was proven before anything was changed: `loadWeeklyFiles`
reverses the labels and drops the placeholder rows, so `buildWideDf` produces the identical long
frame and the combined workbook rebuilds byte-for-byte (§6f.7).

What *did* break was consistency. The weekly sheet said `Student Number`; the combined workbook,
built from it, still said `student_number`. So the combined workbook was relabelled the same way —
same mechanism, same place in the pipeline, one extra complication.

### 6g.2 Why this is harder than the weekly sheet

Two things make a combined sheet different:

1. **Most of its columns are item codes** (`FP-Week-03`, `41MIBL (524 578)`). They are *data*, not
   headers. `thresholds` is a Series indexed by them, `styleCombinedSheet` colours them by
   position, and `risk_report` finds its week columns by substring. Renaming one would silently
   drop a week from every trend and slope.
2. **The workbook is read back.** `risk_report.py` hard-codes `student_number` (19 uses),
   `student_name` (9) and `missing_item_codes`. It is a standalone module — it imports nothing
   from the reporting stack — so it needed its own compat shim.

### 6g.3 `formatCombinedSheet`

```python
COMBINED_SHEET_COLUMN_LABELS = {**WEEKLY_SHEET_COLUMN_LABELS,
    "low_count": "Low Count",
    "n_attempts": "Attempts", "dates": "Dates", "scores": "Scores",
    "missing_item_codes": "Missing Item Codes",
    "n_forms": "Total Forms", "n_assessors": "Distinct Assessors",
    "most_seen_assessor": "Most Seen Assessor", "most_seen_count": "Most Seen Count",
    "stream": "Stream", "expected_subject": "Expected Subject"}
COMBINED_SHEET_COLUMN_LABELS_INVERSE = {v: k for k, v in COMBINED_SHEET_COLUMN_LABELS.items()}

formatCombinedSheet(df, idCols=None, labels=None, protect=None) -> (out, outIdCols)
```

Only names **present in the map** are renamed, so item codes pass through untouched — that is the
whole safety property, and it is asserted in the verification. `protect` is an explicit override
for a column that must keep its name even if it collides with a map key (no real case today).

**It returns `outIdCols` as well as the frame, and you must use it.** `styleCombinedSheet` and
`highlightRepeatAssessors` locate columns by name; handing them the relabelled frame with the
original `id_cols` would not raise — it would silently colour the wrong columns.

`n_forms` is deliberately **"Total Forms"**, not "Forms": the weekly sheet already uses `Forms`
for a different quantity (§6f.2), and one word meaning two things across the two workbooks is
exactly the confusion this layer exists to remove.

Two constants replaced hard-coded sets so both spellings work:

```python
COMBINED_META_COLS = {"Avg Score", "low_count", "Low Count", "Pass/Fail"}
COMBINED_ASSESSOR_SUMMARY_COLS = {"n_forms", …, "Total Forms", "Distinct Assessors", …}
```

`styleCombinedSheet` used to carry `meta = {"Avg Score", "low_count", "Pass/Fail"}` inline. Had
that not been widened, `Low Count` would have fallen through as a *value* column and been given
threshold colouring — a silent miscolouring, not an error. `Pass/Fail` and `Avg Score` are not in
the label map: they were always display-cased.

### 6g.4 Notebook cell 39

`exportCombinedNotebook` gained `sheet_labels=None`. All the logic above the write is untouched —
`flagged_df["Pass/Fail"]`, the assessor pivot, the Description sheet all still work in
`snake_case`. Only the write block changed:

```python
fmt = lambda df: formatCombinedSheet(df, id_cols, labels=sheet_labels)
score_out, out_id_cols = fmt(score_df)
rating_out,  _ = fmt(global_rating_df)
…
styleCombinedSheet(writer.sheets["scores"], score_out, out_id_cols, "score",
                   thresholds, amber_margin)
```

`sheet_labels={}` returns the frame and idCols unchanged and reproduces the pre-18-Aug workbook
exactly — that is how the two versions were diffed in §6g.6.

### 6g.5 `risk_report.py` — the compat shim

`_loadSheets` is the single place the workbook is read, so the shim goes there:

```python
_COMBINED_HEADER_ALIASES = {"Student Number": "student_number", …}   # duplicated, not imported

def _normaliseHeaders(df):
    return df.rename(columns=_COMBINED_HEADER_ALIASES)

def _loadSheets(path, cfg):
    …
    return tuple(_normaliseHeaders(pd.read_excel(path, sheet_name=cfg[key]))
                 for key in ("sheetScores", "sheetRatings", "sheetPr",
                             "sheetMissing", "sheetRepeated"))
```

The map is **duplicated rather than imported**, because `risk_report` is deliberately standalone
(its docstring presents it as importable on its own; importing `general_utils` would drag in
sqlalchemy and psycopg). **Keep the two in step** — a label added to
`COMBINED_SHEET_COLUMN_LABELS` and missed here surfaces as a `KeyError` on the snake_case name.

That the shim is load-bearing was demonstrated, not assumed: the **unmodified** `risk_report`
raises `KeyError: 'student_number'` on a new-format workbook and loads an old one fine. With the
shim, both load.

### 6g.6 Verification — real DDS2 FP data, both versions diffed

The real `exportCombinedNotebook` was extracted from cell 39 with `ast.get_source_segment` (not a
copy — the actual notebook source) and run twice over the 11 real DDS2 Fixed Prosthodontics weekly
workbooks: once with `sheet_labels={}`, once with the default.

| sheet | shape | values | headers renamed |
|---|---|---|---|
| scores | 106 × 10 | identical | 2 |
| global_ratings | 106 × 10 | identical | 2 |
| practice_readiness | 106 × 10 | identical | 2 |
| scores_flagged | 106 × 12 | identical | 3 |
| repeated_attempts | 14 × 5 | identical | 5 |
| scores_missing | 17 × 3 | identical | 3 |
| assessors | 106 × 13 | identical | 6 |
| subject_mismatches | 37 × 7 | identical | 7 |

Every sheet compared with `assert_frame_equal` after mapping the new headers back — so the check
is "only the headers moved", not "the numbers look similar".

- **Item codes untouched:** `FP-Week-01 … FP-Week-07` identical in both.
- **Styling identical:** 149 / 255 / 115 coloured cells on scores / scores_flagged /
  global_ratings, at the same positions with the same colours. `freeze_panes = C2` in both.
- **risk_report reads both:** `weekCols` identical, analytics frame `assert_frame_equal` identical
  (106 students × 33 columns), same risk split — High 7 / Moderate 38 / Watch 30 / OK 31 — and a
  full 7-sheet risk report written from each.
- The §6e and §6f suites were re-run and still pass, and `py_compile` covers both modules. Cell 39
  is checked with `ast.parse` (it is not importable, so `py_compile` cannot reach it).

**Not verified:** not run against the live database, and BOH2 combined workbooks were not used for
the risk-report half — BOH2 has no `Week` in its item codes, so the risk report is skipped for it
anyway (§6d.8). The BOH2 combined workbook itself rebuilds and relabels through the identical code
path.

---

## 7. Downstream consumers — the FHY / SHY / ALL period selector

The Weekly Sim folder feeds three other things, all of which read the workbooks off disk by
filename pattern:

- `runBlrAnalysisForAllFiles(...)` → `BLR_analysis_results.xlsx`
- `exportCombinedNotebook(...)` → `dds2 combined scores and ratings.xlsx`
- `risk_report.generate(...)` → `dds2 sim risk report.xlsx`

They all glob the *whole* folder, so once semester-2 workbooks landed next to semester-1 ones every
one of these silently pooled both semesters. A **period selector** was added to fix that.

### 7.1 The period vocabulary

```python
PERIOD_FHY = "FHY"   # first half year  — dates strictly BEFORE  DDS2_SEMESTER_SPLIT_DATE
PERIOD_SHY = "SHY"   # second half year — dates on/after         DDS2_SEMESTER_SPLIT_DATE
PERIOD_ALL = "ALL"   # whole year, sem 1 + sem 2 pooled (the original behaviour, and the default)

resolvePeriod(period='ALL', minDate=None, maxDate=None, splitDate=None) -> (minDate, maxDate, label)
periodSuffixPath(path, period='ALL') -> path with ' (FHY)' / ' (SHY)' inserted before the extension
```

Both halves are **derived from the single `DDS2_SEMESTER_SPLIT_DATE` constant** — FHY ends the day
before it — so they are complementary by construction: `FHY ∪ SHY == ALL` with no overlap, and
moving the constant moves both. Case-insensitive, and `SEM1`/`S1`/`H1` and `SEM2`/`S2`/`H2` are
accepted as aliases. An unknown value raises rather than silently returning everything.
Explicit `minDate`/`maxDate` override the period's own bounds, so
`period='SHY', maxDate='2026-07-31'` is a valid "second half year up to end of July".

### 7.2 Where it plugs in

Everything funnels through one function, so the filter went in at the bottom:

```
loadWeeklyFiles(folderPath, dateRegex, filePattern,
                period, minDate, maxDate,              <-- date filter lives here
                ignoreCodeList, minItemCount)          <-- item-code filter too (§7.6)
   |
   +-- buildWideDf(...)                 -> scores / GR / PR wide tables
   +-- runBlrAnalysisForAllFiles(...)
   +-- _flag_by_blr(...) <- flag_low_students(...)
```

The date is taken from the **filename** (`dds2 <YYYY-MM-DD> assessment_data.xlsx`), so the filter is
a plain string comparison — ISO dates compare correctly as text, no parsing needed, and it cannot
disagree with the DB-side `::date` because the filename was generated from it.

`exportCombinedNotebook` (still defined inline in notebook cell 40) gained
`period`, `min_date`, `max_date` and `suffix_out_path`. It **resolves the period once** to concrete
dates and passes those down with `period=PERIOD_ALL`, so a nested call cannot re-apply the bounds a
second time. It now also prints the dates actually used, returns the output path, and returns
`None` with a message instead of crashing when a period matches no workbooks.

### 7.3 Filenames

`ALL` keeps the original name; `FHY`/`SHY` are suffixed. That way the existing whole-year filenames
— and anything already pointing at them — keep working, while the three periods can coexist:

```
BLR_analysis_results.xlsx              BLR_analysis_results (FHY).xlsx        … (SHY).xlsx
dds2 combined scores and ratings.xlsx  dds2 combined scores and ratings (FHY).xlsx   … (SHY).xlsx
dds2 sim risk report.xlsx              dds2 sim risk report (FHY).xlsx        … (SHY).xlsx
```

The risk report takes no period argument — it reads the combined workbook, so cell 41 just runs
both its input and output paths through `periodSuffixPath` and inherits the split.

### 7.4 Notebook wiring

`PERIOD` is set once, in the DDS2 Weekly config cell (36) next to `folder`:

```python
folder = 'DDS2/Weekly Sim'
PERIOD = 'SHY'          # 'FHY' | 'SHY' | 'ALL'
```

Cells 39 (BLR), 40 (combined) and 41 (risk) all read it. To produce all three, cell 40 carries a
commented loop:

```python
for p in ("FHY", "SHY", "ALL"):
    exportCombinedNotebook(folder_path=folder,
        out_path=os.path.join(folder, "dds2 combined scores and ratings.xlsx"),
        method=FlagMethod.PERCENTILE, min_low_count=3, borderline_gr=2,
        id_cols=["student_number", "student_name"], period=p)
```

### 7.5 Why this matters more than it looks

The wide tables pivot on **`item_code`**, not date, and the percentile thresholds are computed
per item code. Pooling both semesters therefore mixes two entirely different checklist populations
into one flagging run. Measured on the real data (33 workbooks in one folder):

| period | dates | item codes | students flagged Fail | risk bands (High / Mod / Watch / OK) |
|---|---|---|---|---|
| FHY | 15 | 15 | 44 | 8 / 20 / 29 / **49** |
| SHY | 18 | 21 | 62 | 17 / 57 / 32 / **0** |
| ALL | 33 | 34 | 80 | 22 / 62 / 20 / **2** |

`ALL` is not the average of the two — it is its own (much harsher) picture, because a student is
flagged on `low_count >= min_low_count` across *all* 34 item codes. **`ALL` was the only behaviour
available before this change.** SHY's `OK: 0` is `risk_report`'s own banding applied to a
half-year's worth of columns, not a defect introduced here — but it does mean the risk bands are
not comparable across periods, only within one.

Note that SHY contains 21 item codes for 18 dates: a few students each week are catching up on a
*semester-1* checklist (`2026-Week-03`, `2026-Week-06`) during semester 2. Those codes correctly
appear in both FHY and SHY, and `ALL` merges the attempts — 2026-08-12 output shows student 1270080
doing `2026-Week-03` on both 2026-02-16 and 2026-07-27, caught as a repeated attempt only in `ALL`.

### 7.6 `ignoreCodeList` and `minItemCount` — excluding item codes

Same funnel, same idea: some item codes should not take part in the analysis at all. The obvious
cases are the January test forms (`positioning`, `DDS2-MAR-31`, `19-Jan-SIM`) and the semester-1
catch-up codes that appear inside SHY because one or two students are behind.

```python
matchesIgnoreCode(itemCode, ignoreCodeList) -> bool
dropIgnoredItemCodes(weeklyFiles, ignoreCodeList=None, minItemCount=0, verbose=True,
                     idCol="student_number") -> [(dateStr, df), ...]
```

**Matching** is `fnmatch` glob, case-insensitive, and **both sides are pushed through
`standardizeWeekFormat` first** — so listing the raw DASH spelling `'Paeds 2026-Week-1'` still
matches the normalised `'Paeds-2026-Week-01'` that ends up in the workbook. A pattern with no
wildcard is simply an exact match.

| pattern | matches |
|---|---|
| `positioning` | exactly that code |
| `2026-Week-*` | the whole semester-1 family |
| `Paeds*` | the whole Paeds family |
| `*-Week-0?` | weeks 01–09 of any prefixed family |
| `*` | everything (degrades gracefully — see below) |

**`minItemCount`** is the automatic version: drop any item code sat by fewer than N **distinct
students across the whole loaded period** (not per date, so a code split over two dates is judged
on its combined count). Default `0` = off. This exists because a code done by a single catch-up
student still gets its own column *and its own percentile threshold computed over n = 1*, which is
meaningless. On the real SHY data `minItemCount=5` removes exactly the three n=1 codes
(`2026-Week-03`, `2026-Week-06`, `Week-08`).

**Where it happens.** In `loadWeeklyFiles`, before anything else sees the data — so an ignored code
gets no column in the wide table, no percentile threshold, no contribution to `low_count`, and is
excluded from each date's BLR regression *before* the cutoff is fitted. `_flag_by_blr` is called
with `verbose=False` so the drop report prints once per run, not twice.

**Never silent.** Every dropped code is printed with its reason, and if the drops empty a date
completely that date is removed from the set and named:

```
Ignored 3 item code(s): 2026-Week-03 [minItemCount (n=1)], 2026-Week-06 [minItemCount (n=1)], Week-08 [minItemCount (n=1)]
  1 date(s) left with no rows and were dropped: 2026-08-03
```

`exportCombinedNotebook` also now prints the item-code count next to the date count, and returns
`None` with a message (rather than raising) if the filters remove everything.

**One extra change:** `loadWeeklyFiles` now also runs `standardizeWeekFormat` over the `item_code`
column **on load**, not just at build time. This makes a workbook written before the normaliser was
generalised line up with the rest, and means the ignore list only ever has to match one spelling.
For every workbook currently on disk the function is the identity, so this changes nothing today —
confirmed by the regression below.

Notebook: `IGNORE_CODES = []` and `MIN_ITEM_COUNT = 0` sit in cell 36 next to `folder` and
`PERIOD`, with the common lists as commented one-liners. Cells 39 and 40 pass them through.
Defaults are "drop nothing", so this is opt-in.

```python
IGNORE_CODES = ['positioning', 'DDS2-MAR-31', '19-Jan-SIM']   # January test forms
IGNORE_CODES = ['2026-Week-*']                                # sem-1 catch-ups inside SHY
MIN_ITEM_COUNT = 5                                            # or let it find them
```

Effect on the real SHY data — dropping the two sem-1 catch-up codes takes the Fail list from
62 to 60 (students 1270080 and 1648224 were being pushed over `min_low_count` by a catch-up column
scored against an n=1 threshold). `minItemCount=5` reaches the same 60 without a hand-maintained
list.

This does **not** affect workbook building (`buildWeeklySimReportsDDS2` pulls from the DB, not the
folder) — the ignored codes stay in the per-date workbooks, they are just excluded from the
analyses.

### 7.7 Still an option

Building semester 2 into its own folder (`folder='DDS2/Weekly Sim Sem2'`) also works and
`buildWeeklySimReportsDDS2` creates the folder if missing — but with the period selector there is
no longer a reason to split the folder.

---

## 8. Verification performed

Everything below was run in this session; none of it touched the user's machine or database.

1. **Payload audit** — `fetched_rows 2026 caf.xlsx` (19 MB, 20,312 assessments) parsed and the
   v3 separation replayed in Python: scale keys, bucket layout, flattened item codes, `role`
   absence, checklist families, per-date counts (§2).
2. **Real PostgreSQL 16 run** — a `rawform_forms_v3` table was created in a throwaway local
   Postgres with `TimeZone = Australia/Melbourne`, loaded with all 3,583 replayed DDS2 Simulation
   rows, and the *actual generated SQL strings* were executed:
   `getWeeklySimDatesSqlDDS2` (both bounds), `getGlobalRatingSqlDDS2` (single date and range),
   `getWeeklySimDataSqlDDS2`. All returned the expected shapes; §5 is real output.
3. **Full batch build** — `buildWeeklySimReportsDDS2` run against that database: 20 dates,
   17 workbooks written, 0 errors, with `skipped-exists`, `skipped-low-volume`,
   `skipped-out-of-range` and forced-rebuild paths each exercised.
4. **Regression against a known-good workbook** — semester-1 date 2026-05-25 rebuilt through the
   new path and compared column-by-column with the existing
   `DDS2/Weekly Sim/dds2 2026-05-25 assessment_data.xlsx`:

   - identical column list (44 columns, `MC1…MC25` in the same order),
   - 104 rows matched 104 rows on `(student_number, item_code)`, no orphans either side,
   - **zero** differences in `GR, TS, CS, PS, PR, PEC, Assessor Score` and every MC column,
   - 11 differences in `Student Score` — 10 of them `NaN → value` and one `0.71 → 0.69`, i.e.
     students who filed or edited their self-assessment after the original June workbook was
     built. The student-score CTE was not modified. **Data drift, not a regression.**
5. `py_compile` on the edited `general_utils.py` (locally and on the device), `sqlglot`
   postgres-dialect parse of all five generated statements, and a JSON reload of `main.ipynb`.
6. Unit checks of `standardizeWeekFormat` over all 14 real key formats plus non-week codes and
   `None`, and of `_sortMcColumns`.
7. **Period selector (§7)** — the whole year was built into one folder (33 workbooks, sem 1 and
   sem 2 mixed, exactly the situation the flag exists for) and then:
   - `loadWeeklyFiles` returned 15 / 18 / 33 dates for FHY / SHY / ALL, with
     `FHY ∪ SHY == ALL`, `FHY ∩ SHY == ∅`, every FHY date `< 2026-06-15` and every SHY date `>=`
     it. FHY's 15 dates are exactly the 15 semester-1 Mondays already on disk.
   - Narrowing (`period='SHY', maxDate='2026-07-31'`) returned the expected 13 dates.
   - `resolvePeriod` checked over `FHY/SHY/ALL`, lower-case, all six aliases, `None`, `''`, and an
     unknown value (raises `ValueError`). `periodSuffixPath` checked for all three.
   - Notebook cells 39, 40 and 41 were executed for all three periods against that folder,
     producing the nine correctly-named outputs in §7.3 with no errors.
   - **Regression:** the pre-change `exportCombinedNotebook` was run against the same folder and
     its workbook compared sheet-by-sheet with the new `period='ALL'` output — all six sheets
     (`scores`, `global_ratings`, `practice_readiness`, `scores_flagged`, `repeated_attempts`,
     `scores_missing`) identical in shape, columns and every cell. `ALL` is exactly the old
     behaviour.
8. **Ignore list (§7.6)** — on the same 33-workbook corpus:
   - `matchesIgnoreCode` checked over exact codes, `2026-Week-*`, `paeds*` (lower case),
     `*-Week-0?`, the raw spelling `Paeds 2026-Week-1` → normalised hit, multi-entry lists,
     `[]` and `None`.
   - `ignoreCodeList=['2026-Week-*']` on SHY dropped exactly the two sem-1 catch-up codes
     (21 → 19); `minItemCount=5` dropped exactly the three n=1 codes (21 → 18).
   - `ignoreCodeList=['Paeds*']` on ALL emptied 2026-08-03 and the date was correctly removed
     and reported.
   - Degenerate `ignoreCodeList=['*']` removed everything and `exportCombinedNotebook` returned
     `None` with a message instead of raising.
   - Cell 39 (BLR) run with both mechanisms at once reported both reasons and wrote its workbook.
   - **No-op regression re-run:** `period='ALL', ignore_code_list=[], min_item_count=0` through the
     *current* cell 40 compared against the **original** pre-period, pre-ignore cell 40 — all six
     sheets identical again. This also confirms the new on-load `standardizeWeekFormat` pass is the
     identity for every workbook currently on disk.

9. **Stream split (§6b)** — against the same live Postgres:
   - Classification checked for all 14 real item-code formats; the stream x weekday and
     stream x subject cross-tabs in §6b.2 are real output.
   - `resolveStreams` over 'ALL', a key, lower case, a list, a full stream name, and an
     unknown value (raises).
   - Full `stream='ALL'` build: **44 workbooks across 4 folders, 0 errors**, catch-up days
     correctly routed by item code and flagged `*off-day`.
   - **Conservation:** 3,471 item rows built vs 3,471 classified in the DB — exact, with the
     8 rows under 3 unclassified codes reported rather than dropped silently. **Zero**
     (student, item code, date) triples appear in two stream folders.
     An earlier run was 15 rows short; that is what exposed the SEM1 `endDate` problem.
   - Cells 39/40/41 run for all four streams plus pooled: 15 analysis files, no collisions.
     The `(All streams)` suffix was added after the pooled run was caught overwriting the
     semester-1 combined workbook.
   - Subject mismatch report reproduces the counts in §6b.2 (95 across the year, 76 in sem 2).
   - **No-op regression, third time:** a legacy `stream=None` build fed through the current
     `exportCombinedNotebook` with `period='ALL'`, empty ignore list — all six original sheets
     identical to the ORIGINAL pre-period, pre-ignore, pre-stream cell 40. The only difference
     anywhere is the added `subject` column in workbooks and the new `subject_mismatches` sheet.

10. **Flagging and styling (§6c)** — against the same live Postgres:
    - The BLR bug reproduced on a controlled two-code corpus (thresholds all NaN, 0 flagged),
      then all three methods verified to produce distinct, sensible cutoffs after the fix.
    - `percentile` output unchanged by the whole round — the FP Fail list is the same 11 students
      before and after, so only BLR/borderline behaviour moved.
    - Best-attempt aggregation checked against every repeated (student, code) pair in the real FP
      data: 14/14 match the max.
    - Styled workbook inspected programmatically: Description sheet present and first, navy
      headers, `freeze_panes=C2`, a `colorScale` conditional format over the GR and PR value
      blocks, 102 red cells on `scores`, 19 grey empty cells, Pass/Fail green/red on
      `scores_flagged`.
    - Full notebook run for four streams plus pooled: 15 outputs, and the risk chain now resolves
      every combined workbook (it had been skipping all of them).

11. **BOH2 cohort-generic (§6d)** — the same throwaway Postgres, loaded with the BOH2
    Simulation rows as well (4,695 forms total):
    - Viability check before any code: BOH2 SHY has one session per Tuesday, checklist counts
      per date consistent with one checklist per class, and the two-checklist week visible in
      the data at week 27 (30 June: 36MO ×28, 41MIBL ×12) — which is why the sessions file
      records the choice weeks as 27 and 38, not the 30 and 38 of the covering note.
    - Roster join: all 49 students matched once Jackie Tran's transposed ID was resolved;
      `1234567 Test1 Student1` appears in the data, is deliberately off the roster, and is
      appended and reported rather than dropped.
    - Weekly build with `mcScale='1-5'`, `roster=`, `styleSheet=True`: order, MC values,
      `Assessor Score` range, freeze panes, header fill and cell counts all as listed in §6d.6.
    - Subject mismatch: **337 → 8** after the `streamForDate` fix, the 8 being real `ORAL20003`
      forms; DDS2 unchanged at 76 in the same run (§6d.7).
    - `general_utils.py` re-staged from the device after committing and diffed against the
      working copy — byte-identical, so the verified code is the code on disk.

**Not verified:** the user's own Postgres (it is `localhost` on their machine and unreachable from
here). The first live run should be `dryRun=True`.

---

## 9. Gotchas / things that will bite

- **Session timezone.** `datetimeutc::date` is timezone-dependent and the data is stored at local
  midnight. Under a UTC session every date shifts back one day and every workbook is misnamed and
  misfiled. Check with `SHOW TimeZone;` before a first run on a new machine or connection string.
- **`getChecklistBank` keys changed for sem 2.** Because `standardizeWeekFormat` was generalised,
  the bank now emits `FP-Week-03` / `Paeds-2026-Week-01` where it previously emitted
  `FP-Week-3` / `Paeds 2026-Week-1`. That is the fix, but any spreadsheet already saved with the
  old keys (`DDS2/Checklist_Bank Simulation.xlsx`) will not join to newly-built data until it is
  regenerated (cell 38). Semester-1 keys are unaffected.
- **`createwhereStatementDDS2`'s `date` default changed** from `'2026-04-13'` to `None`. A caller
  relying on the old implicit default would now get an unfiltered range. Nothing in the repo does.
- **`minForms` silently drops dates.** They still appear in the summary frame as
  `skipped-low-volume`, so read the summary rather than the file count. Default is `1` (nothing
  dropped); the notebook cell sets `20`.
- **`no-rows` is a real state**, not a bug: some January dates have forms with reflections but no
  checklist, and the extraction query inner-joins the checklist CTE.
- **Multiple checklist families in one workbook.** On a day where a few students are catching up,
  MC1 of `FP-Week-05` and MC1 of `Paeds-2026-Week-03` land in the same `MC1` column but mean
  different things. This was already true in semester 1 (2026-05-11 had four week keys) and was
  left as-is; `item_code` distinguishes them and `week_keys` warns you before you build.
- **`ignoreCodeList` patterns are full matches, not substrings.** `'Week-08'` will not match
  `'2026-Week-08'` — use `'*Week-08'` if you mean any family. Conversely `'Paeds*'` takes the whole
  family in one go, which is easy to do by accident.
- **`(All streams)` suffix is load-bearing.** Semester 1's folder is the base folder, so a
  pooled output without the suffix overwrites the semester-1 file of the same name. Use
  `weeklySimOutPath`, not a hand-built `os.path.join`.
- **`minForms=20` is wrong for a split build.** Within a stream a 1-form day is a genuine
  catch-up; 20 would silently discard those students' assessments from that stream's combined
  and risk reports. The notebook default for the split build is 1.
- **Stream `codePatterns` rely on full-match globs.** If a future family is named so that one
  pattern is a prefix of another (say `Week-*` and `Week-A-*`), they stop being disjoint —
  `streamForItemCode` returns the FIRST match in registry order, so order the registry
  most-specific first if that ever happens.
- **Combined workbooks produced with `method='blr'` before 2026-08-17 passed everybody** — the
  thresholds were all NaN. Regenerate any that are still in circulation.
- **`borderline` needs students actually rated GR = borderline_gr** for a code. Where none are,
  that code gets no cutoff and is skipped (reported, not silent) — it is the noisiest of the
  three methods for exactly this reason.
- **Subject code is never used for routing** and should not be reintroduced as a filter; it is
  wrong on ~4% of forms and FP and Endo share DENT90148 anyway.
- **`minItemCount` counts across the whole loaded period, not per date**, so it interacts with
  `PERIOD`: a code with 3 students in SHY and 40 across the year survives `minItemCount=5` under
  `ALL` but not under `SHY`. That is the intended reading (you are analysing that period), but it
  means the two periods can legitimately drop different codes.
- **A blank row on a weekly sheet is not missing data — it is an absent student.** It carries a
  name and `Forms = 0` and nothing else, on purpose. Do not "fix" it by filling it in, and do not
  treat `Forms = 0` as a fail: cross-check leave applications first. The roster cannot know who
  applied for leave.
- **The duplicate count is of FORMS, not rows.** A DDS2 form carrying three checklists is one
  form on three rows. `addWeeklyAttendance` counts distinct `assessmentid`, so **keep
  `assessmentid` in the frame until after that call** — without it the count silently falls back
  to rows and every multi-checklist form looks like a duplicate.
- **`duplicateIds` must be PASSED to `styleWeeklySheet`, not recomputed there.** By styling time
  `formatWeeklySheet` has dropped `assessmentid`, so the only thing left to count is rows — which
  is the wrong answer. Forget to pass it and nothing goes amber; there is no error.
- **A greyed row is identified by a blank `Item Code`, so nothing else may ever write one.** The
  extraction query inner-joins the checklist CTE, so a real row cannot have one — that is the
  invariant the whole attendance layer rests on, in the styling AND in `loadWeeklyFiles`.
- **`WEEKLY_FORMS_HIGHLIGHT` matches exact values** (only relevant with `addForms=True`).
  `{3: "red"}` colours exactly three forms, not three or more; a fourth would need a `4`.
- **Anything reading a weekly sheet directly must skip rows with no `Item Code`.**
  `loadWeeklyFiles` does it for you; a hand-rolled `pd.read_excel` will otherwise pick up
  placeholder students, and in the flagging chain a row of all-NaN scores comes out as **Pass**.
- **`risk_report.py` carries a DUPLICATE of the combined label map** (`_COMBINED_HEADER_ALIASES`),
  because it is standalone by design. Add a label to `COMBINED_SHEET_COLUMN_LABELS` and you must
  add it there too, or the risk report dies with a `KeyError` on the snake_case name. Proven:
  the unmodified module raises `KeyError: 'student_number'` on a new-format workbook.
- **`formatCombinedSheet` returns `(df, idCols)` — use BOTH.** Passing the relabelled frame with
  the original `id_cols` to `styleCombinedSheet` does not raise; it colours the wrong columns.
- **Never add an item-code-like name to `COMBINED_SHEET_COLUMN_LABELS`.** Item codes are data and
  are located by substring (`'Week'`) and by index (`thresholds`); renaming one drops a week from
  every trend silently.
- **Widen `COMBINED_META_COLS`, not a local set, when a summary column is added.**
  `styleCombinedSheet` used to hard-code `{"Avg Score", "low_count", "Pass/Fail"}`; a summary
  column missing from that set is treated as a score and gets threshold colouring — wrong colours,
  no error.
- **The weekly sheet's headers are a presentation layer, not the data model.** Anything that
  reads a weekly workbook directly (a hand-written `pd.read_excel`, a colleague's script, a
  Power Query) sees `Student Number`, not `student_number`. Go through `loadWeeklyFiles` and
  the rename is handled; bypass it and you must apply `WEEKLY_SHEET_COLUMN_LABELS_INVERSE`
  yourself.
- **A folder can hold both layouts at once and that is fine** — but a human diffing two
  workbooks from either side of 18 Aug will see every header as changed. Check the build date
  before concluding something broke.
- **Do not add a `WEEKLY_SHEET_COLUMN_LABELS` entry whose *value* equals another column's
  snake name.** `loadWeeklyFiles` applies the inverse map as a single `rename`, so two columns
  would collapse into one. Nothing does this today.
- **Renaming `GR` is a four-place change**, not one: the label map, `addAssessmentCharts`'s
  `headers['GR']`, `styleWeeklySheet`'s `grCols=("GR",)` default and `runBlrAnalysis`'s
  `grCol="GR"` default. Same for `Assessor Score` / `Student Score`, which the charts look up
  by header text. This is why §6e.5 left them alone.
- **`LIKE 'scale-%%'`** — the doubled `%` is carried over from the existing queries. It is
  harmless either way (`scale-%%` and `scale-%` match identically in SQL `LIKE`), so it was left
  alone rather than risk a paramstyle-escaping change.

---

## 10. Open / not done

- Not run against the user's live Postgres.
- ~~Semester-2 workbooks will sit in the same folder as semester-1 ones~~ — **resolved** by the
  FHY/SHY/ALL period selector (§7). Note the risk bands are only comparable *within* a period.
- `getChecklistBank` was not re-run; `DDS2/Checklist_Bank Simulation.xlsx` still holds pre-
  normalisation keys.
- `exportCombinedNotebook` is still defined inline in notebook cell 40 (user's preference), so it
  is the one piece of this work not under `general_utils.py` and not covered by `py_compile`.
- The three unclassified item codes (`positioning`, `DDS2-MAR-31`, `19-Jan-SIM`, 8 rows, all
  January test forms) are reported but never built. Add a stream for them if they ever matter.
- No cross-stream summary workbook (a student's Paeds vs FP vs Endo side by side) — discussed
  and deferred.
- The stream registry hard-codes 2026 dates and the 2026 checklist families; it needs a new
  entry each year.
- The weekly builders do not warn if `type_` is set to something other than `'Simulation'`;
  the weekly model only holds for sim (clinic has no weekly sessions — §6d.1). Offered, not
  taken up.
- `risk_report.generate` still selects columns by substring, so BOH2 gets no risk report
  (§6d.8). An explicit column list is the fix.
- Weekly-sheet styling and the 1-5 MC scale are enabled for BOH2 only, via cell 36 flags.
  Turning them on for DDS2 is a one-word change but would make new DDS2 workbooks look
  different from the semester-1 ones already on disk.
- **Workbooks already on disk keep the pre-18-Aug layout.** Deliberate: the compat shim in
  `loadWeeklyFiles` makes a mixed folder harmless. Rebuild with cell 37's `REBUILD = True`
  (and narrow `STREAM` first — with `STREAM='ALL'` that rewrites semester 1 too) when you want
  the whole folder to look the same.
- The new layout has not been run against the live database — only against a synthetic frame
  with the identical column set (§6e.6). The presentation step never touches SQL, so the risk
  is confined to a column appearing in a real pull that the synthetic frame lacked, which
  would simply pass through under its raw name.
- The scale acronyms (`GR`/`TS`/`CS`/`PS`/`PR`/`PEC`) were left unexpanded by choice (§6e.5).
- Combined workbooks already on disk keep snake_case headers. Harmless — `risk_report` reads
  either — but rerun cell 39 for a consistent set.
- `risk_report.py`'s copy of the label map is a duplication that will drift. Importing it from
  `general_utils` would cost `risk_report` its standalone property; a tiny shared constants module
  would fix both and was not done.
- `flagging_utils.py` writes its own family of workbooks (`<COHORT> Simulation Flagging
  (2026).xlsx`) and was NOT relabelled — it is outside the weekly-sim chain and was not asked for.
  It will now look different from the weekly and combined workbooks.
- The per-row `Forms` column is off by default as of 18 Aug 2026 (§6f.8). Workbooks built during
  the few hours it was on still have it; harmless, `loadWeeklyFiles` strips it either way.
- Absentee rows depend on a roster file; only BOH2 has one, so DDS2 weekly sheets get the
  `Forms` column and the Session Summary but no absentee rows. Add
  `DDS2/DDS2 Roster 2026.xlsx` in the shape `loadRoster` expects to enable them.
- The Session Summary reports attendance for ONE session. There is no across-sessions view
  ("who has missed the most this semester") — `compareSessionsToSchedule` covers the session
  side of that but not the per-student side. Worth building if the tracking use case grows.
- Nothing reconciles `Forms = 0` against leave applications automatically, although
  `Combined_Leave_Report.xlsx` exists in the folder. A roster `notes` value is the only context
  that reaches the sheet today.
- `subject` was kept in the sheet against the original request so cell 39's
  `subject_mismatches` sheet survives (§6e.5). One word in `WEEKLY_SHEET_DROP_COLS` reverses it.
- The pre-existing open items in `INDEX.md` are untouched by this session — in particular
  `getInsertSqlRawform_forms_v3` still reads bare `scales->'patient_complexity'` (always NULL) and
  the dead v2 DDL/insert functions still target the v3 table name.
