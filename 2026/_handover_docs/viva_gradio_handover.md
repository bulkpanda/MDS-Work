# Viva Exam Gradio Dashboard — Handover Document

**File:** `viva_gradio.py`  
**Platform:** DASH (unimelb-dash.com)  
**Purpose:** Live monitoring dashboard for Viva exam assessments. Follows the same architecture as `scbd_gradio.py` with viva-specific additions: multi-domain comment aggregation, MC response distribution chart, and the richer `DDS4-*` form schema.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Environment & Configuration](#2-environment--configuration)
3. [Architecture Overview](#3-architecture-overview)
4. [API Layer](#4-api-layer)
5. [Form Schema & Data Model](#5-form-schema--data-model)
6. [Data Pipeline](#6-data-pipeline)
7. [Comment Aggregation](#7-comment-aggregation)
8. [Filtering & Sorting](#8-filtering--sorting)
9. [UI Components & Defaults](#9-ui-components--defaults)
10. [Charts & Visualisation](#10-charts--visualisation)
11. [Security Decisions](#11-security-decisions)
12. [Auto-Refresh Mechanics](#12-auto-refresh-mechanics)
13. [CSV Export](#13-csv-export)
14. [Deployment Options](#14-deployment-options)
15. [Extending the App](#15-extending-the-app)
16. [Differences from SCBD Dashboard](#16-differences-from-scbd-dashboard)
17. [Known Constraints & Gotchas](#17-known-constraints--gotchas)

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
VIVA_USERNAME=viva
VIVA_PASSWORD=your_password_here
```

### Run

```bash
python viva_gradio.py
# → http://localhost:7860
```

### Share publicly (temporary Gradio tunnel)

```python
demo.launch(..., share=True)
```

Generates a `https://xxxx.gradio.live` URL valid for 72 hours. Login wall applies to the public URL.

---

## 2. Environment & Configuration

All sensitive values are loaded from `.env` via `python-dotenv`. Script falls back to `None` if absent (login wall disabled, token field visible).

| Env Var | Default | Purpose |
|---|---|---|
| `DASH_TOKEN` | *(empty)* | Django REST Framework API token for `api.unimelb-dash.com` |
| `VIVA_USERNAME` | `None` | Gradio login username (login wall disabled if not set) |
| `VIVA_PASSWORD` | `None` | Gradio login password |

```python
load_dotenv()
ENV_TOKEN  = os.getenv("DASH_TOKEN", "")
LOGIN_USER = os.getenv("VIVA_USERNAME")
LOGIN_PASS = os.getenv("VIVA_PASSWORD")
```

**Security rule:** `ENV_TOKEN` is read once at process startup and lives only in server memory — never sent to any browser.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Browser (user)                    │
│  Login → Dashboard UI → Gradio websocket            │
└────────────────────┬────────────────────────────────┘
                     │ Gradio events (click / change)
                     ▼
┌─────────────────────────────────────────────────────┐
│              viva_gradio.py  (Python process)        │
│                                                     │
│  do_load()   ──► fetch_all()   ──► DASH API          │
│                  parse_records()                    │
│                    └─ _build_combined_comments()    │
│                  apply_filters()                    │
│                  make_table_html()                  │
│                  make_charts()   (3 charts)         │
│                  build_stats_html()                 │
│                                                     │
│  do_filter() ──► apply_filters()   (no API call)    │
│  do_export() ──► apply_filters() → temp CSV         │
└─────────────────────────────────────────────────────┘
                     │ HTTPS + DRF Token auth
                     ▼
┌─────────────────────────────────────────────────────┐
│         api.unimelb-dash.com  (DASH backend)        │
│  GET /assessment/viva/get?cohort=...&year=...        │
└─────────────────────────────────────────────────────┘
```

### State management

Raw parsed rows are stored in `gr.State([])` after the first load. All subsequent filter/sort/date changes re-use this cached state without hitting the API again.

```
Load button → fetch API → parse → store in gr.State → apply_filters → render
Filter change             →  read from gr.State → apply_filters → render
```

---

## 4. API Layer

### Endpoint

```
GET https://api.unimelb-dash.com/assessment/viva/get
```

The `ASSESS_TYPE = "viva"` constant at the top of the script drives the URL — change it there if the endpoint slug ever changes.

### Query parameters

| Parameter | Example | Notes |
|---|---|---|
| `cohort` | `DDS3,DDS2` | Comma-separated list |
| `year` | `2026` | 4-digit year |
| `page_size` | `max` | Returns all records in one shot |
| `page` | `1` | Starting page |
| `ordering` | `id` | Ascending by DB id |

### Full example URL

```
https://api.unimelb-dash.com/assessment/viva/get?page_size=max&page=1&cohort=DDS3,DDS2&year=2026&ordering=id
```

### Authentication

Django REST Framework `TokenAuthentication` — note `Token`, not `Bearer`:

```
Authorization: Token abc123yourtokenhere
```

### Response shape (paginated DRF)

```json
{
  "count": 87,
  "next": "https://api.unimelb-dash.com/assessment/viva/get?page=2&...",
  "previous": null,
  "results": [ { ... } ]
}
```

`fetch_all()` also handles flat-list responses (non-paginated fallback):

```python
while url:
    resp = requests.get(url, headers=headers, timeout=60)
    d = resp.json()
    if isinstance(d, list):       # flat list — no pagination
        records.extend(d)
        url = None
    else:                         # paginated DRF
        records.extend(d.get("results", []))
        url = d.get("next")       # None when last page
```

---

## 5. Form Schema & Data Model

### Top-level record

```json
{
  "id": 244,
  "datetime": "2026-06-09T00:00:00",
  "student": "Test Student",
  "assessor": "Kunal Patel",
  "cohort": "DDS3",
  "subject": "DENT90150",
  "submitted": true,
  "version": 1,
  "form": { ... }
}
```

### `form.data.assessor` — the assessor payload

```json
{
  "DDS4-1": { "MC1": "Done well", "MC2": "Done well", "MC3": "Done well", "MC4": "Done well" },
  "DDS4-2": { "MC1": "Done", "MC2": "Done", "MC3": "Done", "MC4": "Done", "MC5": "Done", "MC6": "Done well" },
  "DDS4-3": { "MC1": "Done well", ... },
  "DDS4-4": { "MC1": "Done well", ... },
  "DDS4-5": { "MC1": "Done well", "MC2": "Done well", "MC3": "Done well", "MC4": "Done", "MC5": "Sometimes done" },
  "comments":            "Horrors beyond comprehension.",
  "DDS4-1_comments":     "Domain1",
  "DDS4-2_comments":     "Domain 2",
  "DDS4-3_comments":     "Domain 3",
  "DDS4-4_comments":     "Domain 4",
  "DDS4-5_comments":     "Domain 5",
  "scale-global-rating": { "scale": "3" }
}
```

### Key naming conventions

| Key pattern | Type | Description |
|---|---|---|
| `DDS4-N` | `dict` | Domain N checklist items (`MC1`…`MCn`) |
| `DDS4-N_comments` | `str` | Free-text comment for domain N |
| `comments` | `str` | General (overall) free-text comment |
| `scale-global-rating` | `dict` | `{"scale": "1"–"5"}` |

### MC response values

| Value | Meaning | Chart colour |
|---|---|---|
| `"Done well"` | Strong performance | Green `#15803d` |
| `"Done"` | Adequate | Blue `#2563eb` |
| `"Sometimes done"` | Inconsistent | Amber `#d97706` |
| `"Not done"` | Not demonstrated | Red `#dc2626` |

---

## 6. Data Pipeline

### `parse_records(raw: list) → list`

Transforms raw API records into flat display dicts. Retains the full `_ad` (assessor dict) for chart use.

**Fields extracted per record:**

| Output key | Source | Notes |
|---|---|---|
| `_ts` | `datetime` → `datetime.timestamp()` | Float; used for date sorting; not shown in UI |
| `_ad` | `form.data.assessor` | Full assessor dict retained for MC chart |
| `Date` | `datetime` | e.g. `9 Jun 2026 14:30` (cross-platform format) |
| `Student` | `student` | Skipped if empty or in `EXCLUDE` set |
| `Assessor` | `assessor` | Falls back to `"—"` |
| `Cohort` | `cohort` | Falls back to `"—"` |
| `Subject` | `subject` | Falls back to `"—"` |
| `GR` | `form.data.assessor.scale-global-rating.scale` | String `"1"`–`"5"` or `"—"` |
| `GR_int` | Same | Integer for sort; `-1` when absent |
| `Submitted` | `submitted` (bool) | `"Yes"` / `"No"` |
| `Comments` | All comment fields | Merged by `_build_combined_comments()` |

**Exclusion list (currently empty):**

```python
EXCLUDE = set()   # add lowercase names to exclude e.g. {"test student"}
```

---

## 7. Comment Aggregation

This is the key difference from the SCBD dashboard. Viva assessors write comments at two levels:

- **General** — overall session comment (`comments` key)
- **Per-domain** — one comment per domain (`DDS4-1_comments` … `DDS4-5_comments`)

Rather than showing these in separate columns (which would make the table unmanageably wide), `_build_combined_comments()` merges them into one newline-delimited string:

### `_build_combined_comments(ad: dict) → str`

```python
def _build_combined_comments(ad: dict) -> str:
    parts = []

    # 1. General comment first
    general = (ad.get("comments") or "").strip()
    if general:
        parts.append(f"[General] {general}")

    # 2. Per-domain comments in DOMAIN_ORDER, then any extras
    ordered_keys = [f"{d}_comments" for d in DOMAIN_ORDER]
    extra_keys   = [k for k in ad if k.endswith("_comments") and k not in ordered_keys]

    for key in ordered_keys + extra_keys:
        val = (ad.get(key) or "").strip()
        if val:
            label = key.replace("_comments", "")
            parts.append(f"[{label}] {val}")

    return "\n".join(parts) if parts else "—"
```

**Example output** (stored in `Comments` field):

```
[General] Horrors beyond comprehension.
[DDS4-1] Domain1
[DDS4-2] Domain 2
[DDS4-3] Domain 3
[DDS4-4] Domain 4
[DDS4-5] Domain 5
```

**Table rendering:** `comments_cell()` in `make_table_html()` renders `[Label]` prefixes in navy bold (`#010d44`) and the body text in slate. The cell has `max-height: 72px` with `overflow-y: auto` so long multi-domain comments are scrollable without breaking the table layout.

```
[General] Horrors beyond comprehension.
[DDS4-1] Domain1
...
```
↑ Navy bold labels, scrollable cell, `white-space: normal` so text wraps.

**Search includes comments:** `apply_filters()` includes `"Comments"` in its search fields, so searching for a keyword finds records where that word appears in any domain's comment.

---

## 8. Filtering & Sorting

All handled by `apply_filters()` against the cached `gr.State` — no API call.

### Filter pipeline (applied in order)

```
1. Date range   → keep rows where _ts ∈ [date_from 00:00, date_to 23:59:59]
2. Submitted    → keep only "Yes" rows if checkbox ticked
3. Text search  → case-insensitive substring on Student / Assessor / Cohort / Subject / Comments
4. Sort         → by sort_opt key, ascending or descending
```

Note that **Comments is included in text search** (unlike the SCBD dashboard) — useful for finding records by keyword across all domain comments.

### Sort options

| Option | Sort key | Order |
|---|---|---|
| Date — newest first | `_ts` (float) | Desc |
| Date — oldest first | `_ts` | Asc |
| Student A → Z | `Student` (str lower) | Asc |
| Student Z → A | `Student` | Desc |
| GR — highest first | `GR_int` (int) | Desc |
| GR — lowest first | `GR_int` | Asc |
| Submitted first | `Submitted` | Desc |
| Submitted last | `Submitted` | Asc |

`GR_int` stores `-1` for missing GR — missing values sort last when descending, first when ascending.

---

## 9. UI Components & Defaults

| Component | Default | Notes |
|---|---|---|
| Year dropdown | `2026` | |
| Cohort checkboxes | `["DDS3"]` | Single cohort default (change as needed) |
| Auto-refresh | `Every 30 sec` | Must match `DEFAULT_INTERVAL` constant |
| Submitted only | `False` | |
| Sort | `Date — newest first` | |
| Date from / to | *(empty)* | Blank = no date filter; open range by default |
| Search | *(empty)* | Also searches Comments column |
| Max container width | `1400px` | Wider than SCBD (1280px) to accommodate comments |

### Event wiring

```
load_btn.click / token_in.submit → do_load()  → [raw_state, table, chart, stats, ts, err]
sub_only / search / sort / dates  → do_filter() → [table, chart, stats]
interval_dd.change                → set_interval() → gr.Timer update
timer.tick                        → do_load()
export_btn.click                  → do_export() → csv_out (file)
  .then                           → csv_out visible=True
```

---

## 10. Charts & Visualisation

Three charts rendered side-by-side (16×3.8 inch figure, returned as `gr.Plot` PNG).

### Chart 1 — Global Rating Distribution

Bar chart, X-axis GR 1–5, Y-axis count. Colour-coded bars matching the SCBD dashboard palette. Count label above each non-zero bar.

```python
GR_COLORS = ["", "#ef4444", "#f97316", "#eab308", "#22c55e", "#10b981"]
```

### Chart 2 — Cohort Breakdown

Grouped bars: Total (navy `#010d44`) and Submitted (purple `#4f5fb2`) per cohort. Only cohorts present in the current filtered data are shown. Cohort order follows `ALL_COHORTS`.

### Chart 3 — MC Response Distribution *(viva-specific)*

Horizontal stacked percentage bar showing the breakdown of all MC checklist responses across submitted records. Built by iterating over `_ad` (the retained assessor dict):

```python
for r in sub:                          # submitted records only
    ad = r.get("_ad") or {}
    for key, val in ad.items():
        if isinstance(val, dict) and not key.startswith("scale"):
            for mc_key, mc_val in val.items():
                if mc_key.startswith("MC") and isinstance(mc_val, str):
                    mc_tallies[mc_val.strip()] += 1
```

Colour mapping:

| Response | Colour |
|---|---|
| Done well | `#15803d` (green) |
| Done | `#2563eb` (blue) |
| Sometimes done | `#d97706` (amber) |
| Not done | `#dc2626` (red) |

Count annotations appear inside each segment when the segment is wide enough (>4% of total). `plt.close("all")` is called at the start of `make_charts()` to prevent figure accumulation.

### Stat cards

Five inline HTML cards (identical to SCBD):

| Card | Colour |
|---|---|
| Total records | `#0f172a` (dark) |
| Submitted (count + %) | `#15803d` (green) |
| Avg global rating | `#4f5fb2` (purple) |
| Unique students | dark |
| Assessors active | dark |

### Table colour coding

| Column | Coding |
|---|---|
| GR | Badge: red=1, orange=2, yellow=3, green=4, teal=5 |
| Cohort | Per-cohort colour badge (indigo for DDS, blue-green for BOH) |
| Submitted | ✓ Yes green `#15803d` · ✗ No grey `#94a3b8` |
| Comments | `[Label]` prefixes in navy bold; body in slate; scrollable `max-height: 72px` |

---

## 11. Security Decisions

Identical to the SCBD dashboard. Key points:

- `ENV_TOKEN` is read at startup and used server-side only — never serialised to the browser
- Token field hidden in UI when `ENV_TOKEN` is set; never pre-filled when visible (avoids leaking via DevTools)
- Gradio `auth=` login wall applies to local and `share=True` URLs
- Credentials in `.env`; add `.env` to `.gitignore`

```python
effective_token = ENV_TOKEN or (token or "").strip()
```

---

## 12. Auto-Refresh Mechanics

`gr.Timer` (Gradio ≥ 4.16) fires `do_load` at a fixed interval. The timer init and the dropdown `value=` **must** reference the same `DEFAULT_INTERVAL`:

```python
DEFAULT_INTERVAL = "Every 30 sec"
_def_secs, _def_active = INTERVAL_MAP[DEFAULT_INTERVAL]
timer = gr.Timer(value=_def_secs, active=_def_active)

# Later in layout:
interval_dd = gr.Dropdown(..., value=DEFAULT_INTERVAL, ...)
```

If they diverge, the timer won't fire until the user changes the dropdown.

---

## 13. CSV Export

```python
def do_export(rows, submitted_only, search, sort_opt, date_from, date_to):
    filtered = apply_filters(...)
    df  = make_df(filtered)    # uses EXPORT_COLUMNS — drops _ts, _ad, GR_int
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False,
                                      mode="w", newline="", encoding="utf-8-sig")
    df.to_csv(tmp.name, index=False)
    return tmp.name
```

**EXPORT_COLUMNS:**

```python
EXPORT_COLUMNS = ["Date", "Student", "Assessor", "Cohort", "Subject", "GR",
                  "Submitted", "Comments"]
```

The `Comments` column in the CSV contains the full merged text (newlines preserved), including all `[General]`, `[DDS4-1]` … `[DDS4-5]` prefixed entries. UTF-8-BOM encoding ensures Excel on Windows opens it without garbled characters.

---

## 14. Deployment Options

### Local (default)

```python
demo.launch(server_name="localhost", server_port=7860, share=False, auth=...)
```

### Local network

```python
demo.launch(server_name="0.0.0.0", server_port=7860, ...)
# Users access via http://<your-ip>:7860
```

### Public Gradio tunnel (temporary, 72h)

```python
demo.launch(..., share=True)
```

### Hugging Face Spaces (permanent, free)

1. Create Space with SDK = Gradio
2. Upload `viva_gradio.py` as `app.py` and a `requirements.txt`
3. Add Space secrets for `DASH_TOKEN`, `VIVA_USERNAME`, `VIVA_PASSWORD`
4. Remove `server_name` / `server_port` from `demo.launch()`

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

## 15. Extending the App

### Change default cohorts

```python
cohort_in = gr.CheckboxGroup(ALL_COHORTS, value=["DDS3", "DDS2"], ...)
```

### Add a new cohort

```python
ALL_COHORTS = [..., "NEW1"]
COHORT_COLORS["NEW1"] = "#fb923c"
```

### Add/change domain order

```python
DOMAIN_ORDER = ["DDS4-1", "DDS4-2", "DDS4-3", "DDS4-4", "DDS4-5", "DDS4-6"]
```

`_build_combined_comments()` uses `DOMAIN_ORDER` for ordering, then appends any additional `_comments` keys discovered dynamically — so new domains are handled automatically even if `DOMAIN_ORDER` isn't updated.

### Add a new MC response value

```python
MC_COLORS["Partially done"] = "#8b5cf6"   # purple
```

The MC chart tallier checks `if label in mc_tallies` — add the new key there too:

```python
mc_tallies = {k: 0 for k in MC_COLORS}
```

### Add a new sort option

```python
SORT_OPTIONS["Assessor A → Z"] = ("Assessor", False)
```

### Exclude test students

```python
EXCLUDE = {"test student", "kunal patel"}
```

### Open-ended date filter by default

```python
date_from = gr.Textbox(label="From date", value="", ...)
date_to   = gr.Textbox(label="To date",   value="", ...)
```

### Multiple login users

```python
demo.launch(auth=[("viva", "pass1"), ("admin", "pass2")], ...)
```

### Expose per-domain MC breakdowns in CSV

Replace `EXPORT_COLUMNS` with a wider list and compute per-domain counts in `make_df()`. The `_ad` dict is available on every row for this purpose.

---

## 16. Differences from SCBD Dashboard

| Feature | SCBD | Viva |
|---|---|---|
| API endpoint slug | `scbd` | `viva` |
| Form fields extracted | GR + single `comments` | GR + `comments` + `DDS4-N_comments` × 5 |
| Comments column | Single free-text string | Multi-domain merged string with `[Label]` prefixes |
| Search includes Comments | No | Yes |
| Charts | 2 (GR dist, cohort breakdown) | 3 (GR dist, cohort breakdown, MC response dist) |
| `_ad` retained in row | No | Yes (needed for MC chart) |
| `GR_int` field | No (sorts GR as string) | Yes (dedicated int field for correct numeric sort) |
| Container max-width | 1280px | 1400px (comments column needs space) |
| Default cohort | `["DDS3", "DDS2"]` | `["DDS3"]` |
| Default date range | Today only | Open (blank) |
| Env var for login | `SCBD_USERNAME/PASSWORD` | `VIVA_USERNAME/PASSWORD` |

---

## 17. Known Constraints & Gotchas

| Issue | Detail |
|---|---|
| `gr.Timer` requires Gradio ≥ 4.16 | Older versions crash on `gr.Timer`. Run `pip install --upgrade gradio` |
| `_ad` retained in `gr.State` | Each row keeps the full assessor dict for the MC chart. For cohorts with very large numbers of MC items this may increase state size; acceptable at current volumes |
| MC chart counts submitted records only | `sub = [r for r in rows if r["Submitted"] == "Yes"]` — unsubmitted records are intentionally excluded from MC tallies to avoid partial data |
| Domain detection is dynamic | The MC chart iterates all dict-valued keys in `_ad` that don't start with `"scale"`. If a new non-MC dict key is added to the form, it will be included in the tally. Guard with `if mc_key.startswith("MC")` already in place |
| Comments cell height | Fixed at `max-height: 72px` with scroll. Increase if assessors routinely write very long comments across all 5 domains |
| `GR_int = -1` for missing GR | Sorts missing GR last when descending (highest first), first when ascending. Consistent with SCBD |
| Charts rebuild on every filter | `plt.close("all")` prevents matplotlib figure accumulation |
| Date filter uses local time | `datetime.strptime` parses without timezone. If the API returns UTC and the server is in a different timezone, off-by-one-day edge cases are possible |
| Max 500 rows shown | `MAX_ROWS = 500`. Increase if needed, but large unfiltered tables slow browser rendering |
| `.env` must be alongside the script | `load_dotenv()` looks in the current working directory |
| `share=True` tunnel expires after 72h | Use HuggingFace Spaces or `server_name="0.0.0.0"` on a VM for permanent access |
