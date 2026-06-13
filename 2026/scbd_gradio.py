#!/usr/bin/env python3
"""
DASH · SCBD Dashboard — Gradio App
────────────────────────────────────
Install:  pip install gradio requests pandas python-dotenv matplotlib numpy
Run:      python scbd_gradio.py
Opens at: http://localhost:7860
"""
import os
import gradio as gr
import requests
import pandas as pd
import tempfile
import numpy as np
from datetime import datetime
from urllib.parse import urlencode
from dotenv import load_dotenv

# ── Load .env (optional — token field is still editable if not set) ──────────
load_dotenv()
ENV_TOKEN = os.getenv("DASH_TOKEN", "")
LOGIN_USER = os.getenv("SCBD_USERNAME")
LOGIN_PASS = os.getenv("SCBD_PASSWORD")

# ── Constants ────────────────────────────────────────────────────────────────
API_BASE    = "https://api.unimelb-dash.com"
EXCLUDE     = set(['kunal patel', 'suhrid gupta', 'test student'])
ALL_COHORTS = ["DDS3", "DDS2"]
COLUMNS     = ["Date", "Student", "Assessor", "Cohort", "Subject", "GR", "Submitted", "Comments"]
MAX_ROWS    = 500

NAVY   = "#010d44"
PURPLE = "#4f5fb2"

# Matches the HTML dashboard colour scheme exactly
GR_COLORS = ["", "#ef4444", "#f97316", "#eab308", "#22c55e", "#10b981"]
COHORT_COLORS = {
    "DDS1": "#818cf8", "DDS2": "#a78bfa", "DDS3": "#c084fc", "DDS4": "#e879f9",
    "BOH1": "#38bdf8", "BOH2": "#22d3ee", "BOH3": "#2dd4bf",
}
TABLE_MAX_HEIGHT = "800px"  # Used in two places; set to "300px" for testing with fewer records
# ── Auto-refresh helpers ──────────────────────────────────────────────────────
INTERVAL_MAP = {
    "Manual only":  (60,  False),
    "Every 15 sec": (15,  True),
    "Every 30 sec": (30,  True),
    "Every 1 min":  (60,  True),
    "Every 5 min":  (300, True)
}

DEFAULT_INTERVAL = "Every 15 sec"
_def_secs, _def_active = INTERVAL_MAP[DEFAULT_INTERVAL] 

# (sort_key, descending)

SORT_OPTIONS = {
    "Date — newest first": ("_ts",       True),
    "Date — oldest first": ("_ts",       False),
    "Student A → Z":       ("Student",   False),
    "Student Z → A":       ("Student",   True),
    "GR — highest first":  ("GR",        True),
    "GR — lowest first":   ("GR",        False),
    "Submitted first":     ("Submitted", True),
    "Submitted last":      ("Submitted", False),
}

DEFAULT_SORT = "Date — newest first"

def set_interval(choice):
    secs, active = INTERVAL_MAP.get(choice, INTERVAL_MAP[DEFAULT_INTERVAL])
    return gr.Timer(value=secs, active=active)


# ── API layer ────────────────────────────────────────────────────────────────
def fetch_all(token: str, cohorts: list, year: str) -> list:
    """
    Fetch all SCBD records for the given cohorts and year, handling pagination.
    Mirrors the JavaScript fetchAll() in scbd_dashboard.html.
    """
    cohort_str = ",".join(cohorts)
    params = urlencode({"page_size": "max", "page": 1,
                        "cohort": cohort_str, "year": year,
                        "ordering": "id"})
    url     = f"{API_BASE}/assessment/scbd/get?{params}"
    headers = {"Authorization": f"Token {token}"}
    records = []
    while url:
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        try:
            d = resp.json()
        except ValueError:
            raise ValueError(f"Non-JSON response from API (HTTP {resp.status_code}): {resp.text[:200]}")
        if isinstance(d, list):
            records.extend(d)
            url = None
        else:
            records.extend(d.get("results", []))
            url = d.get("next")
    return records


# ── Parse ────────────────────────────────────────────────────────────────────
def parse_records(raw: list) -> list:
    """
    Transform raw API records into flat display rows.
    Excludes test students; strips large form/checklist JSON fields.
    """
    rows = []
    for r in raw:
        student = (r.get("student") or "").strip()
        if not student or student.lower() in EXCLUDE:
            continue

        ad = {}
        frm = r.get("form")
        if isinstance(frm, dict):
            ad = (frm.get("data") or {}).get("assessor") or {}
        gr_raw = ad.get("scale-global-rating") or {}
        gr = None
        if isinstance(gr_raw, dict):
            try:
                gr = int(gr_raw["scale"])
            except (KeyError, TypeError, ValueError):
                pass

        dt_str = r.get("datetime") or ""
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            dt_display = f"{dt.day} {dt.strftime('%b %Y')} {dt.strftime('%H:%M')}"
            ts = dt.timestamp()
        except Exception:
            dt_display = dt_str or "—"
            ts = 0.0

        rows.append({
            "_ts":       ts,
            "Date":      dt_display,
            "Student":   student,
            "Assessor":  (r.get("assessor") or "—").strip() or "—",
            "Cohort":    r.get("cohort")  or "—",
            "Subject":   r.get("subject") or "—",
            "GR":        str(gr) if gr is not None else "—",
            "Submitted": "Yes" if r.get("submitted") else "No",
            "Comments":  r.get("form", {}).get("data", {}).get("assessor", {}).get("comments", "—").strip() or "—",
        })

    return rows


# ── Filter / stats helpers ────────────────────────────────────────────────────
def _parse_date_ts(date_str: str, end_of_day: bool = False) -> float | None:
    """Parse YYYY-MM-DD string to a UTC midnight timestamp (or end-of-day)."""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.timestamp()
    except (ValueError, AttributeError):
        return None


def apply_filters(rows: list, submitted_only: bool, unsubmitted_only: bool, search: str,
                  sort_opt: str = DEFAULT_SORT,
                  date_from: str = "", date_to: str = "") -> list:
    # ── Date range ────────────────────────────────────────────────────────
    ts_from = _parse_date_ts(date_from)           if date_from.strip() else None
    ts_to   = _parse_date_ts(date_to, end_of_day=True) if date_to.strip()   else None
    if ts_from is not None:
        rows = [r for r in rows if r["_ts"] >= ts_from]
    if ts_to is not None:
        rows = [r for r in rows if r["_ts"] <= ts_to]
    # ── Submission filter ─────────────────────────────────────────────────
    if submitted_only:
        rows = [r for r in rows if r["Submitted"] == "Yes"]
    elif unsubmitted_only:
        rows = [r for r in rows if r["Submitted"] == "No"]
    # ── Text search ───────────────────────────────────────────────────────
    q = (search or "").lower().strip()
    if q:
        rows = [r for r in rows if any(
            q in (r.get(k) or "").lower()
            for k in ["Student", "Assessor", "Cohort", "Subject"]
        )]
    sort_col, descending = SORT_OPTIONS.get(sort_opt, ("_ts", True))
    def _key(r):
        val = r.get(sort_col, "")
        if sort_col == "_ts":
            return float(val or 0)
        if sort_col == "GR":
            try:
                return int(val)
            except (ValueError, TypeError):
                return -1 if descending else 9999
        return (val or "").lower()
    rows.sort(key=_key, reverse=descending)
    return rows


def make_df(rows: list) -> pd.DataFrame:
    """Plain DataFrame used only for CSV export."""
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame(rows)[COLUMNS]


def _stat_card(label: str, value, color: str = "#0f172a") -> str:
    return (
        f'<div style="flex:1;min-width:200;background:#fff;border:1px solid #e2e8f0;'
        f'border-radius:6px;padding:5px 12px;display:flex;align-items:center;gap:10px;">'
        f'<div style="font-size:18px;font-weight:700;color:{color};white-space:nowrap;">{value}</div>'
        f'<div style="font-size:10px;color:#64748b;font-weight:500;text-transform:uppercase;'
        f'letter-spacing:.4px;line-height:1.2;white-space:nowrap;">{label}</div>'
        f'</div>'
    )

_WRAP = "display:flex;gap:8px;flex-wrap:nowrap;width:100%;padding:2px 0 4px;"
_CARD_LABELS = ["Total records", "Submitted", "Avg global rating", "Unique students", "Assessors active"]

def build_stats_html(rows: list) -> str:
    """Render five stat cards matching the HTML dashboard layout."""
    if not rows:
        cards = "".join(_stat_card(lbl, "—") for lbl in _CARD_LABELS)
        return f'<div style="{_WRAP}">{cards}</div>'
    sub  = [r for r in rows if r["Submitted"] == "Yes"]
    gr_v = [int(r["GR"]) for r in sub if r["GR"] not in ("—", "")]
    avg  = f"{sum(gr_v)/len(gr_v):.2f}" if gr_v else "—"
    pct  = f"{len(sub)} ({round(100*len(sub)/len(rows))}%)"
    stu  = len({r["Student"] for r in rows})
    asr  = len({r["Assessor"] for r in rows if r["Assessor"] != "—"})
    cards = "".join([
        _stat_card("Total records",    len(rows)),
        _stat_card("Submitted",        pct,  color="#15803d"),
        _stat_card("Avg global rating",avg,  color="#4f5fb2"),
        _stat_card("Unique students",  stu),
        _stat_card("Assessors active", asr),
    ])
    return f'<div style="{_WRAP}">{cards}</div>'


# ── HTML table renderer ───────────────────────────────────────────────────────
def make_table_html(rows: list) -> str:
    """
    Render a styled HTML table with:
      · colour-coded GR badges  (red → green, matching HTML dashboard)
      · colour-coded cohort badges
      · green ✓ Yes / grey ✗ No for submitted status
    """
    if not rows:
        return (
            '<div style="text-align:center;padding:60px 0;color:#94a3b8;">'
            '<p style="font-size:14px;">No records to display.<br>'
            'Enter your token, select cohorts, and click Load.</p></div>'
        )

    TH = ("background:#010d44;color:#c7d2fe;padding:9px 14px;"
          "text-align:left;font-weight:500;white-space:nowrap;font-size:12px;")
    TD = "padding:8px 14px;border-bottom:1px solid #f1f5f9;font-size:12px;color:#334155;"

    def gr_badge(gr_str):
        if gr_str == "—":
            return '<span style="color:#94a3b8">—</span>'
        try:
            gi = int(gr_str)
            gc = GR_COLORS[gi] if 1 <= gi <= 5 else "#94a3b8"
            return (f'<span style="background:{gc}33;color:{gc};border-radius:4px;'
                    f'padding:2px 9px;font-size:11px;font-weight:700;">{gi}</span>')
        except (ValueError, IndexError):
            return '<span style="color:#94a3b8">—</span>'

    def cohort_badge(cohort):
        cc = COHORT_COLORS.get(cohort, "#64748b")
        return (f'<span style="background:{cc}22;color:{cc};border-radius:4px;'
                f'padding:2px 8px;font-size:11px;font-weight:600;">{cohort}</span>')

    def sub_cell(val):
        if val == "Yes":
            return '<span style="color:#15803d;font-weight:600;">✓ Yes</span>'
        return '<span style="color:#94a3b8;">✗ No</span>'
    def comments_cell(text):
        if not text:
            return '<span style="color:#cbd5e1;font-size:11px;">—</span>'
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'<div style="max-height:32px;overflow-y:auto;width:420px;'
            f'word-break:break-word;white-space:pre-wrap;font-size:11px;'
            f'color:#475569;line-height:1.4;padding-right:4px;">{escaped}</div>'
    )
    headers  = ["Date", "Student", "Assessor", "Cohort", "GR", "Submitted", "Comments"]
    thead    = "".join(f'<th style="{TH}">{h}</th>' for h in headers)
    display  = rows[:MAX_ROWS]
    body     = []

    for i, r in enumerate(display):
        bg   = "#ffffff" if i % 2 == 0 else "#f8fafc"
        # subj = r["Subject"] or "—"
        # subj_cell = (
        #     f'<span title="{subj}" style="display:inline-block;max-width:180px;'
        #     f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#334155;">{subj}</span>'
        # )
        body.append(
            f'<tr style="background:{bg}">'
            f'<td style="{TD}color:#64748b;white-space:nowrap;">{r["Date"]}</td>'
            f'<td style="{TD}font-weight:500;">{r["Student"]}</td>'
            f'<td style="{TD}">{r["Assessor"]}</td>'
            f'<td style="{TD}">{cohort_badge(r["Cohort"])}</td>'
            # f'<td style="{TD}">{subj_cell}</td>'
            f'<td style="{TD}">{gr_badge(r["GR"])}</td>'
            f'<td style="{TD}">{sub_cell(r["Submitted"])}</td>'
            f'<td style="{TD}">{comments_cell(r["Comments"])}</td>'
            f'</tr>'
        )

    trunc = ""
    if len(rows) > MAX_ROWS:
        trunc = (
            f'<tr><td colspan="7" style="padding:10px 14px;color:#94a3b8;font-size:11px;">'
            f'Showing {MAX_ROWS} of {len(rows)} records — use search to narrow down'
            f'</td></tr>'
        )

    return (
        f'<div style="overflow-x:auto;overflow-y:auto;max-height:{TABLE_MAX_HEIGHT};border-radius:8px;border:1px solid #e2e8f0;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(body)}{trunc}</tbody>'
        '</table></div>'
    )


# ── Chart builder ─────────────────────────────────────────────────────────────
def _style_ax(ax, title):
    ax.set_facecolor("#f8fafc")
    ax.yaxis.grid(True, color="white", linewidth=1.5, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title(title, fontsize=12, fontweight="600", color="#475569", pad=12)
    ax.tick_params(colors="#64748b", labelsize=10)
    for spine in ax.spines.values():
        spine.set_visible(False)

# ── Gradio event handlers ─────────────────────────────────────────────────────
#
# Return order for load_outputs:
#   [raw_state, table_html, chart_plot, stats_html, updated_md, error_md]

def do_load(cohorts, submitted_only, unsubmitted_only, search, sort_opt=DEFAULT_SORT,
            date_from="", date_to=""):
    """Fetch from API → parse → cache in State → return filtered view."""
    _empty = ([], make_table_html([]), build_stats_html([]), "", "")

    if not ENV_TOKEN:
        return *_empty, "❌ No API token found in .env file."
    if not cohorts:
        return *_empty, "❌ Please select at least one cohort."

    try:
        raw  = fetch_all(ENV_TOKEN, cohorts, "2026")
        rows = parse_records(raw)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        msg = {401: "Unauthorised — check your API token",
               403: "Forbidden — token may lack permissions for this cohort"}.get(
                   status, f"HTTP {status} from API")
        return *_empty, f"❌ {msg}"
    except Exception as e:
        return *_empty, f"❌ Connection error: {e}"

    filtered = apply_filters(rows, submitted_only, unsubmitted_only, search, sort_opt, date_from, date_to)
    ts       = datetime.now().strftime("%H:%M:%S")
    return (
        rows,
        make_table_html(filtered),
        build_stats_html(filtered),
        f"*Last loaded {ts}*",
        "",
    )


def do_filter(rows, submitted_only, unsubmitted_only, search, sort_opt=DEFAULT_SORT, date_from="", date_to=""):
    """Re-filter cached rows without hitting the API."""
    filtered = apply_filters(rows, submitted_only, unsubmitted_only, search, sort_opt, date_from, date_to)
    return make_table_html(filtered), build_stats_html(filtered)


def do_export(rows, submitted_only, unsubmitted_only, search, sort_opt=DEFAULT_SORT, date_from="", date_to=""):
    """Write the filtered view to a temp Excel file and return its path."""
    filtered = apply_filters(rows, submitted_only, unsubmitted_only, search, sort_opt, date_from, date_to)
    df  = make_df(filtered)
    tmp = tempfile.NamedTemporaryFile(
        suffix=".xlsx", delete=False, mode="w", newline="", encoding="utf-8-sig"
    )
    df.to_excel(tmp.name, index=False)
    tmp.close()
    return tmp.name


# ── Layout ────────────────────────────────────────────────────────────────────
css = f"""
.gradio-container {{ max-width: 1400px !important; margin: 0 auto; }}
#dash-header {{ background:{NAVY}; border-radius:8px; padding:8px 16px; margin-bottom:4px; display:flex; align-items:center; gap:16px; }}
#dash-header h2 {{ color:white; margin:0; font-size:16px; letter-spacing:1px; }}
#dash-header p  {{ color:#c7d2fe; margin:0; font-size:11px; }}
#err-bar    {{ color:#dc2626; min-height:0; }}
#ts-bar     {{ color:#94a3b8; font-size:11px; text-align:right; min-height:0; }}
.compact-row .gap {{ gap:6px !important; }}
footer {{ display:none !important; }}
"""

with gr.Blocks(title="DASH · SCBD Monitor", css=css,
               theme=gr.themes.Default(primary_hue="indigo")) as demo:

    raw_state = gr.State([])
    timer     = gr.Timer(value=_def_secs, active=_def_active)

    # ── Header (compact single line) ──────────────────────────────────────
    gr.HTML(
        '<div id="dash-header">'
        '<h2>DASH</h2>'
        '<p>SCBD Live Monitor</p>'
        '</div>'
    )

    # ── Row 1: date range + refresh interval + load button ───────────────
    with gr.Row(elem_classes="compact-row"):
        date_from   = gr.Textbox(label="From", value="2026-06-09", placeholder="YYYY-MM-DD", scale=2)
        date_to     = gr.Textbox(label="To",   value="2026-06-10", placeholder="YYYY-MM-DD", scale=2)
        interval_dd = gr.Dropdown(
            list(INTERVAL_MAP.keys()), value=DEFAULT_INTERVAL,
            label="Refresh", scale=2,
        )
        load_btn = gr.Button("↻ Load", variant="primary", scale=1)

    # ── Row 2: cohorts + search + sort + submitted checkboxes ────────────
    with gr.Row(elem_classes="compact-row"):
        cohort_in = gr.CheckboxGroup(
            ALL_COHORTS, value=["DDS3"],
            label="Cohorts", scale=2,
        )
        search_in = gr.Textbox(
            label="Search",
            placeholder="student · assessor · cohort · subject…",
            scale=3,
        )
        sort_dd = gr.Dropdown(
            list(SORT_OPTIONS.keys()), value=DEFAULT_SORT,
            label="Sort by", scale=2,
        )
        with gr.Column(scale=1, min_width=160):
            sub_only   = gr.Checkbox(label="Submitted only",   value=False)
            unsub_only = gr.Checkbox(label="Unsubmitted only", value=False)

    # ── Stats + status bar (single row) ──────────────────────────────────
    with gr.Row(elem_classes="compact-row"):
        stats_html = gr.HTML(build_stats_html([]))
        error_md   = gr.Markdown("", elem_id="err-bar")
        updated_md = gr.Markdown("", elem_id="ts-bar")

    # ── Table ─────────────────────────────────────────────────────────────
    table_html = gr.HTML(make_table_html([]))

    # ── CSV export ────────────────────────────────────────────────────────
    with gr.Row(elem_classes="compact-row"):
        export_btn = gr.Button("⬇ Export CSV", size="sm", scale=1)
        csv_out    = gr.File(label="Download CSV", visible=False, scale=3)

    # ── Event wiring ──────────────────────────────────────────────────────
    load_inputs  = [cohort_in, sub_only, unsub_only, search_in, sort_dd, date_from, date_to]
    load_outputs = [raw_state, table_html, stats_html, updated_md, error_md]

    load_btn.click(fn=do_load, inputs=load_inputs, outputs=load_outputs)

    filter_inputs = [raw_state, sub_only, unsub_only, search_in, sort_dd, date_from, date_to]
    for widget in [sub_only, unsub_only, search_in, sort_dd, date_from, date_to]:
        widget.change(fn=do_filter, inputs=filter_inputs, outputs=[table_html, stats_html])

    interval_dd.change(fn=set_interval, inputs=[interval_dd], outputs=[timer])
    timer.tick(fn=do_load, inputs=load_inputs, outputs=load_outputs)

    export_btn.click(
        fn=do_export,
        inputs=[raw_state, sub_only, unsub_only, search_in, sort_dd, date_from, date_to],
        outputs=[csv_out],
    ).then(fn=lambda: gr.update(visible=True), outputs=[csv_out])


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  DASH · SCBD Gradio Dashboard")
    print("  ─────────────────────────────")
    print("  Opening at http://localhost:7860")
    print("  Press Ctrl+C to stop\n")
    demo.launch(server_name="localhost", server_port=7860, share=True, auth =(LOGIN_USER, LOGIN_PASS) if LOGIN_USER and LOGIN_PASS else None)