# Handover — Individual Student Report redesign (V2)

**Date:** 2026-09-09
**Cohorts:** BOH2 (generic to BOH1/DDS1–3; Sim/Clinic gating identical to the original)
**Main code file:** `boh2_dds2_dds3_utils.py` (all changes appended as section 7, "REDESIGNED student report (V2)")
**Backup taken before work:** `boh2_dds2_dds3_utils.py.bak_reportv2_20260907_083404`
**Related:** [[HANDOVER_boh2_dds2_dds3_report_v3_and_timeseries.md]] (the original per-student report chain this redesigns)

---

## 0. TL;DR

A **new, visually redesigned** per-student PDF report was built alongside the original one. It is **purely additive** — every existing element-builder (`buildStudentReport`, `_addReflectionsTable`, `_addSectionPerformance`, `_addTimeSeriesPage`, `_addItemCodeCountsBarChart`, `_makeRatingsFigure`, `_computeSummaryMetrics`, …) is byte-for-byte untouched, so the old report still runs. The new report is a parallel set of `*V2` functions with a new entry point that writes to a **separate folder**.

Run it:
```python
import importlib, boh2_dds2_dds3_utils as bu
importlib.reload(bu)
bu.buildEntireCohortStudentReportsV2(engine, "BOH2")                      # whole cohort
bu.buildEntireCohortStudentReportsV2(engine, "BOH2", onlyStudents=["1775573"])  # one student, fast
```
Output: `{cohort}/Individual Student Reports V2/{studentNumber}.pdf`
(original stays at `{cohort}/Individual Student Reports/{studentNumber}.pdf`).

Sample student used throughout development: **1775573 (Amal Barakat, BOH2)**.

---

## 1. Architectural decision — additive only

**Rule the user set:** *"don't remove or change existing functions to create these elements, add new functions and use them."*

So V2 is a sibling stack, not an edit:

| Concern | Original (untouched) | New (V2) |
|---|---|---|
| Cohort loop / doc build | `buildEntireCohortStudentReports` | `buildEntireCohortStudentReportsV2` |
| Per-student flowables | `buildStudentReport` | `buildStudentReportV2` |
| Rating distribution | `_makeRatingsFigure` (pies) | `_makeRatingBarsFigureV2` (stacked bars) |
| Procedures | `_addItemCodeCountsBarChart` (vertical) | `_addProceduresV2` + `_v2ProcPanel` (horizontal meters, Sim+Clinic side by side) |
| Section performance | `_addSectionPerformance` | `_addSectionPerformanceV2` + `_v2SectionAggs` + `_v2DrawSpider` |
| Time series | `_addTimeSeriesPage` | `_addTimeSeriesPageV2` (+ `_v2SessionMeanByDate`, `_v2FullFigImage`) |
| Reflections | `_addReflectionsTable` | `_addReflectionCardsV2` + `_v2ReflectionCard` (+ `_v2IsMinorReflection`, `_v2LogTag`) |
| Summary metrics | `_computeSummaryMetrics` | reused unchanged; V2 post-processes its output |
| Section→code mapping | `Utils._mergeSection` | reused unchanged; V2 adds a fallback re-map on top |

`_computeSummaryMetrics`, `_mergeSection`, `plotStudentScoresTimeSeries`, `rubricPlot`, `_drawScoresScatter`, `createTable`, `addPlotImage`, `getBannerDrawer` are all **reused as-is**.

---

## 2. Entry points / API

### `buildEntireCohortStudentReportsV2(engine, cohort, formsTable="rawform_forms_v3", patientInfo=True, pageSize=None, leftMargin=None, rightMargin=None, topMargin=None, bottomMargin=None, subheadingStyle=None, subsubheadingStyleL=None, tableTextStyle=None, tableTextStyleSmall=None, uniColor=None, scoreMap=None, combined=None, sectionStreams=("Clinic",), outSubfolder="Individual Student Reports V2", onlyStudents=None)`
Mirrors the original cohort builder. **Differences:**
- `patientInfo` defaults to **`True`** (original defaults `False`) so the patient rows render without an explicit arg.
- `sectionStreams=("Clinic",)` — which streams get a spider chart. Pass `("Simulation","Clinic")` to add Sim.
- `outSubfolder` — output folder name (kept separate from the original).
- `onlyStudents=None` — list of student numbers (str/int, matched by str) to build just those. Testing aid.
- Class averages for the procedures chart are computed once per cohort via the existing `getCohortItemCodeAverages` (same gating: Sim skipped for DDS2/DDS3, Clinic skipped for BOH1).
- Uses `getStudentsInCohort`, `getDataDf`, `DDS2_REMOVED_STUDENTS`/`BOH2_REMOVED_STUDENTS`, `getBannerDrawer` exactly like the original.

### `buildStudentReportV2(studentDataDf, patientInfo=False, scoreMap=None, subheadingStyle=None, subsubheadingStyleL=None, tableTextStyle=None, tableTextStyleSmall=None, uniColor=None, cohort=None, classAvgItemCounts=None, combined=None, sectionStreams=("Clinic",))`
Returns a list of reportlab flowables for one student. Same shape/contract as `buildStudentReport`. `studentDataDf` is the raw `getDataDf(engine, cohort, formsTable, {"student_number": n})` frame (i.e. **before** the assessor-submitted filter — the function applies that internally, like the original).

### Page decorators — `_v2MakePageDecorators(firstLine, secondLine, groundColor="#e9edf3", sheetColor="#ffffff", bannerHeight=132)`
Returns `(firstPage, laterPage)` canvas callbacks. Paints the whole page with the soft grey ground `#e9edf3` (this is the "tinted page" look), then draws the banner (reusing `getBannerDrawer`) on the first page. Wired into the cohort builder's `doc.build(elements, onFirstPage=..., onLaterPages=...)`.

---

## 3. Page-by-page implementation

### Page 1 — Summary + Rating Distribution
- **No KPI cards.** (An earlier `_addKpiStripV2` exists in the module but is **not called** — left in place, harmless.)
- **`_v2SummaryTable(allKeys, simMetrics, clinicMetrics, hasSim, hasClinic, subheadingStyle, uniColor)`** — custom table (not `createTable`): navy header, left-aligned metric, right-aligned values (`alignment=2`), zebra rows (`ROWBACKGROUNDS [white, #dfe6f0]`), Clinic column widened (`ratio=[2.0, 1.0, 1.25]`). Returns a `KeepTogether([heading, table])`.
  - Multi-value rows render in a **compact two-line layout**: metric name + a small grey sub-label, values dot/slash-separated. Parsed from the existing `"label: n<br/> label: n"` strings via `_v2SplitPairs`; labels shortened via `_v2ShortLabel` + `_V2_METRIC_DISPLAY` (`"Patient Age Dist."`→"Patient age distribution", `"Role Counts"`→"Role counts", `"Patient Details"`→"Patient outcomes"). Separator is `" / "` for 2 values else `" · "`. Empty cells render as an em-dash.
  - Example (Clinic): `Patient age distribution / 0-6 · 7-17 · 18+` → `6 · 3 · 70`; `Role counts / Operator · Support` → `47 / 41`; `Patient outcomes / Saw pt · FTA · Cancelled <24h` → `78 · 7 · 3`.
- **`_makeRatingBarsFigureV2(simDf, clinicDf, hasSim, hasClinic)`** replaces the four pies with **two 100%-stacked horizontal bar panels** (Entrustment, Global Rating), Clinic above Simulation, on one 0–100% axis. `_v2StackedRow` draws each bar; segments ≥9% get `"lvl: n (p%)"` white inside, 3–9% get just the count inside, smaller slivers are unlabeled (the legend identifies them). Figure `facecolor=V2_PAGE` so it blends into the tinted page. A horizontal legend sits under each panel (`Level 1–4` / `GR 1–5`). `dpi=200`.

### Page 2 — Procedures Performed (Sim + Clinic side by side)
- **`_addProceduresV2(elements, panels, subheadingStyle)`** where `panels = [(title, adf, classAvg, barColor), …]` (Sim and/or Clinic, same gating as the original). Builds one figure with 1–2 subplots via **`_v2ProcPanel`**, then a single-occurrence chip block per panel.
- **`_v2ProcPanel(ax, title, adf, classAvg, barColor, maxRows, maxCodes=14)`** — "meter" bars: a light grey track (`V2_TRACK`) behind a coloured bar (blue=Sim, orange=Clinic), the **class average as a white vertical tick** with the **rounded integer** printed above it, and to the right the **count (bold) + a coloured delta** — `▲ +k` green (above cohort), `▽ −k` amber (below), `= 0` grey — where `delta = count − round(avg)`. Only codes with count ≥2 are drawn as bars (top 14, sorted by count); count-1 codes are returned as `singles`. Both panels share `maxRows` so bar thickness is identical across Sim/Clinic.
- **Single occurrences** render as **rounded pill chips** via **`_v2ChipsImage(items, fontsize=7.5, dpi=200)`** — a matplotlib image using `FancyBboxPatch` (rounded), measured text widths, wrapped rows, real gaps. reportlab's inline `<font backColor>` was rejected as "too basic" (square, tight, no gaps), hence the image approach. Amber-filled pill when the code's class average rounds >1 (you did fewer than the cohort).

### Page 3 — Performance by Section (spider, **Clinic default**)
- **`_addSectionPerformanceV2(elements, longDf, typePages, subheadingStyle, tableTextStyle, uniColor, sectionStreams=("Clinic",), minSectionsForSpider=3)`** — kept the radar but made it readable: `_v2DrawSpider` draws a 25/50/75/100 ring scale, the value printed at each vertex, a filled polygon, and a per-section summary table beneath. Only streams in `sectionStreams` get a chart (default Clinic only). The heading is glued to the first stream's chart in one `KeepTogether` (no orphaned heading).
- **Section starts on a new page** (a `PageBreak` before it in `buildStudentReportV2`, guarded by `if procPanels`). *Note: this page is intentionally sparse for now — the Section visual is parked for a later redesign pass, so the lower half is whitespace.*

### Page 4+ — Performance Over Time (original charts + rolling average)
- **`_addTimeSeriesPageV2`** is a faithful copy of `_addTimeSeriesPage` (separate scatter figure via `plotStudentScoresTimeSeries`, then the entrustment/GR rubric panels via `rubricPlot`) with three additions:
  1. a **navy rolling-average(3, per-date) line** over the score scatter (`_v2SessionMeanByDate` → reindex to xCategories → `rolling(3).mean()`), thin + semi-transparent (`linewidth=1.4, alpha=0.5`);
  2. **figure + axes facecolor = `V2_PAGE`** so both charts blend into the page;
  3. **`dpi=200`** and image ratio **`0.98`** (near the max the page fits) for larger, sharper charts.

### Page 5+ — Reflections (GR-keyed cards + collapsed log)
- **`_addReflectionCardsV2`** — substantive reflections become **cards** with a coloured left band keyed to that session's Global Rating (`V2_GR_COLORS`), a header (date · item codes · `GR n`), and a two-column body (Your reflection | Assessor feedback). Short assist/DA/FTA rows (`_v2IsMinorReflection`, student text ≤25 chars) collapse into one compact **log table** (Date · Type · Note) via `_v2LogTag` (`FTA`/`Support`/`DA / Assist`/`—`).
- **`_v2ReflectionCard(dateStr, itemCodes, studentHtml, assessorHtml, gr)`** — nested reportlab `Table`s: outer `[barCell | inner]`, inner `[header][body]`. **Column widths are based on `innerContent = innerW - 20`** (the inner cell's 10px L/R padding) — this was the fix for the GR badge spilling past the card edge.

---

## 4. Data-logic fixes (these change *numbers*, not just looks)

### 4a. Section re-map for checklist / composite codes — `_v2RemapUnmappedSections`
**Symptom.** The section spider was dominated by *Miscellaneous*.
**Root cause.** `item_section_mapping.xlsx` keys on **3-digit codes** (334/365 keys are pure `\d{3}`; `115`→PPB, `531`→Restorative, `222`→Periodontics, `011`/`022`→Diagnostics…). `Utils._mergeSection` matches the code whole (only splitting on `/` and a leading numeric `-`), so checklist-style codes carry a session prefix that never matches:
```
'BOH2 S2 115'  -> _MappingCode='BOH2 S2 115' -> UNMAPPED
'36MO (532)'   -> _MappingCode='36MO (532)'  -> UNMAPPED
'14MODB (534 577)' -> UNMAPPED
```
→ all fell to `Unmapped` → relabelled `Miscellaneous`.
**Fix.** After `_mergeSection`, for any row still `Unmapped`, pull the **first 3-digit code** (`re.findall(r"\b\d{3}\b", code)[0]`) and re-look-up the section. Wired in `buildStudentReportV2`:
```python
longDf = _mergeSection(longDf)
longDf = _v2RemapUnmappedSections(longDf)   # NEW
longDf["Section"] = longDf["Section"].replace("Unmapped", "Miscellaneous")
```
`_v2SectionLookup()` caches the code→(Section, Sub-section) maps (module global `_V2_SECTION_LOOKUP`).
**Verified** against the real mapping file:
```
BOH2 S2 115 -> 115 -> Preventive, Prophylactic and Bleaching Services
BOH2 S2 141/123 -> 141/123 -> Preventive, Prophylactic and Bleaching Services
36MO (532) -> 532 -> Restorative Services
14MODB (534 577) -> 534 -> Restorative Services
26O (531) & 64DO 65MO (532) -> 531 -> Restorative Services
BOH2-Week-1B, pe-scaling -> no 3-digit -> stays Miscellaneous (correct)
```
Only genuine non-coded items (week markers, `pe-scaling`) remain Miscellaneous. **V2 report only** — the original report's section split is unchanged.

### 4b. Patient age + patient outcomes → Operator forms only — `_v2OperatorClinicDf`
**Request.** *"In summary for patient age counts and patient outcomes only use the Operator roles ones."*
**Fix.** After `clinicMetrics = _computeSummaryMetrics(clinicDf, patientInfo=…)`, recompute just those two rows on the Operator-only clinic frame and overwrite:
```python
if patientInfo and clinicMetrics:
    _opClinic = _v2OperatorClinicDf(clinicDf)
    _opMetrics = _computeSummaryMetrics(_opClinic, patientInfo=patientInfo)
    for _k in ("Patient Age Dist.", "Patient Details"):
        if _k in clinicMetrics:
            clinicMetrics[_k] = _opMetrics.get(_k, clinicMetrics[_k])
```
`_v2OperatorClinicDf` resolves role via the same `_labelMapFromSnapshots(snaps, "role", ROLE_LABELS_FALLBACK)` used elsewhere and keeps rows whose resolved label casefolds to `"operator"` (role **CODE `O`** in v3; `SO`/`OB` excluded). This reuses `_computeSummaryMetrics` so the string format is identical and the two-line summary parser keeps working.
**Note:** *Mean Patient Age* and *Role Counts* deliberately still count all roles — only the two named rows were scoped. Easy to extend the loop if Mean Patient Age should follow.

### 4c. Time-series x-tick alignment — `_v2FullFigImage`
**Symptom.** After the tint/dpi changes the score scatter and the rubric panels no longer lined up column-for-column.
**Root cause.** `Utils.addPlotImage`→`createPlotImage` saves with **`bbox_inches='tight'`**, which trims each figure to its own content. The scatter's y-label/legend differ in width from the rubric's, so tight-trim removed different left margins; scaled to the same width afterwards, the plot rectangles started at different fractions.
**Fix.** `_v2FullFigImage(fig, ratio)` embeds the figure **without** tight-trimming (`fig.savefig(buf, facecolor=fig.get_facecolor())`, no `bbox_inches`). Both time-series figures are figsize-14 wide with identical `subplots_adjust(left=0.09, right=0.985, …)`, so the full-frame images have the plot rectangle at the same fraction → **perfect alignment** (verified by stacking both PNGs). Used for both the scatter and the rubric image in `_addTimeSeriesPageV2` only.

---

## 5. Palette / constants (all new, module-level)
```
V2_SIM_COLOR   = "#2f6fb0"   V2_CLINIC_COLOR = "#c8622d"
V2_INK = "#1b2230"  V2_MUTED = "#5b6478"  V2_LINE = "#d7dbe4"  V2_PAGE = "#e9edf3"
V2_TRACK = "#d7dce4"  V2_UP = "#2e8b57"  V2_DOWN = "#d98a2b"  V2_EQ = "#8a90a0"
V2_CHIP_BG = "#dfe4ee"  V2_CHIP_AMBER_BG = "#f6e3c9"  V2_CHIP_AMBER_TEXT = "#b5691f"
V2_GR_COLORS  = {1:#c1443b, 2:#e0863a, 3:#e7c757, 4:#8fbf5a, 5:#3e9b57}   # rating ramp, reused everywhere
V2_ENT_COLORS = {1:#c1443b, 2:#e0863a, 3:#8fbf5a, 4:#3e9b57}
```

---

## 6. Gotchas / traps (read before touching these)
- **Higher DPI** for reused figures is set by giving the figure `dpi=200` (or `fig.set_dpi(200)`); `createPlotImage` saves at the figure's dpi (no explicit dpi arg). Don't rely on an `addPlotImage(dpi=…)` — there isn't one.
- **Page tint** works because `createPlotImage` uses the *figure's* facecolor and `bbox_inches='tight'` fills the pad with it. Set `fig.patch.set_facecolor(V2_PAGE)` **and** each `ax.set_facecolor(V2_PAGE)` (some existing draw helpers leave axes white).
- **`bbox_inches='tight'` desyncs stacked figures** — see §4c. Use `_v2FullFigImage` when two images must align.
- **reportlab `<font backColor>`** gives no rounded corners / padding — chips are a matplotlib image instead (`_v2ChipsImage`). Keep chip text non-breaking (`" "→"&nbsp;"` inside a chip) so a pill never splits across a line.
- **KeepTogether orphan** — a bare heading + a large `KeepTogether(image+table)` can push the block to the next page, orphaning the heading. Group the heading *into* the first `KeepTogether` (done in `_addSectionPerformanceV2`).
- **Reflection card widths** must subtract the inner cell padding (`innerContent = innerW - 20`) or the right-aligned GR badge spills past the border.
- **`variableUtils.itemSectionMappingFile`** is a Windows absolute path — `_loadSectionMapping()` works on the user's machine but not in a Linux sandbox; test section logic against the file by relative name there.
- The two time-series builders (`_addTimeSeriesPage` v1 and `_addTimeSeriesPageV2`) share several identical lines; when editing, anchor replacements on V2-unique text (the rolling-avg legend line / `facecolor=V2_PAGE`) so you don't hit v1.

---

## 7. Verification status
- Every page was rendered locally with dummy/representative data (reportlab + matplotlib + `pdftoppm`) and eyeballed; the section re-map and Operator-role filter were verified against the **real** `item_section_mapping.xlsx` and the role-code fallback.
- **Not yet run end-to-end against live Postgres by me** — the sandbox has no DB. The user runs `buildEntireCohortStudentReportsV2(engine, "BOH2", onlyStudents=["1775573"])` each iteration and confirms.
- `py_compile`/`ast.parse` clean after every change. Original functions confirmed **byte-identical** to the pre-work backup (diff of `_addTimeSeriesPage`).

## 8. Open items / next
- **Section page redesign** is parked (user: "we will come at the end to this"). The page is currently half-empty; fill it (e.g. add the Sim spider, a cohort-comparison overlay, or per-section detail) or let it share the page.
- Decide whether **Mean Patient Age** should also be Operator-only (currently all roles).
- `sectionStreams` default is Clinic-only; expose it from a notebook cell if per-cohort control is wanted.
- Consider promoting the section 3-digit re-map into `_mergeSection` itself so the original report benefits too (currently V2-only, by design).
