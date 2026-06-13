# SCBD Gradio Dashboard — Handover Document

**File:** `scbd_gradio.py`  
**Platform:** DASH (unimelb-dash.com)  
**Purpose:** Live monitoring dashboard for SCBD assessments, built with Gradio as a shareable Python web app replacing the static `scbd_dashboard.html` + `scbd_proxy.py` setup.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Environment & Configuration](#2-environment--configuration)
3. [Architecture Overview](#3-architecture-overview)
4. [API Layer](#4-api-layer)
5. [Data Pipeline](#5-data-pipeline)
6. [Filtering & Sorting](#6-filtering--sorting)
7. [UI Components & Defaults](#7-ui-components--defaults)
8. [Charts & Visualisation](#8-charts--visualisation)
9. [Security Decisions](#9-security-decisions)
10. [Auto-Refresh Mechanics](#10-auto-refresh-mechanics)
11. [CSV Export](#11-csv-export)
12. [Deployment Options](#12-deployment-options)
13. [Extending the App](#13-extending-the-app)
14. [Known Constraints & Gotchas](#14-known-constraints--gotchas)

---

## 1. Quick Start

### Install dependencies

```bash
pip install gradio requests pandas python-dotenv matplotlib numpy
```

> Gradio ≥ 4.16 required for `gr.Timer` auto-refresh support.

### Create `.env` file (next to the script)

```env
DASH_TOKEN=your_django_rest_framework_token_here
SCBD_USERNAME=scbd
SCBD_PASSWORD=dbcs@2026
```

### Run

```bash
python scbd_gradio.py
# → http://localhost:7860
```

### Share publicly (temporary Gradio tunnel)

Change the last line in the script:

```python
demo.launch(..., share=True)
```

This generates a `https://xxxx.gradio.live` URL valid for 72 hours. The login wall applies to the public URL as well.

---

## 2. Environment & Configuration

All sensitive values are loaded from `.env` via `python-dotenv`. The script falls back to hardcoded defaults if the file is absent.

| Env Var | Default | Purpose |
|---|---|---|
| `DASH_TOKEN` | *(empty)* | Django REST Framework API token for `api.unimelb-dash.com` |
| `SCBD_USERNAME` | `scbd` | Gradio login username |
| `SCBD_PASSWORD` | `dbcs@2026` | Gradio login password |

```python
load_dotenv()
ENV_TOKEN  = os.getenv("DASH_TOKEN", "")
LOGIN_USER = os.getenv("SCBD_USERNAME", "scbd")
LOGIN_PASS = os.getenv("SCBD_PASSWORD", "dbcs@2026")
```

**Security rule:** `ENV_TOKEN` is read once at process startup and lives only in server memory. It is never sent to any browser. See [Section 9](#9-security-decisions).

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Browser (user)                    │
│  Login form → Dashboard UI → Gradio websocket       │
└────────────────────┬────────────────────────────────┘
                     │ Gradio events (click / change)
                     ▼
┌─────────────────────────────────────────────────────┐
│              scbd_gradio.py  (Python process)        │
│                                                     │
│  do_load()   ──► fetch_all()  ──► DASH API          │
│                  parse_records()                    │
│                  apply_filters()                    │
│                  make_table_html()                  │
│                  make_charts()                      │
│                  build_stats_html()                 │
│                                                     │
│  do_filter() ──► apply_filters()  (no API call)     │
│  do_export() ──► apply_filters() → temp CSV         │
└─────────────────────────────────────────────────────┘
                     │ HTTPS + DRF Token auth
                     ▼
┌─────────────────────────────────────────────────────┐
│         api.unimelb-dash.com  (DASH backend)        │
│  GET /assessment/scbd/get?cohort=...&year=...        │
└─────────────────────────────────────────────────────┘
```

### Key architectural decision: server-side API calls

The original `scbd_dashboard.html` made API calls from the browser and required `scbd_proxy.py` to bypass CORS restrictions. Gradio runs Python server-side, so API calls happen on the server — no proxy needed and no CORS issues.

### State management

Raw parsed rows are stored in `gr.State([])` after the first load. All subsequent filter/sort/date changes re-use this cached state without hitting the API again.

```
Load button → fetch API → parse → store in gr.State → apply_filters → render
Filter change                  →  read from gr.State → apply_filters → render
```

---

## 4. API Layer

### Endpoint

```
GET https://api.unimelb-dash.com/assessment/scbd/get
```

### Query parameters

| Parameter | Example | Notes |
|---|---|---|
| `cohort` | `DDS3,DDS4` | Comma-separated list |
| `year` | `2026` | 4-digit year |
| `page_size` | `max` | Returns all records in one shot if supported |
| `page` | `1` | Starting page |
| `ordering` | `id` | Ascending by DB id |

### Full example URL

```
https://api.unimelb-dash.com/assessment/scbd/get?page_size=max&page=1&cohort=DDS3&year=2026&ordering=id
```

### Authentication

Django REST Framework `TokenAuthentication` — **not** Bearer:

```
Authorization: Token abc123yourtokenhere
```

### Response shape (paginated)

```json
{
  "count": 142,
  "next": "https://api.unimelb-dash.com/assessment/scbd/get?page=2&...",
  "previous": null,
  "results": [
    {
      "id": 1001,
      "student": "Jane Smith",
      "assessor": "Dr. John Lee",
      "cohort": "DDS3",
      "subject": "Periodontal Assessment",
      "datetime": "2026-06-09T08:42:00Z",
      "submitted": true,
      "version": 2,
      "form": {
        "data": {
          "assessor": {
            "scale-global-rating": { "scale": "4" },
            "comments": "Good technique overall.",
            "checklist-item-1": { ... }
          }
        }
      }
    }
  ]
}
```

> The `form` field contains the full JSONB payload including checklist items. Only `scale-global-rating.scale` and `comments` are extracted; the rest is discarded.

### Pagination

`fetch_all()` follows `next` links until exhausted:

```python
while url:
    resp = requests.get(url, headers=headers, timeout=60)
    d = resp.json()
    records.extend(d.get("results", []))
    url = d.get("next")   # None when last page
```

---

## 5. Data Pipeline

### `parse_records(raw: list) → list`

Transforms raw API records into flat display dicts. Strips all large JSON fields.

**Fields extracted per record:**

| Output key | Source in API payload | Notes |
|---|---|---|
| `_ts` | `datetime` → `datetime.timestamp()` | Float, used for date sorting; never shown in UI |
| `Date` | `datetime` | Formatted as `9 Jun 2026 08:42` |
| `Student` | `student` | Skipped if empty or in `EXCLUDE` set |
| `Assessor` | `assessor` | Falls back to `"—"` |
| `Cohort` | `cohort` | Falls back to `"—"` |
| `Subject` | `subject` | Falls back to `"—"` |
| `GR` | `form.data.assessor.scale-global-rating.scale` | Cast to `int`; `"—"` if absent |
| `Submitted` | `submitted` (bool) | `"Yes"` / `"No"` |

**Exclusion list:**

```python
EXCLUDE = set()   # currently empty — test students are included
```

To re-enable exclusions, add lowercase names:

```python
EXCLUDE = {"test student", "kunal patel"}
```

---

## 6. Filtering & Sorting

All filtering and sorting is handled by `apply_filters()`, which runs entirely in Python against the cached `gr.State` — no API call.

### `apply_filters(rows, submitted_only, search, sort_opt, date_from, date_to)`

Filter pipeline (applied in this order):

```
1. Date range   → keep rows where _ts ∈ [date_from 00:00, date_to 23:59:59]
2. Submitted    → keep only "Yes" rows if checkbox ticked
3. Text search  → case-insensitive substring match on Student / Assessor / Cohort / Subject
4. Sort         → by sort_opt key, ascending or descending
```

### Date parsing

```python
def _parse_date_ts(date_str, end_of_day=False):
    dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.timestamp()
```

- `From date` maps to `00:00:00` (midnight start of day)
- `To date` maps to `23:59:59` (end of day — inclusive)
- Either field blank = no bound on that side

### Sort options

```python
SORT_OPTIONS = {
    "Date — newest first": ("_ts",       True),   # default
    "Date — oldest first": ("_ts",       False),
    "Student A → Z":       ("Student",   False),
    "Student Z → A":       ("Student",   True),
    "GR — highest first":  ("GR",        True),
    "GR — lowest first":   ("GR",        False),
    "Submitted first":     ("Submitted", True),
}
DEFAULT_SORT = "Date — newest first"
```

Tuple format: `(row_dict_key, descending: bool)`. GR is cast to `int` for numeric sort; missing GR values sort to the bottom.

---

## 7. UI Components & Defaults

### Component map

```
Row 1: [Token field*] [Year] [Auto-refresh] [Load/Refresh btn]
Row 2: [Cohort checkboxes — all 7 cohorts]
Row 3: [Submitted only] [Search box] [Sort by]
Row 4: [From date] [To date] [hint text]
       ─────────────────────────────────
       [5× Stat cards]
       [Error message]    [Last loaded timestamp]
       [Charts — GR dist | Cohort breakdown]
       [HTML table — up to 500 rows]
       ─────────────────────────────────
Row 5: [Export CSV btn]  [CSV file download]
```

*Token field is hidden when `DASH_TOKEN` is set in `.env`.

### Defaults

| Widget | Default value | Constant |
|---|---|---|
| Year | `2026` | hardcoded |
| Cohorts | `["DDS3"]` | hardcoded |
| Auto-refresh | `"Every 30 sec"` | `DEFAULT_INTERVAL` |
| Sort by | `"Date — newest first"` | `DEFAULT_SORT` |
| From date | `"2026-06-09"` | hardcoded |
| To date | `"2026-06-09"` | hardcoded |
| Submitted only | `False` | hardcoded |

### Event wiring

```python
# Full API fetch
load_inputs  = [token_in, year_in, cohort_in, sub_only,
                search_in, sort_dd, date_from, date_to]
load_outputs = [raw_state, table_html, chart_plot,
                stats_html, updated_md, error_md]

load_btn.click     → do_load(load_inputs)   # manual refresh
token_in.submit    → do_load(load_inputs)   # Enter key in token field
timer.tick         → do_load(load_inputs)   # auto-refresh

# In-memory re-filter (no API call)
[sub_only, search_in, sort_dd, date_from, date_to].change
    → do_filter(raw_state, sub_only, search_in, sort_dd, date_from, date_to)
    → [table_html, chart_plot, stats_html]

interval_dd.change → set_interval() → gr.Timer(value, active)
export_btn.click   → do_export()    → csv_out (file download)
```

---

## 8. Charts & Visualisation

Charts are rendered server-side with **matplotlib** and returned as a `gr.Plot` component (PNG). They are rebuilt on every load and every filter change.

### Chart 1 — Global Rating Distribution (bar chart)

- X-axis: GR 1–5
- Y-axis: count
- Colours match the HTML dashboard: red (1) → orange (2) → yellow (3) → green (4) → teal (5)
- Count label displayed above each bar

```python
GR_COLORS = ["", "#ef4444", "#f97316", "#eab308", "#22c55e", "#10b981"]
```

### Chart 2 — Cohort Breakdown (grouped bar chart)

- Only cohorts present in the current filtered data are shown
- Two bars per cohort: Total (navy `#010d44`) and Submitted (purple `#4f5fb2`)
- Cohort order follows `ALL_COHORTS` list

### Stat cards (HTML, not a chart)

Five cards rendered as inline HTML before the charts, matching the HTML dashboard layout:

| Card | Colour |
|---|---|
| Total records | Default dark |
| Submitted (count + %) | Green `#15803d` |
| Avg global rating | Purple `#4f5fb2` |
| Unique students | Default dark |
| Assessors active | Default dark |

### Table colour coding

| Column | Coding |
|---|---|
| GR | Coloured badge: red=1, orange=2, yellow=3, green=4, teal=5 |
| Cohort | Per-cohort colour badge (indigo palette for DDS, blue-green for BOH) |
| Submitted | ✓ Yes in green `#15803d` · ✗ No in grey `#94a3b8` |

```python
COHORT_COLORS = {
    "DDS1": "#818cf8", "DDS2": "#a78bfa", "DDS3": "#c084fc", "DDS4": "#e879f9",
    "BOH1": "#38bdf8", "BOH2": "#22d3ee", "BOH3": "#2dd4bf",
}
```

> **Why `gr.HTML` instead of `gr.Dataframe`?** Gradio's `gr.Dataframe` has no per-cell styling API. Using raw HTML gives full control over badge colours, bold text, and ellipsis truncation.

---

## 9. Security Decisions

### API Token

| Scenario | Behaviour |
|---|---|
| `DASH_TOKEN` in `.env` | Token field hidden in UI; `ENV_TOKEN` used server-side only — never serialised to browser |
| No `.env` / no `DASH_TOKEN` | Token field visible; user pastes token manually |

```python
# In do_load — server-side only, never sent to browser
effective_token = ENV_TOKEN or (token or "").strip()
```

**Why not pre-fill `value=ENV_TOKEN`?** Even a `type="password"` field sends its value to the browser on page load, visible in DevTools network tab or page state.

### Login wall

Gradio's built-in `auth=` parameter gates the entire app before any content loads:

```python
demo.launch(
    auth=(LOGIN_USER, LOGIN_PASS),
    auth_message="DASH · SCBD Monitor — please log in"
)
```

This applies equally to the local URL and any `share=True` public URL.

### Credentials in `.env`

```env
SCBD_USERNAME=scbd
SCBD_PASSWORD=dbcs@2026
```

Add `.env` to `.gitignore` to prevent committing credentials.

---

## 10. Auto-Refresh Mechanics

`gr.Timer` (Gradio ≥ 4.16) fires `do_load` at a fixed interval.

```python
INTERVAL_MAP = {
    "Manual only":   (60,  False),   # (seconds, active)
    "Every 15 sec":  (15,  True),
    "Every 30 sec":  (30,  True),    # ← DEFAULT_INTERVAL
    "Every 1 min":   (60,  True),
    "Every 5 min":   (300, True),
}
DEFAULT_INTERVAL = "Every 30 sec"

# Timer initialised to match the dropdown default
_def_secs, _def_active = INTERVAL_MAP[DEFAULT_INTERVAL]
timer = gr.Timer(value=_def_secs, active=_def_active)   # active=True from start
```

**Critical rule:** the `gr.Timer` init and the dropdown `value=` must always reference the same `DEFAULT_INTERVAL`. If they diverge, the timer won't run until the user interacts with the dropdown.

When the dropdown changes, `set_interval()` returns a new `gr.Timer` with updated `value` and `active`:

```python
def set_interval(choice):
    secs, active = INTERVAL_MAP.get(choice, (60, False))
    return gr.Timer(value=secs, active=active)

interval_dd.change(fn=set_interval, inputs=[interval_dd], outputs=[timer])
timer.tick(fn=do_load, inputs=load_inputs, outputs=load_outputs)
```

---

## 11. CSV Export

```python
def do_export(rows, submitted_only, search, sort_opt, date_from, date_to):
    filtered = apply_filters(rows, submitted_only, search, sort_opt, date_from, date_to)
    df = make_df(filtered)   # drops _ts, keeps COLUMNS only
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False,
                                      mode="w", newline="", encoding="utf-8-sig")
    df.to_csv(tmp.name, index=False)
    return tmp.name
```

- Encoding is `utf-8-sig` (UTF-8 with BOM) so Excel on Windows opens it correctly without garbled characters
- The exported file reflects exactly what is visible in the table — same date range, search, submitted-only filter, and sort order
- `gr.File` becomes visible after export via `.then(lambda: gr.update(visible=True))`

---

## 12. Deployment Options

### Local (default)

```python
demo.launch(server_name="localhost", server_port=7860, share=False,
            auth=(LOGIN_USER, LOGIN_PASS), ...)
```

### Local network (accessible to others on the same WiFi)

```python
demo.launch(server_name="0.0.0.0", server_port=7860, ...)
# Users access via http://<your-ip>:7860
```

### Public Gradio tunnel (temporary, 72h)

```python
demo.launch(..., share=True)
# Prints: Running on public URL: https://xxxx.gradio.live
```

### Hugging Face Spaces (permanent, free)

1. Create a Space at huggingface.co with SDK = Gradio
2. Upload `scbd_gradio.py` (rename to `app.py`) and a `requirements.txt`
3. Add secrets in the Space settings for `DASH_TOKEN`, `SCBD_USERNAME`, `SCBD_PASSWORD`
4. Remove `server_name` / `server_port` args from `demo.launch()`

```
# requirements.txt
gradio>=4.16
requests
pandas
python-dotenv
matplotlib
numpy
```

---

## 13. Extending the App

### Add a new cohort

```python
ALL_COHORTS = ["DDS1", "DDS2", "DDS3", "DDS4", "BOH1", "BOH2", "BOH3", "NEW1"]
COHORT_COLORS["NEW1"] = "#fb923c"   # add a colour
```

### Change the default date range

```python
date_from = gr.Textbox(label="From date", value="2026-07-01", ...)
date_to   = gr.Textbox(label="To date",   value="2026-07-01", ...)
```

### Add a new sort option

```python
SORT_OPTIONS["Subject A → Z"] = ("Subject", False)
```

### Change default cohorts

```python
cohort_in = gr.CheckboxGroup(ALL_COHORTS, value=["DDS3", "DDS4"], ...)
```

### Add multiple login users

```python
demo.launch(auth=[("scbd", "dbcs@2026"), ("admin", "adminpass")], ...)
```

### Exclude test students

```python
EXCLUDE = {"test student", "kunal patel", "suhrid gupta"}
```

### Extract additional form fields

In `parse_records()`, `ad` is the full `form.data.assessor` dict. Add any key:

```python
rows.append({
    ...
    "Comments": ad.get("comments") or "",
})
```

Then add `"Comments"` to the `COLUMNS` list and update `make_table_html()`.

---

## 14. Known Constraints & Gotchas

| Issue | Detail |
|---|---|
| `gr.Timer` requires Gradio ≥ 4.16 | Older versions will crash on `gr.Timer`. Run `pip install --upgrade gradio` |
| Table sorting is server-side only | No clickable column headers — sort via the dropdown. Implementing JS-based header sort would require injecting JavaScript into `gr.HTML` |
| Charts rebuild on every filter | `plt.close("all")` is called at the start of `make_charts()` to prevent matplotlib figure accumulation |
| Date filter uses local time | `datetime.strptime` parses without timezone. If the API returns UTC datetimes and the server is in a different timezone, there may be off-by-one-day edge cases. The `_ts` values from `datetime.fromisoformat` are timezone-aware |
| Max 500 rows shown in table | `MAX_ROWS = 500` constant. Increase if needed, but very large tables will slow browser rendering. Use search/date filters to narrow down |
| `gr.File` stays hidden until first export | Intentional — it becomes visible after the first click via `.then()` |
| `share=True` tunnel expires after 72h | For permanent sharing use HuggingFace Spaces or `server_name="0.0.0.0"` on a VM |
| `.env` must be in the same directory as the script | `load_dotenv()` with no arguments looks in the current working directory |
