# `dash_app_export.py`

> Summary and Detailed Excel workbooks for [`dash_app.py`](dash_app.md) — same design for every exam: Overview, Records, Follow-up, Students, Scores/Std Setting/Sections/Items per checklist, Assessors, Roster, Ignored Assessors. Also holds the statistics (BLR, BGM, viability, Cronbach α, Spearman, 2PL-lite, importance).
> Hand-written 2026-11-06 with an `ast` pass on that date (counts, signatures, line numbers).

| | |
|---|---|
| **Lines of code** | 1,212 |
| **Top-level functions** | 49 |
| **Classes** | 1 (`SheetWriter`) |
| **Module constants** | 5 |
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
| 63 | `pctFill` | `(p)` | Fill for a % value. |
| 67 | `rnd` | `(v, d=1)` | Round, None-safe (NaN → None). |
| 71 | `sheetName` | `(wb, base: str)` | Excel-safe unique sheet name (≤31 chars). |
| 80 | **class `SheetWriter`** | | Row cursor + common blocks (title, section bar, header row, key/value, table). |
| 83 | `SheetWriter.__init__` | `(self, ws, width=6)` | Bind to a sheet; cursor at row 1. |
| 86 | `SheetWriter.title` | `(self, text, sub='')` | Navy title bar + subtitle. |
| 95 | `SheetWriter.bar` | `(self, text, color='4F5FB2')` | Section bar. |
| 101 | `SheetWriter.para` | `(self, text, size=9, color='334155')` | Merged wrapped paragraph row. |
| 106 | `SheetWriter.header` | `(self, labels, start=1, fill='E0E7FF', color='1E293B')` | Header row. |
| 112 | `SheetWriter.row` | `(self, vals, start=1, bold0=False, fills=None, wrap=False)` | Data row with optional per-cell fills. |
| 120 | `SheetWriter.gap` | `(self, n=1)` | Skip rows. |
| 123 | `SheetWriter.widths` | `(self, ws_)` | Set column widths. |
| 128 | `finishSheet` | `(ws, landscape=True)` | No gridlines, landscape, fit to width. |

### Statistics

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 136 | `tCrit` | `(df, alpha=0.05)` | Two-sided t critical value (scipy, else 1.96). |
| 140 | `tPvalue` | `(t, df)` | Two-sided p for a t statistic. |
| 146 | `rankData` | `(v)` | Average ranks (for Spearman). |
| 158 | `pearsonR` | `(xs, ys)` | Pearson r (NaN when undefined). |
| 168 | `spearman` | `(xs, ys)` | (rho, p). |
| 180 | `computeBlr` | `(xs, ys, borderline)` | Borderline regression: score on GR, cut = prediction at the borderline GR (95% CI). |
| 202 | `computeBgm` | `(xs, ys, borderline)` | Borderline group: cut = mean score of candidates rated borderline (95% CI). |
| 219 | `gradeMeans` | `(xs, ys, levels=5)` | {GR: (n, mean, SD)} of the score. |
| 229 | `viabilityChecks` | `(xs, ys, blr, bgm, bl)` | [(method, test, value, criterion, PASS/WARN/FAIL, note)] — AMEE Guide 49 style checks. |
| 274 | `cronbachAlpha` | `(X)` | α for an (n × k) matrix with NaN → column mean imputation; None if k < 2 or n < 3. |
| 285 | `irtLite` | `(item, ability)` | 2PL-style logistic of item fraction on standardised rest-score (IRLS): (a = discrimination, b = difficulty). |
| 304 | `importance` | `(Xg, target)` | Per-item importance for predicting the total: RandomForest if scikit-learn exists, else \|item-rest r\|. |

### Shared row helpers

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 323 | `basePct` | `(r)` | Overall % before administrative penalties, unrounded (used for all analysis). |
| 331 | `ssPoints` | `(rows)` | (GR, base %, row) for submitted forms with both. |
| 336 | `borderlineOf` | `(examKey)` | EXAMS[exam]['borderline'] (default 2). |
| 340 | `grLabels` | `(rows)` | {level: label} from the forms' own scale (latest wins). |
| 349 | `tplTag` | `(tpl, many)` | Short sheet suffix for a template. |
| 356 | `itemColumns` | `(rows, tpl)` | Ordered (ck, mc, secKey, sub, question) over the template's forms. |
| 368 | `itemLookup` | `(r)` | {(checklist, MC): item} for one row. |
| 372 | `itemFrac` | `(r, c)` | points ÷ max for item column c (NaN when unanswered/unscored; unansweredAsZero profiles count blanks as 0). |
| 382 | `weightedPoints` | `(it)` | weight × points for an item cell (None when blank). |
| 390 | `autoWidth` | `(ws, minW=6, maxW=40)` | Column widths from content length. |

### Records (summary) sheet

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 397 | `recordColumns` | `(rows, templates)` | (header, valueFn, fillFn) list; section % columns when one template is in view. |
| 432 | `writeRecords` | `(wb, title, rows, templates)` | Records-format sheet (also used for Ignored Assessors). |

### Per-checklist score sheet (MC grid)

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 458 | `writeScoreSheet` | `(wb, title, rows, tpl)` | Per-template MC grid with section totals, summary and comments blocks. |

### Standard setting sheet

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 553 | `writeStandardSetting` | `(wb, title, rows, tpl, examKey)` | BLR + BGM on Overall % (pre-penalty) and per section; viability; grade means; charts. Returns summary dict. |

### Section analysis

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 665 | `writeSections` | `(wb, title, rows, tpl, examKey, ss)` | Section descriptives, α, correlations, mean % by GR, intercorrelations, chart. Returns whole-checklist α. |

### Item analysis

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 739 | `writeItems` | `(wb, title, rows, tpl)` | Item analysis table + charts for one template. |

### Assessors

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 806 | `writeAssessors` | `(wb, rows, templates, ssByTpl, examKey)` | Assessor leniency / harshness sheet (raw and GR-adjusted Δ) + chart. |

### Students + follow-up

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 870 | `cutOf` | `(r, ssByTpl)` | BLR cut of the row's template (None if not computable). |
| 875 | `writeStudents` | `(wb, rows, ssByTpl, examKey)` | Per-student summary with Review flag. |
| 909 | `writeFollowUp` | `(wb, rows, ssByTpl, examKey)` | Forms needing action, with reasons. |

### Double marking

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 952 | `linearKappa` | `(a, b)` | Linearly weighted Cohen's κ for two raters' integer levels (None if undefined). |
| 971 | `writeDoubleMarking` | `(wb, rows, templates)` | Students with ≥ 2 submitted forms on the same checklist: E1 vs E2 (by form id = submission order). |

### Roster

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 1022 | `loadRoster` | `()` | studentEmailList.csv → {cohort: {normName: name}} (None if missing). |
| 1035 | `writeRoster` | `(wb, rows)` | Roster coverage per cohort. |

### Overview

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 1062 | `writeOverview` | `(wb, examKey, rows, ign, templates, ssByTpl, alphaByTpl, filterDesc, sheetsMade)` | First sheet: key figures, checklist table, scoring method, legend, sheet guide. |

### Entry points

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 1166 | `splitIgnored` | `(rows)` | (main rows, rows by ignored assessors). |
| 1170 | `summaryExport` | `(examKey, rows, templates, filterDesc)` | Records (+ Ignored Assessors) workbook → temp path. |
| 1183 | `detailedExport` | `(examKey, rows, templates, filterDesc)` | Full analysis workbook → temp path (sheet order: Overview, Records, Follow-up, Students, per-checklist sheets, Assessors, Roster, Ignored). |

## Module constants

`THIN` (L42), `THICK` (L42), `FRAC_FILLS` (L43), `GR_FILL` (L44), `FLAG_FILL` (L45)
