# `cbd_gradio.py`

> A standalone Gradio 6 web application ("DASH · Case Based Discussion (CBD) Live
> Monitor") that polls the DASH assessment API for DDS4 CBD records, scores each
> form against its own rubric, renders a live auto-refreshing HTML table with
> comment and full-form modals, and exports the filtered view to plain or
> formatted XLSX. Modelled on [`viva_gradio.py`](viva_gradio.md).

| | |
|---|---|
| **Lines of code** | 1,213 † (750 on 2026-11-03 creation) |
| **Top-level functions** | 35 † (53 incl. nested) |
| **Classes** | 0 |
| **Module constants** | 12 (`ENV_PATH`, `ENV_FILE`, `DASH_EMAIL`, `DASH_PASSWORD`, `ENV_TOKEN`, `LOGIN_USER`, `LOGIN_PASS`, `APP_BUILD`, `TOKEN_CACHE`, `FORM_MODAL_HANDLER`, `COMMENT_MODAL_HANDLER`, `css`) |
| **Imports from this codebase** | `cbd_gradio_utils` — `import cbd_gradio_utils as cgu` and `from cbd_gradio_utils import *` |
| **Imported by** | Nothing. Not used by `main.ipynb`. |
| **Run how** | `python cbd_gradio.py` → `http://localhost:<SERVER_PORT>` (currently 7860). Public link via `pyngrok` inside `__main__` (see §6). |
| **Written** | 2026-11-03 (hand-written doc; counts from an `ast` pass on that date — not AST-generated like the 2026-08-14 docs). |

## 1. Purpose and role in the pipeline

Operational monitoring tool for the **DDS4 Case Based Discussion (CBD)** exam
(subject `DENT90124`), open on a screen while the sitting runs. It is *not* part
of the batch reporting pipeline and never touches Postgres.

It deliberately does **not** share `gradio_utils.py` with the viva app: viva's
`DOMAIN_ORDER`, `DOMAIN_LABELS`, `MC_SCORE` are viva-specific and would collide.
All CBD config lives in [`cbd_gradio_utils.py`](cbd_gradio_utils.md).

**Not the same exam as DDS3-CBD.** The DDS3 CBD is scored inside `scbd_gradio.py`
(`_CBD_CFG`: Done Well 3 / Done 2 / Partially Done 1 / Not Done 0, weighted
domains). This module handles the DDS4 CBD form (`d1-dds4` … `d6-dds4`, five-level
rubric) and uses its own scoring (§4).

**Data flow.** `doLoad()` → `loadRaw()` (API via `fetchAll()`, or `LOCAL_JSON`) →
`parseRecords()` → cache in `gr.State` → `applyFilters()` → `makeTableHtml()` +
`buildStatsHtml()`. `doFilter`, `doExport`, `doExportDetailed` work only from the
cached State. A `gr.Timer` re-runs `doLoad()` (default every 30 s). Changing the
cohort checkboxes also triggers `doLoad()` (cohort filtering is server-side).

## 2. External dependencies

| Library / resource | Used for |
|---|---|
| `gradio` | Whole UI (`Blocks`, `State`, `Timer`, `HTML`, `Textbox`, `Dropdown`, `CheckboxGroup`, `Checkbox`, `Button`, `File`, `Markdown`). Tested on 6.31. |
| `requests` | Login (`POST /accounts/login`) and record fetch (`GET /assessment/cbd/get`), 60 s timeouts. |
| `pandas` | `makeDf()` → summary XLSX. |
| `openpyxl` | `doExportDetailed()` formatted workbook. |
| `python-dotenv` | Loads `.env` with `override=True`. |
| `pyngrok` | `ngrok.connect(SERVER_PORT, domain="app.mds-dash.ngrok.app")` in `__main__` — permanent public URL. |
| `scipy` (optional) | Exact t-distribution p-values / 95% CIs in the Standard Setting sheet; falls back to a normal approximation (t ≈ 1.96) if missing. |
| `json`, `tempfile`, `datetime`, `urllib.parse`, `pathlib`, `os` | Local JSON mode, temp export files, date parsing, query strings, `.env` path. |

**Environment variables (`.env` next to `cbd_gradio_utils.py`)**

| Var | Required | Purpose |
|---|---|---|
| `DASH_EMAIL`, `DASH_PASSWORD` | Yes (live mode) | Dynamic API token via `/accounts/login`. |
| `DASH_TOKEN` | No | Last-resort static token if email/password are absent. |
| `CBD_USERNAME`, `CBD_PASSWORD` | No | Gradio login gate. Both must be set or the app is **open to anyone with the link**. Console prints `[CBD] login gate: ON/OFF`. |

## 3. API and payload

**Login** — `POST https://api.unimelb-dash.com/accounts/login`
```json
{"email": "<DASH_EMAIL>", "password": "<DASH_PASSWORD>"}
```
→ `result.user.token`. Header for data calls: `Authorization: Token <token>`
(DRF Token, not Bearer). On HTTP 400/401/403 `loadRaw()` re-logs in once.

**Records** — `GET /assessment/cbd/get?page_size=max&page=1&cohort=DDS4&year=2026&ordering=id`
(`ASSESS_TYPE = "cbd"`). Handles both a flat list and DRF pagination (`results`/`next`).

One record (trimmed, from `temp 2026 cbd.json`):
```json
{
  "id": 11, "datetime": "2026-11-03T00:00:00+11:00",
  "student": "Dummy Student 10", "assessor": "Kunal Patel",
  "cohort": "DDS4", "subject": "DENT90124", "submitted": true,
  "form": {
    "examiner_2": "Kunal Patel",
    "data": {"assessor": {
      "d1-dds4": {"MC1": "Done Well", "MC2": "Done", "MC3": "Mostly Done", "MC4": "Done"},
      "d1-dds4_comments": "Good",
      "...": "d2-dds4 … d6-dds4 (+ _comments)",
      "comments": "No further comments here",
      "critical_concerns": "No",
      "critical_concerns_comments": "",
      "scale-global-rating": {"scale": "4"}
    }},
    "scales": {"scale-global-rating": {"name": "Global Rating",
      "fields": {"1": "Fail", "2": "Borderline Fail", "3": "Pass", "4": "Good", "5": "Excellent"}}},
    "checklists": {"d1-dds4": {
      "name": "Domain 1 - Clinical Information Gathering",
      "fields": {"MC1": "Presents only relevant medical history …"},
      "extra_config": {"rubric": {"MC1": {"O1": "Done Well", "O2": "Done", "O3": "Mostly Done",
                                          "O4": "Sometimes Done", "O5": "Not Done", "label": ""}}}
    }}
  }
}
```
Unsubmitted placeholders arrive with `form.data.assessor = {}` → row shows "—"
in every score cell.

**Domains** (from the 2026 form): D1 Clinical Information Gathering · D2 Patient
Assessment · D3 Planned and Completed Treatment · D4 Reflective Practice ·
D5 Communication · D6 Professionalism and Collegiality.

## 4. Scoring (architectural decision)

- **Per item:** score by rubric *position* — `O1`=4, `O2`=3, `O3`=2, `O4`=1, `O5`=0
  (`optionScore = N_LEVELS − n`). The answer label is matched case-insensitively to
  the enabled O-labels; if a record has no rubric, `MC_SCORE` (label → points) is used.
- **Item max:** score of the best **enabled** option. Where `O1` is blank in the
  rubric (Done Well switched off) the item caps at 3.
- **Domain:** Σ item scores / Σ item maxes over **all** checklist fields;
  unanswered items score 0 but stay in the max.
- **Overall %:** unweighted Σraw / Σmax ×100, or Σ wᵢ·(rawᵢ/maxᵢ) ×100 when
  `DOMAIN_WEIGHTS` is set in `cbd_gradio_utils`.
- **Per-record rubrics.** Each record is scored against **its own** `form.checklists`,
  so form-version changes are handled. Observed in test data: record 3 (2 Nov,
  older form) totals /99 (D2 /13, D5 /11); records 11–12 (3 Nov) total /105
  (D2 /16, D5 /14).

Same rank-based idea as the DDS4 OSCE dynamic scoring (`osce_utils`), viva-style
0–4 scale. **Unconfirmed:** whether DDS4 CBD should instead use the DDS3-CBD rule
(3/2/1/0 + weights) — change `optionScore` / `N_LEVELS` / `DOMAIN_WEIGHTS` if so.

Worked example (record 12): D1 3/16, D2 8/16, D3 6/18, D4 7/20, D5 12/14,
D6 17/21 → Total 53/105 → Overall 50.5 %.

## 5. Function reference

### 5.1 Env / auth / timer
| Function | Lines | Description |
|---|---|---|
| `readEnvFile(path)` | 32–43 | Parse `KEY=VALUE` lines into a dict; file values beat stale shell vars. |
| `getToken(force=False)` | 59–72 | Cached login; `force=True` re-authenticates. Falls back to `ENV_TOKEN` if no email/password. |
| `setInterval(choice)` | 75–78 | Refresh dropdown label → `gr.Timer(value, active)` via `INTERVAL_MAP`. |

### 5.2 API layer
| Function | Lines | Description |
|---|---|---|
| `fetchAll(token, cohorts, year)` | 82–96 | Paginated GET of `/assessment/cbd/get`. |
| `loadRaw(cohorts)` | 99–112 | `LOCAL_JSON` set → read file (path relative to utils module), filter by cohort client-side; else `fetchAll` with one re-login retry on 400/401/403. |

### 5.3 Scoring
| Function | Lines | Description |
|---|---|---|
| `optionScore(oKey)` | 116–118 | `"O1"` → 4 … `"O5"` → 0. |
| `scoreItem(value, rubricItem)` | 121–130 | → `(score | None, itemMax)`. `None` = unanswered. |
| `scoreDomain(answers, clMeta)` | 133–144 | → `{score, max, items, perItem{MCk:(s,m)}, answered, n}`. |
| `overallPct(ds)` | 147–155 | Unweighted or weighted overall %; `None` if no domains. |

### 5.4 Comments / parse
| Function | Lines | Description |
|---|---|---|
| `buildCombinedComments(ad)` | 159–172 | One line per field: `[General]`, `[D1]`…`[D6]`, `[Critical Concerns: Yes] …` (only if Yes or text present). |
| `isExcluded(name, hideTest)` | 176–178 | Exact `EXCLUDE` match always; `EXCLUDE_SUBSTRINGS` only when Hide dummy/test is ticked. |
| `parseRecords(raw)` | 181–229 | API record → row dict (see §5.8). GR label read from `form.scales`, fallback `GR_LABELS`. |

### 5.5 Filter / export frame
| Function | Lines | Description |
|---|---|---|
| `parseDateTs(s, endOfDay)` | 233–238 | `YYYY-MM-DD` → timestamp; `None` if blank/invalid (= no bound). |
| `applyFilters(rows, submittedOnly, unsubmittedOnly, ccOnly, hideTest, search, sortOpt, dateFrom, dateTo)` | 241–261 | Date window, exclusions, submitted/unsubmitted, critical-concerns-only, free-text search (Student, Assessor, Examiner2, Cohort, Subject, Comments), sort via `SORT_OPTIONS`. |
| `makeDf(rows)` | 264–277 | Summary DataFrame in `EXPORT_COLUMNS` order. |

### 5.6 HTML rendering
| Function | Lines | Description |
|---|---|---|
| `statCard(label, value, color)` | 281–286 | One stat tile. |
| `buildStatsHtml(rows)` | 289–305 | 7 cards: Total records, Submitted (n, %), Avg GR, Avg overall %, Critical concerns (red if > 0), Unique students, Assessors active. Averages use submitted rows only. |
| `pctColor(p)` | 309–310 | ≥85 green · ≥65 blue · ≥40 amber · else red. |
| `buildFormHtml(row)` | 314–375 | Full-form modal HTML: header (student, assessor, examiner 2, GR, overall), each domain with MC text, answer, `(score/max)`, domain comment; Critical Concerns box (red if Yes); Additional Comments. User text double-encoded, `"`→`&quot;` for the `data-html` attribute. |
| `makeTableHtml(rows)` | 422–535 | Table driven by `TABLE_COLS`; sticky header; rows with critical concerns tinted red; truncates at `MAX_ROWS`. Nested helpers: `grBadge`, `cohortBadge`, `ccCell`, `domainCell`, `commentsCell`. |

### 5.7 Gradio handlers
| Function | Lines | Description |
|---|---|---|
| `doLoad(cohorts, …filters)` | 539–559 | Fetch → parse → State → filtered view. Returns `(rows, tableHtml, statsHtml, lastLoaded, error)`. Friendly messages for 401/403/404. |
| `doFilter(rows, *filters)` | 562–565 | Re-filter cached rows. |
| `doExport(rows, *filters)` | 568–572 | `*_CBD_Summary.xlsx`. |
| `doExportDetailed(rows, *filters)` | 575–676 | `*_CBD_Detailed.xlsx` — see §5.9. |

### 5.8 Row dict (output of `parseRecords`)
| Key | Meaning |
|---|---|
| `_ts`, `_ad`, `_checklists`, `_domain_scores` | Private: timestamp, assessor data, checklist meta, `{domain: scoreDomain()}` |
| `Date`, `Student`, `Assessor`, `Examiner2`, `Cohort`, `Subject` | Display fields (`Examiner2` from `form.examiner_2`) |
| `GR`, `GR_int`, `GR_label` | Global rating (`GR_int = -1` if blank) |
| `Total`, `Max`, `Pct` | Raw total, max, overall % (`Pct = -1` if unscored) |
| `CC`, `CC_int` | Critical concerns text ("Yes"/"No"/"—") and 1/0 for sorting |
| `Submitted`, `Comments` | "Yes"/"No"; combined comments string |

### 5.9 Detailed XLSX layout (updated 2026-11-03)

Three sheets, in this order:

**1. `Scoring Guide`** (`buildGuideSheet`, L746–837) — export stamp + active filters;
(1) item scoring table O1–O5 → 4…0 and the item-max rule; (2) domain/total/overall-%
formula and a domain table (items, max points, weight) from the first record's
checklist; (3) colour legends — MC cell fills, GR fills (labels read from the forms'
own GR scale via `grLabelMap`, latest-dated record wins; GR 2 marked as the borderline level), Critical Concerns /
Submitted fills; (4) standard-setting summary (BLR cut + R², BGM cut + n,
PASS/WARN/FAIL counts); (5) score-sheet
column key. Opens as the active sheet; fit-to-width for printing.

**2. `CBD Detailed`** — unchanged score sheet. Row 1 merged block headers, row 2
sub-headers, data from row 3, freeze at C3.
- **Student Info:** Date, Student, Assessor, Examiner 2, Cohort, Submitted (green/red).
- **One block per domain** (`XL_SCHEME`): `MC1 (/4)` … item points coloured by
  score/max (full green → 0 red), then `Score /max`.
- **Summary:** GR (colour by level), `Total /max`, Overall %, Critical Concerns (red if Yes).
- **Comments:** General, D1–D6 Comments, Critical Concerns Comments.

Header maxima come from the first filtered record's checklist; per-row colours are
always correct even with mixed form versions.

**3. `Standard Setting`** (`buildStandardSettingSheet`, L840–1027) — see §5.10.

### 5.10 Standard setting — BLR + BGM

**Population:** filtered rows with `Submitted == "Yes"`, a GR (1–5) and an Overall %.
Respects every dashboard filter (date window, Hide dummy/test, search …).
Borderline level = `BORDERLINE_GR` (2 = "Borderline").

| Method | Function | Cut score | Extras |
|---|---|---|---|
| **BLR** (borderline regression) | `computeBlr(xs, ys)` L623 | `a + b·BORDERLINE_GR` from OLS of Overall % on GR | slope, intercept, R², Pearson r, std error of estimate, slope p, 95% CI of the mean prediction at GR=2 (`SE = s·√(1/n + (2−x̄)²/Sxx)`), pass count |
| **BGM** (borderline group) | `computeBgm(xs, ys)` L648 | mean Overall % of GR=2 candidates | median, SD, range, 95% CI (t, n−1), pass count |

**Viability tests** (`viabilityChecks`, L678; thresholds in `cbd_gradio_utils`):

| Scope | Test | PASS | Otherwise |
|---|---|---|---|
| BLR | Sample size n | ≥ `SS_MIN_N` (10) | WARN ≥ 5, else FAIL |
| BLR | Distinct GR levels | ≥ 3 | WARN |
| BLR | GR 2 inside observed GR range | yes | WARN (extrapolated cut) |
| BLR | R² | ≥ `R2_MIN` (0.5, AMEE Guide 49) | FAIL |
| BLR | Slope > 0 and p < 0.05 | yes | FAIL |
| BLR | Inter-grade discrimination (slope, %-pts per GR) | `DISCRIM_LOW`–`DISCRIM_HIGH` (5–16.7; guide ≈ 10 = max/10) | WARN |
| BLR | Cut 95% CI width | ≤ 10 %-pts | WARN |
| BGM | Borderline group size | ≥ `BGM_MIN_BORDERLINE` (5) | WARN ≥ 2, else FAIL |
| BGM | Borderline SD | ≤ 15 %-pts | WARN |
| BGM | Cut 95% CI width | ≤ 10 %-pts | WARN |
| Both | Mean Overall % non-decreasing across GR 1→5 | yes | WARN |
| Both | Spearman ρ (GR vs score) > 0, p < 0.05 | yes | WARN |
| Both | \|BLR − BGM\| | ≤ `METHOD_AGREE_TOL` (5) | WARN |

**No automatic recommendation** (removed 2026-11-03 at Kunal's request): both cuts and
their tests are shown side by side; the choice of cut is left to the reader.
PASS = criterion met · WARN = usable but review · FAIL = method not supported.

**Sheet layout:** BLR-vs-BGM statistics table (cut, 95% CI, pass count …);
viability table (PASS green / WARN yellow / FAIL red); Overall % by GR table (GR label
from the forms, n, mean, SD; borderline row orange); per-domain BLR and BGM cuts (domain % vs GR, with R²
flag). Charts at G3 and G23: **BLR scatter** (candidates + linear trendline, red ◆ BLR
cut and orange ▲ BGM cut at GR 2, R² in title; x-axis fixed to integer GR ticks 1–5) and **BGM bar chart** (mean Overall % per
GR, borderline bar orange, value labels). Chart source data sits in columns AD–AJ
(kept visible — Excel/LibreOffice charts skip hidden cells).

Helpers: `tCrit`, `tPvalue` (scipy or normal fallback), `rankData` (average ranks for
Spearman), `pearsonR`, `gradeMeans`, `grLabelMap` (GR labels from the latest-dated form's scale, fallback `GR_LABELS`).

**Example** (synthetic 43-candidate test cohort): BLR 35.4% (R² 0.79, CI 30.4–40.4),
BGM 37.4% (n = 11, SD 19.3); discrimination 19.1 %-pts/GR → WARN. Dummy Students 2–9
(`Claude outputs/cbd_dummy_forms/`): BLR 45.6% (R² 0.99), BGM 46.5% (n = 3).

## 6. UI layout and run

- Row 1: From / To (default `DEFAULT_DATE_FROM`/`TO`), Refresh interval, Load.
- Row 2: Cohorts (`ALL_COHORTS`, default `DEFAULT_COHORTS`), Search, Sort by,
  Submitted only / Unsubmitted only, Critical concerns only / Hide dummy/test.
- Stats row + error bar + "Last loaded HH:MM:SS" (adds "(local JSON)" in offline mode).
- Table, then Export Summary / Export Detailed.

**Public link.** `__main__` calls `ngrok.connect(SERVER_PORT, domain="app.mds-dash.ngrok.app")`
(same pattern as `scbd_gradio.py`), then `demo.launch(server_name="localhost",
server_port=SERVER_PORT, auth=…)`. The free ngrok plan has one static domain, so only
one of viva / SCBD / CBD can be public at a time.

Launch with `python cbd_gradio.py` — no `.bat` wrapper (the `pyngrok` call replaces the
`ngrok http` line viva's `start.bat` uses).

## 7. Gotchas

1. **Date window must cover the sitting**, otherwise the table looks empty
   (same gotcha as viva). Defaults: 2026-11-01 → 2026-11-30.
2. **Port:** `SERVER_PORT` (utils) now drives both `demo.launch` and `ngrok.connect`; it is
   currently 7860, the same as viva/SCBD, so only one of those can run at a time.
3. **Dummy students** are shown by default (needed for testing). Tick *Hide dummy/test*,
   or set the checkbox `value=True` (line 715), once real data flows.
4. **Endpoint name `cbd`** was inferred from the JSON filename; a 404 shows
   "endpoint /assessment/cbd/get not found" — fix `ASSESS_TYPE`.
5. **Year hard-coded** via `YEAR = "2026"` in utils.
6. **Gradio 6:** `theme` and `css` are passed to `launch()`, not `Blocks()`.
   `<script>` in `gr.HTML` never runs, so both modals use self-contained inline
   `onclick`/`ondblclick` IIFEs and attach to `document.body` (survive re-renders);
   `sanitize_html=False` on the table component keeps those attributes.
7. **Offline testing:** set `LOCAL_JSON = "temp 2026 cbd.json"` in utils; revert to
   `""` for live use.
8. Backups of this file live in `_bak/cbd_gradio.py.bak_<timestamp>`.

## 7b. Open issue — 4-option rubrics (not yet fixed)
Domain 2 on the current form has only O1–O4 (O1 = Done … O4 = Not Done). Slot scoring
gives Done = 4 and Not Done = 1 there. Also, saved answers use the `options.assessor`
labels (e.g. D5 MC4 saves "Mostly Done"/"Not Done" while the rubric displays Yes/No);
`scoreItem` currently matches rubric labels and reaches the right D5 MC4 score only via
the `MC_SCORE` fallback. Proposed fix: match on `options.assessor` labels and score
bottom-aligned (last option = 0). Awaiting Kunal's go-ahead.

## 8. Change log
| Date | Change |
|---|---|
| 2026-11-03 (late) | Recommended cut + `recommendCut` removed; GR labels read from the forms ("Borderline", was "Borderline Fail"); BLR scatter x-axis fixed to ticks 1–5. |
| 2026-11-03 (eve) | Detailed export gains `Scoring Guide` (first) and `Standard Setting` (BLR + BGM, viability tests, charts) sheets — §5.9–5.10; standard-setting thresholds added to utils. |
| 2026-11-03 | Created (with `cbd_gradio_utils.py`). Login gate via `CBD_USERNAME`/`CBD_PASSWORD` added same day. `pyngrok` tunnel + `server_name="localhost"` added by Kunal. |
