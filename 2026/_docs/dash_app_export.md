# `dash_app_export.py`

> Summary and Detailed Excel workbooks for [`dash_app.py`](dash_app.md) — same design for every exam: Overview, Records, Follow-up, Students, Scores/Std Setting/Sections/Items per checklist, Assessors, Roster, Ignored Assessors. Also holds the statistics (BLR, BGM, viability, Cronbach α, Spearman, 2PL-lite, importance).
> Hand-written 2026-11-06 with an `ast` pass on that date (counts, signatures, line numbers).

| | |
|---|---|
| **Lines of code** | 1,683 |
| **Top-level functions** | 64 |
| **Classes** | 1 (`SheetWriter`) |
| **Module constants** | 6 |
| **Imports from this codebase** | `dash_app_config` (as `cfg`), `dash_app_core` (as `core`) |
| **Imported by** | `dash_app`. |
| **Run how** | Imported only — run `python dash_app.py`. |

Overview, scoring rules, data model, how-to recipes and gotchas: see **[`dash_app.md`](dash_app.md)**.

## Functions


### Style helpers

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 50 | `xFill` | `(h)` | Solid PatternFill. |
| 51 | `xFont` | `(bold=False, color='1E293B', size=9)` | Calibri font helper. |
| 52 | `xAlign` | `(h='left', v='center', wrap=False)` | Alignment helper. |
| 53 | `xBorder` | `(l=False, r=False)` | Thin border, thick left/right at block edges. |
| 56 | `fracFill` | `(v, m)` | Fill for points ÷ max (green → red bands). |
| 63 | `rhoColour` | `(rho)` | Bar colour for an item-vs-GR correlation: green ≥ .30, amber .20–.30, red < .20 / NaN. |
| 68 | `rhoFill` | `(rho)` | Light cell fill for ρ with GR (None when NaN). |
| 75 | `pctFill` | `(p)` | Fill for a % value. |
| 79 | `rnd` | `(v, d=1)` | Round, None-safe (NaN → None). |
| 83 | `sheetName` | `(wb, base: str)` | Excel-safe unique sheet name (≤31 chars). |
| 92 | **class `SheetWriter`** | | Row cursor + common blocks (title, section bar, header row, key/value, table). |
| 95 | `SheetWriter.__init__` | `(self, ws, width=6)` | Bind to a sheet; cursor at row 1. |
| 98 | `SheetWriter.title` | `(self, text, sub='')` | Navy title bar + subtitle. |
| 107 | `SheetWriter.bar` | `(self, text, color='4F5FB2')` | Section bar. |
| 113 | `SheetWriter.para` | `(self, text, size=9, color='334155')` | Merged wrapped paragraph row. |
| 118 | `SheetWriter.header` | `(self, labels, start=1, fill='E0E7FF', color='1E293B')` | Header row. |
| 124 | `SheetWriter.row` | `(self, vals, start=1, bold0=False, fills=None, wrap=False)` | Data row with optional per-cell fills. |
| 132 | `SheetWriter.gap` | `(self, n=1)` | Skip rows. |
| 135 | `SheetWriter.widths` | `(self, ws_)` | Set column widths. |
| 140 | `finishSheet` | `(ws, landscape=True)` | No gridlines, landscape, fit to width. |

### Statistics

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 148 | `tCrit` | `(df, alpha=0.05)` | Two-sided t critical value (scipy, else 1.96). |
| 152 | `tPvalue` | `(t, df)` | Two-sided p for a t statistic. |
| 158 | `rankData` | `(v)` | Average ranks (for Spearman). |
| 170 | `pearsonR` | `(xs, ys)` | Pearson r (NaN when undefined). |
| 180 | `spearman` | `(xs, ys)` | (rho, p). |
| 192 | `computeBlr` | `(xs, ys, borderline)` | Borderline regression: score on GR, cut = prediction at the borderline GR (95% CI). |
| 214 | `computeBgm` | `(xs, ys, borderline)` | Borderline group: cut = mean score of candidates rated borderline (95% CI). |
| 231 | `gradeMeans` | `(xs, ys, levels=5)` | {GR: (n, mean, SD)} of the score. |
| 241 | `viabilityChecks` | `(xs, ys, blr, bgm, bl)` | [(method, test, value, criterion, PASS/WARN/FAIL, note)] — AMEE Guide 49 style checks. |
| 286 | `cronbachAlpha` | `(X)` | α for an (n × k) matrix with NaN → column mean imputation; None if k < 2 or n < 3. |
| 297 | `irtLite` | `(item, ability)` | 2PL-style logistic of item fraction on standardised rest-score (IRLS): (a = discrimination, b = difficulty). |
| 316 | `importance` | `(Xg, target)` | Per-item importance for predicting the total: RandomForest if scikit-learn exists, else \|item-rest r\|. |

### Shared row helpers

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 335 | `basePct` | `(r)` | Overall % before administrative penalties, unrounded (used for all analysis). |
| 343 | `ssPoints` | `(rows)` | (GR, base %, row) for submitted forms with both. |
| 348 | `borderlineOf` | `(examKey)` | EXAMS[exam]['borderline'] (default 2). |
| 352 | `grLabels` | `(rows)` | {level: label} from the forms' own scale (latest wins). |
| 361 | `tplTag` | `(tpl, many)` | Short sheet suffix for a template. |
| 368 | `itemColumns` | `(rows, tpl)` | Ordered (ck, mc, secKey, sub, question) over the template's forms. |
| 380 | `itemLookup` | `(r)` | {(checklist, MC): item} for one row. |
| 384 | `itemFrac` | `(r, c)` | points ÷ max for item column c (NaN when unanswered/unscored; unansweredAsZero profiles count blanks as 0). |
| 394 | `weightedPoints` | `(it)` | weight × points for an item cell (None when blank). |
| 402 | `autoWidth` | `(ws, minW=6, maxW=40)` | Column widths from content length. |

### Records (summary) sheet

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 409 | `recordColumns` | `(rows, templates)` | (header, valueFn, fillFn) list; section % columns when one template is in view. |
| 444 | `writeRecords` | `(wb, title, rows, templates)` | Records-format sheet (also used for Ignored Assessors). |

### Per-checklist score sheet (MC grid)

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 470 | `writeScoreSheet` | `(wb, title, rows, tpl)` | Per-template MC grid with section totals, summary and comments blocks. |

### Standard setting sheet

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 600 | `writeStandardSetting` | `(wb, title, rows, tpl, examKey)` | BLR + BGM on Overall % (pre-penalty) and per section; viability; grade means; charts. Returns summary dict. |

### Section analysis

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 712 | `writeSections` | `(wb, title, rows, tpl, examKey, ss)` | Section descriptives, α, correlations, mean % by GR, intercorrelations, chart. Returns whole-checklist α. |

### Item analysis

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 786 | `writeItems` | `(wb, title, rows, tpl)` | Item analysis table + charts for one template. |

### Assessors

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 876 | `writeAssessors` | `(wb, rows, templates, ssByTpl, examKey)` | Assessor leniency / harshness sheet (raw and GR-adjusted Δ) + chart. |

### Students + follow-up

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 941 | `cutOf` | `(r, ssByTpl)` | BLR cut of the row's template (None if not computable). |
| 946 | `writeStudents` | `(wb, rows, ssByTpl, examKey)` | Per-student summary with Review flag. |
| 983 | `writeFollowUp` | `(wb, rows, ssByTpl, examKey)` | Forms needing action, with reasons. |

### Double marking

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 1036 | `linearKappa` | `(a, b)` | Linearly weighted Cohen's κ for two raters' integer levels (None if undefined). |
| 1055 | `writeDoubleMarking` | `(wb, rows, templates)` | Students with ≥ 2 submitted forms on the same checklist: E1 vs E2 (by form id = submission order). |

### Paired examiners (BOH viva: Examiner 1 + Examiner 2 forms → one row per student)

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 1110 | `scaleShort` | `(key: str, name: str='')` | Column label for a scale: GR / RTP, else its name. |
| 1115 | `scaleMap` | `(r)` | {scale key: scale dict} for one form (primary GR + extra scales). |
| 1120 | `pickForm` | `(forms: list)` | One form per examiner role: submitted first, then latest date, then highest id. |
| 1125 | `makeSitting` | `(e1, e2, nForms: int, examKey: str)` | Merge one student's Examiner 1 and Examiner 2 forms. Score, sections, items come from E2 (the scorer). |
| 1164 | `pairSittings` | `(examKey: str, rows: list)` | Exams with 'pairing': forms with an examiner role → one row per student (at the first form's position). |
| 1191 | `ratingPair` | `(r, key=None)` | (E1, E2) value of one scale (default: the primary rating) for a paired row. |
| 1197 | `ratingValues` | `(r)` | All primary ratings on a row: both examiners when paired, else the form's GR. |
| 1204 | `formsOf` | `(r)` | [(label, form row)] behind a row: E1 + E2 when paired, else the row itself. |
| 1211 | `pairedRecordColumns` | `(rows, templates)` | Records / summary columns for paired rows: one row per student, E1 and E2 side by side. |
| 1253 | `writeStandardSettingPaired` | `(wb, title, rows, tpl, examKey)` | Paired rows: BLR + BGM on Overall % against E2's rating, E1's rating and their mean, side by side. |
| 1364 | `writeExaminerAgreement` | `(wb, rows)` | Paired rows: E1 vs E2 agreement on every rating scale, by examiner pair, and the ≥ 2-level disagreements. |
| 1427 | `writeRaterProfiles` | `(ws, w, rows, examKey)` | Assessors sheet, paired exams: ratings each examiner gave as E1 and as E2, and vs their partner. |

### Roster

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 1461 | `loadRoster` | `()` | studentEmailList.csv → {cohort: {normName: name}} (None if missing). |
| 1474 | `writeRoster` | `(wb, rows)` | Roster coverage per cohort. |

### Overview

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 1501 | `writeOverview` | `(wb, examKey, rows, ign, templates, ssByTpl, alphaByTpl, filterDesc, sheetsMade)` | First sheet: key figures, checklist table, scoring method, legend, sheet guide. |

### Entry points

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 1623 | `splitIgnored` | `(rows)` | (main rows, rows by ignored assessors). |
| 1627 | `writeRecordsSplit` | `(wb, title, rows, templates)` | Records sheet(s): paired (E1 + E2) rows get their own column layout, other rows the standard one. |
| 1639 | `summaryExport` | `(examKey, rows, templates, filterDesc)` | Records (+ Ignored Assessors) workbook → temp path. |
| 1652 | `detailedExport` | `(examKey, rows, templates, filterDesc)` | Full analysis workbook → temp path (sheet order: Overview, Records, Follow-up, Students, per-checklist sheets, Assessors, Roster, Ignored). |

## Module constants

`THIN` (L42), `THICK` (L42), `FRAC_FILLS` (L43), `GR_FILL` (L44), `FLAG_FILL` (L45), `SCALE_SHORT` (L1106)
