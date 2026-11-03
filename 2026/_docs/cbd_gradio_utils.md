# `cbd_gradio_utils.py`

> Configuration-only module for [`cbd_gradio.py`](cbd_gradio.md) (DDS4 Case Based
> Discussion live monitor). No functions; every name is pulled into the app via
> `from cbd_gradio_utils import *`. Kept separate from `gradio_utils.py` (viva) so
> the two dashboards cannot break each other.

| | |
|---|---|
| **Lines of code** | 126 |
| **Functions / classes** | 0 / 0 |
| **Module constants** | 40 |
| **Imported by** | `cbd_gradio.py` only |
| **Written** | 2026-11-03 (hand-written doc) |

Naming: no leading underscores, because the app uses `import *` (same rule as
`main.ipynb`).

## Constants

### API / data
| Name | Value | Purpose |
|---|---|---|
| `API_BASE` | `"https://api.unimelb-dash.com"` | DASH API root |
| `ASSESS_TYPE` | `"cbd"` | → `/assessment/cbd/get` |
| `YEAR` | `"2026"` | `year=` query param |
| `EXCLUDE` | `{'kunal patel', 'suhrid gupta', 'test student'}` | Exact lowercase student names always hidden |
| `EXCLUDE_SUBSTRINGS` | `["dummy", "test"]` | Hidden only when *Hide dummy/test* is ticked |
| `ALL_COHORTS` | `["BOH3", "DDS3", "DDS4"]` | Cohort checkboxes |
| `DEFAULT_COHORTS` | `["DDS4"]` | Ticked on start |
| `LOCAL_JSON` | `""` | Set to `"temp 2026 cbd.json"` to read a local file instead of the API |
| `DEFAULT_DATE_FROM` / `DEFAULT_DATE_TO` | `"2026-11-01"` / `"2026-11-30"` | Startup date window — must cover the sitting |

### Domains and scoring
| Name | Value | Purpose |
|---|---|---|
| `DOMAIN_ORDER` | `["d1-dds4", …, "d6-dds4"]` | Form keys under `form.data.assessor` |
| `DOMAIN_LABELS` | `{"d1-dds4": "D1", …}` | Short table / export labels |
| `DOMAIN_WEIGHTS` | `None` | Optional `{domain: fraction}` (sum 1) → weighted Overall % |
| `N_LEVELS` | `5` | `O1` → 4 … `O5` → 0 |
| `MC_SCORE` | `{"done well": 4, "done": 3, "mostly done": 2, "sometimes done": 1, "not done": 0}` | Fallback when a record has no rubric |

### Colours
| Name | Purpose |
|---|---|
| `NAVY` `#010d44`, `PURPLE` `#4f5fb2` | Header / accents (same as viva) |
| `GR_COLORS` | GR 1–5 badge colours (index 0 unused) |
| `COHORT_COLORS` | Cohort badges (DDS3, DDS4, BOH3) |
| `MC_COLORS` | Answer-label colours in the form modal (lowercase keys) |
| `GR_LABELS` | Fallback GR names (Fail … Excellent); `form.scales` wins |
| `XL_SCHEME` | Detailed-XLSX `(header, sub-header)` hex per block: identity, d1–d6, summary, comments |

### UI / layout
| Name | Value | Purpose |
|---|---|---|
| `MAX_ROWS` | 500 | Table truncation |
| `DASH_MAX_WIDTH` | `"1800px"` | Container width |
| `TABLE_MAX_HEIGHT` | `"600px"` | Scrollable table height |
| `TABLE_FONT_SIZE` | `"12px"` | Table text |
| `STAT_VALUE_FONT_SIZE` / `STAT_LABEL_FONT_SIZE` | `"18px"` / `"10px"` | Stat cards |
| `COMMENTS_MAX_HEIGHT` | `"36px"` | Comment cell height before scroll (double-click to expand) |
| `SERVER_PORT` | `7861` | viva/SCBD use 7860. **Also update `ngrok.connect(7861, …)` in `cbd_gradio.py`.** |
| `TABLE_COLS` | dict | `show` / `width` per column: Date (hidden), Student, Assessor, Examiner2, Cohort (hidden), GR, D1–D6, Total, Pct, CC, Submitted, View, Comments (`width: None` = fill) |
| `EXPORT_COLUMNS` | list | Summary-XLSX column order |
| `INTERVAL_MAP` / `DEFAULT_INTERVAL` / `DEF_SECS` / `DEF_ACTIVE` | | Auto-refresh options (default every 30 s) |
| `SORT_OPTIONS` / `DEFAULT_SORT` | | Sort dropdown → `(row key, descending)`; adds Overall % and Critical-concerns sorts vs viva |
| `CARD_WRAP` / `CARD_LABELS` | | Stat-card row style and empty-state labels |

## Common changes
| Want to… | Edit |
|---|---|
| Hide dummy students permanently | Add names to `EXCLUDE`, or default the checkbox to `True` in `cbd_gradio.py` |
| Weight domains | Set `DOMAIN_WEIGHTS` |
| Test offline | `LOCAL_JSON = "temp 2026 cbd.json"` |
| Show/hide a table column | `TABLE_COLS[col]["show"]` |
| Change sitting window | `DEFAULT_DATE_FROM` / `DEFAULT_DATE_TO` |

## Change log
| Date | Change |
|---|---|
| 2026-11-03 | Created. |
