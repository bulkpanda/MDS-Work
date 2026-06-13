
# ── Constants ────────────────────────────────────────────────────────────────
API_BASE    = "https://api.unimelb-dash.com"
ASSESS_TYPE = "viva"
EXCLUDE     = set(['kunal patel', 'suhrid gupta', 'test student'])   # lowercase names of test students to skip; empty = include all
ALL_COHORTS = ["DDS2", "DDS3", "DDS4"]

# Known viva domain keys (DDS4 schema). Non-comment, non-scale keys under assessor.
# The parser discovers domains dynamically, so this list only drives display ordering.
DOMAIN_ORDER = ["DDS4-1", "DDS4-2", "DDS4-3", "DDS4-4", "DDS4-5"]



MAX_ROWS = 500
NAVY     = "#010d44"
PURPLE   = "#4f5fb2"

GR_COLORS = ["", "#ef4444", "#f97316", "#eab308", "#22c55e", "#10b981"]
COHORT_COLORS = {
    "DDS1": "#818cf8", "DDS2": "#a78bfa", "DDS3": "#c084fc", "DDS4": "#e879f9",
    "BOH1": "#38bdf8", "BOH2": "#22d3ee", "BOH3": "#2dd4bf",
}

MC_COLORS = {
    "Done well":      "#15803d",   # green
    "Done":           "#2563eb",   # blue
    "Mostly done":    "#0891b2",   # cyan
    "Sometimes done": "#d97706",   # amber
    "Not done":       "#dc2626",   # red
}

# Numeric score per MC response label (equal weighting per criterion)
MC_SCORE = {
    "Done well":      4,
    "Done":           3,
    "Mostly done":    2,
    "Sometimes done": 1,
    "Not done":       0,
    "Yes":            1,
    "No":             0,
}

# Short display labels for domain columns in table
DOMAIN_LABELS = {
    "DDS4-1": "D1",
    "DDS4-2": "D2",
    "DDS4-3": "D3",
    "DDS4-4": "D4",
    "DDS4-5": "D5",
}

GR_LABELS = {
    1: "Unsatisfactory", 2: "Borderline", 3: "Satisfactory",
    4: "Good", 5: "Excellent",
}

# Official domain max scores (not all items go to 4; some cap at 3 or less)
DOMAIN_MAX = {
    "DDS4-1": 16,
    "DDS4-2": 19,
    "DDS4-3": 34,
    "DDS4-4": 31,
    "DDS4-5": 16,
}

# Columns written to CSV export (table view uses a wider set rendered in HTML)
EXPORT_COLUMNS = ["Date", "Student", "Assessor", "Cohort", "Subject", "GR"] + ['D1', 'D2', 'D3', 'D4', 'D5'] + ["Overall",
                  "Submitted", "Comments"]


TOTAL_MAX = 116  # sum of DOMAIN_MAX values; used for overall % coloring in table
# ── UI / Layout config ────────────────────────────────────────────────────────
DASH_MAX_WIDTH        = "1800px"   # overall container max-width
TABLE_MAX_HEIGHT      = "600px"    # scrollable table height
TABLE_FONT_SIZE       = "12px"     # font size for table cells and headers
CHART_FIGSIZE         = (18, 3.8)  # matplotlib figure size (width, height)
CHART_BAR_WIDTH       = 0.55       # bar width for GR distribution chart
STAT_VALUE_FONT_SIZE  = "18px"     # large number in stat cards
STAT_LABEL_FONT_SIZE  = "10px"     # small label text in stat cards
COMMENTS_MAX_HEIGHT   = "36px"     # max height of comments cell before scroll
COMMENTS_MIN_WIDTH    = "400px"    # min width of comments cell
COMMENTS_MAX_WIDTH    = "none"     # max width of comments cell ("none" = uncapped)

# ── Table column config ───────────────────────────────────────────────────────
# show: True = visible in the dashboard table, False = hidden.
# width: pixel width (integer). Comments is None — it always fills remaining space.
# Domain score columns use the short labels D1–D5 (matching DOMAIN_LABELS above).
TABLE_COLS = {
    "Date":      {"show": False,  "width": 72},
    "Student":   {"show": True,  "width": 100},
    "Assessor":  {"show": True,  "width": 100},
    "Cohort":    {"show": False,  "width": 50},
    "GR":        {"show": True,  "width": 50},
    "D1":        {"show": True,  "width": 50},
    "D2":        {"show": True,  "width": 50},
    "D3":        {"show": True,  "width": 50},
    "D4":        {"show": True,  "width": 50},
    "D5":        {"show": True,  "width": 50},
    "Total":     {"show": True,  "width": 58},
    "Submitted": {"show": True,  "width": 46},
    "View":      {"show": True,  "width": 36},   # full form modal — set show: False to hide
    "Comments":  {"show": True,  "width": None},  # None = fills remaining space
}

# ── Auto-refresh helpers ──────────────────────────────────────────────────────
INTERVAL_MAP = {
    "Manual only":  (60,  False),
    "Every 15 sec": (15,  True),
    "Every 30 sec": (30,  True),
    "Every 1 min":  (60,  True),
    "Every 5 min":  (300, True),
}
DEFAULT_INTERVAL = "Every 30 sec"
_def_secs, _def_active = INTERVAL_MAP[DEFAULT_INTERVAL]

SORT_OPTIONS = {
    "Date — newest first": ("_ts",       True),
    "Date — oldest first": ("_ts",       False),
    "Student A → Z":       ("Student",   False),
    "Student Z → A":       ("Student",   True),
    "GR — highest first":  ("GR_int",    True),
    "GR — lowest first":   ("GR_int",    False),
    "Submitted first":     ("Submitted", True),
    "Submitted last":      ("Submitted", False),
}
DEFAULT_SORT = "Date — newest first"

_WRAP        = "display:flex;gap:8px;flex-wrap:nowrap;width:100%;padding:2px 0 4px;"
_CARD_LABELS = ["Total records", "Submitted", "Avg global rating",
                "Unique students", "Assessors active"]