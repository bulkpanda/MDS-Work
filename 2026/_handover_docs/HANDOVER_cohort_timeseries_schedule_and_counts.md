# Handover — Cohort Time-Series PDF: surname order, session timetable, Smile Squad, item-code counts

**Date:** 2026-08-18
**Cohorts:** BOH2 primarily; every change is cohort-generic and applies to BOH1 / DDS1 / DDS2 / DDS3
through the same shared functions.
**Code file:** `boh2_dds2_dds3_utils.py` (only file changed)
**Data file changed:** `BOH2/BOH2 Sim Sessions 2026.xlsx` (15 FHY rows + a BREAK row added)
**Backups:** `boh2_dds2_dds3_utils.py.bak_20260818_035857` (pre-change),
`boh2_dds2_dds3_utils.py.bak_20260818_041958` (pre-revision 1, §12),
`boh2_dds2_dds3_utils.py.bak_20260818_060622` (pre-revision 2, §12),
`BOH2/BOH2 Sim Sessions 2026.xlsx.bak_20260818_035857`
**Notebook:** `main.ipynb` cell 11 — **unchanged**, no edits required. The new behaviour is on by
default.
**Related:** [[HANDOVER_boh2_dds2_dds3_report_v3_and_timeseries]] (the chart rework this builds on),
[[HANDOVER_dds2_weekly_sim_v3_multidate]] (§6d.4 — where the session-schedule and roster files came
from).

---

## 1. What changed, in one screen

`buildCohortTimeSeriesPdf` — the `for ft in ["Clinic","Simulation"]` loop in cell 11 — now:

| # | Change | Applies to | Off switch |
|---|---|---|---|
| 1 | Students ordered by **surname**, not by display name | Sim + Clinic | `rosterOrder=False` |
| 2 | **Date range** the charts cover, on the first-page banner | Sim + Clinic | `dateRangeInBanner=False` |
| 3 | **Time Management** y-axis follows the scale's real level count (5 *or* 2) | Sim + Clinic | — (auto) |
| 4 | No **"Complex"** legend key on Simulation charts | Sim | — (auto) |
| 5 | x ticks include every **timetabled session**; missed ones get a **purple dot at y=0** on the scatter *and* all five rubric panels | Sim | `useSchedule=False` |
| 6 | **Smile Squad** points drawn in **orange**, and the old `" SS"` label suffix removed | Clinic (and anywhere else SS forms appear) | `SMILE_SQUAD_LABEL_SUFFIX = " SS"` |
| 7 | **Item Code counts table** (`Item Code / Count / Cohort Avg`) beside the charts, with code variants merged | **Clinic only by default** | `itemCountsTable=` |
| 8 | Page **widened 1.25×** when a table is drawn; charts render at exactly their previous size | whichever type gets the table | `pageWidthFactor=1.0` |

Setting the switches to their "off" value reproduces the pre-change PDF byte-for-byte in
layout (verified — see §10).

---

## 2. Call signature

```python
buildCohortTimeSeriesPdf(
    *, engine, cohort, outPath, bannerTitle,
    formType=None, formsTable="rawform_forms_v3",
    scoreMap=None, subheadingStyle=None, uniColor=None,
    pageSize=None, rightMargin=36, leftMargin=36, topMargin=48, bottomMargin=36,
    combined=None,
    # --- new 2026-08-18 ---
    pageWidthFactor=1.25,      # widens the PAGE only; charts keep their old size
    itemCountsTable=ITEM_COUNTS_FORM_TYPES,   # ("Clinic",) — True / False / tuple of types
    normalizeItemCodes=True,   # merge 'BOH2 S2 011' + '011-COE' -> '011' in that table
    useSchedule=True,          # timetable-driven x ticks + purple missing markers
    scheduleYear=2026,         # picks the "<COHORT> Sim Sessions <year>.xlsx" file
    scheduleMaxDate=None,      # default: today — see §5.2
    rosterOrder=True,          # surname ordering
    dateRangeInBanner=True,    # "Covering 10 Feb 2026 – 18 Aug 2026"
)
```

Cell 11 is unchanged and picks up every default:

```python
for ft in ["Clinic", "Simulation"]:
    buildCohortTimeSeriesPdf(
        engine=engine, cohort="BOH2",
        outPath=f"BOH2/BOH2 {ft} Time Series ({today}).pdf",
        bannerTitle=f"BOH2 {ft} – Performance Over Time",
        formType=ft, subheadingStyle=subheadingStyle, uniColor=uniColor, combined=True)
```

---

## 3. New public functions

All live in `boh2_dds2_dds3_utils.py` and are exported by `from boh2_dds2_dds3_utils import *`
(deliberately **not** underscore-prefixed — notebook cells must be able to call them; see the
`import *` underscore rule).

```python
getScheduledSessionDates(cohort, formType=None, year=2026, path=None,
                         maxDate=None, minDate=None) -> list[str]      # "%Y-%m-%d"
orderStudentsBySurname(studentsDf, cohort=None, year=2026, rosterMap=None,
                       nameCol="student_name", idCol="student_number") -> DataFrame
rubricAxisMax(label, series=None, snapshots=None, default=None, headroom=0.5) -> float | None
makeItemCodeCountsTable(df, classAvgItemCounts=None, title=None, titleStyle=None,
                        headerColor=None, fontSize=7.5, maxWidth=None,
                        maxRowsPerGroup=26, maxGroups=4, sortBy="count",
                        asList=False, normalizeCodes=True,
                        fitColumns=True, cellPad=7) -> Flowable | list | None
wantsItemCountsTable(itemCountsTable, formType) -> bool
normalizeItemCodeCounts(counts, classAvgItemCounts=None) -> (Series, dict)
formatDateRange(dates, fmt="%d %b %Y", sep=" – ") -> str
typeLabelFor(formType) -> str
```

Private helpers: `_scheduleFrame`, `_rosterNameMap`, `_surnameKey`, `_scaleMaxFromSnapshots`,
`_missingSessionMarks`, `_countsColumnWidths`.

New module constants:

```python
MISSING_SESSION_COLOR = "purple"        SMILE_SQUAD_COLOR = "darkorange"
COMPLEX_PATIENT_COLOR = "red"           DEFAULT_POINT_COLOR = "blue"
SMILE_SQUAD_LABEL_SUFFIX = ""           # was " SS"; colour + legend carry it now
SCHEDULED_FORM_TYPES = ("Simulation",)  # only these consult the timetable
ITEM_COUNTS_FORM_TYPES = ("Clinic",)    # only these get the counts table
SCALE_SNAPSHOT_KEYS = {...}             # snapshot key aliases per rubric
ITEM_COUNTS_MAX_ROWS_PER_GROUP = 26     ITEM_COUNTS_MAX_GROUPS = 4
ITEM_COUNTS_GUTTER_PAD = 12             ITEM_COUNTS_MIN_SIDE_WIDTH = 170
```

---

## 4. Surname ordering (change 1)

`getStudentsInCohort` returns `student_number | student_name | student_email`, ordered by
`student_name` in SQL — i.e. by **first** name. `orderStudentsBySurname` re-sorts it.

**Why the roster is authoritative.** A display name cannot be split reliably. From
`BOH2/BOH2 Roster 2026.xlsx`:

| student_name | first_name | last_name | last-token guess |
|---|---|---|---|
| Lexy Mhaye San Pablo Huang | Lexy Mhaye San Pablo | Huang | Huang ✓ |
| Kate Mclennan Arnott | Kate | Mclennan Arnott | Arnott ✗ |
| Tala Aktam Anjrini | Tala | Aktam Anjrini | Anjrini ✗ |

`_surnameKey(name, number, rosterMap)` therefore returns
`(last_name, first_name, number)` when the student number is on the roster, and
`(last_token, everything_before_it, number)` when it is not. **Both key shapes sort in one list**,
so the PDF reads as a single A–Z run rather than "roster students, then the rest".

The roster is read through `general_utils.loadRoster(cohort, year)` →
`<COHORT>/<COHORT> Roster <year>.xlsx`. Only BOH2 has one today; every other cohort silently uses
the last-token fallback. `_rosterNameMap` catches every exception (missing file, missing columns,
`general_utils` not importable) and returns `{}`.

---

## 5. Session timetable (changes 5 + the FHY data)

### 5.1 The data file

`BOH2/BOH2 Sim Sessions 2026.xlsx` already held the SHY timetable (created for the weekly-sim
workbooks — see `HANDOVER_dds2_weekly_sim_v3_multidate.md` §6d.4). Columns:

```
cohort | period | week_no | date | weekday | task | is_choice_week
       | choice_options | counts_toward_total | notes
```

**Added this session:** the 15 FHY Tuesdays supplied by the user, plus the mid-semester BREAK row.
`week_no` is the **ISO week number**, matching the convention the SHY rows already used
(2026-06-30 → 27):

| period | week_no | date | weekday | task | counts_toward_total |
|---|---|---|---|---|---|
| FHY | 7–14 | 2026-02-10 … 2026-03-31 | Tue | *(blank — not supplied)* | 1 |
| FHY | 15 | *(blank)* | | BREAK | 0 |
| FHY | 16–22 | 2026-04-14 … 2026-05-26 | Tue | *(blank)* | 1 |
| SHY | 27–43 | 2026-06-30 … 2026-10-20 | Tue | *(as before, untouched)* | 1 / 0 |

FHY task names were not supplied and are blank. They are **not** used by the time series (only
`date` is), so filling them in later is optional and safe.

### 5.2 How the dates reach the chart

```python
observedDates = set(studentDataDf["datetimeutc"].dt.strftime("%Y-%m-%d"))
xCategories   = sorted(observedDates | set(scheduledDates))   # union — never a subtraction
missingDates  = sorted(set(scheduledDates) - observedDates)
```

Three rules worth knowing:

1. **Observed dates are never dropped.** A form on a date that is not on the timetable (a catch-up,
   an extra session) keeps its own column. This was an explicit requirement.
2. **Clinic never consults the timetable.** `SCHEDULED_FORM_TYPES = ("Simulation",)` and
   `getScheduledSessionDates` returns `[]` for any other `formType`. The file is a *Sim* Sessions
   file and clinic attendance is not timetabled.
3. **Future sessions are capped at today** (`scheduleMaxDate=None` → `pd.Timestamp.today()`).
   Without the cap, BOH2 SHY runs to 2026-10-20 and every student's chart would carry nine empty
   purple columns for sessions that have not happened — a wall of false absences. Pass an explicit
   `scheduleMaxDate="2026-12-31"` if you ever want the whole planned year drawn.

`getScheduledSessionDates("BOH2", "Simulation", maxDate="2026-08-18")` → 23 dates
(15 FHY + 8 SHY). BREAK rows drop out automatically because their `date` is blank.

### 5.3 The purple markers

`_missingSessionMarks(ax, missingDates, xCategories, y=0, size=45)` is shared by the scatter and
by `rubricPlot`, so a missed session reads as **one vertical run of purple down the whole page**.
Dates not present in `xCategories` are ignored rather than shifting the axis.

On rubric panels the floor is dropped to `-0.06 * maxY` when any marker is drawn, so the dot is not
bisected by the frame. On the scatter the y-limit was already `(-10, 120)`, so no adjustment is
needed.

Legend: the scatter carries **"No form for scheduled session"** only when at least one purple dot
was actually drawn (§6).

---

## 6. Data-driven legend (change 4) and Smile Squad colour (change 6)

The legend used to be a fixed one-entry list — a red "Complex" key printed on every chart including
Simulation, where patient complexity does not exist. It is now built from what was drawn:

```python
legendSpec = [
    (drewComplex,     "Complex",                       COMPLEX_PATIENT_COLOR),
    (drewSmileSquad,  "Smile Squad",                   SMILE_SQUAD_COLOR),
    (drewMissing,     "No form for scheduled session", MISSING_SESSION_COLOR),
]
```

No red point → no "Complex" key. That satisfies "for Sim there is no Complex label" **without** a
form-type flag, and also removes it from a Clinic chart where no complex patient was seen.

`_getColor` precedence is now **Smile Squad → Complex → default**:

```python
if row["NA_Flag"]:                          return "gray"
if isSmileSquadClinic(row.get("Clinic")):   return SMILE_SQUAD_COLOR   # "darkorange"
if row["Patient Complexity"] == "complex":  return COMPLEX_PATIENT_COLOR
return DEFAULT_POINT_COLOR
```

Smile Squad wins because picking those sessions out at a glance is the whole point of colouring
them. `isSmileSquadClinic` matches both the v3 code `"SS"` and the legacy label `"Smile Squad"` —
see [[smile-squad-boh2-swap-v3]].

**The `" SS"` label suffix is gone.** Point labels used to read `532 SS`; the orange marker plus
the legend key now say the same thing without adding text to an already-crowded scatter.
`SMILE_SQUAD_LABEL_SUFFIX = ""` at module level, or `_drawScoresScatter(..., smileSquadSuffix=" SS")`
per call, restores it.

**This also changes the per-student reports** (`_addTimeSeriesPage` → `buildStudentReport`), which
share `_drawScoresScatter` / `_getColor`: Smile Squad points there are orange too, and a chart with
no complex patients no longer prints a "Complex" key. That is consistent with the request; revert by
restoring the old `_getColor` body if it is ever unwanted.

---

## 7. Time Management axis (change 3)

Old: `("Time Management", "red", 5.0)` — hardcoded. A student assessed on a **2-level** template got
their whole line squashed into the bottom fifth of the panel.

New, resolved **per student**:

```python
rubricAxisMax("Time Management",
              series=rubricDf.get("Time Management"),
              snapshots=studentDataDf["context_schema_snapshot"],
              default=5.0)
```

Resolution order:

1. **`context_schema_snapshot`** — the form's own field definition, the authoritative answer
   because it says how many levels the student *could* have been given, not how many they scored.
   `_scaleMaxFromSnapshots` scans each snapshot (list of `{key, options:{code: label}}`, accepted
   as a parsed list *or* a JSON string) for any of
   `("scale-time-mgmt", "scale-time-management", "time-mgmt", "time_management")` and takes the
   highest **integer-parsable** option key. Non-numeric options (an "N/A" choice) cannot inflate
   the axis.
2. **Observed maximum**, rounded up — only when no snapshot publishes the scale.
3. **`default`** (5.0) — when neither resolves.

`headroom=0.5` is added, so 5 levels → `maxY=5.5` (unchanged from before) and 2 levels → `2.5`.

Only Time Management is resolved dynamically; Entrustment / Global Rating / Communication /
Professionalism keep their fixed ceilings because every template in use publishes the same level
count for them. `SCALE_SNAPSHOT_KEYS` already carries their aliases if that changes.

---

## 8. Item-code counts table + page width (changes 7 + 8)

### 8.0 Which form types get it

`itemCountsTable=` accepts **True** (every type), **False** (none), or a **collection of form-type
names** matched case-insensitively. It defaults to `ITEM_COUNTS_FORM_TYPES = ("Clinic",)`:

```python
itemCountsTable=ITEM_COUNTS_FORM_TYPES        # default — Clinic only
itemCountsTable=True                          # Simulation as well
itemCountsTable=False                         # nowhere
itemCountsTable=("Clinic", "Simulation")      # explicit
```

Simulation is excluded by default because a sim session **is** one task: the code list just
restates the timetable and repeats what the scatter labels already show. Clinic is where a student
sees a genuinely varied mix of items, so the counts are worth tabulating.

`wantsItemCountsTable(itemCountsTable, formType)` resolves it once at the top of
`buildCohortTimeSeriesPdf`, and that one boolean gates three things: whether the cohort-averages
query runs, whether the page is widened at all, and whether the per-student layout has a second
column. **A form type with no table keeps the original page width** — otherwise the Simulation PDF
would be 1.25× wide with an empty gutter.

### 8.0b Item-code normalisation

DASH stores the same clinical item under several labels, which split one item across three rows:

```
011           BOH2 S2 011        011-COE          →  all three are item 011
LA            BOH-DD                              →  no 3-digit code, left alone
```

`normalizeItemCodeCounts(counts, classAvgItemCounts)` (on by default via
`makeItemCodeCountsTable(normalizeCodes=True)` /
`buildCohortTimeSeriesPdf(normalizeItemCodes=True)`) runs every label through the existing
`_shortItemCode` — the same reduction the scatter point labels already use — and sums the counts
of everything that lands on the same code. Labels with no standalone 3-digit code fall through
`_shortItemCode` unchanged, which is exactly why `LA` and `BOH-DD` survive as their own rows.

**Cohort averages are summed across merged codes, and that is exact,** not an approximation: the
average is *mean forms per student per code*, and the mean of a sum is the sum of the means.

Scope is the **counts table only** — the scatter labels already did this, and the individual
student reports' item-code bar chart and every Excel export still use raw DASH labels. Pass
`normalizeCodes=False` / `normalizeItemCodes=False` for the raw labels in the table too.

### 8.1 Where the numbers come from

| Column | Source |
|---|---|
| `Item Code` | `studentDataDf["item_codes"]` exploded — the same column the individual-report bar chart uses |
| `Count` | `value_counts()` of that explode (forms per code, assessor-submitted only) |
| `Cohort Avg` | `getCohortItemCodeAverages(engine, cohort, formType=...)` — mean forms-per-code **per student** across the cohort |

This is the **identical pairing** the individual student reports already use in
`_addItemCodeCountsBarChart`, so the table and that bar chart agree by construction. The averages
query runs **once per PDF**, not once per student, and is wrapped in try/except — if it fails, the
PDF still builds and the table simply drops the `Cohort Avg` column. When `formType=None` the
average is skipped entirely, because a per-type mean is meaningless across pooled types.

**Smile Squad forms ARE counted, on both sides of the table.** Student counts: `getDataDf` runs
`applySmileSquadSwap`, which moves SS `student_data` into `assessor_data` **and re-derives
`item_codes` from it**, so SS rows survive the `submitted_by_assessor` filter and their codes are
counted. Cohort average: `getCohortItemCodeAverages` → `getStudentItemCodeDf` reads
`_effChecklistsSrc("BOH2")`, which is `(student_data->'checklists' || checklists)` because BOH2 is
in `STUDENT_FALLBACK_COHORTS`, so student-filled SS checklists are in the average too. The two
sides are consistent. There is currently **no way to split SS out of the counts** — say so if you
want a separate row or an SS column.

Codes are sorted by descending count (`sortBy="count"`; pass `"code"` for alphabetical).

### 8.2 Layout — beside the charts, not underneath

The charts are **height**-limited: `addPlotImage` takes
`min(max_width/w, max_height/h)`, and a 16×22 in figure on a 11.69×16.54 in page always binds on
height. So the width the page gains is width the charts will *never* use. The table goes in that
gutter:

```
contentWidth = pageSize[0] * pageWidthFactor - leftMargin - rightMargin   # 1148 pt
chartWidth   = max(f.drawWidth for f in chartFlowables)                   #  731 pt
gutter       = contentWidth - chartWidth - ITEM_COUNTS_GUTTER_PAD         #  405 pt
```

`gutter >= ITEM_COUNTS_MIN_SIDE_WIDTH` (170 pt) → a 2-column reportlab `Table`
`[[chartFlowables, countsTable]]`, one page per student. Otherwise the table **stacks underneath**
at full width, splitting into up to 4 side-by-side `Item Code / Count / Cohort Avg` groups
(balanced, so 30 codes become 15+15, not 26+4).

`pageWidthFactor=1.25` gives 1052 × 1191 pt. Page **height is untouched**, and every chart is
scaled against `chartPageSize` — a snapshot of the *original* `variableUtils.pageSize` taken before
the widening — so the graphs are pixel-identical to the previous release.

### 8.2b Column widths are content-fitted, not stretched

`_countsColumnWidths` measures every column against its widest actual cell with
`pdfmetrics.stringWidth` and adds `cellPad` (7 pt) a side. `maxWidth` is a **ceiling**, not a
target: the table only ever scales *down*. Item codes are three characters, so in practice the
**headers** set the widths:

| Column | Width | Set by |
|---|---|---|
| Item Code | ~50 pt | the header, not the codes |
| Count | ~36 pt | the header |
| Cohort Avg | ~55 pt | the header |
| **total** | **~141 pt** | |

The first release split the columns 3 : 1 : 1.3 and stretched them to fill the gutter, which gave
the code column ~55% of a table already wider than its contents. `fitColumns=False` restores that.

The `LEFTPADDING` / `RIGHTPADDING` in the `TableStyle` are set from the same `cellPad`. They have
to match: reportlab's 6 pt default would re-wrap cells that the measurement said would fit.

Column widths are shared across the side-by-side groups (position *j* in every group gets the same
width), so the group separator rules line up.

### 8.3 Three traps found here

1. **`addPlotImage`'s `pageSize` default is bound at import time**
   (`def addPlotImage(fig, ratio=None, pageSize=variableUtils.pageSize)` in `Utils.py`).
   Reassigning `variableUtils.pageSize` at runtime would *not* change it. Every call in this
   function now passes `pageSize=chartPageSize` explicitly. Do the same in any new code that wants
   a page size other than the module default.

2. **`KeepTogether` cannot go inside a `Table` cell.** `KeepTogether.wrap()` returns a height of
   `0xFFFFFF`, which the table reads as infinitely tall and then refuses to lay out:

   ```
   LayoutError: Flowable <Table 1 rows x 2 cols(tallest row 16777215)> with cell(0,0) …
                too large on page 2 in frame 'normal'
   ```

   `makeItemCodeCountsTable(..., asList=True)` returns a plain
   `[Paragraph, Spacer, Table]` list for exactly this reason. Anything destined for a cell must be
   a plain flowable or a list of them.

3. **The first-page spacer budget is only ~4 pt.** Frame height is
   `1190.88 - 48 - 36 = 1106.88`; the per-student composite is a single unsplittable flowable up to
   `(1190.88 - 72 - 72) * 0.95 = 994.54` pt tall; the student title costs ~36 pt. So
   `spacer ≤ 76.3`. Raising the leading `Spacer(1, 72)` to 96 to clear a taller banner pushed
   student 1's charts onto page 2 and left a near-empty first page. The spacer stays at **72** and
   the **banner** was sized to fit under it instead (§9).

---

## 9. Banner date range (change 2)

`coveredDates` accumulates every student's `xCategories` during the loop and is read after it,
because `getBannerDrawer` is only invoked by `doc.build()` at the very end:

```python
doc.build(elements, onFirstPage=getBannerDrawer(
    bannerTitle, f"Covering {formatDateRange(coveredDates)}", bannerHeight=116))
```

→ `Covering 10 Feb 2026 – 18 Aug 2026`. `formatDateRange` collapses to a single date when the
range is one day, so the banner never reads "X – X".

**`bannerHeight=116` is load-bearing.** `getBannerDrawer` draws line 2 at a *fixed* 108 pt from the
top of the page (`topOffset=72 + lineSpacing=36`) regardless of the rectangle height — its own
docstring warns about this. The default `bannerHeight=82` used before would have painted the date
range on white. 116 clears the 24 pt font's descenders (~113 pt) and still stops just above where
the first student's title begins (`topMargin 48 + spacer 72 = 120`).

---

## 10. Verification

`test_timeseries.py` (kept alongside the working copy, not shipped into the repo) — no database:
`getStudentsInCohort`, `getDataDf` and `getCohortItemCodeAverages` are monkey-patched with frames
carrying the exact column set the real SQL returns, including `assessor_data` with nested
`scales`, `context_schema_snapshot`, `item_codes`, `clinic="SS"` and `role="O"`.

**69 checks, all passing:**

- schedule: 23 dates found (15 FHY + 8 SHY), starts 2026-02-10, BREAK rows dropped, `maxDate`
  honoured, future sessions excluded by the default cap, Clinic returns `[]`, unknown cohort
  returns `[]` without raising.
- ordering: multi-token surnames resolved from the roster; no-roster fallback still produces a
  single sorted list; the rendered PDF text confirms Anjrini → Huang → Mclennan Arnott order.
- scale: 5-level snapshot → 5.5; 2-level → 2.5; snapshot beats observed data; no snapshot →
  observed; nothing → default; non-numeric options ignored.
- render: both PDFs written; **Clinic** widened to 1.25× with the table, **Simulation** left at the
  original 841.68 pt with no table; height unchanged; banner date range present; **one page per
  student** (3 students → 3 pages, Sim *and* Clinic). `itemCountsTable=True` puts the table and the
  wide page back on Simulation.
- column widths: the table comes out ~141 pt against a `maxWidth` of 400 (content-fitted, not
  stretched); the code column takes 36% rather than 55%; every column clears its header;
  `maxWidth` still caps it when genuinely too narrow; `fitColumns=False` restores the old
  stretched 3:1:1.3 ratio.
- selector: `True` / `False` / default tuple / bare string / case-insensitivity;
  `formType=None` matches only explicit `True`.
- normalisation: `'011-COE'` + `'BOH2 S2 011'` + `'011'` merge to `'011'` with counts added
  (10+5+2=17); `'BOH2 S2 141'` folds into `'141'`; `'LA'` and `'BOH-DD'` survive untouched; no
  `BOH2 S2` row remains; averages summed exactly; **total count preserved**;
  `normalizeCodes=False` keeps the raw labels.
- Smile Squad: no point label ends in `" SS"` any more, and `smileSquadSuffix=" SS"` brings it back.
- markers: Simulation legend has no "Complex" key; one purple dot per missing session, all at
  `y=0`; Clinic legend has "Complex" **and** "Smile Squad" but no missing-session key; orange
  Smile Squad points drawn; the 2-level student's Time Management panel tops out at 2.5; the
  rubric floor drops below 0 when purple dots are drawn; a "No data available" panel still draws
  them.
- counts table: header columns correct with and without averages; `None` for an empty frame; 60
  codes split into 3 balanced groups of 20.
- regression: with the schedule **and** roster files renamed away, the PDF still builds; with
  `pageWidthFactor=1.0, itemCountsTable=False, useSchedule=False, rosterOrder=False,
  dateRangeInBanner=False` the page returns to the original 841.68 pt width.

`python -m py_compile boh2_dds2_dds3_utils.py` passes.

**Not verified against the live database** — the user runs cell 11. Everything above was checked
against synthetic frames shaped like the v3 query output and against the real
`BOH2 Sim Sessions 2026.xlsx` / `BOH2 Roster 2026.xlsx` files.

---

## 11. Open items

- **Run cell 11 against the live DB** and check one BOH2 Simulation page: the purple dots should
  match the sessions that student actually missed, and the counts table's `Cohort Avg` should match
  the bar chart in the same student's individual report.
- **FHY task names** are blank in `BOH2 Sim Sessions 2026.xlsx`. Nothing reads them today; fill in
  if you want `compareSessionsToSchedule` output to name the FHY tasks.
- **No roster for BOH1 / DDS1 / DDS2 / DDS3**, so those cohorts get the last-token surname
  fallback. Adding `<COHORT>/<COHORT> Roster 2026.xlsx` fixes it with no code change.
- **No `Sim Sessions` file for any cohort but BOH2**, so change 5 is BOH2-only in practice. Adding
  `<COHORT>/<COHORT> Sim Sessions 2026.xlsx` (same columns) turns it on with no code change.
- If the wide page is awkward to print, `pageWidthFactor=1.0` moves the table underneath the charts
  (each student then takes two pages).
- **Smile Squad forms are pooled into the item-code counts**, not broken out. If staff need to see
  "how many of these were Smile Squad", that needs a fourth column or a second table — not built.
- Normalisation merges on the **3-digit code only**, so a genuinely different item that happens to
  share a code with another label would silently merge. Nothing in the 2026 BOH2 clinic data does
  this, but check the row count against `normalizeCodes=False` if a new checklist family appears.

---

## 12. Revision log

**2026-08-18, same day, after review of the first Clinic output.** Backup
`boh2_dds2_dds3_utils.py.bak_20260818_041958` is the state *before* these four:

1. `itemCountsTable` changed from a bool to a **form-type selector**, defaulting to
   `("Clinic",)` — the table is off for Simulation (§8.0).
2. The page is **only widened when that form type actually gets a table**, so the Simulation PDF
   keeps its original width.
3. **Item-code normalisation** added (§8.0b): `BOH2 S2 011` / `011-COE` / `011` collapse to `011`,
   `LA` and `BOH-DD` stay. Counts table only.
4. The `" SS"` **label suffix removed** from Smile Squad scatter points, now that they are orange
   with a legend key (§6).

**2026-08-18, second revision, after the Clinic table came out too wide.** Backup
`boh2_dds2_dds3_utils.py.bak_20260818_060622` is the state before these two:

5. Counts-table columns are **content-fitted** via the new `_countsColumnWidths` (§8.2b) — the
   table is ~141 pt instead of filling whatever gutter it was handed, and `maxWidth` became a
   ceiling. `fitColumns=False` / `cellPad=` on `makeItemCodeCountsTable` tune it.
6. `pageWidthFactor` default **1.45 → 1.25** (page 1052 pt), since a tight table no longer needs a
   405 pt gutter. Charts are unaffected either way — they size against `chartPageSize`.
