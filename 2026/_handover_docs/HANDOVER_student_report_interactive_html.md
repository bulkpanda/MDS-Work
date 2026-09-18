# HANDOVER — Interactive HTML student report (`student_report_html_utils.py`)

**Date:** 2026-09-15
**Author session:** Interactive HTML conversion of the per-student "Till Date performance report"
**Scope:** New, self-contained module that produces one interactive `.html` per student
(Apache ECharts inlined) mirroring the PDF V2 report, page-for-page.
**Cohorts:** BOH2 first (sample), but cohort-generic (BOH1/DDS1/DDS2/DDS3 handled by the same gating as the PDF V2 driver).
**Main files:**
- `student_report_html_utils.py` (new, project root)
- `_assets/echarts.min.js` (new, vendored ECharts 5.5.1 — inlined into every report)
- PDF source of truth reused unchanged: `boh2_dds2_dds3_utils.py` (the `*V2` stack)

---

## 1. Why this exists / what the student asked for

Students wanted the per-student report to be **explorable** rather than a static PDF:
filter by Simulation/Clinic, hover charts for detail, zoom the timeline, search reflections,
less on-page clutter. The PDF banner already tells them *"We are working on an interactive
live dashboard for future reports"* — this is that dashboard, delivered as a single HTML file
per student they can open offline or receive by email.

**Non-negotiable design constraint (Kunal):** *keep the quantized functions (one function per
element), a new utils file, keep the colour grading and formatting the same as the PDF.*

---

## 2. Architectural decisions

| Decision | Choice | Why |
|---|---|---|
| Chart library | **Apache ECharts 5.5.1**, vendored + **inlined** | Native radar/spider, 100%-stacked bars, scatter, line; rich hover, legend-toggle, `dataZoom`. One library covers all five chart types with the least custom code. |
| Packaging | **Self-contained single `.html` per student** | Safe to email / open offline anywhere; no broken relative links. Cost: ~1.05 MB/file (1 MB is the shared ECharts lib). |
| Code reuse | **Additive only.** The module *imports and calls* the existing V2 data functions in `boh2_dds2_dds3_utils.py`; it never re-implements a number. | HTML figures can never drift from the PDF. Nothing in `boh2_dds2_dds3_utils.py` is edited. |
| Two layers | **DATA** (`prepareReportData`, needs pandas + DB) vs **RENDER** (pure-Python `render*`, no pandas/DB) | The render layer is trivially testable/editable and can be run anywhere; only data prep needs the engine. |
| One function per element | Every visible block has its own `render*` (HTML fragment) **and** its own `_ec*`/`render*` builder in the embedded JS | Matches the PDF V2 stack's one-function-per-element structure; each block is edited in exactly one place. |
| Colour | `PALETTE` is built **from the imported `V2_*` constants** | Single source of truth for colour across PDF and HTML. |

---

## 3. Module layout (`student_report_html_utils.py`)

```
PALETTE                         # dict built from bu.V2_* + variableUtils.uniColor (navy)

# ── DATA LAYER (pandas + DB) ─────────────────────────────────────────────
prepareReportData(engine, cohort, studentNumber, ...) -> dict   # the one entry point
  _summaryBlock(...)            # summary rows (reuses bu._v2SplitPairs / _v2ShortLabel / _V2_METRIC_DISPLAY)
  _ratingsBlock(...)            # entrust+GR counts (reuses bu._v2EntCounts / _v2GrCounts)
  _proceduresBlock(...)         # item-code counts vs class avg (same panel gating as V2)
  _sectionsBlock(...)           # per-section aggregates (reuses bu._v2SectionAggs / _sectionLabel)
  _timeseriesBlock(...)         # per-item scatter + rubric + rolling avg (reuses bu._v2SessionMeanByDate)
  _reflectionsBlock(...)        # GR cards + assist/FTA log (reuses bu._v2VisibleReflection / _v2LogTag / truncateText)
  _streamGating(...)            # DDS3 no Sim; BOH1/DDS1 no Clinic  (identical to buildStudentReportV2)

# ── RENDER LAYER (pure Python) ───────────────────────────────────────────
renderBanner / renderIntro / renderFilterBar
renderSummary / renderRatingDistribution / renderProcedures
renderSectionPerformance / renderTimeSeries / renderReflections
_css() / _reportJs() / _loadEcharts(assetsDir)
renderPage(data, echartsJs) -> full HTML string
buildStudentReportHtml(data, outPath, assetsDir="_assets", echartsJs=None)

# ── COHORT DRIVER ────────────────────────────────────────────────────────
buildEntireCohortStudentReportsHtml(engine, cohort, ...) # mirrors buildEntireCohortStudentReportsV2
```

Each `render*` returns an **HTML fragment** with stable `id`s; the paired JS builder in
`_reportJs()` (`renderSummaryTable`, `_ecStacked`+`renderRatings`, `_ecProc`+`renderProcedures`,
`_ecRadarScore`/`_ecRadarGr`+`renderSections`, `_ecScatter`/`_ecRubric`+`renderTimeSeries`,
`_cardHtml`+`renderReflections`) reads the embedded `REPORT` object and draws into those ids.
To change a block you edit its `render*` (markup) and its `_ec*` (chart option) — nothing else.

---

## 4. The data dict (payload embedded as `const REPORT = {...}`)

`prepareReportData` returns a JSON-serialisable dict. Shape (BOH2 example):

```jsonc
{
  "meta": {"cohort":"BOH2","studentNumber":"1775573","studentName":"Amal Barakat",
           "title":"Till Date performance report","generated":"15 Sep 2026"},
  "streams": ["Simulation","Clinic"],                 // after cohort gating
  "summary": {"hasSim":true,"hasClinic":true,"rows":[
     {"key":"# Forms","label":"# Forms","sim":"18","clinic":"41","pairs":false},
     {"key":"Patient Age Dist.","label":"Patient age distribution",
      "subLabels":["0-6","7-17","18+"],"sim":null,"clinic":["2","5","32"],"pairs":true}
  ]},
  "ratings": {"sim":{"entrust":{"2":3,"3":9,"4":5},"gr":{"3":6,"4":8,"5":2}},
              "clinic":{"entrust":{...},"gr":{...}}},
  "procedures": {"Clinic":{
     "codes":[{"code":"311","count":12,"classAvg":8.4}, ...],   // count>=2, worst-first
     "singles":[{"code":"701","classAvg":2.4}, ...]}},           // count==1 -> chips
  "sections": {"Clinic":{"rows":[
     {"section":"Restorative","label":"Restorative","count":22,
      "meanScore":0.82,"meanGr":3.9,"meanEs":3.1}, ...]}},
  "timeseries": {"Clinic":{
     "dates":["2026-03-04", ...],
     "points":[{"date":"2026-03-04","code":"311","score":70,"entrust":2,"gr":3,
                "clinic":"RMH","assessor":"Dr Lee"}, ...],       // one per assessed item
     "rubric":[{"date":"2026-03-04","entrust":2,"gr":3}, ...],   // one per form
     "roll":[{"date":"2026-03-04","mean":65}, ...]}},            // 3-pt rolling mean of session mean %
  "reflections": {"Clinic":{
     "cards":[{"date":"2026-06-19","codes":"534, 311","gr":5,
               "student":"…","assessor":"…"}, ...],
     "log":[{"date":"2026-05-01","type":"FTA","note":"Patient failed to attend"}, ...]}},
  "palette": { ...V2_* + navy/zebra/grColors/entColors... }
}
```

`score` is `sd["score"] * 100` (0–100) — same `scores` dict the PDF scatter uses.
`meanScore` is a 0–1 fraction (radar divides by nothing; GR by 5, ES by 4 — same as `_v2DrawSpider`).

---

## 5. Interactivity delivered

- **Global stream switch** (Both / Simulation / Clinic), sticky at top. Hides summary columns,
  toggles the Sim/Clinic ratings bars, and shows/hides the per-stream Procedures / Sections /
  Time-series / Reflections panels via `applyStream()` (`[data-stream]` attribute driven).
- **Rating distribution:** 100% stacked bars, hover shows `level: n (pct%)`, legend toggles levels.
- **Procedures:** hover shows *You vs Class avg* + ▲/▽/= delta; diamond marker = rounded class avg;
  single-occurrence codes as chips (amber when class avg > 1, i.e. you did fewer than typical).
- **Sections:** two radars per stream (Mean Score; GR/5 + ES/4 overlay) + a section summary table.
- **Time series:** per-item scatter + navy rolling-avg(3) line, hover shows item/score/GR/ES/assessor/clinic;
  a **`dataZoom` slider** to zoom a date range; a separate rubric line panel (Entrustment/Global Rating).
  **Item-code filter (2026-09-15):** a text box per stream accepts a comma list of codes and wildcard
  patterns (`x`/`*`, e.g. `5xx`, `4*`); the scatter and its rolling average recompute on the filtered set
  (`_parseCodeQuery`/`_matchCode`/`_rollFromPoints`/`applyTsFilter`), with an `N of M items` counter.
- **Reflections:** GR-coloured cards (left band keyed to `V2_GR_COLORS`), a **GR chip filter**,
  a **free-text search**, and a collapsed assist/support/cancelled **log** table.

---

## 6. How to run (on the machine with the notebook env + DB)

```python
import importlib, student_report_html_utils as sh
importlib.reload(sh)

# one student (BOH2 sample):
avg = {"Simulation": None,
       "Clinic": sh.bu.getCohortItemCodeAverages(engine, "BOH2", formType="Clinic")}
data = sh.prepareReportData(engine, "BOH2", "1775573", classAvgItemCounts=avg)
sh.buildStudentReportHtml(data, "BOH2/Individual Student Reports HTML/1775573.html")

# whole cohort (computes class averages itself, same gating/removed-student skips as V2 PDF):
sh.buildEntireCohortStudentReportsHtml(engine, "BOH2")
# -> BOH2/Individual Student Reports HTML/<studentNumber>.html  (PDF folders untouched)
```

`_assets/echarts.min.js` must exist at the project root (vendored — done). It is read once per
cohort run and inlined into every file.

---

## 7. Gotchas / traps

- **This is import-star safe by convention but the module uses explicit `import boh2_dds2_dds3_utils as bu`**,
  not `from … import *`, so `Table`/`Paragraph` etc. do NOT collide (unlike the notebook). Keep it that way.
- **`allow_nan=False`** on `json.dumps` — the data layer converts every NaN/None to JSON `null`
  via `_num()`. If a new field is added, pass it through `_num()` or the dump will raise.
- **Self-contained size:** ~1.05 MB/file; ~1 MB is the shared ECharts lib. A whole cohort is
  fine on disk, but do not commit the generated folder into anything size-sensitive.
- **Sample was rendered from representative data**, not the live DB — the DB is not reachable from
  the Cowork Linux VM (connection refused; it is on the UniMelb network). All *numbers* must be
  validated on first real run against a student whose PDF V2 you already have (recommend 1775573,
  Amal Barakat — the V2 sample student). Layout/interaction were verified headless (7 charts, no JS errors).
- **`getCohortItemCodeAverages` gating**: Sim averages are skipped for DDS2/DDS3, Clinic for BOH1 —
  the driver already does this; if you call `prepareReportData` directly, pass `classAvgItemCounts`
  with the right streams or the Procedures block is simply omitted (charts still render).
- **`main.ipynb` NOT edited** (project rule: ask before edits). A ready notebook cell is in §6;
  add it after the V2 report cell.

---

## 8. Open / next steps

- **Validate numbers on the live DB** against the matching PDF V2 for 1–2 students (esp. summary
  age/outcome pairs, section means, procedure class-avg deltas).
- Decide whether to add the run cell to `main.ipynb` (held pending Kunal's OK per the ask-before rule).
- Optional: a lightweight **cohort index.html** linking every student file.
- Optional: per-stream **section filter** on the time-series scatter (item-code / pattern filter is done; section-name grouping still optional).
- Optional: print stylesheet is present (`@media print`) but not tuned for A3 landscape parity with the PDF.
