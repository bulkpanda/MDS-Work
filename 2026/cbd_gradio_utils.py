"""
cbd_gradio_utils.py — constants/config for cbd_gradio.py (DDS4 Case Based Discussion monitor).
Mirrors gradio_utils.py (viva) so the two dashboards stay independent.
"""

# ── API / data ───────────────────────────────────────────────────────────────
API_BASE    = "https://api.unimelb-dash.com"
ASSESS_TYPE = "cbd"                                   # GET /assessment/cbd/get
YEAR        = "2026"
EXCLUDE     = set(['kunal patel', 'suhrid gupta', 'test student'])   # exact lowercase names to skip
EXCLUDE_SUBSTRINGS = ["dummy", "test"]                # used only when "Hide dummy/test" is ticked
ALL_COHORTS     = ["BOH3", "DDS3", "DDS4"]
DEFAULT_COHORTS = ["DDS4"]
LOCAL_JSON  = ""   # e.g. "temp 2026 cbd.json" → read this file instead of the API (offline testing); "" = live API

# Default date window (YYYY-MM-DD). Must cover the sitting or the table looks empty.
DEFAULT_DATE_FROM = "2026-11-01"
DEFAULT_DATE_TO   = "2026-11-30"

# ── Domains ──────────────────────────────────────────────────────────────────
DOMAIN_ORDER  = ["d1-dds4", "d2-dds4", "d3-dds4", "d4-dds4", "d5-dds4", "d6-dds4"]
DOMAIN_LABELS = {d: f"D{i}" for i, d in enumerate(DOMAIN_ORDER, start=1)}

# Optional domain weights (fractions summing to 1). None = unweighted (Overall % = Σraw / Σmax).
# e.g. {"d1-dds4": .15, "d2-dds4": .10, "d3-dds4": .25, "d4-dds4": .20, "d5-dds4": .25, "d6-dds4": .05}
DOMAIN_WEIGHTS = None

# ── MC scoring ───────────────────────────────────────────────────────────────
# Score by rubric position: O1 (Done Well)=4 … O5 (Not Done)=0.
# Item max = score of its best ENABLED option (O1 blank → item caps at "Done" = 3).
N_LEVELS = 5
# Fallback when a record has no rubric (matched case-insensitively)
MC_SCORE = {"done well": 4, "done": 3, "mostly done": 2, "sometimes done": 1, "not done": 0}

# ── Colours ──────────────────────────────────────────────────────────────────
NAVY   = "#010d44"
PURPLE = "#4f5fb2"
GR_COLORS = ["", "#ef4444", "#f97316", "#eab308", "#22c55e", "#10b981"]
COHORT_COLORS = {"DDS3": "#c084fc", "DDS4": "#e879f9", "BOH3": "#2dd4bf"}
MC_COLORS = {                                         # keys lowercase
    "done well":      "#15803d",
    "done":           "#2563eb",
    "mostly done":    "#0891b2",
    "sometimes done": "#d97706",
    "not done":       "#dc2626",
}
GR_LABELS = {1: "Fail", 2: "Borderline", 3: "Pass", 4: "Good", 5: "Excellent"}   # fallback; form.scales wins

# ── UI / layout ──────────────────────────────────────────────────────────────
MAX_ROWS             = 500
DASH_MAX_WIDTH       = "1800px"
TABLE_MAX_HEIGHT     = "600px"
TABLE_FONT_SIZE      = "12px"
STAT_VALUE_FONT_SIZE = "18px"
STAT_LABEL_FONT_SIZE = "10px"
COMMENTS_MAX_HEIGHT  = "36px"
SERVER_PORT          = 7860                           # viva/SCBD use 7860

# show: visible in table; width: px (None = fill remaining space)
TABLE_COLS = {
    "Date":      {"show": False, "width": 72},
    "Student":   {"show": True,  "width": 110},
    "Assessor":  {"show": True,  "width": 100},
    "Examiner2": {"show": True,  "width": 100},
    "Cohort":    {"show": False, "width": 50},
    "GR":        {"show": True,  "width": 46},
    "D1":        {"show": True,  "width": 48},
    "D2":        {"show": True,  "width": 48},
    "D3":        {"show": True,  "width": 48},
    "D4":        {"show": True,  "width": 48},
    "D5":        {"show": True,  "width": 48},
    "D6":        {"show": True,  "width": 48},
    "Total":     {"show": True,  "width": 58},
    "Pct":       {"show": True,  "width": 54},
    "CC":        {"show": True,  "width": 40},          # critical concerns
    "Submitted": {"show": True,  "width": 40},
    "View":      {"show": True,  "width": 36},
    "Comments":  {"show": True,  "width": None},
}

EXPORT_COLUMNS = (["Date", "Student", "Assessor", "Examiner 2", "Cohort", "Subject", "GR"]
                  + list(DOMAIN_LABELS.values())
                  + ["Total", "Max", "Overall %", "Critical Concerns", "Submitted", "Comments"])

# ── Auto-refresh ─────────────────────────────────────────────────────────────
INTERVAL_MAP = {
    "Manual only":  (60,  False),
    "Every 15 sec": (15,  True),
    "Every 30 sec": (30,  True),
    "Every 1 min":  (60,  True),
    "Every 5 min":  (300, True),
}
DEFAULT_INTERVAL = "Every 30 sec"
DEF_SECS, DEF_ACTIVE = INTERVAL_MAP[DEFAULT_INTERVAL]

SORT_OPTIONS = {
    "Date — newest first":    ("_ts",       True),
    "Date — oldest first":    ("_ts",       False),
    "Student A → Z":          ("Student",   False),
    "Student Z → A":          ("Student",   True),
    "GR — highest first":     ("GR_int",    True),
    "GR — lowest first":      ("GR_int",    False),
    "Overall % — highest":    ("Pct",       True),
    "Overall % — lowest":     ("Pct",       False),
    "Critical concerns first": ("CC_int",   True),
    "Submitted first":        ("Submitted", True),
    "Submitted last":         ("Submitted", False),
}
DEFAULT_SORT = "Date — newest first"

CARD_WRAP   = "display:flex;gap:8px;flex-wrap:nowrap;width:100%;padding:2px 0 4px;"
CARD_LABELS = ["Total records", "Submitted", "Avg global rating", "Avg overall %",
               "Critical concerns", "Unique students", "Assessors active"]

# Excel domain colour scheme (header hex, sub-header hex)
XL_SCHEME = {
    "identity": ("010D44", "C7D2FE"),
    "d1-dds4":  ("4338CA", "E0E7FF"),
    "d2-dds4":  ("6D28D9", "EDE9FE"),
    "d3-dds4":  ("0E7490", "CFFAFE"),
    "d4-dds4":  ("065F46", "D1FAE5"),
    "d5-dds4":  ("92400E", "FEF3C7"),
    "d6-dds4":  ("9D174D", "FCE7F3"),
    "summary":  ("1E293B", "F1F5F9"),
    "comments": ("374151", "F3F4F6"),
}

# ── Standard setting (Detailed export → "Standard Setting" sheet) ─────────────
# Uses SUBMITTED rows with a GR and an Overall % from the current dashboard filters.
BORDERLINE_GR      = 2      # GR level treated as borderline (2 = "Borderline")
SS_MIN_N           = 10     # BLR: minimum candidates for a usable regression
BGM_MIN_BORDERLINE = 5      # BGM: minimum candidates in the borderline group
R2_MIN             = 0.5    # BLR: R² ≥ 0.5 acceptable (AMEE Guide 49)
DISCRIM_GUIDE      = 10.0   # BLR: inter-grade discrimination guideline, %-points per GR step (≈ max/10)
DISCRIM_LOW        = 5.0    # below this the checklist barely separates grades
DISCRIM_HIGH       = 100 / 6  # above this, slope likely driven by outliers/low performers (AMEE)
METHOD_AGREE_TOL   = 5.0    # |BLR cut − BGM cut| ≤ this many %-points = methods agree
