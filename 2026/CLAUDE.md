This folder contains codes for report creation and data analysis alongside dashboard creations.

---

## viva_gradio.py — Context & Decisions

### File structure
- `viva_gradio.py` — main Gradio app. Imports everything from `gradio_utils.py` via `from gradio_utils import *`
- `gradio_utils.py` — all constants and config variables (NAVY, COMMENTS_MAX_HEIGHT, TABLE_COLS, DOMAIN_ORDER, etc.) moved here to keep `viva_gradio.py` shorter

### Gradio version quirks (important)
- On **Gradio 6**, `js=`, `css=`, `head=` moved from `gr.Blocks()` to `demo.launch()`
- `gr.HTML()` **never executes `<script>` tags** — scripts in innerHTML don't run (browser security, not a Gradio bug)
- `launch(js=...)` is broken in some Gradio 6 builds
- `launch(head=...)` was tried and broke the app
- `sanitize_html=False` is set on the `table_html = gr.HTML(...)` component — this preserves `ondblclick` and other event handler attributes

### Comment cell modal (double-click to expand)
- Located in `comments_cell()` inside `make_table_html()` in `viva_gradio.py`
- Uses a **self-contained inline `ondblclick` handler** — no globally defined JS functions needed
- The handler is a minified IIFE built via Python string concatenation in `comments_cell()`
- Modal is appended to `document.body` (outside `gr.HTML` component) so it **survives auto-refresh table re-renders**
- `data-comment` attribute stores the raw comment text (HTML-entity encoded); JS reads it via `getAttribute` which auto-decodes entities
- Modal built entirely with `createElement` / `textContent` / `style.cssText` — no innerHTML with quoted strings, avoids HTML entity escaping issues
- Closes via ✕ button, backdrop click, or Escape key

### What was tried and failed for JS injection (don't repeat)
1. `<script>` block inside `make_table_html()` return string — scripts in innerHTML never execute
2. `gr.Blocks(js=_startup_js)` — Gradio 6 ignores this parameter
3. `demo.launch(js=_startup_js)` — broken in current Gradio 6 build
4. `demo.launch(head=_startup_head)` — broke the app entirely
5. `<details>/<summary>` CSS-only expand — works but collapses on every auto-refresh since the table HTML is fully rebuilt

### Table structure
- `make_table_html(rows)` in `viva_gradio.py` — renders full HTML table
- Column visibility/width controlled by `TABLE_COLS` dict in `gradio_utils.py`
- `TABLE_MAX_HEIGHT = "600px"`, `COMMENTS_MAX_HEIGHT = "72px"` (scrollable by default)
- Domain columns: DDS4-1 through DDS4-5, displayed as D1–D5
- Color coding: GR badges, domain score %, overall %, submitted status

### Auto-refresh
- `gr.Timer` drives auto-refresh; interval controlled by dropdown (default: Every 30 sec)
- Timer calls `do_load()` which re-fetches API and rebuilds entire table HTML
- `INTERVAL_MAP` in `gradio_utils.py` maps dropdown labels to (seconds, active) tuples

### API
- Base: `https://api.unimelb-dash.com`
- Auth: Django REST Framework Token (not Bearer) — `Authorization: Token <token>`
- Endpoint: `GET /assessment/viva/get?page_size=max&page=1&cohort=...&year=...`
- Token loaded from `.env` as `DASH_TOKEN`; optional login auth via `VIVA_USERNAME` / `VIVA_PASSWORD`