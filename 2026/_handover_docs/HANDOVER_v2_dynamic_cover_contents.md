# Handover — V2 report dynamic cover / contents page (with page numbers)

**Date:** 2026-09-15
**Cohorts:** all V2 cohorts (BOH1/BOH2/DDS1–3).
**Main code file:** `boh2_dds2_dds3_utils.py`
**Backup:** `boh2_dds2_dds3_utils.py.bak_covertoc_20260915_140707`
**Related:** [[HANDOVER_student_report_v2_redesign.md]], [[HANDOVER_v2_reflections_dynamic_composite.md]], [[HANDOVER_v2_sim_stream_labels_and_scatter_legend.md]] (same-session V2 work).

---

## 0. TL;DR

The V2 per-student PDF now opens with a **cover / contents page** that lists **exactly the sections present in that PDF**, in order, each with a one-line explanation and a **real page number**. It is fully dynamic — add or remove a section and the contents follow, with no hard-coded list — via a two-pass `multiBuild`.

Run (unchanged entry point):
```python
import importlib, boh2_dds2_dds3_utils as bu; importlib.reload(bu)
bu.buildEntireCohortStudentReportsV2(engine, "DDS2", patientInfo=True, combined=True)
```

---

## 1. Mechanism

Standard reportlab TOC pattern, adapted:

- **`_V2TocMark(Flowable)`** — a zero-size flowable carrying `tocText` (the contents-line markup) + `tocLevel`. Placed at the **top of each section's content**.
- **`_V2DocTemplate(SimpleDocTemplate)`** — overrides `afterFlowable`; when it lays out a `_V2TocMark` it calls `self.notify("TOCEntry", (level, text, self.page))`.
- **`TableOfContents`** on the cover collects those notifications and renders `title — explanation …… page`.
- **`doc.multiBuild(elements, onFirstPage=…, onLaterPages=…)`** runs the layout twice so the page numbers resolve (pass 1 records where each marker landed, pass 2 fills the TOC). The page decorators still work through `multiBuild`.

Helpers added (before `buildStudentReportV2`):
```python
class _V2TocMark(Flowable): ...           # zero-size marker (tocText, tocLevel)
class _V2DocTemplate(SimpleDocTemplate):  # afterFlowable -> notify('TOCEntry', ...)
def _v2TocText(title, explanation):       # "<b>title</b>  <font size=8 …>— explanation</font>"
def _v2MakeTocFlowable():                 # TableOfContents w/ a V2 level style
def _v2AddSection(elements, mark, builder):  # append mark, run builder, PageBreak — but
                                             # DROP the mark if the builder rendered nothing
```

New imports: `Flowable` (from reportlab.platypus) and `TableOfContents` (from reportlab.platypus.tableofcontents).

## 2. buildStudentReportV2 changes

- Signature gained `studentName=None, studentNumber=None` (for the cover; the banner already draws them, so the cover body doesn't repeat the title).
- After the top `Spacer(1,72)` (which clears the banner on the **cover**), it appends: intro paragraph → "Contents" heading → the `TableOfContents` flowable → `PageBreak()`. So the cover is page 1; the banner (from the page decorator) sits on it.
- Each section is now preceded by a `_V2TocMark`:
  - Summary & Rating Distribution (always) — marker added right after the cover `PageBreak`.
  - Procedures Performed — marker only inside `if procPanels`.
  - Performance by Section — via `_v2AddSection(...)` (marker dropped if the spider didn't render, e.g. BOH1).
  - `{type} — Performance Over Time` and `{type} — Reflections` — via `_v2AddSection(...)` per type in `typePages`.
- `_v2AddSection` replaces the earlier ad-hoc `len(elements)` guard for the section page-break and generalises it to every optional section, so the contents never lists an empty page.

## 3. buildEntireCohortStudentReportsV2 changes

- `SimpleDocTemplate(...)` → **`_V2DocTemplate(...)`**.
- `doc.build(elements, onFirstPage=…, onLaterPages=…)` → **`doc.multiBuild(elements, onFirstPage=…, onLaterPages=…)`**.
- Passes `studentName=studentName, studentNumber=studentNumber` into `buildStudentReportV2`.

## 4. Decisions / notes

- **Banner moves to the cover.** Page 1 is now the cover and carries the banner ("Till Date performance report / Name (number)"); the Summary is page 2, without a banner (page 2+ never had one). If the banner should repeat on content pages, add it to the `later` decorator.
- **Markers, not heading-text detection.** afterFlowable is unreliable for headings nested in `KeepTogether`; a top-level zero-size marker placed just after each section's leading `PageBreak` lands on the section's own page, so `self.page` is correct.
- **`_v2AddSection` drops orphan markers** so a section that renders nothing produces no contents entry and no blank page.
- **Cost:** `multiBuild` lays the document out twice → cohort builds take modestly longer.
- **Contents text is static markup** (`&` written as `&amp;`), no user data, so no escaping needed there.

## 5. Verification

Module can't import in the bridge VM (`win32com`), so the mechanism was validated standalone with reportlab: (a) `multiBuild` + `_V2TocMark` + `TableOfContents` resolves page numbers (cover=1, sections 2,3,4…); (b) it works with `onFirstPage`/`onLaterPages` decorators; (c) matplotlib **Image** flowables survive both passes (charts present on every pass). `py_compile` clean. NOT run against the live DB — user runs the cell.

## 6. Open items

- Banner not repeated on content pages (by design) — trivial to add if wanted.
- Same cover not applied to the cohort time-series PDF or the original V1 report.
