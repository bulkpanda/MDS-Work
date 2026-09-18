#!/usr/bin/env python3
"""
DASH · Viva Exam Dashboard — Gradio App
────────────────────────────────────────
Install:  pip install gradio requests pandas python-dotenv matplotlib numpy
Run:      python viva_gradio.py
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
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from gradio_utils import *
from gradio_utils import _WRAP, _CARD_LABELS, _def_active, _def_secs
# ── Load .env (optional — token field is still editable if not set) ──────────
load_dotenv()
ENV_TOKEN  = os.getenv("DASH_TOKEN", "")
LOGIN_USER = os.getenv("VIVA_USERNAME")
LOGIN_PASS = os.getenv("VIVA_PASSWORD")
# print gradio version for debugging
print(f"Using Gradio version: {gr.__version__}")


def set_interval(choice):
    secs, active = INTERVAL_MAP.get(choice, INTERVAL_MAP[DEFAULT_INTERVAL])
    return gr.Timer(value=secs, active=active)


# ── API layer ────────────────────────────────────────────────────────────────
def fetch_all(token: str, cohorts: list, year: str) -> list:
    """
    Fetch all viva records for the given cohorts and year, following pagination.
    Endpoint: GET /assessment/viva/get?page_size=max&page=1&cohort=...&year=...
    Auth: Django REST Framework Token (not Bearer).
    """
    cohort_str = ",".join(cohorts)
    params = urlencode({"page_size": "max", "page": 1,
                        "cohort": cohort_str, "year": year,
                        "ordering": "id"})
    url     = f"{API_BASE}/assessment/{ASSESS_TYPE}/get?{params}"
    headers = {"Authorization": f"Token {token}"}
    records = []
    while url:
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        d = resp.json()
        if isinstance(d, list):          # flat list response (no pagination)
            records.extend(d)
            url = None
        else:                            # paginated DRF response
            records.extend(d.get("results", []))
            url = d.get("next")
    return records


# ── Comment builder ──────────────────────────────────────────────────────────
def _build_combined_comments(ad: dict) -> str:
    """
    Concatenate all comment fields from the assessor dict into one string.

    Combines:
      · General comments  (key: "comments")
      · Per-domain comments (keys matching pattern "<domain>_comments",
        e.g. "DDS4-1_comments", "DDS4-2_comments", …)

    Result format (only non-empty fields included):
        [General] Horrors beyond comprehension.
        [DDS4-1] Domain1
        [DDS4-2] Domain 2
        …
    """
    parts = []

    general = (ad.get("comments") or "").strip()
    if general:
        parts.append(f"[General] {general}")

    # Collect domain comment keys in defined order first, then any extras
    seen = set()
    ordered_keys = [f"{d}_comments" for d in DOMAIN_ORDER]
    extra_keys   = [k for k in ad if k.endswith("_comments") and k not in ordered_keys]

    for key in ordered_keys + extra_keys:
        val = (ad.get(key) or "").strip()
        if val:
            label = key.replace("_comments", "")
            parts.append(f"[{label}] {val}")
            seen.add(key)

    # Critical error / clinical incident fields
    for fld, label in [("critical_error", "Critical Error"), ("clinical_incident", "Clinical Incident")]:
        val = (ad.get(fld) or "").strip()
        if val:
            parts.append(f"[{label}] {val}")

    return "\n".join(parts) if parts else "—"


# ── Domain scoring ────────────────────────────────────────────────────────────
def _domain_score(domain_dict: dict, domain: str) -> tuple[int, int]:
    """Return (score, official_max) for a domain's MC items."""
    items = {k: v for k, v in domain_dict.items() if k.startswith("MC")}
    score = sum(MC_SCORE.get(v, 0) for v in items.values())
    max_s = DOMAIN_MAX.get(domain, len(items) * 4)
    return score, max_s


# ── Parse ────────────────────────────────────────────────────────────────────
def parse_records(raw: list) -> list:
    """
    Transform raw API records into flat display rows.

    For each record the assessor block (form.data.assessor) is expected to contain:
      · "scale-global-rating": {"scale": "3"}   — numeric GR 1-5
      · "comments": "…"                         — general free-text comment
      · "<domain>_comments": "…"                — per-domain comment
      · "<domain>": {"MC1": "Done well", …}     — checklist items per domain

    All comment fields are merged by _build_combined_comments() into a single
    "Comments" column so the table stays manageable.
    """
    rows = []
    for r in raw:
        student = (r.get("student") or "").strip()
        if not student or student.lower() in EXCLUDE:
            continue

        ad          = {}
        _checklists = {}
        frm = r.get("form")
        if isinstance(frm, dict):
            ad          = (frm.get("data") or {}).get("assessor") or {}
            _checklists = frm.get("checklists") or {}

        # ── Global rating ─────────────────────────────────────────────────
        gr_raw = ad.get("scale-global-rating") or {}
        gr_int = None
        if isinstance(gr_raw, dict):
            try:
                gr_int = int(gr_raw["scale"])
            except (KeyError, TypeError, ValueError):
                pass

        # ── Datetime ──────────────────────────────────────────────────────
        dt_str = r.get("datetime") or ""
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            dt_display = f"{dt.day} {dt.strftime('%b %Y')}"
            ts = dt.timestamp()
        except Exception:
            dt_display = dt_str or "—"
            ts = 0.0

        # ── Domain scores ─────────────────────────────────────────────────
        domain_scores = {}
        for domain in DOMAIN_ORDER:
            d = ad.get(domain)
            if isinstance(d, dict):
                score, max_s = _domain_score(d, domain)
                domain_scores[domain] = {"score": score, "max": max_s, "items": d}

        # ── Combined comments ─────────────────────────────────────────────
        combined = _build_combined_comments(ad)

        rows.append({
            "_ts":           ts,
            "_ad":           ad,
            "_checklists":   _checklists,
            "_domain_scores": domain_scores,
            "Date":      dt_display,
            "Student":   student,
            "Assessor":  (r.get("assessor") or "—").strip() or "—",
            "Cohort":    r.get("cohort")  or "—",
            "Subject":   r.get("subject") or "—",
            "GR":        str(gr_int) if gr_int is not None else "—",
            "GR_int":    gr_int if gr_int is not None else -1,
            "GR_label":  GR_LABELS.get(gr_int, "—") if gr_int else "—",
            "Overall":   sum(ds["score"] for ds in domain_scores.values()),
            "Submitted": "Yes" if r.get("submitted") else "No",
            "Comments":  combined,
        })

    return rows


# ── Filter / stats helpers ────────────────────────────────────────────────────
def _parse_date_ts(date_str: str, end_of_day: bool = False) -> float | None:
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
    """Filter and sort cached rows (no API call)."""
    ts_from = _parse_date_ts(date_from)                if date_from.strip() else None
    ts_to   = _parse_date_ts(date_to, end_of_day=True) if date_to.strip()   else None
    if ts_from is not None:
        rows = [r for r in rows if r["_ts"] >= ts_from]
    if ts_to is not None:
        rows = [r for r in rows if r["_ts"] <= ts_to]
    if submitted_only:
        rows = [r for r in rows if r["Submitted"] == "Yes"]
    elif unsubmitted_only:
        rows = [r for r in rows if r["Submitted"] == "No"]
    q = (search or "").lower().strip()
    if q:
        rows = [r for r in rows if any(
            q in (r.get(k) or "").lower()
            for k in ["Student", "Assessor", "Cohort", "Subject", "Comments"]
        )]
    sort_col, descending = SORT_OPTIONS.get(sort_opt, ("_ts", True))
    def _key(r):
        val = r.get(sort_col, "")
        if sort_col in ("_ts", "GR_int"):
            return float(val or 0)
        return (val or "").lower()
    rows.sort(key=_key, reverse=descending)
    return rows


def make_df(rows: list) -> pd.DataFrame:
    """Plain DataFrame for summary export using EXPORT_COLUMNS.
    D1–D5 and Overall in EXPORT_COLUMNS are populated from _domain_scores."""
    if not rows:
        return pd.DataFrame(columns=EXPORT_COLUMNS)
    records = []
    for r in rows:
        ds = r.get("_domain_scores") or {}
        rec = {}
        for k in EXPORT_COLUMNS:
            if k in DOMAIN_LABELS.values():  # D1, D2, D3, D4, D5
                domain_key = next((d for d, lbl in DOMAIN_LABELS.items() if lbl == k), None)
                info = ds.get(domain_key) if domain_key else None
                rec[k] = info["score"] if info else ""
            elif k == "Overall":
                rec[k] = r.get("Overall", "") if ds else ""
            else:
                rec[k] = r.get(k, "")
        records.append(rec)
    return pd.DataFrame(records, columns=EXPORT_COLUMNS)


# ── Stat cards ────────────────────────────────────────────────────────────────
def _stat_card(label: str, value, color: str = "#0f172a") -> str:
    return (
        f'<div style="flex:1;min-width:200;background:#fff;border:1px solid #e2e8f0;'
        f'border-radius:6px;padding:5px 12px;display:flex;align-items:center;gap:10px;">'
        f'<div style="font-size:{STAT_VALUE_FONT_SIZE};font-weight:700;color:{color};white-space:nowrap;">{value}</div>'
        f'<div style="font-size:{STAT_LABEL_FONT_SIZE};color:#64748b;font-weight:500;text-transform:uppercase;'
        f'letter-spacing:.4px;line-height:1.2;white-space:nowrap;">{label}</div>'
        f'</div>'
    )


def build_stats_html(rows: list) -> str:
    if not rows:
        cards = "".join(_stat_card(lbl, "—") for lbl in _CARD_LABELS)
        return f'<div style="{_WRAP}">{cards}</div>'
    sub  = [r for r in rows if r["Submitted"] == "Yes"]
    gr_v = [r["GR_int"] for r in sub if r["GR_int"] > 0]
    avg  = f"{sum(gr_v)/len(gr_v):.2f}" if gr_v else "—"
    pct  = f"{len(sub)} ({round(100*len(sub)/len(rows))}%)"
    stu  = len({r["Student"] for r in rows})
    asr  = len({r["Assessor"] for r in rows if r["Assessor"] != "—"})
    cards = "".join([
        _stat_card("Total records",     len(rows)),
        _stat_card("Submitted",         pct,  color="#15803d"),
        _stat_card("Avg global rating", avg,  color="#4f5fb2"),
        _stat_card("Unique students",   stu),
        _stat_card("Assessors active",  asr),
    ])
    return f'<div style="{_WRAP}">{cards}</div>'


# ═══════════════════════════════════════════════════════════════════════════════
# ── Full form modal ────────────────────────────────────────────────────────────
#
#  build_form_html(row)  →  HTML string (data-html attr on the View button)
#  _FORM_MODAL_HANDLER   →  self-contained onclick JS (no global functions needed)
#
#  To HIDE the column only:   set TABLE_COLS["View"]["show"] = False in gradio_utils.py
#  To SKIP the HTML build:    comment out the `build_form_html(r)` call in make_table_html
#  To REMOVE the feature:     delete this entire section + the View wiring in make_table_html
# ═══════════════════════════════════════════════════════════════════════════════

def build_form_html(row: dict) -> str:
    """
    Build full-form HTML for `row`, returned with " escaped as &quot; so it is
    safe to embed in a data-html="..." attribute.

    JS will set modal.innerHTML = el.getAttribute('data-html'), so:
      · Structural HTML uses normal " (escaped to &quot; at the end).
      · User text is double-encoded via e() so it survives the getAttribute decode.

    To disable this builder entirely, just return "" here.
    """
    # ── text escaper for user data (double-encode for getAttribute round-trip) ─
    def e(s: object) -> str:
        return (str(s or "")
                .replace("&", "&amp;amp;")
                .replace("<", "&amp;lt;")
                .replace(">", "&amp;gt;"))

    ad  = row.get("_ad")            or {}
    cl  = row.get("_checklists")    or {}
    ds  = row.get("_domain_scores") or {}
    p   = []   # HTML parts list

    # ── Header ────────────────────────────────────────────────────────────────
    sub_color = "#15803d" if row.get("Submitted") == "Yes" else "#94a3b8"
    gr_int    = row.get("GR_int", -1)
    gr_color  = GR_COLORS[gr_int] if 1 <= gr_int <= 5 else "#64748b"
    p.append(
        f'<div style="margin-bottom:20px;padding-bottom:14px;border-bottom:2px solid #e2e8f0;">'
        f'<div style="font-size:15px;font-weight:700;color:#010d44;margin-bottom:8px;">'
        f'{e(row.get("Cohort",""))} &middot; {e(row.get("Subject",""))} &middot; {e(row.get("Date",""))}'
        f'</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 24px;font-size:12px;">'
        f'<div style="color:#0f172a;"><span style="color:#64748b;">Student:</span> <b>{e(row.get("Student","—"))}</b></div>'
        f'<div style="color:#0f172a;"><span style="color:#64748b;">Assessor:</span> {e(row.get("Assessor","—"))}</div>'
        f'<div><span style="color:#64748b;">GR:</span> '
        f'<b style="color:{gr_color};">{e(row.get("GR","—"))} — {e(row.get("GR_label",""))}</b></div>'
        f'<div><span style="color:#64748b;">Submitted:</span> '
        f'<span style="color:{sub_color};font-weight:600;">{e(row.get("Submitted","—"))}</span></div>'
        f'</div></div>'
    )

    # ── Domain sections ────────────────────────────────────────────────────────
    for domain in DOMAIN_ORDER:
        domain_cl   = cl.get(domain)   or {}
        domain_name = domain_cl.get("name") or domain
        domain_info = ds.get(domain)   or {}
        all_items   = domain_info.get("items") or {}
        mc_items    = {k: v for k, v in all_items.items() if k.startswith("MC")}
        fields      = domain_cl.get("fields") or {}
        hdr_map     = (domain_cl.get("extra_config") or {}).get("headers") or {}
        score       = domain_info.get("score")
        max_s       = domain_info.get("max")

        if not mc_items:
            continue

        score_str = f"{score}/{max_s}" if score is not None else "—"
        p.append(
            f'<div style="margin-bottom:20px;">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'background:#010d44;color:#c7d2fe;padding:7px 12px;border-radius:6px;margin-bottom:8px;">'
            f'<span style="font-weight:600;font-size:13px;">{e(domain_name)}</span>'
            f'<span style="font-size:12px;opacity:.8;">{score_str}</span>'
            f'</div>'
        )

        shown_hdrs = set()
        for mc_key in sorted(mc_items.keys()):
            val   = mc_items.get(mc_key) or "—"
            label = fields.get(mc_key) or mc_key
            rc    = MC_COLORS.get(val, "#64748b")

            # Sub-section header
            hdr_entry = hdr_map.get(mc_key)
            if isinstance(hdr_entry, list) and hdr_entry:
                title = (hdr_entry[0].get("title") or "").strip()
                if title and title not in shown_hdrs:
                    shown_hdrs.add(title)
                    p.append(
                        f'<div style="background:#334155;color:#e2e8f0;padding:4px 10px;'
                        f'font-size:11px;font-weight:600;letter-spacing:.3px;'
                        f'margin:6px 0 3px;border-radius:3px;">{e(title)}</div>'
                    )

            p.append(
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;'
                f'padding:4px 8px;border-bottom:1px solid #f1f5f9;font-size:12px;">'
                f'<span style="color:#475569;flex:1;padding-right:12px;">{e(label)}</span>'
                f'<span style="color:{rc};font-weight:600;white-space:nowrap;">{e(val)}</span>'
                f'</div>'
            )

        # Per-domain comment
        dcmt = (ad.get(f"{domain}_comments") or "").strip()
        if dcmt:
            p.append(
                f'<div style="margin-top:7px;padding:5px 8px;background:#f8fafc;'
                f'border-left:3px solid #c7d2fe;border-radius:0 4px 4px 0;font-size:12px;">'
                f'<span style="color:#64748b;font-weight:600;">Comments: </span>'
                f'<span style="color:#475569;">{e(dcmt)}</span>'
                f'</div>'
            )

        p.append('</div>')   # close domain div

    # ── Critical Error ─────────────────────────────────────────────────────────
    critical = (ad.get("critical_error") or "").strip()
    p.append(
        f'<div style="margin-bottom:14px;padding:9px 12px;border:1px solid #fecaca;'
        f'border-radius:6px;background:#fff5f5;">'
        f'<div style="font-weight:600;color:#dc2626;font-size:11px;'
        f'text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px;">Critical Error</div>'
        f'<div style="font-size:12px;color:#334155;">'
        f'{e(critical) if critical else "<i>None reported</i>"}'
        f'</div></div>'
    )

    # ── Global Rating ──────────────────────────────────────────────────────────
    p.append(
        f'<div style="margin-bottom:14px;padding:9px 12px;border:1px solid #e2e8f0;'
        f'border-radius:6px;">'
        f'<div style="font-weight:600;color:#334155;font-size:11px;'
        f'text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px;">Global Rating Scale</div>'
        f'<div style="font-size:14px;font-weight:700;color:{gr_color};">'
        f'{e(row.get("GR","—"))} — {e(row.get("GR_label","—"))}'
        f'</div></div>'
    )

    # ── Additional Comments ────────────────────────────────────────────────────
    general = (ad.get("comments") or "").strip()
    p.append(
        f'<div style="margin-bottom:4px;padding:9px 12px;border:1px solid #e2e8f0;'
        f'border-radius:6px;">'
        f'<div style="font-weight:600;color:#334155;font-size:11px;'
        f'text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px;">Additional Comments</div>'
        f'<div style="font-size:12px;color:#475569;">'
        f'{e(general) if general else "<i>None provided</i>"}'
        f'</div></div>'
    )

    html = "".join(p)
    return html.replace('"', '&quot;')


# Self-contained form modal handler — same pattern as the comments modal.
# Creates/reuses a <div id="_vfm"> on document.body (survives table re-renders).
# Sets modal body innerHTML from the pre-built data-html attribute.
_FORM_MODAL_HANDLER = (
    "(function(el){"
    "var m=document.getElementById('_vfm');"
    "if(!m){"
    "m=document.createElement('div');"
    "m.id='_vfm';"
    "m.style.cssText='display:none;position:fixed;inset:0;background:rgba(1,13,68,.45);z-index:9999;align-items:center;justify-content:center';"
    "var w=document.createElement('div');"
    "w.style.cssText='background:#fff;border-radius:10px;max-width:820px;width:95%;max-height:88vh;overflow-y:auto;padding:28px 32px;position:relative;box-shadow:0 20px 60px rgba(0,0,0,.3)';"
    "var x=document.createElement('button');"
    "x.textContent='\\u2715';"
    "x.style.cssText='position:absolute;top:12px;right:14px;background:none;border:1px solid #e2e8f0;border-radius:4px;width:26px;height:26px;cursor:pointer;font-size:13px;color:#64748b';"
    "x.onclick=function(){m.style.display='none'};"
    "var b=document.createElement('div');"
    "b.id='_vfb';"
    "w.appendChild(x);w.appendChild(b);m.appendChild(w);"
    "m.onclick=function(e){if(e.target===m)m.style.display='none'};"
    "document.addEventListener('keydown',function(e){if(e.key==='Escape')m.style.display='none'});"
    "document.body.appendChild(m);"
    "}"
    "document.getElementById('_vfb').innerHTML=el.getAttribute('data-html');"
    "m.style.display='flex';"
    "})(this)"
)

# ── HTML table renderer ───────────────────────────────────────────────────────
def make_table_html(rows: list) -> str:
    """
    Styled HTML table.  Column visibility and widths are controlled by TABLE_COLS
    in the config section at the top of this file.
    """
    if not rows:
        return (
            '<div style="text-align:center;padding:60px 0;color:#94a3b8;">'
            '<p style="font-size:14px;">No records to display.<br>'
            'Enter your token, select cohorts, and click Load.</p></div>'
        )

    TH = (f"background:#010d44;color:#c7d2fe;padding:9px 14px;"
          f"text-align:left;font-weight:500;white-space:nowrap;font-size:{TABLE_FONT_SIZE};")
    TD = f"padding:8px 14px;border-bottom:1px solid #f1f5f9;font-size:{TABLE_FONT_SIZE};color:#334155;"

    def _on(key):
        return TABLE_COLS.get(key, {}).get("show", True)

    def _col(key):
        w = TABLE_COLS.get(key, {}).get("width")
        return f'<col style="width:{w}px">' if w else '<col>'

    # ── Cell helpers ──────────────────────────────────────────────────────────
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
            return '<span style="color:#15803d;font-weight:600;">✓</span>'
        return '<span style="color:#94a3b8;">✗</span>'

    def comments_cell(text):
        if not text or text == "—":
            return '<span style="color:#cbd5e1;font-size:11px;">—</span>'
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines = escaped.split("\n")
        html_lines = []
        for line in lines:
            if line.startswith("[") and "]" in line:
                bracket_end = line.index("]") + 1
                label_part  = line[:bracket_end]
                body_part   = line[bracket_end:]
                html_lines.append(
                    f'<span style="color:{NAVY};font-weight:600;">{label_part}</span>'
                    f'<span style="color:#475569;">{body_part}</span>'
                )
            else:
                html_lines.append(f'<span style="color:#475569;">{line}</span>')
        inner = "<br>".join(html_lines)
        # encode raw text for the data attribute (browser decodes on getAttribute)
        data_val = (text.replace("&", "&amp;").replace('"', "&quot;")
                        .replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;"))
        # Self-contained modal handler — creates/reuses a modal on document.body.
        # Built entirely with DOM methods so there are no nested HTML-entity issues.
        # The modal lives outside the gr.HTML component, so it survives table re-renders.
        handler = (
            "(function(el){"
            "var m=document.getElementById('_vcm');"
            "if(!m){"
            "m=document.createElement('div');"
            "m.id='_vcm';"
            "m.style.cssText='display:none;position:fixed;inset:0;background:rgba(1,13,68,.45);z-index:9999;align-items:center;justify-content:center';"
            "var w=document.createElement('div');"
            "w.style.cssText='background:#fff;border-radius:10px;max-width:700px;width:90%;max-height:80vh;overflow-y:auto;padding:28px 32px;position:relative;box-shadow:0 20px 60px rgba(0,0,0,.3)';"
            "var x=document.createElement('button');"
            "x.textContent='\\u2715';"
            "x.style.cssText='position:absolute;top:12px;right:14px;background:none;border:1px solid #e2e8f0;border-radius:4px;width:26px;height:26px;cursor:pointer;font-size:13px;color:#64748b';"
            "x.onclick=function(){m.style.display='none'};"
            "var b=document.createElement('div');"
            "b.id='_vcb';"
            "b.style.cssText='font-size:13px;line-height:1.8';"
            "w.appendChild(x);w.appendChild(b);m.appendChild(w);"
            "m.onclick=function(e){if(e.target===m)m.style.display='none'};"
            "document.addEventListener('keydown',function(e){if(e.key==='Escape')m.style.display='none'});"
            "document.body.appendChild(m);"
            "}"
            "var raw=el.getAttribute('data-comment');"
            "var bd=document.getElementById('_vcb');"
            "bd.innerHTML='';"
            "raw.split('\\n').forEach(function(l){"
            "var r=document.createElement('div');"
            "r.style.marginBottom='12px';"
            "if(l.charAt(0)==='['&&l.indexOf(']')!==-1){"
            "var i=l.indexOf(']')+1;"
            "var s1=document.createElement('span');"
            "s1.style.cssText='color:#010d44;font-weight:700';"
            "s1.textContent=l.slice(0,i);"
            "var s2=document.createElement('span');"
            "s2.style.color='#334155';"
            "s2.textContent=l.slice(i);"
            "r.appendChild(s1);r.appendChild(s2);"
            "}else{"
            "r.style.color='#334155';"
            "r.textContent=l;"
            "}"
            "bd.appendChild(r);"
            "});"
            "m.style.display='flex';"
            "})(this)"
        )
        return (
            f'<div ondblclick="{handler}" data-comment="{data_val}" '
            f'title="Double-click to read full comment" '
            f'style="max-height:{COMMENTS_MAX_HEIGHT};overflow-y:auto;cursor:pointer;'
            f'width:100%;word-break:break-word;white-space:normal;font-size:11px;'
            f'line-height:1.5;padding-right:4px;">{inner}</div>'
        )

    def domain_score_cell(ds: dict, domain: str) -> str:
        info = ds.get(domain)
        if not info:
            return '<span style="color:#cbd5e1;font-size:11px;">—</span>'
        s, m = info["score"], info["max"]
        pct  = s / m if m else 0
        color = ("#15803d" if pct >= 0.85 else
                 "#2563eb" if pct >= 0.65 else
                 "#d97706" if pct >= 0.40 else "#dc2626")
        return (f'<span style="font-weight:700;color:{color};">{s}</span>'
                f'<span style="color:#94a3b8;font-size:10px;">/{m}</span>')

    def overall_cell(row):
        ds = row.get("_domain_scores") or {}
        if not ds:
            return '<span style="color:#94a3b8;font-size:11px;">N/A</span>'
        score = row.get("Overall", 0)
        pct   = score / TOTAL_MAX
        color = ("#15803d" if pct >= 0.85 else
                 "#2563eb" if pct >= 0.65 else
                 "#d97706" if pct >= 0.40 else "#dc2626")
        return (f'<span style="font-weight:700;color:{color};">{score}</span>'
                f'<span style="color:#94a3b8;font-size:10px;">/{TOTAL_MAX}</span>')

    # ── Build header + colgroup + body driven by TABLE_COLS ───────────────────
    header_cells = []
    col_tags     = []

    def _add_col(key, th_html, w_key=None):
        if _on(key):
            header_cells.append(th_html)
            col_tags.append(_col(w_key or key))

    _add_col("Date",      f'<th style="{TH}">Date</th>')
    _add_col("Student",   f'<th style="{TH}">Student</th>')
    _add_col("Assessor",  f'<th style="{TH}">Assessor</th>')
    _add_col("Cohort",    f'<th style="{TH}">Cohort</th>')
    _add_col("GR",        f'<th style="{TH}text-align:center;">GR</th>')
    for d in DOMAIN_ORDER:
        dl = DOMAIN_LABELS.get(d, d)
        _add_col(dl, f'<th style="{TH}text-align:center;" title="{d}">{dl}</th>')
    _add_col("Total",     f'<th style="{TH}text-align:center;" title="Total score / {TOTAL_MAX}">Total</th>')
    _add_col("Submitted", f'<th style="{TH}text-align:center;">Sub</th>')
    _add_col("View",      f'<th style="{TH}text-align:center;" title="Full form view">&#128065;</th>')
    _add_col("Comments",  f'<th style="{TH}">Comments</th>')

    headers_html = "".join(header_cells)
    colgroup     = "<colgroup>" + "".join(col_tags) + "</colgroup>"
    n_active     = len(col_tags)

    display = rows[:MAX_ROWS]
    body    = []
    for i, r in enumerate(display):
        bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
        ds = r.get("_domain_scores") or {}
        tds = []
        if _on("Date"):      tds.append(f'<td style="{TD}color:#64748b;white-space:nowrap;">{r["Date"]}</td>')
        if _on("Student"):   tds.append(f'<td style="{TD}font-weight:500;">{r["Student"]}</td>')
        if _on("Assessor"):  tds.append(f'<td style="{TD}">{r["Assessor"]}</td>')
        if _on("Cohort"):    tds.append(f'<td style="{TD}">{cohort_badge(r["Cohort"])}</td>')
        if _on("GR"):        tds.append(f'<td style="{TD}text-align:center;">{gr_badge(r["GR"])}</td>')
        for d in DOMAIN_ORDER:
            dl = DOMAIN_LABELS.get(d, d)
            if _on(dl):
                tds.append(f'<td style="{TD}text-align:center;">{domain_score_cell(ds, d)}</td>')
        if _on("Total"):     tds.append(f'<td style="{TD}text-align:center;">{overall_cell(r)}</td>')
        if _on("Submitted"): tds.append(f'<td style="{TD}text-align:center;">{sub_cell(r["Submitted"])}</td>')
        if _on("View"):
            fhtml = build_form_html(r)
            tds.append(
                f'<td style="{TD}text-align:center;padding:4px 6px;">'
                f'<span onclick="{_FORM_MODAL_HANDLER}" data-html="{fhtml}"'
                f' title="View full form"'
                f' style="cursor:pointer;font-size:13px;color:#6366f1;display:inline-block;'
                f'padding:2px 5px;border-radius:4px;border:1px solid #e0e7ff;background:#eef2ff;"'
                f'>&#128065;</span>'
                f'</td>'
            )
        if _on("Comments"):  tds.append(f'<td style="{TD}vertical-align:top;padding-top:6px;">{comments_cell(r["Comments"])}</td>')
        body.append(f'<tr style="background:{bg}">' + "".join(tds) + "</tr>")

    trunc = ""
    if len(rows) > MAX_ROWS:
        trunc = (
            f'<tr><td colspan="{n_active}" style="padding:10px 14px;color:#94a3b8;font-size:11px;">'
            f'Showing {MAX_ROWS} of {len(rows)} records — use search to narrow down'
            f'</td></tr>'
        )

    return (
        f'<div style="overflow-x:auto;overflow-y:auto;max-height:{TABLE_MAX_HEIGHT};border-radius:8px;border:1px solid #e2e8f0;">'
        f'<table style="width:100%;border-collapse:collapse;table-layout:fixed;">'
        f'{colgroup}'
        f'<thead><tr>{headers_html}</tr></thead>'
        f'<tbody>{"".join(body)}{trunc}</tbody>'
        '</table></div>'
    )



# ── Gradio event handlers ─────────────────────────────────────────────────────
def do_load(cohorts, submitted_only, unsubmitted_only, search,
            sort_opt=DEFAULT_SORT, date_from="", date_to=""):
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


def do_filter(rows, submitted_only, unsubmitted_only, search,
              sort_opt=DEFAULT_SORT, date_from="", date_to=""):
    """Re-filter cached rows without hitting the API."""
    filtered = apply_filters(rows, submitted_only, unsubmitted_only, search, sort_opt, date_from, date_to)
    return make_table_html(filtered), build_stats_html(filtered)


def do_export(rows, submitted_only, unsubmitted_only, search,
              sort_opt=DEFAULT_SORT, date_from="", date_to=""):
    """Write the filtered view to an XLSX file."""
    filtered = apply_filters(rows, submitted_only, unsubmitted_only, search, sort_opt, date_from, date_to)
    df  = make_df(filtered)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    df.to_excel(tmp.name, index=False)
    return tmp.name


def do_export_detailed(rows, submitted_only, unsubmitted_only, search,
                       sort_opt=DEFAULT_SORT, date_from="", date_to=""):
    """
    Export a professionally formatted XLSX with:
      · Double headers — merged domain block header (row 1) + item sub-header (row 2)
      · Per-domain colour scheme
      · MC cells colour-coded by score value (4→green … 0→red)
      · Column order: Identity → [Domain blocks: MC items then Score/Max] → Summary → Comments
      · Thick borders between blocks, freeze panes after identity columns
    """
    filtered = apply_filters(rows, submitted_only, unsubmitted_only, search, sort_opt, date_from, date_to)

    # ── Metadata ──────────────────────────────────────────────────────────
    cl_meta = next((r["_checklists"] for r in filtered if r.get("_checklists")), {})

    mc_keys_per_domain = {}
    for domain in DOMAIN_ORDER:
        seen = []
        for r in filtered:
            items = ((r.get("_domain_scores") or {}).get(domain) or {}).get("items") or {}
            for k in sorted(items):
                if k not in seen:
                    seen.append(k)
        mc_keys_per_domain[domain] = seen

    def _mc_hdr(domain, mc_key):
        d_meta = cl_meta.get(domain) or {}
        hdr = ((d_meta.get("extra_config") or {}).get("headers") or {}).get(mc_key)
        if hdr and isinstance(hdr, list) and hdr[0].get("title"):
            return hdr[0]["title"].rstrip(":").strip()
        fld = (d_meta.get("fields") or {}).get(mc_key, mc_key)
        return (fld[:32] + "…") if len(fld) > 32 else fld

    def _domain_name(domain):
        return (cl_meta.get(domain) or {}).get("name") or domain

    # ── Colour palette ────────────────────────────────────────────────────
    SCHEME = {
        "identity": ("010D44", "C7D2FE"),
        "DDS4-1":   ("4338CA", "E0E7FF"),   # indigo
        "DDS4-2":   ("6D28D9", "EDE9FE"),   # violet
        "DDS4-3":   ("0E7490", "CFFAFE"),   # cyan
        "DDS4-4":   ("065F46", "D1FAE5"),   # emerald
        "DDS4-5":   ("92400E", "FEF3C7"),   # amber
        "summary":  ("1E293B", "F1F5F9"),
        "comments": ("374151", "F3F4F6"),
    }
    MC_FILL_MAP = {4: "BBFFD9", 3: "BFDBFE", 2: "A5F3FC", 1: "FEF08A", 0: "FECACA"}
    GR_FILL_MAP = {5: "BBFFD9", 4: "D1FAE5", 3: "FEF9C3", 2: "FED7AA", 1: "FECACA"}

    # ── Column definitions ────────────────────────────────────────────────
    # Each entry: (block_key, block_label, hdr_hex, sub_hex, col_label, val_fn, fill_fn)
    cols = []

    # ── Identity block (includes Submitted)
    ih, is_ = SCHEME["identity"]
    for lbl, key in [("Date","Date"),("Student","Student"),("Assessor","Assessor"),("Cohort","Cohort")]:
        cols.append(("identity", "Student Info", ih, is_, lbl,
                     (lambda r, k=key: r.get(k, "")), None))
    def _sub_fill(v):
        return "BBFFD9" if v == "Yes" else ("FECACA" if v == "No" else "F1F5F9")
    cols.append(("identity", "Student Info", ih, is_, "Submitted",
                 lambda r: r.get("Submitted",""), _sub_fill))

    # ── Domain blocks: MC items (numeric, labelled MC1/MC2…) then Score only
    for domain in DOMAIN_ORDER:
        hh, sh = SCHEME.get(domain, ("4B5563", "F3F4F6"))
        dname  = _domain_name(domain)
        for mc_key in mc_keys_per_domain.get(domain, []):
            def _mc_val(r, d=domain, k=mc_key):
                items = ((r.get("_domain_scores") or {}).get(d) or {}).get("items") or {}
                raw   = items.get(k, "")
                return MC_SCORE.get(raw, "") if raw else ""
            cols.append((domain, dname, hh, sh, mc_key, _mc_val, None))   # mc_key = "MC1", "MC2"…
        def _score(r, d=domain):
            return ((r.get("_domain_scores") or {}).get(d) or {}).get("score", "")
        dmax = DOMAIN_MAX.get(domain, "?")
        cols.append((domain, dname, hh, sh, f"Score /{dmax}", _score, None))

    # ── Summary block (GR + Overall only, no label)
    sh2, ss2 = SCHEME["summary"]
    def _gr_fill(v, gf=GR_FILL_MAP):
        try:    return gf.get(int(v), "F1F5F9")
        except: return "F1F5F9"
    cols.append(("summary", "Summary", sh2, ss2, "GR",      lambda r: r.get("GR",""),         _gr_fill))
    cols.append(("summary", "Summary", sh2, ss2, f"Overall /{TOTAL_MAX}",
                 lambda r: r.get("Overall", ""), None))

    # ── Comments block (always last)
    ch, cs = SCHEME["comments"]
    def _ad(r): return r.get("_ad") or {}
    cols.append(("comments", "Comments", ch, cs, "General",
                 lambda r: (_ad(r).get("comments") or "").strip() or "—", None))
    for domain in DOMAIN_ORDER:
        dl = DOMAIN_LABELS.get(domain, domain)
        def _dcmt(r, d=domain): return (_ad(r).get(f"{d}_comments") or "").strip() or "—"
        cols.append(("comments", "Comments", ch, cs, f"{dl} Comments", _dcmt, None))
    cols.append(("comments", "Comments", ch, cs, "Critical Error",
                 lambda r: (_ad(r).get("critical_error") or "").strip() or "—", None))
    # cols.append(("comments", "Comments", ch, cs, "Clinical Incident",
    #              lambda r: (_ad(r).get("clinical_incident") or "").strip() or "—", None))

    # ── openpyxl helpers ──────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Viva Detailed"
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 38

    def _fill(hex_c):
        return PatternFill(fill_type="solid", fgColor=hex_c)
    def _font(bold=False, color="1E293B", size=9):
        return Font(bold=bold, color=color, name="Calibri", size=size)
    def _align(h="left", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)
    thin  = Side(style="thin",   color="E2E8F0")
    thick = Side(style="medium", color="94A3B8")
    def _border(lthick=False, rthick=False):
        return Border(left=(thick if lthick else thin),
                      right=(thick if rthick else thin),
                      top=thin, bottom=thin)

    # ── Identify block boundaries ─────────────────────────────────────────
    # blocks: list of (block_key, block_label, hdr_hex, start_col_1idx, end_col_1idx)
    blocks, prev_key = [], None
    for ci, (bk, bl, hh, sh, *_) in enumerate(cols, start=1):
        if bk != prev_key:
            if blocks:
                blocks[-1] = (*blocks[-1][:4], ci - 1)
            blocks.append((bk, bl, hh, ci, ci))
            prev_key = bk
    if blocks:
        blocks[-1] = (*blocks[-1][:4], len(cols))

    # helper: is this column the last in its block?
    block_last = {ec for _, _, _, _, ec in blocks}

    # ── Row 1: merged block headers ───────────────────────────────────────
    for bk, bl, hh, sc, ec in blocks:
        for c in range(sc, ec + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill      = _fill(hh)
            cell.font      = _font(bold=True, color="FFFFFF", size=10)
            cell.alignment = _align(h="center", v="center")
            cell.border    = _border(lthick=(c == sc), rthick=(c == ec))
        ws.cell(row=1, column=sc).value = bl
        if ec > sc:
            ws.merge_cells(start_row=1, start_column=sc, end_row=1, end_column=ec)

    # ── Row 2: column sub-headers ─────────────────────────────────────────
    for ci, (bk, bl, hh, sh, col_lbl, vf, ff) in enumerate(cols, start=1):
        cell = ws.cell(row=2, column=ci)
        cell.value     = col_lbl
        cell.fill      = _fill(sh)
        cell.font      = _font(bold=True, size=9)
        cell.alignment = _align(h="center", wrap=True)
        cell.border    = _border(rthick=(ci in block_last))

    # ── Data rows ─────────────────────────────────────────────────────────
    wrap_labels = {"General", "Critical Error", "Clinical Incident"}
    for ri, r in enumerate(filtered, start=3):
        row_bg = "FFFFFF" if ri % 2 == 1 else "F8FAFC"
        ws.row_dimensions[ri].height = 15
        for ci, (bk, bl, hh, sh, col_lbl, vf, ff) in enumerate(cols, start=1):
            val  = vf(r)
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font      = _font(size=9)
            cell.alignment = _align(wrap=("Comments" in col_lbl or col_lbl in wrap_labels))
            cell.border    = _border(rthick=(ci in block_last))
            fc = ff(val) if ff else None
            cell.fill = _fill(fc if fc else row_bg)

    # ── Column widths ─────────────────────────────────────────────────────
    for ci, (bk, bl, hh, sh, col_lbl, vf, ff) in enumerate(cols, start=1):
        cl = get_column_letter(ci)
        if "Comments" in col_lbl or col_lbl in wrap_labels:
            ws.column_dimensions[cl].width = 32
        elif col_lbl.startswith("Score /") or col_lbl in ("GR", "Submitted", f"Overall /{TOTAL_MAX}"):
            ws.column_dimensions[cl].width = 9
        elif col_lbl in ("Student", "Assessor"):
            ws.column_dimensions[cl].width = 18
        elif col_lbl in ("Date", "Cohort"):
            ws.column_dimensions[cl].width = 11
        elif col_lbl.startswith("MC"):        # MC1, MC2… — keep tight
            ws.column_dimensions[cl].width = 6
        else:
            ws.column_dimensions[cl].width = 14

    # ── Freeze panes: identity cols + 2 header rows ───────────────────────
    n_id = sum(1 for bk, *_ in cols if bk == "identity")
    ws.freeze_panes = ws.cell(row=3, column=n_id + 1)

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    wb.save(tmp.name)
    return tmp.name


# ── Layout ────────────────────────────────────────────────────────────────────
css = f"""
/* ── Container ── */
.gradio-container {{
    max-width: {DASH_MAX_WIDTH} !important;
    width: 100% !important;
    margin: 0 auto !important;
    padding-left: 12px !important;
    padding-right: 12px !important;
}}
/* stretch inner Gradio wrapper to fill container */
.gradio-container > .main > .wrap {{ padding: 0 !important; }}

/* ── Header ── */
#dash-header {{ background:{NAVY}; border-radius:8px; padding:8px 16px; margin-bottom:4px; display:flex; align-items:center; gap:16px; }}
#dash-header h2 {{ color:white; margin:0; font-size:16px; letter-spacing:1px; }}
#dash-header p  {{ color:#c7d2fe; margin:0; font-size:11px; }}

/* ── Status bars ── */
#err-bar {{ color:#dc2626; min-height:0; }}
#ts-bar  {{ color:#94a3b8; font-size:11px; text-align:right; min-height:0; }}

/* ── Row spacing ── */
.compact-row .gap {{ gap:4px !important; }}

/* ── Table fills full width ── */
#table-wrap {{ width:100% !important; }}

footer {{ display:none !important; }}
"""


with gr.Blocks(title="DASH · Viva Monitor", theme=gr.themes.Default(primary_hue="indigo")) as demo:

    raw_state = gr.State([])
    timer     = gr.Timer(value=_def_secs, active=_def_active)

    # ── Header (compact single line) ──────────────────────────────────────
    gr.HTML(
        '<div id="dash-header">'
        '<h2>DASH</h2>'
        '<p>Viva Exam Live Monitor</p>'
        '</div>'
    )

    # ── Row 1: date range + refresh interval + load button ───────────────
    with gr.Row(elem_classes="compact-row"):
        date_from   = gr.Textbox(label="From", value="2026-06-10", placeholder="YYYY-MM-DD", scale=2)
        date_to     = gr.Textbox(label="To",   value="2026-06-11", placeholder="YYYY-MM-DD", scale=2)
        interval_dd = gr.Dropdown(
            list(INTERVAL_MAP.keys()), value=DEFAULT_INTERVAL,
            label="Refresh", scale=2,
        )
        load_btn = gr.Button("↻ Load", variant="primary", scale=1)

    # ── Row 2: cohorts + search + sort + submitted checkboxes ────────────
    with gr.Row(elem_classes="compact-row"):
        cohort_in = gr.CheckboxGroup(
            ALL_COHORTS, value=["DDS3", "DDS4", "DDS2"],
            label="Cohorts", scale=2,
        )
        search_in = gr.Textbox(
            label="Search",
            placeholder="student · assessor · cohort · subject · comments…",
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
    table_html = gr.HTML(make_table_html([]), elem_id="table-wrap", sanitize_html = False)

    # ── Export buttons ────────────────────────────────────────────────────
    with gr.Row(elem_classes="compact-row"):
        export_btn        = gr.Button("\u2b07 Export Summary",  size="sm", scale=1)
        export_detail_btn = gr.Button("\u2b07 Export Detailed", size="sm", scale=1)
        csv_out           = gr.File(label="Download", visible=False, scale=3)

    # ── Event wiring ──────────────────────────────────────────────────────
    load_inputs  = [cohort_in, sub_only, unsub_only, search_in,
                    sort_dd, date_from, date_to]
    load_outputs = [raw_state, table_html, stats_html, updated_md, error_md]

    load_btn.click(fn=do_load, inputs=load_inputs, outputs=load_outputs)
    demo.load(
        fn=lambda: do_load(["DDS3", "DDS4", "DDS2"], False, False, "", DEFAULT_SORT, "2026-06-09", "2026-06-10"),
        outputs=load_outputs,
    )

    filter_inputs  = [raw_state, sub_only, unsub_only, search_in, sort_dd, date_from, date_to]
    filter_outputs = [table_html, stats_html]

    for widget in [sub_only, unsub_only, search_in, sort_dd, date_from, date_to]:
        widget.change(fn=do_filter, inputs=filter_inputs, outputs=filter_outputs)

    interval_dd.change(fn=set_interval, inputs=[interval_dd], outputs=[timer])
    timer.tick(fn=do_load, inputs=load_inputs, outputs=load_outputs)

    export_inputs = [raw_state, sub_only, unsub_only, search_in, sort_dd, date_from, date_to]

    export_btn.click(
        fn=do_export, inputs=export_inputs, outputs=[csv_out],
    ).then(fn=lambda: gr.update(visible=True), outputs=[csv_out])
    export_detail_btn.click(
        fn=do_export_detailed, inputs=export_inputs, outputs=[csv_out],
    ).then(fn=lambda: gr.update(visible=True), outputs=[csv_out])

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  DASH \u00b7 Viva Gradio Dashboard")
    print("  ─────────────────────────────")
    print("  Opening at http://localhost:7860")
    print("  Press Ctrl+C to stop\n")
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True, max_threads=10, css=css,
                auth=(LOGIN_USER, LOGIN_PASS) if LOGIN_USER and LOGIN_PASS else None)
