# `student_report_html_utils.py` — module reference

Interactive HTML version of the per-student **"Till Date performance report"**. Produces one
self-contained `.html` per student (Apache ECharts inlined) that mirrors the PDF V2 report
(`buildStudentReportV2` in `boh2_dds2_dds3_utils.py`) page-for-page, with hover, filtering and zoom.

**Canonical detail:** `_handover_docs/HANDOVER_student_report_interactive_html.md`
(indexed in `_handover_docs/INDEX.md`).

## Design
- **Additive only.** Imports and *calls* the existing `*V2` data functions in
  `boh2_dds2_dds3_utils.py`; never re-implements a number, never edits that module.
- **Two layers:** DATA (`prepareReportData`, needs pandas + DB) → JSON-serialisable dict;
  RENDER (`render*`, pure Python) → HTML string.
- **One function per element**, camelCase; colours from the imported `V2_*` palette.

## Public API
| Function | Purpose |
|---|---|
| `prepareReportData(engine, cohort, studentNumber, formsTable="rawform_forms_v3", patientInfo=True, classAvgItemCounts=None, studentName=None, scoreMap=None)` | Build the data dict for one student by reusing the V2 pipeline. |
| `buildStudentReportHtml(data, outPath, assetsDir="_assets", echartsJs=None)` | Render one data dict to a self-contained `.html`. |
| `buildEntireCohortStudentReportsHtml(engine, cohort, formsTable="rawform_forms_v3", patientInfo=True, outSubfolder="Individual Student Reports HTML", assetsDir="_assets", onlyStudents=None, scoreMap=None)` | Whole-cohort driver; same gating/removed-student skips as `buildEntireCohortStudentReportsV2`. Writes `{cohort}/Individual Student Reports HTML/{n}.html`. |
| `renderPage(data, echartsJs)` | Assemble the full HTML document from element fragments. |
| `renderBanner / renderIntro / renderFilterBar / renderSummary / renderRatingDistribution / renderProcedures / renderSectionPerformance / renderTimeSeries / renderReflections` | One HTML fragment per report element. |

## Element ↔ JS builder map (edit a block in one place)
| Element (`render*`) | Container id(s) | JS builder in `_reportJs()` |
|---|---|---|
| Summary | `#summaryTable` | `renderSummaryTable` |
| Rating distribution | `#chartEntrust`, `#chartGr` | `_ecStacked` + `renderRatings` |
| Procedures | `#chartProc_<stream>`, `#chips_<stream>` | `_ecProc` + `renderProcedures` |
| Section performance | `#radarScore_<stream>`, `#radarGr_<stream>`, `#secTable_<stream>` | `_ecRadarScore` / `_ecRadarGr` + `renderSections` |
| Time series | `#tsScatter_<stream>`, `#tsRubric_<stream>` | `_ecScatter` / `_ecRubric` + `renderTimeSeries` |
| Reflections | `#reflCards_<stream>`, `#reflLog_<stream>` | `_cardHtml` + `renderReflections` + `filterReflections` |

## Requirements
- `_assets/echarts.min.js` at project root (vendored ECharts 5.5.1), inlined into every file.
- Runs where the notebook env + DB engine live (the report numbers come from the live V2 functions).

## Run
```python
import student_report_html_utils as sh
sh.buildEntireCohortStudentReportsHtml(engine, "BOH2")
# one: sh.buildStudentReportHtml(sh.prepareReportData(engine,"BOH2","1775573"), "BOH2/Individual Student Reports HTML/1775573.html")
```
