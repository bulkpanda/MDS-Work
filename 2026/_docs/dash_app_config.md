# `dash_app_config.py`

> Settings and **all scoring rules** for [`dash_app.py`](dash_app.md): API/cache/server constants, `LABEL5`, `LEVEL_SCHEMES`, `PROFILES` (how points, section % and Overall % are computed) and `EXAMS` (endpoint, cohorts, dates, profile rules, GR scales, borderline). Config only — never executed directly.
> Hand-written 2026-11-06 with an `ast` pass on that date (counts, signatures, line numbers).

| | |
|---|---|
| **Lines of code** | 221 |
| **Top-level functions** | 0 |
| **Classes** | 0 |
| **Module constants** | 53 |
| **Imports from this codebase** | — |
| **Imported by** | Nothing in this codebase imports it except `dash_app`, `dash_app_core`, `dash_app_export`. |
| **Run how** | Imported only — run `python dash_app.py`. |

Overview, scoring rules, data model, how-to recipes and gotchas: see **[`dash_app.md`](dash_app.md)**.

## Constants

| Line | Name | Value / purpose |
|---:|---|---|
| 11 | `API_BASE` | `'https://api.unimelb-dash.com'` |
| 12 | `YEAR` | `'2026'` |
| 13 | `PAGE_SIZE` | `200` |
| 14 | `CACHE_TTL` | `30` |
| 15 | `LOCAL_JSON_DIR` | `''` |
| 17 | `EXCLUDE` | `{'kunal patel', 'suhrid gupta', 'test student'}` |
| 18 | `EXCLUDE_SUBSTRINGS` | `['dummy', 'test']` |
| 21 | `APP_BUILD` | `'build 20261109a'` |
| 22 | `SERVER_PORT` | `7863` |
| 23 | `USE_NGROK` | `True` |
| 24 | `NGROK_DOMAIN` | `'app.mds-dash.ngrok.app'` |
| 25 | `CONCURRENCY` | `5` |
| 26 | `OVERRIDES_SUFFIX` | `'_overrides.json'` |
| 27 | `ROSTER_CSV` | `'studentEmailList.csv'` |
| 44 | `LABEL5` | `{'done well': 4, 'done': 3, 'mostly done': 2, 'sometimes done': 1, 'not done': 0}` |
| 45 | `LEVEL_SCHEMES` | `{2: [0, 1], 3: [0, 1, 2], 4: [0, 2, 3, 4], 5: [0, 1, 2, 3, 4]}` |
| 49 | `ECCA_MATRIX` | `{('B1', 'B1'): (25, 'Fail', 'Significant omissions or errors in the presentation. Questioning reveals signi…` |
| 67 | `ECCA_ROW_LABELS` | `{'B1': 'Below minimum, limited reasoning', 'B2': 'Below minimum, some reasoning', 'M1': 'Meets minimum, lim…` |
| 69 | `ECCA_COL_LABELS` | `{'B1': 'Significant gaps', 'B2': 'Partial understanding', 'M1': 'Meets minimum', 'M2': 'Strong reasoning an…` |
| 73 | `ORAL_ITEM_WEIGHTS` | `{'BOH3-OCT': {'MC1': 3, 'MC2': 2, 'MC3': 1, 'MC4': 1, 'MC5': 1}}` |
| 75 | `PROFILES` | `{'label5Raw': {'title': 'Label points, raw total', 'points': 'labelMap', 'labelMap': LABEL5, 'unansweredAsZ…` |
| 146 | `EXAMS` | `{'CBD': {'title': 'Case Based Discussion (CBD)', 'endpoint': 'cbd', 'cohorts': ['BOH3', 'DDS3', 'DDS4'], 'd…` |
| 173 | `` | `{'title': 'Oral Presentation (OCT · OHTR · ECCA)', 'endpoint': 'oral-presentation', 'cohorts': ['BOH3'], 'd…` |
| 181 | `DEFAULT_EXAM` | `'CBD'` |
| 184 | `NAVY, PURPLE, UOM_BLUE, UOM_ORANGE` | `('#010d44', '#4f5fb2', '#094183', '#e87722')` |
| 185 | `GR_COLORS` | `{1: '#ef4444', 2: '#f97316', 3: '#eab308', 4: '#22c55e', 5: '#10b981'}` |
| 186 | `COHORT_COLORS` | `{'BOH1': '#60a5fa', 'BOH2': '#38bdf8', 'BOH3': '#2dd4bf', 'DDS1': '#a3e635', 'DDS2': '#f472b6', 'DDS3': '#c…` |
| 190 | `MAX_ROWS` | `500` |
| 191 | `DASH_MAX_WIDTH, TABLE_MAX_HEIGHT, TABLE_FONT_SIZE` | `('1800px', '620px', '12px')` |
| 192 | `STAT_VALUE_FONT_SIZE, STAT_LABEL_FONT_SIZE, COMMENTS_MAX_HEIGHT` | `('18px', '10px', '36px')` |
| 193 | `MAX_SECTION_COLS` | `12` |
| 194 | `TABLE_COLS` | `{'Date': (True, 78), 'Student': (True, 120), 'Assessor': (True, 110), 'Examiner': (True, 100), 'Cohort': (T…` |
| 200 | `INTERVAL_MAP` | `{'Manual only': (60, False), 'Every 15 sec': (15, True), 'Every 30 sec': (30, True), 'Every 1 min': (60, Tr…` |
| 202 | `DEFAULT_INTERVAL` | `'Every 30 sec'` |
| 203 | `STATUS_RANK` | `{'Submitted': 0, 'In progress': 1, 'Not started': 2}` |
| 204 | `SORT_OPTIONS` | `{'Status: submitted → in progress → not started': ('_status', False), 'Date — newest first': ('_ts', True),…` |
| 213 | `DEFAULT_SORT` | `'Status: submitted → in progress → not started'` |
| 216 | `SS_MIN_N, BGM_MIN_BORDERLINE, R2_MIN` | `(10, 5, 0.5)` |
| 217 | `DISCRIM_GUIDE, DISCRIM_LOW, DISCRIM_HIGH` | `(10.0, 5.0, 100 / 6)` |
| 218 | `METHOD_AGREE_TOL` | `5.0` |
| 219 | `ALPHA_GOOD` | `0.7` |
| 220 | `DOUBLE_MARK_GAP` | `10.0` |
| 221 | `LENIENCY_MIN_CUT` | `5.0` |

### `PROFILES` keys

| Key | Values | Meaning |
|---|---|---|
| `title` | text | name shown in the form view / Excel |
| `points` | `labelMap` · `levels` · `slot` | how an answer becomes points |
| `labelMap` | `{label: points}` (lowercase) | for `labelMap`; unknown labels fall back to slot |
| `unansweredAsZero` | bool | blank items score 0 and stay in the max (True) or are left out (False) |
| `sectionPct` | `pooled` · `itemMean` | section % (overridden per group by `groups`) |
| `overall` | `raw` · `item` · `sections` · `groups` | Overall % |
| `weights` | `{short: weight}` or absent | for `sections`; absent = equal |
| `missingAsZero` | bool (default True) | for `sections`: blank section keeps its weight at 0% |
| `groups` | `[(label, nameRegex, method, weight)]` | for `groups` (OM-OS) |
| `guide` | text | Scoring-method paragraph on the Excel Overview |

### `EXAMS` keys

| Key | Meaning |
|---|---|
| `title` | full name in header / Excel |
| `endpoint` | `/assessment/<endpoint>/get` and the offline file name |
| `cohorts`, `defaultCohorts` | checkbox choices / ticked on open |
| `dateFrom`, `dateTo` | default date filter |
| `defaultProfile` | profile when no rule matches |
| `profileRules` | `[{optionsAny: [...] \| headerRegex: str \| keyRegex: str, profile: name}]`, first match wins |
| `grScales` | preferred GR scale keys; other scales become extra columns |
| `borderline` | GR level used by BLR / BGM |
