# HANDOVER — DDS3 interactive embedded time-series + FHY/SHY two-page split

**Date:** 2026-09-16
**Module:** `boh2_dds2_dds3_utils.py` (additive; `student_report_html_utils.py` reused, not changed)
**Backup:** `_bak/boh2_dds2_dds3_utils.py.bak_20260916_004355`
**Scope:** The V2 per-student PDF report (`buildStudentReportV2` / `buildEntireCohortStudentReportsV2`).
`main.ipynb` was **NOT** edited (ask-before rule) — run cells are given below.

---

## 1. Why

Two requests against the V2 "Till Date performance report":

1. **DDS3 time-series clutter.** The Clinic `… — Performance Over Time` scatter stacks every
   assessed item's 3-digit code as text above each session, producing an unreadable pile of
   labels (see the reported screenshot). DDS3 sessions carry many item codes, so the effect is
   worst there. Fix: reveal codes **on hover** instead of printing them, and make the chart
   **interactive** — but only for DDS3; the other cohorts are fine static.
2. **Half-year split.** Optionally split a stream's time-series (Sim **or** Clinic) into a
   **first-half-of-year (FHY)** page and a **second-half (SHY)** page, dividing at **15 Jun 2026**,
   because the Entrustment/Global-Rating rubric panels are also split and read better per half.

A PDF page cannot run hover/JS in any mainstream viewer, so "interactive" is delivered as a
**self-contained interactive HTML embedded inside the PDF as a file attachment** (one file to send),
with an **in-page paperclip annotation** on the chart page that opens it in a browser. The printable
page keeps a clean, **label-free** static preview.

---

## 2. Configuration constants (new, near `COMBINE_TIMESERIES_PANELS`)

```python
TS_SPLIT_DATE = pd.Timestamp("2026-06-15", tz="Australia/Melbourne")   # FHY < date <= SHY
INTERACTIVE_TS_COHORTS = ("DDS3",)   # cohorts whose V2 time-series is interactive-embedded by default
```

The report tz-converts `datetimeutc` to `Australia/Melbourne` before the time-series, so the split
boundary is a Melbourne-local timestamp to match.

---

## 3. Public API — how to run

Both new behaviours are switchable per call. **Nothing else about how you already call the driver
changes** — the new kwargs all have defaults that reproduce the previous output for every cohort
except DDS3 (which now gets the interactive embed by default).

### `buildEntireCohortStudentReportsV2(engine, cohort, …)` — new kwargs

| kwarg | default | meaning |
|---|---|---|
| `interactiveTimeSeries` | `None` | `None` → cohort default: **True for DDS3** (any cohort in `INTERACTIVE_TS_COHORTS`), **False** otherwise. `True`/`False` forces it for any cohort. |
| `tsSplit` | `True` | `True` → split a stream into an FHY page + an SHY page **only when both halves have forms**; single page otherwise. `False` → never split (original single page). |
| `tsSplitDate` | `None` | `None` → `TS_SPLIT_DATE` (15 Jun 2026). Pass a tz-aware `pd.Timestamp` to move the boundary. |

`buildStudentReportV2(…)` takes the same three kwargs, plus `attachSink` (a mutable list the
interactive path appends embed payloads to — the driver supplies and post-processes it; a **direct**
caller who passes no `attachSink` gets the static split page instead of the embed).

### Examples

```python
import importlib, boh2_dds2_dds3_utils as bu; importlib.reload(bu)

# DDS3 — interactive embed + FHY/SHY split, both ON by default:
bu.buildEntireCohortStudentReportsV2(engine, "DDS3")                       # whole cohort
bu.buildEntireCohortStudentReportsV2(engine, "DDS3", onlyStudents=["1234567"])  # one student

# Other cohorts — static charts, but NOW split FHY/SHY when a stream spans 15 Jun:
bu.buildEntireCohortStudentReportsV2(engine, "DDS2")
bu.buildEntireCohortStudentReportsV2(engine, "BOH2")

# Force DDS3 back to static (no embed):
bu.buildEntireCohortStudentReportsV2(engine, "DDS3", interactiveTimeSeries=False)

# Turn OFF the half-year split everywhere (single page as before):
bu.buildEntireCohortStudentReportsV2(engine, "DDS2", tsSplit=False)

# Make BOH2 interactive too, or move the boundary:
bu.buildEntireCohortStudentReportsV2(engine, "BOH2", interactiveTimeSeries=True)
bu.buildEntireCohortStudentReportsV2(engine, "DDS3",
        tsSplitDate=pd.Timestamp("2026-07-01", tz="Australia/Melbourne"))
```

Output folder is unchanged: `{cohort}/Individual Student Reports V2/{n}.pdf`.
Requires `_assets/echarts.min.js` at project root (already vendored for the HTML report).

---

## 4. New functions (all additive; `_addTimeSeriesPageV2` is UNCHANGED)

| function | role |
|---|---|
| `_v2SplitFhyShy(df, splitDate=None, dateCol="datetimeutc")` | Returns `[(suffix, subDf), …]`. **Two** segments `("First half (to 14 Jun)", fhy)` + `("Second half (from 15 Jun)", shy)` **only when both halves have rows**; otherwise one `("", df)` segment. Compares in `splitDate.tz`. |
| `_addTimeSeriesPageV2Split(elements, df, typeLabel, subheadingStyle, combined, cohort, tsSplit, splitDate)` | **Static** path. Calls the original `_addTimeSeriesPageV2` **once per segment**, `PageBreak` between. Passes `typeLabel = f"{typeLabel} · {suffix}"` so the stream word stays first (keeps the Sim label-shortening in `_addTimeSeriesPageV2` working). Single segment ⇒ byte-for-byte the original page. |
| `_v2CleanPreviewImage(segments, typeLabel, cohort)` | **Clean, label-free** printable preview for the interactive page: scatter (no code labels) + rolling-avg on top, ES/GR rubric below, one **column per FHY/SHY segment**. Data via `student_report_html_utils._timeseriesBlock`. Embedded with `_v2FullFigImage`. |
| `_v2InteractiveTsHtml(segments, typeLabel, cohort, studentName, studentNumber, echartsJs=None)` | Builds the **self-contained interactive HTML** (ECharts inlined). Data via `_sh._timeseriesBlock`; ECharts via `_sh._loadEcharts(_sh.DEFAULT_ASSETS_DIR)`. FHY/SHY become **tabs** when 2 segments. |
| `_addTimeSeriesPageV2Interactive(elements, df, typeLabel, subheadingStyle, cohort, tsSplit, splitDate, studentName, studentNumber, attachSink)` | **Interactive** page: heading + callout + clean preview + a zero-size `_V2AttachAnchor`; appends `{name, html, page}` to `attachSink`. If `attachSink is None`, **degrades** to `_addTimeSeriesPageV2Split`. |
| `class _V2AttachAnchor(Flowable)` | Zero-size flowable; its `draw()` records `self.canv.getPageNumber()` into the payload dict so the driver knows which page to put the paperclip on (final `multiBuild` pass wins). |
| `_v2EmbedInteractiveAttachments(pdfPath, attachSink)` | **Post-build** step (runs in the driver after `multiBuild`). Lazy-imports `pikepdf`; embeds each HTML as a catalog attachment (`pdf.attachments[name]`) and adds a `/FileAttachment` paperclip annotation on the recorded page. No-op when `attachSink` is empty. |

`_V2_INTERACTIVE_TS_JS` is a module-level raw-string ECharts config (`%NAVY%/%POINT%/%INK%/%MUTED%`
tokens substituted) that mirrors `student_report_html_utils._ecScatter` / `_ecRubric`.

---

## 5. Architecture decisions

- **Additive only.** `_addTimeSeriesPageV2` (the existing static page) is untouched and is *reused*
  verbatim by the split wrapper. Everything new is a separate function; the dispatch lives in
  `buildStudentReportV2`'s time-series loop.
- **Reuse the HTML report's data layer.** The embedded chart's data comes from
  `student_report_html_utils._timeseriesBlock` — the same function the standalone HTML report uses —
  so the embedded numbers **cannot drift** from the HTML report or (since `_timeseriesBlock` and the
  PDF both read the `scores` dict via `bu._v2SessionMeanByDate`) from the PDF.
- **Lazy import to avoid a cycle.** `student_report_html_utils` imports `boh2_dds2_dds3_utils as bu`
  at module top; `boh2_dds2_dds3_utils` imports it **only inside** the interactive functions, so there
  is no import cycle at load. `pikepdf` is likewise imported lazily inside `_v2EmbedInteractiveAttachments`.
- **Why an attachment, not "live in the page".** No mainstream PDF viewer runs HTML/JS on a page.
  A **standard embedded-file attachment** works everywhere (Acrobat, Foxit, Edge/Chrome PDF viewer
  all show an attachments panel), keeps it **one file**, and the in-page `/FileAttachment` paperclip
  gives an on-page click target. Live hover therefore happens in the browser when the attachment opens.
- **Page-number capture over guesswork.** The interactive section can land on any page (cover + a
  variable number of prior sections), so the paperclip page is captured at render time by a zero-size
  flowable rather than hard-coded.
- **DDS3 preview is label-free; other cohorts keep labels.** The static split path preserves the
  existing labelled scatter (those cohorts wanted static). The interactive preview omits labels on
  purpose — codes are on hover.

## 6. Embed mechanism (schematic)

```
buildStudentReportV2  ──(interactiveTimeSeries)──►  _addTimeSeriesPageV2Interactive
        │                                               │  builds: heading, callout,
        │                                               │  _v2CleanPreviewImage(segs)  [label-free]
        │                                               │  appends {name, html, page:None} to attachSink
        │                                               └► appends _V2AttachAnchor(payload)  [captures page]
        ▼
buildEntireCohortStudentReportsV2
   doc.multiBuild(...)          # 2 passes; anchor.draw() sets payload["page"] on the final pass
   _v2EmbedInteractiveAttachments(filename, attachSink)
        for each payload:
            pdf.attachments[name] = AttachedFileSpec(pdf, html.encode(), text/html)   # attachments panel
            page = pdf.pages[payload["page"]-1]
            page.Annots += FileAttachment annot (Name=/Paperclip, FS=filespec)        # on-page paperclip
```

### The interactive HTML (features)
- Scatter: item scores (%), **hover tooltip** = `date · code`, `Score`, `GR · ES`, `Assessor`, `Clinic`.
- Rolling-avg(3) navy line (recomputed on the filtered set).
- **Code filter** input: comma list + wildcards (`x`/`*`, e.g. `5xx`, `4*`, `011`) with an
  "N of M items" counter (mirrors the HTML report's `_parseCodeQuery`/`_matchCode`).
- **FHY/SHY tabs** (only when both halves have data).
- Rubric chart: Entrustment / Global Rating lines, `connectNulls`.
- Self-contained (~1.05 MB with ECharts inlined) → each DDS3 PDF grows ~1 MB.

---

## 7. FHY/SHY split semantics

- Boundary `TS_SPLIT_DATE` (15 Jun 2026, Melbourne). **FHY = before**, **SHY = on/after**.
- Split happens **per stream** and **only when both halves have forms** ("if needed"); a stream
  entirely on one side stays a single page/section.
- **Static path:** two **separate pages** with a `PageBreak` between (so the split scatter *and* its
  ES/GR rubric panels each read per half — the reason the user wanted two pages).
- **Interactive path:** two **tabs** in the embedded HTML; the printable preview shows the two halves
  **side by side**.
- Applies to **both** streams (Sim and Clinic) and **all** cohorts (static ones included).

---

## 8. Verification status & limitations

- `py_compile` **clean** on the shipped file (both the Cowork container and the device VM).
- AST checks: all seven new defs present; original `_addTimeSeriesPageV2` still present; the only
  public top-level defs changed are the two intended builders.
- **Rendering proven on a prototype** in the Cowork container (headless Chromium): interactive
  hover tooltip, `5xx` filter → "12 of 85 items", FHY/SHY tabs, clean scatter, and a PDF with the
  embedded attachment **verified present** + the on-page `/FileAttachment` paperclip rendered.
- **Glue verified by source:** `_loadEcharts(assetsDir)` reads `_assets/echarts.min.js`;
  `_timeseriesBlock(typeDf, cohort)` returns `{"points","rubric","roll","dates"}` with fields
  `date/code/score/gr/entrust/assessor/clinic` and `mean` — exactly what the new code consumes.
- **NOT run against the live DB or on Windows.** The Cowork Linux VM that mounts the folder is not
  the notebook's Python runtime: it lacks `win32com`, `arial.ttf` (font registration) and the DB, so
  a full `import boh2_dds2_dds3_utils` cannot complete there. **Kunal runs the cell on the real
  machine** — recommend one student first, e.g. a DDS3 student via `onlyStudents=[…]`, then check:
  (a) the paperclip opens the chart in the viewer students use; (b) the embedded numbers match the
  PDF preview and the HTML report; (c) FHY/SHY pages appear only when a stream spans 15 Jun.

## 9. Gotchas / traps

- **Viewer dependence.** The paperclip + attachments panel work in Acrobat, Foxit and Chromium-based
  PDF viewers. Some minimal/mobile viewers hide attachments — if DDS3 PDFs are distributed to such
  viewers, switch that cohort to the standalone HTML report (`buildEntireCohortStudentReportsHtml`)
  or ship a sidecar `.html`. Live hover never runs inside the PDF page itself — by design.
- **`_addTimeSeriesPageV2` heading.** The split passes `"{stream} · {suffix}"`, so the page heading
  reads e.g. `Clinic · First half (to 14 Jun) — Performance Over Time`. Intentional; keeps the
  Sim-label-shortening trigger (`startswith("sim")`) intact.
- **`KeepTogether` not used** for the interactive page — each interactive section starts on a fresh
  page (every `_v2AddSection` ends with a `PageBreak`), so the heading won't orphan and the tall
  preview flows naturally.
- **`import *` safety.** New helpers are underscore-private (won't leak into `main.ipynb`'s
  `from … import *`); the two new module constants are uppercase and collide with nothing.
- **PDF size.** ~1 MB/DDS3 file from inlined ECharts. To shrink, load ECharts from a CDN in
  `_V2_INTERACTIVE_TS_JS` (needs internet when the HTML is opened) — not done, to keep it offline.

## 10. Open

- Live-DB validation of the DDS3 embed numbers vs the PDF preview and the HTML report (Kunal).
- Confirm the paperclip/attachment UX in the students' actual PDF viewer.
- Optional: CDN ECharts option to cut file size; optional per-cohort `INTERACTIVE_TS_COHORTS` growth.

See also [[student-report-html]], [[student-report-v2-redesign]],
[[cohort-timeseries-schedule-and-counts]], [[handover-doc-workflow]].
