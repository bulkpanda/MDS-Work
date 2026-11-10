"""
osce_utils.py
=============
Support functions to build the station-wise OSCE workbook (detail sheets, station
summary, MC item stats, checklist legend), Borderline-Regression (BLR) standard-setting
analysis with embedded graphs, per-station validity/reliability metrics, and a
standard-setting cut-score comparison.

Scoring (integer points, chosen per checklist by its number of response levels):
  * 4-level checklists (Very good / Satisfactory / Borderline / Unsatisfactory):
        Very good = 4, Satisfactory = 3, Borderline = 2, Unsatisfactory = 0
  * 3-level checklists (Very good / Satisfactory / Unsatisfactory):
        Very good = 2, Satisfactory = 1, Unsatisfactory = 0
  Level count is detected from the checklist rubric (distinct O-keys) and the labels
  actually used; e.g. Occlusal Assessment is 3-level, the rest of round 1 are 4-level.
  Score (%) = total points / (n items x max points per item) x 100.

Score items by the response LABEL, never the O-key (O-keys are inconsistent across
checklists, e.g. O3 = 'Borderline' in one, 'Unsatisfactory' in another).

Global Rating is reversed to the standard direction (5=Excellent .. 1=Fail), so the BLR
slope is positive and the cut is taken at GR = Borderline (2).

Students are excluded when: (a) a test/dummy/model placeholder, or (b) their student number
is in IGNORE_STUDENT_NUMBERS (resolved to names via the roster CSV).

Public entry point:
    buildOsceWorkbook(srcPath, outPath, imgDir, cohortLabel="", borderlineGr=2,
                      ignoreStudentNumbers=None, rosterPath="studentEmailList.csv")
"""

import os
import re
import csv
import json
import statistics
from collections import Counter, OrderedDict

import numpy as np
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XlImage

# ── students to exclude by student number (add more as needed) ──
IGNORE_STUDENT_NUMBERS = {"1357773"}   # 1357773 = Nethmini Nanayakkara (DDS2)

# ── manual name -> student number overrides (OSCE record uses a preferred/English name the roster
#    doesn't carry). Key is the OSCE `student` name, lower-cased. Add more as they turn up. ──
STUDENT_NUMBER_OVERRIDES = {
    "yong (miranda) wang": "1361370",   # roster: Yong Wang (DDS2)
    "karan nahal":         "1677856",   # roster: Karanvir Nahal (DDS2)
    "gloria xu":           "1351773",   # roster: Nuo Xu (DDS2)
}

# ── DYNAMIC per-item scoring scales (points assigned by RANK, best -> worst) ──
# Each MC item is scored by how many response options ITS OWN rubric offers, so different
# items within one checklist can be on different scales (DDS4). Points are read off by the
# option's rank (O1 = best .. On = worst), never by the label text, because O-key -> label
# maps are inconsistent across checklists (and contain typos, e.g. "Unsatifactory") and the
# same key can mean different things in different checklists.
#   4-level (best->worst):  4, 3, 2, 0     (max 4)
#   3-level (best->worst):  2, 1, 0        (max 2)
#   2-level (best->worst):  1, 0           (max 1)
# Each item is then normalised to a 0..1 fraction (points / its own max) so every MC item
# carries EQUAL WEIGHT in the checklist score regardless of its number of levels; the
# checklist score is the mean of the answered items' fractions.
LEVEL_POINTS = {4: [4, 3, 2, 0], 3: [2, 1, 0], 2: [1, 0]}   # index 0 = best option
# ── Per-item WEIGHTS override (stationOverrides[ck]["itemWeights"]) ──
# Give only the items you want to weight, as % of the station score: e.g. {5: 30, 3: 20}.
# Every item NOT listed shares the leftover (100 - sum of listed) EQUALLY by default.
#   e.g. DDS3 S7 (10 items): {5: 30, 3: 20} -> MC5 30%, MC3 20%, other 8 items 50/8 = 6.25% each.
# Station score = sum(w_i * frac_i) / sum(w_i over ANSWERED items)  (blank items don't pull it down).
# Listed weights must total <= 100 (if they cover every item they are rescaled to 100).
LEVEL_MAX = {4: 4, 3: 2, 2: 1}


def resolveItemWeights(items, weightSpec):
    """
    Expand a PARTIAL per-item weight spec into a full {item: weight%} map over `items`.
      weightSpec : {mcNumber: pct} for the items to weight explicitly (keys may be 5, "5" or "MC5").
      Unlisted items share (100 - sum(listed)) equally. Returns None when weightSpec is empty
      (-> default equal weighting). Raises if listed weights exceed 100 or leave unlisted items
      with nothing (sum == 100 but some items unlisted). Items not in `items` (dropped / absent)
      are ignored with a printed warning.
    """
    if not weightSpec:
        return None
    spec = {}
    for k, v in weightSpec.items():
        n = int(str(k).upper().replace("MC", "").strip())
        if n in items:
            spec[n] = float(v)
        else:
            print(f"  itemWeights: MC{n} not a scored item for this station -> ignored")
    listed = sum(spec.values())
    rest = [i for i in items if i not in spec]
    if listed > 100 + 1e-9:
        raise ValueError(f"itemWeights total {listed}% > 100%")
    if rest:
        left = 100.0 - listed
        if left <= 1e-9:
            raise ValueError(f"itemWeights use all 100% but {len(rest)} item(s) unlisted: "
                             + ", ".join(f"MC{i}" for i in rest))
        spec.update({i: left / len(rest) for i in rest})
    elif listed > 0:                                           # all items listed -> rescale to 100
        spec = {i: w * 100.0 / listed for i, w in spec.items()}
    return {i: spec[i] for i in items}

# ── checklists to drop from the OSCE output entirely (incomplete / not-run stations) ──
# 2026-09-16: all stations now have complete data (endodontics 104, orthodontics 104), so nothing is
# excluded. Add a key here (or pass excludeChecklists=) to drop an incomplete station in a future run.
EXCLUDE_CHECKLISTS = set()

# Back-compat label maps (legacy DDS2 reference only; scoring no longer uses them).
POINTS_4LEVEL = {"Very good": 4, "Satisfactory": 3, "Borderline": 2, "Unsatisfactory": 0}
POINTS_3LEVEL = {"Very good": 2, "Satisfactory": 1, "Unsatisfactory": 0, "Borderline": 1}
MAXPTS = {4: 4, 3: 2}

# ── MC cell colours keyed by LABEL (unambiguous; the integer value is not) ──
LABEL_FILL = {"Very good": "C6EFCE", "Satisfactory": "DDEBF7", "Borderline": "FFEB9C", "Unsatisfactory": "FF0000"}
LABEL_FONT = {"Very good": "000000", "Satisfactory": "000000", "Borderline": "000000", "Unsatisfactory": "FFFFFF"}

# ── Global Rating, normalised to standard 5=best .. 1=worst ──
# Some cohorts store the GR key already in standard order (DDS4: 1=Fail..5=Excellent), others store
# it reversed (DDS2: 1=Excellent..5=Fail) and need flipping. `reverseGr` controls this: True/False to
# force it, or "auto" (default) to decide from the scale's own label order via GRADE_RANK.
GRADE_RANK = {"fail": 1, "borderline": 2, "pass": 3, "very good": 4, "excellent": 5}

GR_LABELS = {5: "Excellent", 4: "Very good", 3: "Pass", 2: "Borderline", 1: "Fail"}

# ── Derive a Global Rating from the raw checklist total for stations marked WITHOUT a GR ──
# Used for the DDS4 Day-2 diagnostics station (unobserved, marked post-task, GR never entered).
# The raw total sums each item's option value (Very Good=4, Satisfactory=3, Borderline=2,
# Unsatisfactory=0), max 66 over the 21 items, then maps to a GR by the examiner-agreed bands.
GR_LABEL_VALUES = {"very good": 4, "satisfactory": 3, "borderline": 2,
                   "unsatisfactory": 0, "unsatifactory": 0}   # last = data typo
GR_SCORE_BANDS = {
    # checklist key: [(minTotal, maxTotal, grNumber), ...]  gr 5=Excellent .. 1=Fail
    "diagnostics": [(63, 66, 5), (50, 62, 4), (44, 49, 3), (36, 43, 2), (0, 35, 1)],
}


def grFromBands(total, bands):
    """Map a raw checklist total to a GR number via (min,max,gr) bands; None if out of range."""
    for lo, hi, gr in bands:
        if lo <= total <= hi:
            return gr
    return None
GR_FILL   = {5: "C6EFCE", 4: "C6EFCE", 3: "E2EFDA", 2: "FFEB9C", 1: "FF0000"}
GR_FONTC  = {5: "000000", 4: "000000", 3: "000000", 2: "000000", 1: "FFFFFF"}
GR_COLORS = {5: "#1D9E75", 4: "#57B894", 3: "#3266ad", 2: "#EF9F27", 1: "#E24B4A"}
HEAD = "1F3864"

CHECKLIST_SHORT = {
    "infection-control": "Infection Control",
    "communication-with-a-patient": "Communication",
    "occlusal-assessment-note-to-markers-student-must-write-no-nil-no-marks-awarded-for-blank-boxes": "Occlusal",
    "conservative-dentistry": "Conservative Dent",
    "radiography": "Radiography",
    "local-anaesthetic": "Local Anaesthetic",
    "medical-history": "Medical History",
    "medical-emergency": "Medical Emergency",
    "periodontics": "Periodontics",
    "risk-and-recall": "Risk & Recall",
    "referral": "Referral",
    "informed-consent": "Informed Consent",
    "communication-with-staff": "Comm with Staff",
    "orthodontics": "Orthodontics",
}

# short sheet-name abbreviations: sheet = f"S{station} {abbr}"
CHECKLIST_ABBR = {
    "infection-control": "IC",
    "radiography": "Rad",
    "communication-with-a-patient": "Comm",
    "local-anaesthetic": "LA",
    "medical-history": "MedHx",
    "occlusal-assessment-note-to-markers-student-must-write-no-nil-no-marks-awarded-for-blank-boxes": "Occl",
    "conservative-dentistry": "ConsDent",
    "medical-emergency": "MedEmerg",
    "periodontics": "Perio",
    "risk-and-recall": "RiskRecall",
    "referral": "Referral",
    "informed-consent": "Consent",
    "communication-with-staff": "CommStaff",
    "orthodontics": "Ortho",
    "oral-medicine": "OralMed",
    "orthodontics-paediatrics": "OrthoPaed",
}


# ───────────────────────── pure support functions ─────────────────────────
def isTestStudent(name):
    """True for test/dummy/model placeholder students (excluded from analysis)."""
    n = (name or "").lower()
    return any(t in n for t in ["dummy", "model", "test"])


def loadRoster(rosterPath):
    """Return {studentNumber(str): studentName} from the roster CSV (student_number, student_name)."""
    roster = {}
    if rosterPath and os.path.exists(rosterPath):
        with open(rosterPath, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                num = (row.get("student_number") or "").strip()
                nm = (row.get("student_name") or "").strip()
                if num:
                    roster[num] = nm
    return roster


def _normName(nm):
    """Lower-case, trim, and collapse internal whitespace for name matching."""
    return re.sub(r"\s+", " ", (nm or "").strip().lower())


def nameToNumberMap(rosterPath):
    """Return {student_name(normalised): student_number} inverted from the roster CSV, for
    labelling analysis output with student numbers alongside names."""
    return {_normName(nm): num for num, nm in loadRoster(rosterPath).items() if nm}


def studentNumberFor(name, nameToNum):
    """Roster student number for an OSCE student name, tolerant of preferred-vs-legal name gaps:
    manual overrides first, then an exact (normalised) match, then the name with any
    '(parenthetical)' preferred name removed. Returns '' if still unresolved."""
    key = _normName(name)
    if key in STUDENT_NUMBER_OVERRIDES:
        return STUDENT_NUMBER_OVERRIDES[key]
    if key in nameToNum:
        return nameToNum[key]
    stripped = re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", key)).strip()
    return nameToNum.get(stripped, "")


def resolveIgnoreNames(ignoreNumbers, rosterPath):
    """Map a set of student numbers to lower-cased student names via the roster."""
    roster = loadRoster(rosterPath)
    names = set()
    for num in (ignoreNumbers or set()):
        nm = roster.get(str(num).strip())
        if nm:
            names.add(nm.strip().lower())
    return names


def loadOsceRecords(srcPath, ignoreStudentNumbers=None, rosterPath="studentEmailList.csv", cohort=None):
    """Load OSCE JSON; keep submitted, real students, minus any ignored-by-number students.
    `cohort` (e.g. "DDS4") filters to records whose `session` contains it (case-insensitive) —
    a guard for a JSON that holds more than one cohort; None/"" means no cohort filter."""
    with open(srcPath, encoding="utf-8") as fh:
        data = json.load(fh)
    ignoreSet = IGNORE_STUDENT_NUMBERS if ignoreStudentNumbers is None else ignoreStudentNumbers
    ignoreNums = {str(n).strip() for n in (ignoreSet or set())}
    ignoreNames = resolveIgnoreNames(ignoreSet, rosterPath)   # roster fallback for records lacking a number
    cohortKey = (cohort or "").strip().lower()
    out = []
    for r in data:
        if not r.get("submitted"):
            continue
        if cohortKey and cohortKey not in (r.get("session") or "").lower():
            continue
        nm = r.get("student")
        sno = str(r.get("student_number") or "").strip()
        if sno and sno in ignoreNums:                        # exclude by the record's own number
            continue
        if isTestStudent(nm) or (nm or "").strip().lower() in ignoreNames:
            continue
        out.append(r)
    return out


def _okeyNum(k):
    """Numeric part of an option key, e.g. 'O3' -> 3 (for best->worst ordering)."""
    m = re.search(r"\d+", str(k))
    return int(m.group()) if m else 0


def checklistItems(cfg):
    """Ordered MC item indices actually defined for a checklist (from 'fields', e.g. [1..14])."""
    fields = cfg.get("fields", {}) or {}
    return sorted({_okeyNum(k) for k in fields if str(k).upper().startswith("MC") and _okeyNum(k) > 0})


def itemAvailableKeys(cfg, i):
    """The response options ACTUALLY available for MC item i, best -> worst (O1 best).
    Authoritative source = the checklist's `extra_config.options` (the full scale) MINUS the item's
    `extra_config.row_config[MCi].disabled_options`. The per-item `rubric` only holds descriptions and
    is often empty/partial, so it must NOT decide availability (doing so dropped answers on items whose
    rubric was blank). Falls back to the rubric keys only when there is no options map."""
    ec = cfg.get("extra_config", {}) or {}
    opts = [k for k in (ec.get("options", {}) or {}) if str(k).startswith("O")]
    if opts:
        disabled = set(((ec.get("row_config", {}) or {}).get(f"MC{i}", {}) or {}).get("disabled_options") or [])
        avail = [k for k in opts if k not in disabled]
    else:                                                    # no options map -> fall back to rubric keys
        avail = [k for k in ((ec.get("rubric", {}) or {}).get(f"MC{i}", {}) or {}) if str(k).startswith("O")]
    return sorted(avail, key=_okeyNum)


def resolveScoreConfig(scoreConfig=None):
    """
    Normalise a scoring configuration into {mode, levelPoints, labelPoints, aggregate}.
    Defaults reproduce the historical behaviour EXACTLY (rank mode, LEVEL_POINTS, normalize).
    Three knobs:
      mode        : "rank"  -> points by the option's RANK within its item, from levelPoints[level]
                    "label" -> points by the option's LABEL value from labelPoints, ignoring level
      levelPoints : {level: [best..worst]} used in rank mode (e.g. {3:[3,2,0]} makes 3-level = 0/2/3)
      labelPoints : {labelLower: value} used in label mode (default Very Good=4/Satisf=3/Border=2/Unsat=0)
      aggregate   : "normalize" -> checklist Score = mean(points_i / max_i)  (equal weight per item)
                    "total"     -> checklist Score = sum(points_i) / sum(max_i)  (raw total / max denom)
    """
    sc = dict(scoreConfig or {})
    return {
        "mode": sc.get("mode", "rank"),
        "levelPoints": sc.get("levelPoints", LEVEL_POINTS),
        "labelPoints": {str(k).strip().lower(): v for k, v in (sc.get("labelPoints", GR_LABEL_VALUES)).items()},
        "aggregate": sc.get("aggregate", "normalize"),
    }


def itemScaleFromKeys(order, sconf=None, optLabels=None):
    """
    Scoring scale for one MC item from its available O-keys (best->worst). Returns
    (keyPoints, maxPts, level, order). Behaviour depends on the resolved score config `sconf`:
      rank mode  : points by RANK from sconf['levelPoints'][level]; maxPts = max of that vector.
                   Levels absent from levelPoints fall back to a linear best->worst scale; 1-option = 1/1.
      label mode : points = sconf['labelPoints'][option label]; maxPts = best attainable label value for
                   THIS item (so a fully-correct answer normalises to 1.0 whatever the item's levels).
    """
    sconf = sconf or resolveScoreConfig()
    lvl = len(order)
    if sconf["mode"] == "label":
        lp, ol = sconf["labelPoints"], (optLabels or {})
        kp = {k: lp.get(str(ol.get(k) or k).strip().lower(), 0) for k in order}
        mx = max(kp.values()) if kp else 0
        return kp, mx, lvl, order
    lpts = sconf["levelPoints"]
    if lvl in lpts:
        pts = list(lpts[lvl])
    elif lvl >= 2:
        pts = list(range(lvl - 1, -1, -1))                   # linear fallback
    elif lvl == 1:
        pts = [1]
    else:
        return {}, 0, 0, []
    mx = max(pts) if pts else 0
    return {k: pts[j] for j, k in enumerate(order)}, mx, lvl, order


def checklistItemScales(cfg, sconf=None):
    """Per-item scales for a checklist: {i: (keyPoints, maxPts, level, order)}, options from the
    checklist options map minus each item's disabled_options (see itemAvailableKeys). `sconf` is a
    resolved score config (resolveScoreConfig); None = defaults (rank / LEVEL_POINTS / normalize)."""
    sconf = sconf or resolveScoreConfig()
    ol = checklistOptionLabels(cfg)
    return {i: itemScaleFromKeys(itemAvailableKeys(cfg, i), sconf, ol) for i in checklistItems(cfg)}


def checklistOptionLabels(cfg):
    """Checklist-level O-key -> label map (extra_config.options); used only for display/reporting."""
    return (cfg.get("extra_config", {}) or {}).get("options", {}) or {}


def levelsText(itemLevel):
    """Human-readable level summary for a checklist, e.g. '4-level', '2-level', or 'mixed 2/4'."""
    lv = sorted({v for v in itemLevel.values() if v >= 2})
    if not lv:
        return "-"
    return f"{lv[0]}-level" if len(lv) == 1 else "mixed " + "/".join(str(x) for x in lv)


GR_SCALE_KEYS = ("global-rating", "global-rating-scale")   # DDS2/DDS4 use the first, DDS3 the second


def grScale(scales):
    """Return the Global Rating scale entry from a scales dict, whichever key the form uses (or {})."""
    scales = scales or {}
    for k in GR_SCALE_KEYS:
        if scales.get(k):
            return scales[k]
    return {}


# Free-text key aliases (first non-blank wins) — forms name the same field differently per cohort.
FEEDBACK_TEXT_KEYS = ("feedback-on-student-performance", "student-feedback", "comments")  # DDS2/DDS4, DDS3, BOH2
BLFAIL_TEXT_KEYS = ("if-you-have-awarded-a-global-rating-of-borderline-or-fail-please-provide-additional-information",)
OSCE_COMMENT_TEXT_KEYS = ("comments-on-the-osce",)


# ── Readiness to Progress + pre-built comments (added 2026-11-06, BOH2 OSCE) ──────────────────
# RTP: a 1..4 scale ("Level 1: will not be able to practice .." -> "Level 4: .. indirect supervision").
# Pre-built comments: multi-select fields shown conditionally on the GR key (one field per GR band,
# e.g. "polypharmacy-comments-good-rating"); the examiner ticks any of the canned statements.
# Neither feeds scoring, GR or the BLR/validity workbook — station workbook display only.
RTP_SCALE_KEYS = ("readiness-to-progress-scale",)
RTP_FILL  = {1: "FFC7CE", 2: "FFEB9C", 3: "DDEBF7", 4: "C6EFCE"}
RTP_FONTC = {1: "9C0006", 2: "7F6000", 3: "000000", 4: "000000"}
PREBUILT_KEY_PATTERN = "comment"   # multi-select field keys containing this are treated as pre-built comments


def rtpScale(scales):
    """Return the Readiness to Progress scale entry from a scales dict (or {})."""
    scales = scales or {}
    for k in RTP_SCALE_KEYS:
        if scales.get(k):
            return scales[k]
    return {}


def rtpLevelFields(records):
    """{level int: label} for the Readiness to Progress scale, from the first record that has it."""
    for r in records or []:
        f = rtpScale((r.get("form_config") or {}).get("scales")).get("fields") or {}
        if f:
            out = {}
            for k, v in f.items():
                try:
                    out[int(k)] = str(v).strip()
                except (TypeError, ValueError):
                    pass
            return dict(sorted(out.items()))
    return {}


def prebuiltFieldConfigs(cfg):
    """Pre-built comment multi-select configs from a form_config: {fieldKey: {name, items, grKey}}.
    grKey = the raw GR key the field is shown for (from its 'show' condition on scales.global-rating*)."""
    out = OrderedDict()
    ms = (cfg or {}).get("multi-select") or {}
    for k, v in sorted(ms.items(), key=lambda kv: ((kv[1] or {}).get("order") or 0, kv[0])):
        if PREBUILT_KEY_PATTERN not in k.lower() or not isinstance(v, dict):
            continue
        grKey = None
        for c in v.get("conditions") or []:
            w = (c or {}).get("when") or {}
            if str(w.get("field", "")).startswith("scales.global-rating"):
                grKey = str(w.get("value"))
        out[k] = {"name": str(v.get("name") or k).strip(),
                  "items": [(it.get("key"), str(it.get("value") or "").strip()) for it in (v.get("items") or [])],
                  "grKey": grKey}
    return out


def prebuiltSelections(formData):
    """Ticked pre-built comments on one form: list of (fieldKey, optionKey, text), O-key order per field."""
    out = []
    ms = (formData or {}).get("multi-select") or {}
    for k in sorted(ms):
        if PREBUILT_KEY_PATTERN not in k.lower():
            continue
        sel = [x for x in (ms.get(k) or []) if isinstance(x, dict)]
        for x in sorted(sel, key=lambda x: _okeyNum(x.get("key"))):
            txt = str(x.get("value") or "").strip()
            if txt:
                out.append((k, x.get("key"), txt))
    return out


def firstText(texts, keys):
    """First non-blank string among `keys` in a form_data texts dict ('' if none)."""
    texts = texts or {}
    for k in keys:
        v = texts.get(k)
        if v is not None and str(v).strip():
            return v
    return ""


def grScaleFields(records):
    """The Global Rating scale's {key: label} map from the first record's form_config (or {})."""
    if not records:
        return {}
    return grScale((records[0].get("form_config", {}) or {}).get("scales")).get("fields", {}) or {}


def shouldReverseGr(scaleFields):
    """Auto-decide whether GR keys need flipping: True when the LOWEST key is the BETTER grade
    (e.g. 1=Excellent..5=Fail). Unknown/ambiguous labels -> False (trust the key as stored)."""
    try:
        nums = sorted(int(k) for k in scaleFields)
    except Exception:
        return False
    if not nums:
        return False
    rlo = GRADE_RANK.get(str(scaleFields.get(str(nums[0]), "")).strip().lower())
    rhi = GRADE_RANK.get(str(scaleFields.get(str(nums[-1]), "")).strip().lower())
    return bool(rlo and rhi and rlo > rhi)


def resolveReverseGr(records, reverseGr="auto"):
    """Resolve the reverseGr setting to a bool (auto -> detect from the GR scale labels)."""
    if reverseGr in (True, False):
        return reverseGr
    return shouldReverseGr(grScaleFields(records))


def buildStationSpecs(records, reverseGr="auto", excludeChecklists=None, grScoreBands=None,
                      scoreConfig=None, stationOverrides=None):
    """
    Group records by (station, checklist) actually filled, tidy each into rows, and attach the
    DYNAMIC per-item scoring scales. Scoring is controlled by `scoreConfig` (see resolveScoreConfig):
    mode rank|label, the levelPoints/labelPoints table, and aggregate normalize|total. Default
    (scoreConfig=None) = rank / LEVEL_POINTS / normalize (mean of per-item fractions, equal weight).
    stationOverrides[ck]["itemWeights"] = {mc: pct} -> weighted mean of item fractions for that station
    (unlisted items share the leftover % equally; see resolveItemWeights). Overrides `aggregate`.
    GR is normalised to the standard 5=best..1=worst direction.
    Returns list of dicts: {st, ck, cfg, rows, items, itemLevel, itemMax, scales, optLabels,
                            levels(text), maxPerItem(None if mixed)}.
    Each row carries points[i] (raw rank points, for display), frac[i] (0..1, for scoring/stats)
    and labels[i] (option label, for display), keyed by MC item index i.
    `reverseGr` (True/False/"auto"): flip the GR key so 5=best; "auto" decides from the scale labels
    (DDS2 stores 1=Excellent..5=Fail -> reversed; DDS4 stores 1=Fail..5=Excellent -> not reversed).
    """
    rev = resolveReverseGr(records, reverseGr)
    scaleFields = grScaleFields(records)
    try:
        maxGr = max(int(k) for k in scaleFields) if scaleFields else 5
    except Exception:
        maxGr = 5

    exclude = EXCLUDE_CHECKLISTS if excludeChecklists is None else set(excludeChecklists)
    grScoreBands = GR_SCORE_BANDS if grScoreBands is None else grScoreBands   # {} disables derivation
    sconf = resolveScoreConfig(scoreConfig)                                   # mode / points / aggregate
    # Group by CHECKLIST (not station): one assessment rubric = one station group, so a checklist
    # run across several station numbers/circuits (e.g. DDS4 oral-medicine at S1 and S5) is merged
    # into a single station. This also matches the ck-keyed dicts downstream (blr, cutP, ...).
    groups = OrderedDict()
    for r in records:
        for ck, cv in r["form_data"].get("checklists", {}).items():
            if cv and ck not in exclude:
                groups.setdefault(ck, []).append(r)

    specs = []
    for ck, recs in sorted(groups.items(), key=lambda kv: (min(r["station"] for r in kv[1]), kv[0])):
        stations = sorted({r["station"] for r in recs})
        st = stations[0] if len(stations) == 1 else "+".join(str(s) for s in stations)
        cfg = recs[0]["form_config"]["checklists"][ck]
        scales = checklistItemScales(cfg, sconf)              # {i: (keyPoints, maxPts, level, order)}
        dropItems = set(((stationOverrides or {}).get(ck, {}) or {}).get("dropItems") or [])   # MC items to exclude
        items = [i for i in checklistItems(cfg) if scales.get(i, ({}, 0, 0, []))[2] >= 2 and i not in dropItems]
        optLabels = checklistOptionLabels(cfg)
        itemLevel = {i: scales[i][2] for i in items}
        itemMax = {i: scales[i][1] for i in items}
        itemWeights = resolveItemWeights(items, ((stationOverrides or {}).get(ck, {}) or {}).get("itemWeights"))

        bands = grScoreBands.get(ck) if grScoreBands else None   # derive GR from raw total (no-GR stations)
        remaps = ((stationOverrides or {}).get(ck, {}) or {}).get("remapGr")  # override: reassign GR values
        remaps = ([remaps] if isinstance(remaps, dict) else list(remaps)) if remaps else []
        grRemapN = 0
        rows = []
        for r in recs:
            cv = r["form_data"]["checklists"][ck]
            labels, points, frac = {}, {}, {}
            lvTotal = 0                                         # raw label-value total (for GR bands)
            for i in items:
                keyPoints, mx, _lvl, _order = scales[i]
                c = cv.get(f"MC{i}")
                key = c.get("key") if isinstance(c, dict) else None
                if key in keyPoints:
                    p = keyPoints[key]
                    points[i] = p
                    frac[i] = (p / mx) if mx else None
                    labels[i] = (c.get("value") if isinstance(c, dict) else None) or optLabels.get(key) or key
                    lvTotal += GR_LABEL_VALUES.get(str(optLabels.get(key) or labels[i]).strip().lower(), 0)
                else:                                          # blank / not marked
                    points[i], frac[i], labels[i] = None, None, None
            answered = [i for i in items if points[i] is not None]
            if itemWeights:                                    # override: weighted mean of per-item fractions
                wa = [(itemWeights[i], frac[i]) for i in answered if frac[i] is not None]
                wsum = sum(w for w, _ in wa)
                score = (sum(w * f for w, f in wa) / wsum) if wsum else None
            elif sconf["aggregate"] == "total":                  # raw total / max denominator
                denom = sum(itemMax[i] for i in answered)
                score = (sum(points[i] for i in answered) / denom) if denom else None
            else:                                              # normalize: mean of per-item fractions
                fr = [frac[i] for i in answered if frac[i] is not None]
                score = (sum(fr) / len(fr)) if fr else None
            gk = grScale(r["form_data"].get("scales")).get("key")
            rk = rtpScale(r["form_data"].get("scales")).get("key")
            pre = prebuiltSelections(r["form_data"])
            if str(gk).isdigit():
                grval = (maxGr + 1 - int(gk)) if rev else int(gk)
            elif bands is not None:
                grval = grFromBands(lvTotal, bands)            # derived from raw total
            else:
                grval = None
            grRemapped = False                                 # apply GR remap rules (scoped by assessor/circuit)
            for rule in remaps:
                if grval is None or rule.get("from") != grval:
                    continue
                if "assessor" in rule and str(rule["assessor"]).strip().lower() != str(r["assessor"]).strip().lower():
                    continue
                if "circuit" in rule and rule["circuit"] != r["circuit"]:
                    continue
                grval = rule.get("to"); grRemapped = True; grRemapN += 1
                break
            rows.append({
                "circuit": r["circuit"], "student": r["student"], "assessor": r["assessor"],
                "studentNo": str(r.get("student_number") or "").strip(),   # from the record itself (DASH now sends it)
                "gr": grval, "grRemapped": grRemapped, "grDerived": (str(gk).isdigit() is False and bands is not None),
                "grRaw": (lvTotal if bands is not None else None),
                "labels": labels, "points": points, "frac": frac,
                "score": score,                                    # 0..1, per scoreConfig aggregate mode
                "feedback": firstText(r["form_data"].get("texts"), FEEDBACK_TEXT_KEYS),
                "blfail": firstText(r["form_data"].get("texts"), BLFAIL_TEXT_KEYS),
                "optComments": firstText(r["form_data"].get("texts"), OSCE_COMMENT_TEXT_KEYS),
                "grKey": (str(gk) if gk is not None else None),        # raw form GR key (pre-built conditions)
                "rtp": (int(rk) if str(rk).isdigit() else None),       # Readiness to Progress level 1..4
                "prebuilt": pre,                                       # [(fieldKey, optionKey, text)]
            })
        maxSet = set(itemMax.values())
        specs.append({"st": st, "stations": stations, "ck": ck, "cfg": cfg, "rows": rows,
                      "grDerived": bands is not None,
                      "items": items, "itemLevel": itemLevel, "itemMax": itemMax,
                      "scales": scales, "optLabels": optLabels,
                      "levels": levelsText(itemLevel),
                      "droppedItems": sorted(dropItems),
                      "itemWeights": itemWeights,                 # {i: %} when overridden, else None
                      "prebuiltCfg": prebuiltFieldConfigs(recs[0]["form_config"]),
                      "grRemaps": remaps, "grRemapN": grRemapN,
                      "maxPerItem": (next(iter(maxSet)) if len(maxSet) == 1 else None)})
    return specs


def computeBlr(rows, borderlineGr=2):
    """Borderline-Regression on the score fraction: cut = predicted score at the borderline grade.
    Returns `valid=False` (with NaN stats) when there are too few paired GR+score points or no GR
    variation for a regression — e.g. a checklist-only station (no GR) or a GR-only station (no
    scored items). Callers must skip BLR/validity output for `valid=False` stations."""
    grs = np.array([r["gr"] for r in rows if r["gr"] is not None and r["score"] is not None], float)
    scs = np.array([r["score"] for r in rows if r["gr"] is not None and r["score"] is not None], float)
    m = float(scs.mean()) if len(scs) else float("nan")
    sd = float(scs.std(ddof=1)) if len(scs) > 1 else 0.0
    if len(scs) < 2 or len(set(grs.tolist())) < 2:            # not enough data / no GR spread
        return dict(slope=float("nan"), intercept=float("nan"), r2=float("nan"), p=float("nan"),
                    cut=float("nan"), cutPct=None, grs=grs, scs=scs, mean=m, sd=sd,
                    mean2sd=(m - 2 * sd) if scs.size else float("nan"),
                    mean2sdPct=(round((m - 2 * sd) * 100, 1) if scs.size else None), valid=False)
    slope, intercept, rval, pval, se = stats.linregress(grs, scs)
    cut = slope * borderlineGr + intercept
    return dict(slope=slope, intercept=intercept, r2=rval ** 2, p=pval,
                cut=cut, cutPct=round(cut * 100, 1), grs=grs, scs=scs,
                mean=m, sd=sd, mean2sd=m - 2 * sd, mean2sdPct=round((m - 2 * sd) * 100, 1), valid=True)


def effectivePassCut(ck, blrEntry, stationOverrides=None, borderlineGr=2):
    """
    Resolve the EFFECTIVE pass/fail cut for a checklist, applying a per-station override.
    Returns (cutFrac, cutPct, forcePass, excludeFromPassFail, note):
      cutFrac : fraction used by countBelow (a student fails when pct1(score) < cutPct)
      cutPct  : display cut % (None when force-passed)
      forcePass : True -> nobody fails (passAll)
      excludeFromPassFail : True -> station omitted from pivot / standard-setting / fail counts
      note    : short text describing the override (or "" for the plain BLR cut)
    Override keys (stationOverrides[ck]): passAll, cutMethod="bgm", cutAdjustPct (percentage pts),
    excludeFromPassFail. Precedence: excludeFromPassFail > passAll > bgm > cutAdjustPct > plain BLR.
    """
    o = ((stationOverrides or {}).get(ck, {}) or {})
    b = blrEntry
    if o.get("excludeFromPassFail"):
        return b.get("cut"), b.get("cutPct"), False, True, "Excluded from pass/fail (by decision)"
    if o.get("passAll"):
        return -1.0, None, True, False, "PASS ALL (by decision)"
    if o.get("cutMethod") == "bgm":
        grs, scs = b.get("grs"), b.get("scs")
        bmask = (grs == borderlineGr) if (grs is not None and len(grs)) else None
        if bmask is not None and bmask.any():
            bgm = float(scs[bmask].mean())
            return bgm, round(bgm * 100, 1), False, False, f"BGM cut (mean of {int(bmask.sum())} Borderline)"
        # no borderline group -> fall through to BLR
    adj = o.get("cutAdjustPct")
    if adj is not None and b.get("cutPct") is not None:
        pct = round(b["cutPct"] + adj, 1)
        return pct / 100.0, pct, False, False, f"BLR cut {adj:+.1f}pp"
    return b.get("cut"), b.get("cutPct"), False, False, ""


def _clip100(x):
    return max(0.0, min(100.0, float(x)))

# ── Final-score scalings (pluggable) → a /100 mark per student, one Outcome-sheet column each ──
# Each scaling is a COHORT-LEVEL function f(students, ctx) -> {student: mark}. This supports both
# one-pass (aggregate) and two-pass (per-station, level-restored) methods uniformly.
#   students[st] = {"raw": mean station %, "stn": [(score%, cut%, stnMean%, stnSD%), ...]}   (counting stations only)
#   ctx          = {"meanCut", "grandMean", "rawSD", "nStn"}  (cohort constants)
# Add a scaling by inserting into FINAL_SCORE_SCALINGS (+ a header in FINAL_SCORE_HEADERS), or pass a
# ("Label", func) tuple in finalScoreMethods (func same signature) without touching this file.

def _stnCut50(score, cut):
    """One station on a cut->50, 100->100 scale (criterion, per-station difficulty via its own cut)."""
    if cut is None:
        return score
    return 50 + 50 * (score - cut) / (100 - cut) if score >= cut else (50 * score / cut if cut else 0.0)

def _scRawMean(students, ctx):
    return {st: d["raw"] for st, d in students.items()}

def _scCutAnchored50(students, ctx):
    mc, gm = ctx["meanCut"], ctx["grandMean"]
    sl = ((gm - 50) / (gm - mc)) if gm > mc else 1.0          # cut->50, cohort mean preserved
    return {st: _clip100(50 + (d["raw"] - mc) * sl) for st, d in students.items()}

def _scCutAnchoredFull(students, ctx):
    mc = ctx["meanCut"]                                        # aggregate cut->50, full->100 (compresses)
    def f(raw):
        return 50 + 50 * (raw - mc) / (100 - mc) if raw >= mc else (50 * raw / mc if mc else 0.0)
    return {st: _clip100(f(d["raw"])) for st, d in students.items()}

def _scZ70(students, ctx):
    gm, sd = ctx["grandMean"], ctx["rawSD"]                    # norm-referenced z on the raw average -> 70/10
    return {st: (_clip100(70 + 10 * (d["raw"] - gm) / sd) if sd else 70.0) for st, d in students.items()}

def _perStationBase(students):
    """Each student's mean of per-station cut->50/100 marks (pass=50 per station). Shared by the
    perStationCut* scalings."""
    return {st: (sum(_stnCut50(s, c) for (s, c, m, sd) in d["stn"]) / len(d["stn"]) if d["stn"] else 0.0)
            for st, d in students.items()}

def _scPerStationCutRaw(students, ctx):
    """PER-STATION criterion, no level restore: each station cut->50/100, averaged. Pass mark = 50
    exactly, but the cohort mean sits low (pulls down). Factors each station's difficulty via its cut."""
    return {st: _clip100(v) for st, v in _perStationBase(students).items()}

def _scPerStationCut(students, ctx):
    """PER-STATION criterion, level restored: as perStationCutRaw, then the spread is stretched about the
    50 pass anchor so the cohort mean returns to grandMean. Keeps pass=50 AND avoids the pull-down, and
    factors each station's difficulty via its own cut (so ranking differs from the raw average)."""
    base = _perStationBase(students)
    bmean = (sum(base.values()) / len(base)) if base else 50.0
    k = ((ctx["grandMean"] - 50) / (bmean - 50)) if bmean > 50 else 1.0   # pivot about 50 (pass anchor)
    return {st: _clip100(50 + (v - 50) * k) for st, v in base.items()}

def _scPerStationWeighted(students, ctx):
    """PER-STATION weighted average: each station weighted by 100/cut, so harder stations (lower cut)
    count more. mark = sum(score * 100/cut) / sum(100/cut). Stays on the raw 0-100 scale (no 50 anchor)."""
    out = {}
    for st, d in students.items():
        num = den = 0.0
        for (s, c, m, sd) in d["stn"]:
            if c:                                             # weight = 100/cut
                w = 100.0 / c; num += s * w; den += w
        out[st] = _clip100(num / den) if den else d["raw"]
    return out

def _scPerStationZ(students, ctx):
    """PER-STATION norm: z-score each station (score-stnMean)/stnSD, average, map to cohort mean / SD.
    Removes each station's difficulty AND spread; ranking differs from the raw average."""
    gm, tsd = ctx["grandMean"], (ctx["rawSD"] or 10.0)
    out = {}
    for st, d in students.items():
        zs = [(s - m) / sd for (s, c, m, sd) in d["stn"] if sd and sd > 0]
        out[st] = _clip100(gm + tsd * (sum(zs) / len(zs))) if zs else gm
    return out

FINAL_SCORE_SCALINGS = {
    "rawMean": _scRawMean, "cutAnchored50": _scCutAnchored50, "cutAnchoredFull": _scCutAnchoredFull,
    "z70": _scZ70, "perStationCut": _scPerStationCut, "perStationCutRaw": _scPerStationCutRaw,
    "perStationWeighted": _scPerStationWeighted, "perStationZ": _scPerStationZ,
}
FINAL_SCORE_HEADERS = {
    "rawMean": "Avg % (raw)", "cutAnchored50": "Cut-anchored /100", "cutAnchoredFull": "Cut->50/100",
    "z70": "Std 70/10", "perStationCut": "Per-stn cut /100", "perStationCutRaw": "Per-stn cut (raw)",
    "perStationWeighted": "Wtd 100/cut", "perStationZ": "Per-stn z /100",
}


def difficultyWeightedScaling(weights="invcut", label="Difficulty-wtd /100"):
    """Build a final-score scaling: a WEIGHTED AVERAGE of station %s where each station's weight
    reflects its DIFFICULTY. Returns ("label", func) for finalScoreMethods.

      weights = "invcut"  (default): w_i = 1 / cut_i  -> lower cut = harder station = higher weight.
              = "invmean"          : w_i = 1 / stationMean_i
              = "inv_sd"           : w_i = 1 / stationSD_i
              = callable(cut, mean, sd, ck) -> w   (any formula; return a constant for flat weights)
              = dict {ck or sheet-title: w}        (HARD per-station weights; stations not listed -> 1/cut)

      mark = clip( sum(score_i * w_i) / sum(w_i) ).  Note a constant factor in w cancels, so "invcut"
      is numerically identical to the built-in perStationWeighted (w = 100/cut); this is its
      configurable twin. Stays on the raw 0-100 scale (no 50 pass-anchor).
    """
    def _w(cut, mean, sd, ck, titles):
        if callable(weights):
            return weights(cut, mean, sd, ck)
        if isinstance(weights, dict):
            if ck in weights: return weights[ck]
            t = titles.get(ck)
            if t in weights: return weights[t]
            return (1.0 / cut) if cut else 0.0
        if weights in (None, "invcut"): return (1.0 / cut) if cut else 0.0
        if weights == "invmean":        return (1.0 / mean) if mean else 0.0
        if weights == "inv_sd":         return (1.0 / sd) if sd else 0.0
        raise ValueError(f"unknown weights spec {weights!r}")
    def f(students, ctx):
        titles = ctx.get("stnTitleByCk", {})
        out = {}
        for st, d in students.items():
            cks = d.get("cks") or [None] * len(d["stn"])
            num = den = 0.0
            for (s, c, m, sd), ck in zip(d["stn"], cks):
                w = _w(c, m, sd, ck, titles)
                if w:
                    num += s * w; den += w
            out[st] = _clip100(num / den) if den else d["raw"]
        return out
    return (label, f)

# register the default (w = 1/cut) so it is selectable by name in finalScoreMethods
FINAL_SCORE_SCALINGS["difficultyWeighted"] = difficultyWeightedScaling()[1]
FINAL_SCORE_HEADERS["difficultyWeighted"] = "Difficulty-wtd /100"

# weight = stationMean / stationCut : up-weights stations where the cohort scored well ABOVE the cut
# (lenient / "easy" stations, big headroom); down-weights hard/discriminating stations (mean ~ cut).
FINAL_SCORE_SCALINGS["meanCutWeighted"] = difficultyWeightedScaling(
    weights=lambda cut, mean, sd, ck: (mean / cut) if cut else 0.0, label="Wtd mean/cut")[1]
FINAL_SCORE_HEADERS["meanCutWeighted"] = "Wtd mean/cut"


def perStationZScaled(mean=50.0, sd=10.0, restandardize=True, label=None):
    """Standardised per-station z aggregate -> ("label", func) for finalScoreMethods.
    Each station score is converted to a z against THAT station's cohort mean/SD, the z's are
    averaged, then rescaled to a readable scale:
        z_i   = (x_i - stationMean_i) / stationSD_i
        zbar  = mean(z_i over the student's stations)
        mark  = clip( mean + sd * zbar )                       if restandardize=False
              = clip( mean + sd * (zbar - mu_zbar)/sigma_zbar ) if restandardize=True (default)
    restandardize=True gives an output with EXACTLY the requested mean/sd (e.g. 50 +/- 10), i.e. a
    true standardised scale; False just shifts/scales the raw mean-z (spread then < sd, like perStationZ).
    NORM-REFERENCED: a mark states standing relative to THIS cohort (good for within-cohort ranking,
    not for an absolute standard or year-on-year comparison)."""
    def f(students, ctx):
        zbar = {}
        for st, d in students.items():
            zs = [(x - m) / s for (x, c, m, s) in d["stn"] if s and s > 0]
            zbar[st] = (sum(zs) / len(zs)) if zs else 0.0
        if restandardize:
            vals = list(zbar.values())
            mu = (sum(vals) / len(vals)) if vals else 0.0
            sig = statistics.pstdev(vals) if len(vals) > 1 else 0.0
            return {st: _clip100(mean + sd * ((z - mu) / sig if sig else 0.0)) for st, z in zbar.items()}
        return {st: _clip100(mean + sd * z) for st, z in zbar.items()}
    return (label or f"Std {mean:.0f}/{sd:.0f}", f)

# default standardised aggregate on a 50 +/- 10 scale
FINAL_SCORE_SCALINGS["perStationZ50"] = perStationZScaled()[1]
FINAL_SCORE_HEADERS["perStationZ50"] = "Std 50/10"


def resolveFinalScoreMethods(methods):
    """Normalise finalScoreMethods into [(header, func)]. Items may be a registry NAME
    (FINAL_SCORE_SCALINGS) or a (header, func(students, ctx)->{st:mark}) tuple. None/[] -> rawMean only."""
    if not methods:
        methods = ["rawMean"]
    out = []
    for m in methods:
        if isinstance(m, (tuple, list)):
            out.append((str(m[0]), m[1]))
        elif m in FINAL_SCORE_SCALINGS:
            out.append((FINAL_SCORE_HEADERS.get(m, m), FINAL_SCORE_SCALINGS[m]))
        else:
            raise ValueError(f"unknown finalScoreMethod {m!r}; known: {list(FINAL_SCORE_SCALINGS)}")
    return out


def pct1(x):
    """Score fraction -> percentage rounded to 1 dp (canonical for pass/fail comparisons)."""
    return round(x * 100, 1)


def gradientHex(t):
    """t in [0,1] -> hex on a red->yellow->green scale (Excel-style)."""
    t = max(0.0, min(1.0, t))
    stops = [(0.0, (248, 105, 107)), (0.5, (255, 235, 132)), (1.0, (99, 190, 123))]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]; t1, c1 = stops[i + 1]
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return "%02X%02X%02X" % tuple(round(c0[k] + (c1[k] - c0[k]) * f) for k in range(3))
    return "%02X%02X%02X" % stops[-1][1]


def countBelow(scs, cutFrac):
    """Number of scores strictly below the 1-dp-rounded cut."""
    cp = round(cutFrac * 100, 1)
    return int(sum(1 for x in scs if round(x * 100, 1) < cp))


def cronbachAlpha(rows, items):
    """Cronbach's alpha over the checklist items, using the normalised item fractions (so items
    on different level scales are comparable). Complete cases only."""
    items = list(items)
    if len(items) <= 1:
        return float("nan")
    M = np.array([[r["frac"][i] for i in items]
                  for r in rows if all(r["frac"].get(i) is not None for i in items)], float)
    if M.ndim != 2 or M.shape[0] < 2 or M.shape[1] <= 1:
        return float("nan")
    k = M.shape[1]
    itemVar = M.var(axis=0, ddof=1).sum()
    totalVar = M.sum(axis=1).var(ddof=1)
    return (k / (k - 1)) * (1 - itemVar / totalVar) if totalVar > 0 else float("nan")


def itemTotalCorrs(rows, items):
    """Item-total correlation (discrimination) for each item, on the normalised item fractions.
    Returns a list aligned to `items`."""
    items = list(items)
    tot = np.array([np.mean([r["frac"][j] for j in items if r["frac"].get(j) is not None])
                    if any(r["frac"].get(j) is not None for j in items) else np.nan
                    for r in rows])
    out = []
    for i in items:
        v = np.array([r["frac"].get(i) if r["frac"].get(i) is not None else np.nan for r in rows], float)
        out.append(np.corrcoef(v, tot)[0, 1] if np.nanstd(v) > 0 else np.nan)
    return out


def itemGrCorrs(rows, items, method="spearman"):
    """Correlation of each MC item (normalised fraction 0..1) with the Global Rating (5=best..1=worst).
    Pairwise-complete: only rows with BOTH a GR and that item marked count. method = "spearman"
    (default; GR and item levels are ordinal) or "pearson". Returns (rList, nList) aligned to `items`;
    r is NaN when n < 3 or either side has no variation."""
    rs, ns = [], []
    for i in items:
        pairs = [(r["gr"], r["frac"].get(i)) for r in rows
                 if r.get("gr") is not None and r["frac"].get(i) is not None]
        ns.append(len(pairs))
        if len(pairs) < 3:
            rs.append(np.nan); continue
        g, f = np.array(pairs, float).T
        if np.std(g) == 0 or np.std(f) == 0:
            rs.append(np.nan); continue
        rs.append((stats.spearmanr(g, f)[0] if method == "spearman" else stats.pearsonr(g, f)[0]))
    return rs, ns


def alphaInterpretation(a):
    if a != a:
        return "-"
    if a >= 0.9:
        return "Excellent"
    if a >= 0.8:
        return "Good"
    if a >= 0.7:
        return "Acceptable"
    if a >= 0.6:
        return "Questionable"
    return "Poor"


def difficultyBand(fracMean):
    return "Easy" if fracMean >= 0.8 else ("Hard" if fracMean < 0.6 else "Moderate")


def stationTitle(st, ck):
    """Short sheet name, e.g. 'S1 IC'."""
    return f"S{st} {CHECKLIST_ABBR.get(ck, ck[:12])}"


def buildBlrFigure(spec, blr, imgDir, borderlineGr=2, grCorrMethod="spearman"):
    """4-panel BLR figure. Saves a PNG into imgDir and returns (path, itemMeanFracs, itemCorrs).
    Panels: Score vs GR (BLR) | Item vs GR correlation | Item analysis (mean + item-total r) | Score histogram.
    grCorrMethod = "spearman" (default) or "pearson" for the Item vs GR panel."""
    st, ck, cfg, rows = spec["st"], spec["ck"], spec["cfg"], spec["rows"]
    grs, scs = blr["grs"], blr["scs"]
    items = spec["items"]
    means = [np.nanmean([r["frac"][i] for r in rows if r["frac"].get(i) is not None] or [np.nan]) for i in items]
    corr = itemTotalCorrs(rows, items)
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(f"Station {st} — {cfg['name'].split('.')[0]}  (BLR, {spec['levels']})", fontsize=14, fontweight="bold")

    a = ax[0, 0]
    for gr in sorted(set(grs)):
        m = grs == gr
        jit = np.random.uniform(-0.13, 0.13, m.sum())
        a.scatter(grs[m] + jit, scs[m] * 100, c=GR_COLORS.get(gr, "#888"), s=38, alpha=0.75,
                  edgecolors="white", linewidth=0.5, label=f"{GR_LABELS[gr]} (n={m.sum()})")
    xl = np.array([0.5, 5.5])
    a.plot(xl, (blr["slope"] * xl + blr["intercept"]) * 100, "k--", lw=1.5, label=f"Regression (R²={blr['r2']:.3f})")
    a.axhline(blr["cut"] * 100, color="#E24B4A", ls=":", lw=1.6, label=f"BLR cut {blr['cut']*100:.1f}%")
    a.axvline(borderlineGr, color="#999", lw=0.8, alpha=0.6)
    a.set_xlabel("Global Rating (1=Fail .. 5=Excellent)"); a.set_ylabel("Checklist score (%)")
    a.set_title("Score vs Global Rating"); a.set_xlim(0.5, 5.5); a.set_ylim(-5, 105)
    a.set_xticks([1, 2, 3, 4, 5]); a.legend(fontsize=7, loc="upper left")

    a = ax[0, 1]                                               # correlation of each MC item with GR
    grR, grN = itemGrCorrs(rows, items, grCorrMethod)
    xg = np.arange(len(items)); rv = np.nan_to_num(np.array(grR, float), nan=0.0)
    cols = ["#1D9E75" if r >= 0.3 else ("#EF9F27" if r >= 0.2 else "#E24B4A") for r in rv]   # good / ok / weak
    a.bar(xg, rv, color=cols, alpha=0.75, edgecolor=cols)
    for k, (r, n) in enumerate(zip(grR, grN)):
        a.text(k, (r if r == r else 0) + (0.02 if (r if r == r else 0) >= 0 else -0.06),
               ("-" if r != r else f"{r:.2f}"), ha="center", va="bottom", fontsize=7)
    a.axhline(0.3, color="#1D9E75", ls=":", lw=1, label="r = 0.3 (good)")
    a.axhline(0.2, color="#EF9F27", ls=":", lw=1, label="r = 0.2 (acceptable)")
    a.axhline(0, color="#333", lw=0.8)
    a.set_ylim(min(-0.2, np.nanmin(rv) - 0.1) if len(rv) else -0.2, 1.05)
    a.set_xticks(xg); a.set_xticklabels([f"MC{i}" for i in items], rotation=45, ha="right")
    a.set_ylabel(f"{'Spearman ρ' if grCorrMethod == 'spearman' else 'Pearson r'} with GR")
    a.set_title(f"Item vs Global Rating correlation (n≈{max(grN) if grN else 0})"); a.legend(fontsize=7, loc="upper right")

    a = ax[1, 0]; x = np.arange(len(items))
    a.bar(x, np.array(means) * 100, color="#3266ad", alpha=0.55, edgecolor="#3266ad", label="Item mean (%)")
    a.set_ylabel("Mean (%)"); a.set_ylim(0, 110)
    a2 = a.twinx(); a2.plot(x, corr, "o-", color="#1D9E75", lw=2, ms=5, label="Item-total r")
    a2.set_ylabel("Item-total r"); a2.set_ylim(0, 1)
    a.set_xticks(x); a.set_xticklabels([f"MC{i}" for i in items], rotation=45, ha="right"); a.set_title("Item analysis")
    l1, la1 = a.get_legend_handles_labels(); l2, la2 = a2.get_legend_handles_labels()
    a.legend(l1 + l2, la1 + la2, fontsize=7, loc="lower left")

    a = ax[1, 1]
    a.hist(scs * 100, bins=15, color="#3266ad", alpha=0.4, edgecolor="#3266ad")
    a.axvline(blr["cut"] * 100, color="#E24B4A", ls=":", lw=2, label=f"BLR cut {blr['cut']*100:.1f}%")
    a.axvline(scs.mean() * 100, color="#333", ls="--", lw=1, label=f"Mean {scs.mean()*100:.1f}%")
    a.set_xlabel("Checklist score (%)"); a.set_ylabel("Frequency"); a.set_title("Score distribution"); a.legend(fontsize=8)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    os.makedirs(imgDir, exist_ok=True)
    path = os.path.join(imgDir, f"blr_station{st}_{ck[:20]}.png")
    fig.savefig(path, dpi=140, bbox_inches="tight"); plt.close(fig)
    return path, means, corr


def computeAssessorHarshness(spec, blr):
    """
    Per-assessor harshness at one station. Assumes ~random allocation of students to
    assessors (OSCE circuits), so an assessor's mean minus the station mean estimates
    harshness. Also reports the mean BLR residual (checklist score vs the score their
    GRs predict). Returns (rows, stationMeanPct, stationMeanGr) sorted harsh -> lenient.
    """
    rows = [r for r in spec["rows"] if r["score"] is not None and r["gr"] is not None]
    if not rows:
        return [], float("nan"), float("nan")
    stMeanPct = float(np.mean([r["score"] for r in rows])) * 100
    stMeanGr = float(np.mean([r["gr"] for r in rows]))
    slope, intercept = blr["slope"], blr["intercept"]
    byA = {}
    for r in rows:
        byA.setdefault(r["assessor"], []).append(r)
    out = []
    for a, rs in byA.items():
        pct = float(np.mean([r["score"] for r in rs])) * 100
        gr = float(np.mean([r["gr"] for r in rs]))
        resid = float(np.mean([(r["score"] - (slope * r["gr"] + intercept)) for r in rs])) * 100
        dpct = pct - stMeanPct
        dgr = gr - stMeanGr
        flag = "Harsh" if (dpct <= -5 or dgr <= -0.4) else ("Lenient" if (dpct >= 5 or dgr >= 0.4) else "Typical")
        out.append({"assessor": a, "n": len(rs), "meanPct": pct, "dPct": dpct,
                    "meanGr": gr, "dGr": dgr, "residPct": resid, "flag": flag})
    out.sort(key=lambda x: x["dPct"])
    return out, stMeanPct, stMeanGr


def buildHarshnessFigure(spec, harsh, stMeanPct, imgDir):
    """Horizontal bar of each assessor's deviation from the station mean checklist %."""
    st, ck, cfg = spec["st"], spec["ck"], spec["cfg"]
    if not harsh:
        return None
    labels = [f"{h['assessor']} (n={h['n']})" for h in harsh]
    deltas = [h["dPct"] for h in harsh]
    colors = ["#E24B4A" if d < -5 else ("#1D9E75" if d > 5 else "#9aa7b4") for d in deltas]
    fig, ax = plt.subplots(figsize=(8, max(2.4, 0.42 * len(harsh) + 1.1)))
    y = np.arange(len(harsh))
    ax.barh(y, deltas, color=colors, edgecolor="white")
    ax.axvline(0, color="#333", lw=1)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Mean checklist % minus station mean  (harsh <-- 0 --> lenient)")
    ax.set_title(f"Station {st} — {cfg['name'].split('.')[0]}: assessor harshness (station mean {stMeanPct:.1f}%)", fontsize=10)
    for yi, d in zip(y, deltas):
        ax.text(d + (0.4 if d >= 0 else -0.4), yi, f"{d:+.1f}", va="center",
                ha="left" if d >= 0 else "right", fontsize=7)
    plt.tight_layout()
    os.makedirs(imgDir, exist_ok=True)
    path = os.path.join(imgDir, f"harsh_station{st}_{ck[:20]}.png")
    fig.savefig(path, dpi=140, bbox_inches="tight"); plt.close(fig)
    return path


# ───────────────────────── workbook assembly ─────────────────────────
# ── OSCE examiner comments sheet (added 2026-10-28) ─────────────────────────────────────────
# Free-text fields about the OSCE/station itself (not the per-student feedback). DDS2 forms use
# "comments-on-the-osce"; DDS4 forms have no such box and use "internal-comments" instead;
# DDS3 forms use "internal-feedback" (confidential, not released to students).
OSCE_COMMENT_KEYS = OrderedDict([
    ("comments-on-the-osce", "OSCE Comments"),
    ("internal-comments", "Internal Comments"),
    ("internal-feedback", "Internal Comments"),
])


def collectOsceComments(records, commentKeys=None):
    """One row per (form, comment field) with non-blank text, sorted by station -> assessor.
    `records` = loadOsceRecords output (submitted, cohort-filtered, ignore list applied).
    `commentKeys` = {textKey: label}; defaults to OSCE_COMMENT_KEYS."""
    keys = OSCE_COMMENT_KEYS if commentKeys is None else commentKeys
    rows = []
    for r in records:
        fd = r.get("form_data") or {}
        texts = fd.get("texts") or {}
        cks = list((fd.get("checklists") or {}).keys())
        for key, label in keys.items():
            txt = str(texts.get(key) or "").strip()
            if not txt:
                continue
            st = r.get("station")
            rows.append({
                "station": st,
                "sheet": ", ".join(stationTitle(st, ck) for ck in cks) if cks else f"S{st}",
                "checklist": ", ".join(cks),
                "circuit": r.get("circuit") or "",
                "assessor": r.get("assessor") or "",
                "student": r.get("student") or "",
                "studentNo": str(r.get("student_number") or "").strip(),
                "field": label,
                "comment": txt,
            })
    def stKey(x):
        try:
            return (0, int(x["station"]))
        except (TypeError, ValueError):
            return (1, str(x["station"]))
    rows.sort(key=lambda x: (stKey(x), x["checklist"], x["assessor"].lower(), x["field"], x["comment"]))
    return rows


def writeOsceCommentsSheet(wb, rows, cohortLabel="", sheetName="OSCE Comments"):
    """Add a styled comments sheet to workbook `wb`. If `rows` is empty, print a notice and add
    nothing. Returns the worksheet or None."""
    tag = (cohortLabel or "this cohort").strip()
    if not rows:
        print(f"No such comments present for {tag}.")
        return None
    ws = wb.create_sheet(sheetName)
    ws.sheet_view.showGridLines = False
    side = Side(style="thin", color="BFBFBF"); box = Border(left=side, right=side, top=side, bottom=side)
    hFont = Font(name="Arial", size=10, bold=True, color="FFFFFF"); hFill = PatternFill("solid", fgColor=HEAD)
    bFont = Font(name="Arial", size=10)
    ws.cell(1, 1, f"{tag} OSCE — examiner comments: {len(rows)} comment(s) across "
                  f"{len({r['assessor'] for r in rows})} assessor(s)").font = Font(name="Arial", size=12, bold=True, color=HEAD)
    heads = ["Station", "Sheet", "Checklist", "Circuit", "Assessor", "Student", "Student No", "Field", "Comment"]
    keys = ["station", "sheet", "checklist", "circuit", "assessor", "student", "studentNo", "field", "comment"]
    widths = [9, 16, 26, 9, 22, 24, 12, 18, 90]
    for c, h in enumerate(heads, 1):
        cc = ws.cell(3, c, h); cc.font = hFont; cc.fill = hFill; cc.border = box
        cc.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    rr = 4
    for r in rows:
        for c, k in enumerate(keys, 1):
            v = r[k]
            if k == "studentNo" and str(v).isdigit():
                v = int(v)
            cc = ws.cell(rr, c, v); cc.font = bFont; cc.border = box
            cc.alignment = Alignment(horizontal=("center" if k in ("station", "circuit", "studentNo") else "left"),
                                     vertical="top", wrap_text=(k in ("comment", "checklist", "sheet")))
        rr += 1
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A4"; ws.auto_filter.ref = f"A3:{get_column_letter(len(heads))}{rr-1}"
    print(f"{tag}: wrote {len(rows)} OSCE comment(s) to sheet '{sheetName}'.")
    return ws


def buildOsceWorkbook(srcPath, stationPath, analysisPath, imgDir, cohortLabel="", borderlineGr=2,
                      ignoreStudentNumbers=None, rosterPath="studentEmailList.csv", cohort=None,
                      reverseGr="auto", excludeChecklists=None, grScoreBands=None, scoreConfig=None,
                      stationOverrides=None, allowedStationFailures=None, finalScoreMethods=None,
                      commentKeys=None):
    """
    Build TWO workbooks from an OSCE JSON dump:
      stationPath  : station workbook (Read Me, Station Summary, per-station detail, MC Item Stats, Checklist Legend)
      analysisPath : analysis workbook (BLR Analysis, Station Validity, Standard Setting, Assessor Harshness)
      imgDir       : folder for BLR + harshness PNGs (created if missing)
    `cohort` filters records by their `session` string when the JSON holds more than one cohort;
    it defaults to `cohortLabel` (so passing cohortLabel="DDS4" also filters to DDS4). Pass
    cohort="" to disable the filter.
    `reverseGr` (True/False/"auto") controls Global-Rating direction: "auto" (default) detects it
    from the scale labels — DDS2 stores 1=Excellent..5=Fail (reversed), DDS4 stores 1=Fail..5=Excellent
    (not reversed). Pass True/False to force it.
    `commentKeys` ({textKey: label}, default OSCE_COMMENT_KEYS) picks the examiner free-text
    fields written to the station workbook's "OSCE Comments" sheet; none found -> a notice is printed.
    Returns a summary dict.
    """
    effectiveCohort = cohort if cohort is not None else (cohortLabel or None)
    records = loadOsceRecords(srcPath, ignoreStudentNumbers, rosterPath, cohort=effectiveCohort)
    specs = buildStationSpecs(records, reverseGr=reverseGr, excludeChecklists=excludeChecklists,
                              grScoreBands=grScoreBands, scoreConfig=scoreConfig,
                              stationOverrides=stationOverrides)
    sconf = resolveScoreConfig(scoreConfig)
    stationOverrides = stationOverrides or {}
    # Student number: primary source is the record's own `student_number` (set in buildStationSpecs);
    # fall back to the roster (name match + overrides) only for any record that lacks it. Build a
    # name -> number map (numOf) so the pivot/grid, which key by name, show the same number.
    nameToNum = nameToNumberMap(rosterPath)
    numOf = {}
    for s in specs:
        for r in s["rows"]:
            if not r.get("studentNo"):
                r["studentNo"] = studentNumberFor(r["student"], nameToNum)
            numOf.setdefault(r["student"], r["studentNo"])
    os.makedirs(imgDir, exist_ok=True)
    blr = {s["ck"]: computeBlr(s["rows"], borderlineGr) for s in specs}
    # Effective pass/fail cut per checklist AFTER applying station overrides (passAll / bgm /
    # cutAdjustPct / excludeFromPassFail). The BLR panel still shows the RAW blr[ck] cut; every
    # pass/fail consumer (Station Summary fails, pivot, standard setting, below-cut list) uses these.
    passCut, passCutPct, forcePass, noPassFail, overrideNote = {}, {}, {}, set(), {}
    for s in specs:
        ck = s["ck"]
        cf, cp, fp, excl, note = effectivePassCut(ck, blr[ck], stationOverrides, borderlineGr)
        passCut[ck], passCutPct[ck], forcePass[ck] = cf, cp, fp
        overrideNote[ck] = note
        if excl:
            noPassFail.add(ck)
    def studentFails(ck, r):
        """True if this row fails under the EFFECTIVE cut; never for force-pass or excluded stations."""
        if ck in noPassFail or forcePass.get(ck) or r["score"] is None or passCutPct.get(ck) is None:
            return False
        return pct1(r["score"]) < passCutPct[ck]
    # OSCE-level outcome membership per station (drives the aggregate pass rule):
    #   inFailCount = station failures here count toward the allowable-failure limit
    #   inTotal     = station score + its raw BLR cut count toward total-score >= total-combined-cut
    # excludeFromPassFail stations are out of BOTH; countsToFailLimit/countsToTotal override the default True.
    inFailCount, inTotal = {}, {}
    for s in specs:
        ck = s["ck"]; o = stationOverrides.get(ck, {}) or {}
        excl = ck in noPassFail
        inFailCount[ck] = (not excl) and o.get("countsToFailLimit", True)
        inTotal[ck] = (not excl) and o.get("countsToTotal", True)
    # perStationWeighted weights (100/cut) for the Read Me, shown when that method is requested
    weightsNote = []
    if finalScoreMethods and "perStationWeighted" in finalScoreMethods:
        wcks = [(stationTitle(s["st"], s["ck"]), blr[s["ck"]]["cutPct"]) for s in specs
                if inTotal.get(s["ck"]) and blr[s["ck"]].get("cutPct")]
        wsum = sum(100.0 / c for _, c in wcks) or 1.0
        weightsNote = ["perStationWeighted station weights = 100 / raw BLR cut (harder station = higher weight; "
                       "mark = sum(score x weight) / sum(weights)):"] + \
                      [f"    {nm}: cut {c:.1f}% -> weight {100.0 / c:.2f}  ({100.0 / c / wsum * 100:.1f}%)"
                       for nm, c in wcks]
    # Stations that can support BLR/validity analysis (paired GR+score with GR spread). Others
    # (checklist-only stations with no GR, or GR-only stations with no scored items) still appear
    # in the STATION workbook, but are skipped in the analysis workbook so an empty regression
    # can't crash the run.
    analysisSpecs = [s for s in specs if blr[s["ck"]].get("valid")]
    skippedAnalysis = [{"station": s["st"], "checklist": s["ck"], "sheet": stationTitle(s["st"], s["ck"]),
                        "reason": ("no Global Rating" if not any(r["gr"] is not None for r in s["rows"])
                                   else ("no scored items" if not s["items"] else "insufficient GR/score data"))}
                       for s in specs if not blr[s["ck"]].get("valid")]

    # shared styles / helpers
    hFont = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    bFont = Font(name="Arial", size=10)
    hFill = PatternFill("solid", fgColor=HEAD)
    thin = Side(style="thin", color="C5D5E8")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    ctrW = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ctr = Alignment(horizontal="center", vertical="center")
    topL = Alignment(horizontal="left", vertical="top", wrap_text=True)
    flatL = Alignment(horizontal="left", vertical="center", wrap_text=False)

    def styleHeader(ws, ncol, row=1):
        for c in range(1, ncol + 1):
            cell = ws.cell(row, c); cell.font = hFont; cell.fill = hFill; cell.alignment = ctrW; cell.border = box

    def scoreDescLines():
        """Read Me lines describing the ACTIVE scoring configuration (mode / points / aggregate)."""
        out = []
        if sconf["mode"] == "label":
            out.append(("Scoring by the option's LABEL value (same value regardless of the item's level):", 11, True))
            seen = {}                                          # dedupe alias labels sharing a value (e.g. typo variant)
            for k, v in sorted(sconf["labelPoints"].items(), key=lambda kv: -kv[1]):
                seen.setdefault(v, k)
            out.append(("    " + ",  ".join(f"{k.title()}={v}" for v, k in
                        sorted(seen.items(), key=lambda kv: -kv[0])) + "   (item max = best available label)", 10, False))
        else:
            out.append(("Scoring is DYNAMIC per MC item, by the option's RANK (best->worst), not the label:", 11, True))
            for lv in sorted(sconf["levelPoints"], reverse=True):
                pts = sconf["levelPoints"][lv]
                out.append((f"    {lv}-level item: " + " / ".join(str(p) for p in pts) + f"   (max {max(pts)})", 10, False))
            out.append(("    Other levels fall back to a linear best->worst scale.", 10, False))
        out.append(("Different items in the SAME checklist may have different levels (e.g. DDS4 Fixed Prosth).", 10, False))
        if sconf["aggregate"] == "total":
            out.append(("Aggregate = TOTAL: Checklist Score(%) = sum(item points) / sum(item max) x 100", 10, False))
            out.append(("    (raw total over max denominator; items with more points weigh MORE).", 10, False))
        else:
            out.append(("Aggregate = NORMALIZE: each item -> points/its-own-max, so every item has EQUAL WEIGHT;", 10, False))
            out.append(("    Checklist Score(%) = mean of the answered items' fractions x 100.", 10, False))
        return out

    def readMe(ws, title, extra):
        ws.sheet_view.showGridLines = False
        lines = [(title, 13, True), ("", 10, False),
                 (f"Source: {os.path.basename(srcPath)} (DASH OSCE v3). Submitted only; test/dummy/model and ignored students excluded.", 10, False),
                 (f"Ignored student numbers: {sorted(IGNORE_STUDENT_NUMBERS if ignoreStudentNumbers is None else ignoreStudentNumbers)} (resolved via roster).", 10, False),
                 ] + [(t, sz, b) for (t, sz, b) in scoreDescLines()] + [
                 ("GR numbered per standard: 5=Excellent .. 1=Fail; BLR cut at GR=Borderline(2).", 10, False),
                 ("", 10, False)] + [(t, 10, False) for t in extra]
        for i, (t, sz, b) in enumerate(lines, 1):
            ws.cell(i, 1, t).font = Font(name="Arial", size=sz, bold=b, color=HEAD if b else "000000")
        ws.column_dimensions["A"].width = 120

    # note for any station whose GR was derived from raw-score bands (no examiner GR)
    derivedNote = []
    for s in specs:
        if s.get("grDerived"):
            b = grScoreBands.get(s["ck"]) if grScoreBands else GR_SCORE_BANDS.get(s["ck"])
            bandTxt = ", ".join(f"{GR_LABELS[gr]} {lo}-{hi}" for lo, hi, gr in (b or []))
            derivedNote.append(f"NOTE: {stationTitle(s['st'], s['ck'])} ({s['cfg']['name'].split('.')[0]}) had NO examiner Global Rating "
                               f"(unobserved / marked post-task). GR was DERIVED from the raw checklist label-value total "
                               f"(Very Good=4, Satisfactory=3, Borderline=2, Unsatisfactory=0; max 66) via examiner bands: {bandTxt}. "
                               f"This total is a separate scale from Score% (mean of per-item fractions); the derived GR re-bands the same "
                               f"responses, so that station's BLR cut is a banded-standard cut, not an independent regression. "
                               f"Full working is shown at the top of that station's panel in the BLR Analysis sheet.")

    # note for any station carrying a pass/fail override (drop / passAll / bgm / cut adjust / item drop)
    overrideNoteLines = []
    def remapText(s):
        out = []
        for rule in s.get("grRemaps") or []:
            scope = []
            if "assessor" in rule: scope.append(f"assessor {rule['assessor']}")
            if "circuit" in rule: scope.append(f"circuit {rule['circuit']}")
            sc = (" for " + ", ".join(scope)) if scope else " (all)"
            out.append(f"GR {rule.get('from')}->{rule.get('to')}{sc}")
        return out
    for s in specs:
        ck = s["ck"]; bits = []
        if s.get("droppedItems"):
            bits.append("dropped items " + ", ".join(f"MC{i}" for i in s["droppedItems"]))
        if s.get("itemWeights"):
            bits.append("item weights (score = weighted mean of item fractions) " +
                        ", ".join(f"MC{i} {w:g}%" for i, w in s["itemWeights"].items()))
        rt = remapText(s)
        if rt:
            bits.append("GR remap [" + "; ".join(rt) + f"] — {s.get('grRemapN', 0)} rating(s) changed")
        if overrideNote.get(ck):
            bits.append(overrideNote[ck])
        if bits:
            overrideNoteLines.append(f"OVERRIDE: {stationTitle(s['st'], ck)} ({s['cfg']['name'].split('.')[0]}) — " + "; ".join(bits) + ".")
    if overrideNoteLines:
        overrideNoteLines = ["Custom result overrides applied (see each station):"] + overrideNoteLines

    # Readiness to Progress / pre-built comments (BOH2 2026+): shown only when the forms carry them
    rtpLevels = rtpLevelFields(records)
    hasRtp = any(r.get("rtp") is not None for s in specs for r in s["rows"])
    hasPrebuilt = any(s.get("prebuiltCfg") for s in specs)
    rtpNote = []
    if hasRtp:
        rtpNote = ["RTP = Readiness to Progress (examiner judgement; display only — NOT used in Score, GR or BLR):"] + \
                  [f"    {lv}: {lab}" for lv, lab in rtpLevels.items()]
    if hasPrebuilt:
        rtpNote += ["Pre-built Comments = canned statements the examiner ticked (the list offered depends on the GR given); "
                    "Feedback = examiner free text. Tick counts per statement are on the 'Pre-built Comment Stats' sheet."]

    # =================== STATION WORKBOOK ===================
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    readMe(wb.create_sheet("Read Me"), f"{cohortLabel} OSCE — Round 1 (stations)".strip(),
           ["This workbook holds the per-station results only.",
            "BLR standard-setting, validity and assessor-harshness analysis are in the separate analysis workbook.",
            "Sheet names are abbreviated: e.g. S1 IC = Station 1 Infection Control, S1 Rad = Radiography.",
            "MC cells show the item's rank points; the fill is a red->green gradient by the item's normalised fraction (red=worst option, green=best option)."]
           + rtpNote + derivedNote + overrideNoteLines)

    # Station Summary
    summ = wb.create_sheet("Station Summary")
    sh = ["Station", "Checklist", "Levels", "N", "Mean %", "SD %", "Median %", "Min %", "Max %", "GR Mean",
          "Excellent", "Very good", "Pass", "Borderline", "Fail", "Fails", "Pass+ %", "Pass Cut %"]
    rtpLvList = list(rtpLevels) or [1, 2, 3, 4]
    if hasRtp:
        sh = sh + ["RTP Mean"] + [f"RTP L{lv}" for lv in rtpLvList]
    summ.append(sh); styleHeader(summ, len(sh))
    for s in specs:
        rows = s["rows"]
        pcts = [r["score"] * 100 for r in rows if r["score"] is not None]
        grs = [r["gr"] for r in rows if r["gr"] is not None]
        lc = Counter(GR_LABELS[g] for g in grs)
        passplus = lc["Excellent"] + lc["Very good"] + lc["Pass"]
        ck = s["ck"]; cutP = passCutPct[ck]                     # effective pass cut (after overrides)
        if ck in noPassFail:
            failsCell, cutCell = "-", "excluded"
        elif forcePass.get(ck):
            failsCell, cutCell = 0, "PASS ALL"
        else:
            failsCell = sum(1 for r in rows if studentFails(ck, r))
            cutCell = cutP if cutP is not None else "-"
        summ.append([s["st"], s["cfg"]["name"].split(".")[0][:40], s["levels"], len(rows),
                     round(statistics.mean(pcts), 1) if pcts else None,
                     round(statistics.pstdev(pcts), 1) if pcts else None,
                     round(statistics.median(pcts), 1) if pcts else None,
                     round(min(pcts), 1) if pcts else None, round(max(pcts), 1) if pcts else None,
                     round(statistics.mean(grs), 2) if grs else None,
                     lc["Excellent"], lc["Very good"], lc["Pass"], lc["Borderline"], lc["Fail"],
                     failsCell, round(passplus / len(grs) * 100, 1) if grs else None, cutCell]
                    + ([round(statistics.mean(rv), 2) if (rv := [r["rtp"] for r in rows if r.get("rtp") is not None]) else None]
                       + [sum(1 for x in rv if x == lv) for lv in rtpLvList] if hasRtp else []))
    failCol = sh.index("Fails") + 1
    for rr in range(2, summ.max_row + 1):
        for c in range(1, len(sh) + 1):
            cell = summ.cell(rr, c); cell.font = bFont; cell.border = box; cell.alignment = ctr
        fv = summ.cell(rr, failCol).value
        if isinstance(fv, int) and fv > 0:
            summ.cell(rr, failCol).fill = PatternFill("solid", fgColor="FFC7CE")
            summ.cell(rr, failCol).font = Font(name="Arial", size=10, bold=True, color="9C0006")
    summ.column_dimensions["A"].width = 8; summ.column_dimensions["B"].width = 26
    for c in range(3, len(sh) + 1):
        summ.column_dimensions[get_column_letter(c)].width = 11
    summ.freeze_panes = "A2"

    # detail sheets (GR Label removed; Borderline/Fail Info AFTER Feedback; rows sorted by Score desc)
    for s in specs:
        st, ck, cfg, rows, items = s["st"], s["ck"], s["cfg"], s["rows"], s["items"]
        ws = wb.create_sheet(stationTitle(st, ck)[:31])
        hdr = ["Circuit", "Student Name", "Student No", "Assessor"] + [f"MC{i}\n(/{s['itemMax'][i]})" for i in items] + \
              ["Score (%)", "GR"] + (["RTP"] if hasRtp else []) + \
              (["Pre-built Comments"] if s.get("prebuiltCfg") else []) + ["Feedback", "Borderline/Fail Info"]
        ws.append(hdr); styleHeader(ws, len(hdr))
        C = {h: i + 1 for i, h in enumerate(hdr)}
        srt = sorted(rows, key=lambda r: (r["score"] if r["score"] is not None else -1), reverse=True)
        for r in srt:
            pts = [r["points"][i] for i in items]
            pct = round(r["score"] * 100, 2) if r["score"] is not None else None
            ws.append([r["circuit"], r["student"], r["studentNo"], r["assessor"]] + pts +
                      [pct, r["gr"]] + ([r.get("rtp")] if hasRtp else []) +
                      (["\n".join(f"\u2022 {t}" for _, _, t in r.get("prebuilt") or [])] if s.get("prebuiltCfg") else []) +
                      [r["feedback"], r["blfail"]])
        nrow = ws.max_row; ncol = len(hdr)
        mc0 = C["Assessor"] + 1; gcol = C["GR"]; icol = C["Borderline/Fail Info"]; fcol = C["Feedback"]
        ws.row_dimensions[1].height = 28   # fit the two-line "MC n / max" headers
        nameCols = (C["Student Name"], C["Student No"], C["Assessor"])
        for ri, r in enumerate(srt, start=2):
            for c in range(1, ncol + 1):
                cell = ws.cell(ri, c); cell.font = bFont; cell.border = box
                cell.alignment = flatL if c in (icol, fcol, C.get("Pre-built Comments")) else (
                    Alignment(horizontal="left", vertical="center") if c in nameCols else ctr)
            for j, i in enumerate(items):
                fr = r["frac"].get(i)
                if fr is not None:
                    cc = ws.cell(ri, mc0 + j)
                    hexfill = gradientHex(fr)
                    cc.fill = PatternFill("solid", fgColor=hexfill)
                    cc.font = Font(name="Arial", size=10, color="FFFFFF" if fr <= 0.001 else "000000")
            ws.cell(ri, C["Score (%)"]).number_format = "0.00"
            gv = ws.cell(ri, gcol).value
            if gv in GR_FILL:
                ws.cell(ri, gcol).fill = PatternFill("solid", fgColor=GR_FILL[gv]); ws.cell(ri, gcol).font = Font(name="Arial", size=10, color=GR_FONTC[gv])
            rv = ws.cell(ri, C["RTP"]).value if "RTP" in C else None
            if rv in RTP_FILL:
                ws.cell(ri, C["RTP"]).fill = PatternFill("solid", fgColor=RTP_FILL[rv]); ws.cell(ri, C["RTP"]).font = Font(name="Arial", size=10, color=RTP_FONTC[rv])
            if gv == 1:
                ws.cell(ri, icol).fill = PatternFill("solid", fgColor="FFC7CE"); ws.cell(ri, icol).font = Font(name="Arial", size=10, bold=True, color="9C0006")
            elif gv == 2:
                ws.cell(ri, icol).fill = PatternFill("solid", fgColor="FFEB9C"); ws.cell(ri, icol).font = Font(name="Arial", size=10, color="7F6000")
        ws.column_dimensions["A"].width = 7
        ws.column_dimensions[get_column_letter(C["Student Name"])].width = 22
        ws.column_dimensions[get_column_letter(C["Student No"])].width = 11
        ws.column_dimensions[get_column_letter(C["Assessor"])].width = 20
        for c in range(mc0, mc0 + len(items)):
            ws.column_dimensions[get_column_letter(c)].width = 6
        ws.column_dimensions[get_column_letter(C["Score (%)"])].width = 9
        ws.column_dimensions[get_column_letter(gcol)].width = 5
        ws.column_dimensions[get_column_letter(fcol)].width = 55
        ws.column_dimensions[get_column_letter(icol)].width = 55
        if "RTP" in C:
            ws.column_dimensions[get_column_letter(C["RTP"])].width = 5
        if "Pre-built Comments" in C:
            ws.column_dimensions[get_column_letter(C["Pre-built Comments"])].width = 60
        ws.freeze_panes = f"{get_column_letter(C['Assessor']+1)}2"; ws.auto_filter.ref = f"A1:{get_column_letter(ncol)}{nrow}"

    # MC Item Stats  (per item: its own level, and the count on each option best->worst)
    mcw = wb.create_sheet("MC Item Stats"); rp = 1
    for s in specs:
        st, ck, cfg, rows, items = s["st"], s["ck"], s["cfg"], s["rows"], s["items"]
        optLabels = s["optLabels"]
        mcw.cell(rp, 1, f"Station {st} — {cfg['name'].split('.')[0]}  ({s['levels']})").font = Font(name="Arial", size=11, bold=True, color=HEAD); rp += 1
        hdr = ["MC", "Description", "Level", "n", "Option counts (best -> worst)", "Avg Points", "Max", "Avg %"]
        for c, h in enumerate(hdr, 1):
            cc = mcw.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
        rp += 1
        for i in items:
            keyPoints, mx, lvl, order = s["scales"][i]
            vals = [r["points"][i] for r in rows if r["points"][i] is not None]
            fvals = [r["frac"][i] for r in rows if r["frac"].get(i) is not None]
            avg = sum(vals) / len(vals) if vals else 0
            # counts per option, best -> worst, identified by the option's rank points
            dist = ", ".join(f"{(optLabels.get(k) or k)}={sum(1 for r in rows if r['points'][i] == keyPoints[k])}"
                             for k in order)
            avgPct = round(sum(fvals) / len(fvals) * 100, 1) if fvals else 0
            line = [f"MC{i}", cfg["fields"].get(f"MC{i}", "").strip(), f"{lvl}-level", len(vals),
                    dist, round(avg, 2), mx, avgPct]
            for c, v in enumerate(line, 1):
                cc = mcw.cell(rp, c, v); cc.font = bFont; cc.border = box
                cc.alignment = topL if c in (2, 5) else ctr
            rp += 1
        rp += 1
    mcw.column_dimensions["A"].width = 6; mcw.column_dimensions["B"].width = 50
    mcw.column_dimensions["C"].width = 9; mcw.column_dimensions["D"].width = 6
    mcw.column_dimensions["E"].width = 48
    for c in "FGH":
        mcw.column_dimensions[c].width = 10

    # Checklist Legend
    leg = wb.create_sheet("Checklist Legend"); leg.append(["Station", "Sheet", "Checklist", "Item Level", "MC", "Description"]); styleHeader(leg, 6)
    for s in specs:
        for i in s["items"]:
            leg.append([s["st"], stationTitle(s["st"], s["ck"]), s["cfg"]["name"].split(".")[0][:40], f"{s['itemLevel'][i]}-level", f"MC{i}", s["cfg"]["fields"].get(f"MC{i}", "").strip()])
    for rr in range(2, leg.max_row + 1):
        for c in range(1, 7):
            cell = leg.cell(rr, c); cell.font = bFont; cell.border = box; cell.alignment = topL if c == 6 else ctr
    leg.column_dimensions["A"].width = 8; leg.column_dimensions["B"].width = 12; leg.column_dimensions["C"].width = 24
    leg.column_dimensions["D"].width = 9; leg.column_dimensions["E"].width = 7; leg.column_dimensions["F"].width = 78
    leg.freeze_panes = "A2"

    # ---- Assessors (unique assessors and the stations they assessed) ----
    asr = wb.create_sheet("Assessors"); asr.sheet_view.showGridLines = False
    aMap = {}   # assessor -> {sheetTitle: n}
    for s in specs:
        title = stationTitle(s["st"], s["ck"])
        for r in s["rows"]:
            aMap.setdefault(r["assessor"], {})
            aMap[r["assessor"]][title] = aMap[r["assessor"]].get(title, 0) + 1
    asr.cell(1, 1, f"Unique assessors: {len(aMap)}   (across {len(specs)} station-checklists)").font = Font(name="Arial", size=12, bold=True, color=HEAD)
    ah = ["Assessor", "# Stations", "Assessments (n)", "Stations assessed (n each)"]
    for c, h in enumerate(ah, 1):
        cc = asr.cell(3, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
    rr = 4
    for a in sorted(aMap, key=lambda a: (-len(aMap[a]), a)):
        stns = sorted(aMap[a])
        detail = ", ".join(f"{t} ({aMap[a][t]})" for t in stns)
        vals = [a, len(stns), sum(aMap[a].values()), detail]
        for c, v in enumerate(vals, 1):
            cc = asr.cell(rr, c, v); cc.font = bFont; cc.border = box
            cc.alignment = Alignment(horizontal="left", vertical="center") if c in (1, 4) else ctr
        rr += 1
    asr.column_dimensions["A"].width = 24; asr.column_dimensions["B"].width = 11
    asr.column_dimensions["C"].width = 15; asr.column_dimensions["D"].width = 90
    asr.freeze_panes = "A4"; asr.auto_filter.ref = f"A3:D{rr-1}"

    # ---- Pre-built Comment Stats (how often each canned statement was ticked) ----
    prebuiltForms = 0
    if hasPrebuilt:
        pcs = wb.create_sheet("Pre-built Comment Stats"); pcs.sheet_view.showGridLines = False; rp = 1
        pcs.cell(rp, 1, f"{cohortLabel} OSCE — pre-built comment usage".strip()).font = Font(name="Arial", size=12, bold=True, color=HEAD); rp += 1
        pcs.cell(rp, 1, "Forms shown = forms whose GR matched the list's rating (the list only appears for that GR). "
                        "% Ticked = Times ticked / Forms shown.").font = Font(name="Arial", size=9, italic=True); rp += 2
        ph = ["Rating List", "Option", "Comment", "Times Ticked", "Forms Shown", "% Ticked"]
        for s in specs:
            pc = s.get("prebuiltCfg")
            if not pc:
                continue
            rows = s["rows"]
            withAny = sum(1 for r in rows if r.get("prebuilt")); prebuiltForms += withAny
            withBoth = sum(1 for r in rows if r.get("prebuilt") and str(r.get("feedback") or "").strip())
            pcs.cell(rp, 1, f"{stationTitle(s['st'], s['ck'])} — {s['cfg']['name'].split('.')[0]}   "
                            f"(forms with pre-built: {withAny}/{len(rows)}; also with free text: {withBoth})").font = Font(name="Arial", size=11, bold=True, color=HEAD); rp += 1
            for c, h in enumerate(ph, 1):
                cc = pcs.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
            rp += 1
            for fk, fcfg in pc.items():
                shown = sum(1 for r in rows if fcfg["grKey"] is not None and r.get("grKey") == fcfg["grKey"])
                band = fcfg["name"].split("(")[-1].rstrip(")").strip() if "(" in fcfg["name"] else fcfg["name"]
                for ok, txt in fcfg["items"]:
                    n = sum(1 for r in rows for (f2, k2, _t) in (r.get("prebuilt") or []) if f2 == fk and k2 == ok)
                    vals = [band, ok, txt, n, shown, (round(n / shown * 100, 1) if shown else None)]
                    for c, v in enumerate(vals, 1):
                        cc = pcs.cell(rp, c, v); cc.font = bFont; cc.border = box
                        cc.alignment = topL if c == 3 else ctr
                    rp += 1
            rp += 1
        for c, w in zip("ABCDEF", (22, 8, 90, 12, 12, 10)):
            pcs.column_dimensions[c].width = w

    # ---- OSCE Comments (examiner free text about the OSCE/station) ----
    osceComments = collectOsceComments(records, commentKeys)
    writeOsceCommentsSheet(wb, osceComments, cohortLabel)

    os.makedirs(os.path.dirname(stationPath) or ".", exist_ok=True)
    wb.save(stationPath)

    # =================== ANALYSIS WORKBOOK ===================
    awb = openpyxl.Workbook(); awb.remove(awb.active)
    readMe(awb.create_sheet("Read Me"), f"{cohortLabel} OSCE — Round 1 (BLR & validity)".strip(),
           ["This workbook holds the standard-setting, reliability/validity and assessor-harshness analysis.",
            "Per-station detail sheets are in the separate station workbook.",
            "BLR = Borderline Regression: cut score = checklist % predicted at GR=Borderline.",
            "Assessor Harshness assumes ~random allocation of students to assessors within a station."]
           + ([f"Overall OSCE outcome (see 'OSCE Outcome' sheet): PASS iff counted station failures <= {allowedStationFailures} "
               f"AND average station score% >= average station raw BLR cut%. Perio score counts to the average but not to the failure limit; "
               f"removed stations (excludeFromPassFail) count to neither."] if allowedStationFailures is not None else [])
           + weightsNote + derivedNote + overrideNoteLines)

    # BLR Analysis
    bl = awb.create_sheet("BLR Analysis"); bl.sheet_view.showGridLines = False; rp = 1
    if skippedAnalysis:
        note = "Stations excluded from analysis (no BLR possible): " + "; ".join(
            f"{x['sheet']} ({x['reason']})" for x in skippedAnalysis)
        bl.cell(rp, 1, note).font = Font(name="Arial", size=9, italic=True, color="9C0006"); rp += 2
    firstBlr = True
    for s in analysisSpecs:
        st, ck, cfg, rows = s["st"], s["ck"], s["cfg"], s["rows"]
        b = blr[ck]; grs, scs = b["grs"], b["scs"]
        img, means, corr = buildBlrFigure(s, b, imgDir, borderlineGr)
        if not firstBlr:
            rp += 1   # blank spacer between stations
        top = rp
        # full-width banner heading + separator line
        for c in range(1, 13):
            hc = bl.cell(rp, c)
            hc.fill = PatternFill("solid", fgColor=HEAD)
            hc.border = Border(top=Side(style="medium", color="000000"))
        tc = bl.cell(rp, 1, f"Station {st} — {cfg['name'].split('.')[0]}   (n={len(scs)}, {s['levels']}, borderline GR={borderlineGr})")
        tc.font = Font(name="Arial", size=12, bold=True, color="FFFFFF"); tc.alignment = Alignment(horizontal="left", vertical="center")
        bl.row_dimensions[rp].height = 22
        rp += 2   # banner row + one blank row before the metrics
        firstBlr = False
        # pass/fail override note (drop / passAll / bgm / cut adjust / GR remap)
        if ck in noPassFail or overrideNote.get(ck) or s.get("droppedItems") or s.get("grRemapN"):
            bits = []
            if s.get("droppedItems"):
                bits.append("dropped items " + ", ".join(f"MC{i}" for i in s["droppedItems"]) + " (excluded from scoring)")
            if s.get("grRemapN"):
                for rule in s.get("grRemaps") or []:
                    sc = (f" for assessor {rule['assessor']}" if "assessor" in rule else "") + (f" circuit {rule['circuit']}" if "circuit" in rule else "")
                    bits.append(f"GR remap {rule.get('from')}->{rule.get('to')}{sc} ({s['grRemapN']} rating(s) changed)")
            if overrideNote.get(ck):
                bits.append(overrideNote[ck])
            bl.cell(rp, 1, "OVERRIDE: " + "; ".join(bits) + ".").font = Font(name="Arial", size=10, bold=True, color="C55A11"); rp += 1
            if ck not in noPassFail and passCutPct.get(ck) is not None and not forcePass.get(ck):
                bl.cell(rp, 1, f"    Effective pass cut = {passCutPct[ck]}% (raw BLR cut was {b['cutPct']}%).").font = Font(name="Arial", size=9, color="C55A11"); rp += 1
            rp += 1
        # derived-GR working block (only for stations with no examiner GR, e.g. diagnostics)
        if s.get("grDerived"):
            bnds = (grScoreBands.get(ck) if grScoreBands else None) or GR_SCORE_BANDS.get(ck) or []
            maxLv = 0                                   # max attainable raw label-value total for THIS checklist
            for i in s["items"]:
                _kp, _mx, _lvl, _order = s["scales"][i]
                maxLv += max((GR_LABEL_VALUES.get(str(s["optLabels"].get(k) or k).strip().lower(), 0)
                              for k in _order), default=0)
            bl.cell(rp, 1, "DERIVED GLOBAL RATING — this station had NO examiner GR (unobserved / marked post-task).").font = Font(name="Arial", size=10, bold=True, color="9C0006"); rp += 1
            for t in [
                "GR is derived from the raw checklist label-value TOTAL (a separate scale from Score%). Each answered item adds its option's value:",
                "    Very Good = 4,  Satisfactory = 3,  Borderline = 2,  Unsatisfactory = 0   (independent of the item's level/denominator).",
                f"    Max attainable total for this checklist = {maxLv}  (best available label per item; 2- & 3-level items cap at Satisfactory=3, only 4-level items reach 4).",
                "    That total is mapped to a GR via the examiner-agreed bands below (Score% is scored separately, as mean of per-item fractions x 100).",
            ]:
                bl.cell(rp, 1, t).font = Font(name="Arial", size=9, color="000000"); rp += 1
            for c, h in enumerate(["GR", "GR Label", "Raw total range"], 1):
                cc = bl.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctr; cc.border = box
            rp += 1
            for lo, hi, gr in bnds:
                bl.cell(rp, 1, gr); bl.cell(rp, 2, GR_LABELS[gr]); bl.cell(rp, 3, f"{lo}-{hi}")
                for c in range(1, 4):
                    bl.cell(rp, c).font = bFont; bl.cell(rp, c).border = box; bl.cell(rp, c).alignment = ctr
                gv = bl.cell(rp, 2); gv.fill = PatternFill("solid", fgColor=GR_FILL[gr]); gv.font = Font(name="Arial", size=10, color=GR_FONTC[gr])
                rp += 1
            bl.cell(rp, 1, "Caveat: this GR is a re-banding of the same responses, so the BLR fit below is largely circular — treat the cut as a banded-standard cut, not an independent borderline regression.").font = Font(name="Arial", size=9, italic=True, color="9C0006"); rp += 2
        bmask = grs == borderlineGr
        bmean = scs[bmask].mean() * 100 if bmask.any() else float("nan")
        bsd = scs[bmask].std(ddof=1) * 100 if bmask.sum() > 1 else 0.0
        cutP = b["cutPct"]; m2P = b["mean2sdPct"]
        nfail = countBelow(scs, b["cut"])
        metrics = [
            ("N (submitted)", len(scs), "BLR cut (%)", cutP),
            ("Overall Mean %", round(scs.mean() * 100, 1), "Overall SD %", round(scs.std(ddof=1) * 100, 1)),
            ("Mean - 2SD (%)", m2P, "Cronbach's a", round(cronbachAlpha(rows, s["items"]), 3)),
            ("Borderline N", int(bmask.sum()), "Borderline Mean %", round(bmean, 1)),
            ("Slope (b)", round(b["slope"] * 100, 2), "Intercept (a) %", round(b["intercept"] * 100, 2)),
            ("R^2", round(b["r2"], 3), "p-value", ("%.2e" % b["p"])),
            ("Students < cut", nfail, "Fail rate %", round(nfail / len(scs) * 100, 1) if len(scs) else 0),
        ]
        for c, h in enumerate(["Metric", "Value", "", "Metric", "Value"], 1):
            if h:
                cc = bl.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctr; cc.border = box
        rp += 1
        for m1, v1, m2, v2 in metrics:
            bl.cell(rp, 1, m1).font = Font(name="Arial", size=10, bold=True); bl.cell(rp, 2, v1).font = bFont
            bl.cell(rp, 4, m2).font = Font(name="Arial", size=10, bold=True); bl.cell(rp, 5, v2).font = bFont
            for c in (1, 2, 4, 5):
                bl.cell(rp, c).border = box; bl.cell(rp, c).alignment = ctr if c in (2, 5) else Alignment(horizontal="left")
            rp += 1
        rp += 1
        for c, h in enumerate(["GR", "GR Label", "N", "Mean %", "SD %"], 1):
            cc = bl.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctr; cc.border = box
        rp += 1
        for g in range(5, 0, -1):
            gm = grs == g
            if gm.any():
                bl.cell(rp, 1, g); bl.cell(rp, 2, GR_LABELS[g]); bl.cell(rp, 3, int(gm.sum()))
                bl.cell(rp, 4, round(scs[gm].mean() * 100, 1))
                bl.cell(rp, 5, round(scs[gm].std(ddof=1) * 100, 1) if gm.sum() > 1 else 0.0)
                for c in range(1, 6):
                    bl.cell(rp, c).font = bFont; bl.cell(rp, c).border = box; bl.cell(rp, c).alignment = ctr
                gv = bl.cell(rp, 2); gv.fill = PatternFill("solid", fgColor=GR_FILL[g]); gv.font = Font(name="Arial", size=10, color=GR_FONTC[g])
                rp += 1
        rp += 1
        effCut = passCutPct[ck]                                 # effective pass cut after overrides
        if ck in noPassFail:
            bl.cell(rp, 1, "Students below cut: n/a — station excluded from pass/fail by decision.").font = Font(name="Arial", size=11, bold=True, color="C55A11"); rp += 2
        elif forcePass.get(ck):
            bl.cell(rp, 1, "Students below cut: none — PASS ALL applied by decision.").font = Font(name="Arial", size=11, bold=True, color="C55A11"); rp += 2
        else:
            bl.cell(rp, 1, f"Students below pass cut ({effCut}%)").font = Font(name="Arial", size=11, bold=True, color=HEAD); rp += 1
            for c, h in enumerate(["Student", "Student No", "Assessor", "GR", "GR Label", "Score %", "vs Cut"], 1):
                cc = bl.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctr; cc.border = box
            rp += 1
            below = sorted([r for r in rows if studentFails(ck, r)], key=lambda r: r["score"])
            for r in below:
                vals = [r["student"], r.get("studentNo", ""), r["assessor"], r["gr"], GR_LABELS.get(r["gr"], ""), pct1(r["score"]), round(pct1(r["score"]) - effCut, 1)]
                for c, val in enumerate(vals, 1):
                    cc = bl.cell(rp, c, val); cc.font = bFont; cc.border = box; cc.alignment = Alignment(horizontal="left") if c in (1, 2, 3) else ctr
                rp += 1
            if not below:
                bl.cell(rp, 1, "None"); rp += 1
        xi = XlImage(img); xi.width = 620; xi.height = 430; bl.add_image(xi, f"H{top+2}")
        rp = max(rp, top + 25) + 2
    for col, w in {"A": 20, "B": 22, "C": 8, "D": 15, "E": 12, "F": 11}.items():
        bl.column_dimensions[col].width = w

    # AMEE Guide 49 rigorous station + assessor analysis (osce_metrics.py)
    import osce_metrics
    osce_metrics.buildStationMetricsSheet(awb, analysisSpecs, blr)
    osce_metrics.buildCircuitCutSheet(awb, analysisSpecs, blr, borderlineGr)
    osce_metrics.buildAssessorAnalysisSheet(awb, analysisSpecs, blr, imgDir)

    # Standard Setting
    ss = awb.create_sheet("Standard Setting"); rp = 1
    ss.cell(rp, 1, "Cut scores by standard-setting method").font = Font(name="Arial", size=12, bold=True, color=HEAD); rp += 2
    for c, h in enumerate(["Station", "Checklist", "N", "BLR cut %", "Mean-2SD %", "BGM cut %", "Cohen 0.6xP95 %", "Fixed 50 %", "Fixed 60 %", "APPLIED cut %"], 1):
        cc = ss.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
    rp += 1
    cutstore = {}
    for s in analysisSpecs:
        ck = s["ck"]; b = blr[ck]; grs, scs = b["grs"], b["scs"]
        bgm = scs[grs == borderlineGr].mean() if (grs == borderlineGr).any() else float("nan")
        cohen = 0.6 * np.percentile(scs, 95)
        m2 = b["mean2sd"]
        cutstore[ck] = (scs, {"BLR": b["cut"], "M2SD": m2, "BGM": bgm, "Cohen": cohen})
        applied = ("excluded" if ck in noPassFail else "PASS ALL" if forcePass.get(ck)
                   else (passCutPct[ck] if passCutPct[ck] is not None else "-"))
        line = [s["st"], s["cfg"]["name"].split(".")[0][:40], len(scs), b["cutPct"], round(m2 * 100, 1), round(bgm * 100, 1), round(cohen * 100, 1), 50.0, 60.0, applied]
        for c, v in enumerate(line, 1):
            cc = ss.cell(rp, c, v); cc.font = bFont; cc.border = box; cc.alignment = ctr
        if isinstance(applied, str) or (b["cutPct"] is not None and applied != b["cutPct"]):
            ss.cell(rp, 10).font = Font(name="Arial", size=10, bold=True, color="C55A11")
        rp += 1
    rp += 2
    ss.cell(rp, 1, "Number failing (score < cut) under each method").font = Font(name="Arial", size=12, bold=True, color=HEAD); rp += 2
    for c, h in enumerate(["Station", "Checklist", "N", "Fails BLR", "Fails M-2SD", "Fails BGM", "Fails Cohen", "Fails F50", "Fails F60", "Fails APPLIED"], 1):
        cc = ss.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
    rp += 1
    for s in analysisSpecs:
        ck = s["ck"]; scs, cuts = cutstore[ck]
        nf = lambda cut: countBelow(scs, cut)
        applFails = ("-" if ck in noPassFail else sum(1 for r in s["rows"] if studentFails(ck, r)))
        line = [s["st"], s["cfg"]["name"].split(".")[0][:40], len(scs), nf(cuts["BLR"]), nf(cuts["M2SD"]), nf(cuts["BGM"]), nf(cuts["Cohen"]), nf(0.5), nf(0.6), applFails]
        for c, v in enumerate(line, 1):
            cc = ss.cell(rp, c, v); cc.font = bFont; cc.border = box; cc.alignment = ctr
        ss.cell(rp, 10).font = Font(name="Arial", size=10, bold=True, color="9C0006" if isinstance(applFails, int) and applFails > 0 else "C55A11")
        rp += 1
    rp += 2
    for i, t in enumerate([
        "BLR = Borderline Regression: score predicted at the Borderline grade (defensible, most used for OSCE).",
        "BGM = Borderline Group Method: mean checklist score of students rated exactly Borderline.",
        "Cohen = 0.6 x 95th-percentile score: norm-referenced backup when borderline groups are small.",
        "Mean-2SD = mean minus two SDs of the checklist score (low-outlier threshold).",
        "Fixed 50 / 60 = absolute cut scores.  Fail = checklist score < cut (both rounded to 1 dp)."]):
        ss.cell(rp + i, 1, t).font = Font(name="Arial", size=9, italic=True, color="555555")
    ss.column_dimensions["A"].width = 8; ss.column_dimensions["B"].width = 26
    for c in range(3, 11):
        ss.column_dimensions[get_column_letter(c)].width = 14

    # ---- Assessor Grid (student x station = assessor name; colour = assessor mean %, red harsh -> green lenient) ----
    ag = awb.create_sheet("Assessor Grid"); ag.sheet_view.showGridLines = False
    aMean = {}          # (ck, assessor) -> mean %
    assessorOf = {}     # student -> {ck: assessor}
    for sp in analysisSpecs:
        byA = {}
        for r in sp["rows"]:
            if r["score"] is None:
                continue
            byA.setdefault(r["assessor"], []).append(r["score"] * 100)
            assessorOf.setdefault(r["student"], {})[sp["ck"]] = r["assessor"]
        for a, vs in byA.items():
            aMean[(sp["ck"], a)] = sum(vs) / len(vs)
    allMeans = list(aMean.values())
    vmin, vmax = (min(allMeans), max(allMeans)) if allMeans else (0.0, 100.0)   # fail-safe: no scored stations
    agStudents = sorted(assessorOf, key=lambda x: (x.split()[-1], x))
    AST0 = 3   # first station column (after Student Name, Student No)
    hdr = ["Student Name", "Student No"] + [stationTitle(sp["st"], sp["ck"]) for sp in analysisSpecs]
    ag.append(hdr); styleHeader(ag, len(hdr))
    for st in agStudents:
        ag.append([st, numOf.get(st, "")] +
                  [assessorOf[st].get(sp["ck"], "") for sp in analysisSpecs])
    nrow = ag.max_row; ncol = len(hdr)
    gthin = Side(style="thin", color="D9D9D9")
    gbox = Border(left=gthin, right=gthin, top=gthin, bottom=gthin)
    for ri, st in enumerate(agStudents, start=2):
        c0 = ag.cell(ri, 1); c0.font = bFont; c0.alignment = Alignment(horizontal="left", vertical="center"); c0.border = gbox
        cN = ag.cell(ri, 2); cN.font = bFont; cN.alignment = Alignment(horizontal="left", vertical="center"); cN.border = gbox
        for ci, sp in enumerate(analysisSpecs, start=AST0):
            c = ag.cell(ri, ci); c.font = Font(name="Arial", size=8); c.border = gbox
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            a = assessorOf[st].get(sp["ck"])
            if a and (sp["ck"], a) in aMean:
                t = (aMean[(sp["ck"], a)] - vmin) / (vmax - vmin) if vmax > vmin else 0.5
                c.fill = PatternFill("solid", fgColor=gradientHex(t))
    ag.column_dimensions["A"].width = 24; ag.column_dimensions["B"].width = 12
    for c in range(AST0, ncol + 1):
        ag.column_dimensions[get_column_letter(c)].width = 16
    ag.freeze_panes = f"{get_column_letter(AST0)}2"; ag.auto_filter.ref = f"A1:{get_column_letter(ncol)}{nrow}"
    # legend (top-right)
    lc = ncol + 2
    ag.cell(1, lc, "Colour = assessor's mean % at that station").font = Font(name="Arial", size=9, bold=True, color=HEAD)
    r2 = ag.cell(2, lc, f"Red = {vmin:.1f}%  (harshest)"); r2.fill = PatternFill("solid", fgColor=gradientHex(0.0)); r2.font = Font(name="Arial", size=9)
    r3 = ag.cell(3, lc, f"Yellow = {(vmin+vmax)/2:.1f}%  (mid)"); r3.fill = PatternFill("solid", fgColor=gradientHex(0.5)); r3.font = Font(name="Arial", size=9)
    r4 = ag.cell(4, lc, f"Green = {vmax:.1f}%  (most lenient)"); r4.fill = PatternFill("solid", fgColor=gradientHex(1.0)); r4.font = Font(name="Arial", size=9)
    ag.column_dimensions[get_column_letter(lc)].width = 28
    ag.cell(nrow + 2, 1, "Each cell = the assessor who marked that student at that station; fill is a red->green gradient by the assessor's mean checklist % at that station (across all stations here).").font = Font(name="Arial", size=9, italic=True, color="555555")

    # ---- Student x Station pivot (BLR / Mean-2SD colour coding) ----
    piv = awb.create_sheet("Student x Station", 1)
    piv.sheet_view.showGridLines = False
    colSpecs = analysisSpecs
    m2P = {sp["ck"]: blr[sp["ck"]]["mean2sdPct"] for sp in colSpecs}
    # scoreOf[student][ck] = (pct, status): 0 pass, 1 <cut only, 2 <Mean-2SD only, 3 <both.
    # Pass/fail uses the EFFECTIVE cut; force-pass and excluded stations never flag (status 0).
    scoreOf = {}; students = set()
    for sp in colSpecs:
        ck = sp["ck"]
        # don't flag stations that don't count toward the failure limit (Perio), force-passed, or excluded
        noFlag = ck in noPassFail or forcePass.get(ck) or passCutPct.get(ck) is None or not inFailCount.get(ck)
        cpp, m2 = passCutPct.get(ck), m2P[ck]
        for r in sp["rows"]:
            if r["score"] is None:
                continue
            pp = pct1(r["score"]); students.add(r["student"])
            if noFlag:
                status = 0
            else:
                bBLR = pp < cpp; b2 = (m2 is not None and pp < m2)
                status = 3 if (bBLR and b2) else (1 if bBLR else (2 if b2 else 0))
            scoreOf.setdefault(r["student"], {})[ck] = (pp, status)
    hdr = ["Student Name", "Student No"] + [stationTitle(sp["st"], sp["ck"]) for sp in colSpecs] + ["Mean % (counted)", "Fails", "< M-2SD"]
    piv.append(hdr); styleHeader(piv, len(hdr))
    ST0 = 3   # first station column (after Student Name, Student No)
    def studFailsBLR(st):
        return sum(1 for sp in colSpecs if scoreOf.get(st, {}).get(sp["ck"], (None, 0))[1] in (1, 3))
    def studBelow2(st):
        return sum(1 for sp in colSpecs if scoreOf.get(st, {}).get(sp["ck"], (None, 0))[1] in (2, 3))
    def studMean(st):
        # mean over COUNTED stations only (those contributing to the OSCE total; excludes removed stations)
        vs = [scoreOf[st][sp["ck"]][0] for sp in colSpecs if inTotal.get(sp["ck"]) and sp["ck"] in scoreOf.get(st, {})]
        return sum(vs) / len(vs) if vs else None
    ordered = sorted(students, key=lambda st: (-studFailsBLR(st), -(studMean(st) or 0), st))
    STATUS_FILL = {1: "FF0000", 2: "FFC000", 3: "7030A0"}
    STATUS_FONT = {1: "FFFFFF", 2: "000000", 3: "FFFFFF"}
    for st in ordered:
        row = [st, numOf.get(st, "")]
        for sp in colSpecs:
            cell = scoreOf.get(st, {}).get(sp["ck"]); row.append(cell[0] if cell else "")
        m = studMean(st)
        row += [round(m, 1) if m is not None else "", studFailsBLR(st), studBelow2(st)]
        piv.append(row)
    nrow = piv.max_row; ncol = len(hdr)
    for ri, st in enumerate(ordered, start=2):
        c0 = piv.cell(ri, 1); c0.font = bFont; c0.alignment = Alignment(horizontal="left", vertical="center"); c0.border = box
        cN = piv.cell(ri, 2); cN.font = bFont; cN.alignment = Alignment(horizontal="left", vertical="center"); cN.border = box
        for ci, sp in enumerate(colSpecs, start=ST0):
            c = piv.cell(ri, ci); c.font = bFont; c.border = box; c.alignment = ctr
            cell = scoreOf.get(st, {}).get(sp["ck"])
            if cell:
                c.number_format = "0.0"; stt = cell[1]
                if stt in STATUS_FILL:
                    c.fill = PatternFill("solid", fgColor=STATUS_FILL[stt])
                    c.font = Font(name="Arial", size=10, bold=(stt != 2), color=STATUS_FONT[stt])
            else:
                c.fill = PatternFill("solid", fgColor="F2F2F2")
        mc = piv.cell(ri, ncol - 2); mc.font = bFont; mc.border = box; mc.alignment = ctr; mc.number_format = "0.0"
        fc = piv.cell(ri, ncol - 1); fc.border = box; fc.alignment = ctr; fv = studFailsBLR(st); fc.value = fv
        fc.font = Font(name="Arial", size=10, bold=True, color="9C0006" if fv else "000000")
        if fv:
            fc.fill = PatternFill("solid", fgColor="FFC7CE")
        bc = piv.cell(ri, ncol); bc.border = box; bc.alignment = ctr; bv = studBelow2(st); bc.value = bv
        bc.font = Font(name="Arial", size=10, bold=True, color="7030A0" if bv else "000000")
    trow = nrow + 1
    piv.cell(trow, 1, "Fails / station").font = Font(name="Arial", size=10, bold=True, color=HEAD)
    for ci, sp in enumerate(colSpecs, start=ST0):
        nf = sum(1 for st in students if scoreOf.get(st, {}).get(sp["ck"], (None, 0))[1] in (1, 3))
        cc = piv.cell(trow, ci, nf); cc.font = Font(name="Arial", size=10, bold=True); cc.alignment = ctr; cc.border = box
    piv.cell(trow, ncol - 1, sum(studFailsBLR(st) for st in students)).font = Font(name="Arial", size=10, bold=True)
    piv.cell(trow, ncol - 1).alignment = ctr; piv.cell(trow, ncol - 1).border = box
    piv.column_dimensions["A"].width = 24; piv.column_dimensions["B"].width = 12
    for c in range(ST0, ncol + 1):
        piv.column_dimensions[get_column_letter(c)].width = 10
    piv.freeze_panes = f"{get_column_letter(ST0)}2"; piv.auto_filter.ref = f"A1:{get_column_letter(ncol)}{nrow}"
    # legend (top-right of the table)
    lc0 = ncol + 2
    piv.cell(1, lc0, "Legend").font = Font(name="Arial", size=10, bold=True, color=HEAD)
    for i, (stt, lab) in enumerate([(1, "Below pass cut"), (2, "Below Mean-2SD"), (3, "Below both"), (None, "Not attempted")], start=2):
        sw = piv.cell(i, lc0); sw.fill = PatternFill("solid", fgColor=(STATUS_FILL[stt] if stt else "F2F2F2")); sw.border = box
        lb = piv.cell(i, lc0 + 1, lab); lb.font = Font(name="Arial", size=9); lb.alignment = Alignment(horizontal="left", vertical="center")
    piv.column_dimensions[get_column_letter(lc0)].width = 5
    piv.column_dimensions[get_column_letter(lc0 + 1)].width = 18
    # average cutoff of the stations actually used (counted toward the total), below the legend.
    # Force-passed stations have no real cut, so for AVERAGING they use a pseudo cut = lowest student score - 1.
    minScorePct = {}
    for sp in colSpecs:
        vs = [pct1(r["score"]) for r in sp["rows"] if r["score"] is not None]
        if vs:
            minScorePct[sp["ck"]] = min(vs)
    def appliedCutForAvg(ck):
        if forcePass.get(ck):
            return (minScorePct[ck] - 1) if ck in minScorePct else None
        return passCutPct.get(ck)
    countedCks = [sp["ck"] for sp in colSpecs if inTotal.get(sp["ck"])]
    appliedVals = [v for ck in countedCks if (v := appliedCutForAvg(ck)) is not None]
    rawVals = [blr[ck]["cutPct"] for ck in countedCks if blr[ck].get("cutPct") is not None]
    nForce = sum(1 for ck in countedCks if forcePass.get(ck) and ck in minScorePct)
    lr = 6
    if appliedVals:
        piv.cell(lr, lc0, f"Avg applied cut ({len(appliedVals)} counted stations): {sum(appliedVals)/len(appliedVals):.1f}%").font = Font(name="Arial", size=9, bold=True, color=HEAD); lr += 1
        if nForce:
            piv.cell(lr, lc0, f"    ({nForce} force-passed station(s) use pseudo cut = lowest score - 1)").font = Font(name="Arial", size=8, italic=True, color="555555"); lr += 1
    if rawVals:
        piv.cell(lr, lc0, f"Avg raw BLR cut ({len(rawVals)} counted stations): {sum(rawVals)/len(rawVals):.1f}%").font = Font(name="Arial", size=9, color="555555"); lr += 1
    note = trow + 2
    def cutDisp(ck):
        if ck in noPassFail: return "excl"
        if forcePass.get(ck):
            return f"PASS(~{minScorePct[ck] - 1:.1f})" if ck in minScorePct else "PASS"
        return passCutPct.get(ck)
    piv.cell(note, 1, "Colours: red=below pass cut; orange=below Mean-2SD; purple=below both; grey=not attempted. Compared at 1 dp. Force-passed / excluded stations are never flagged.").font = Font(name="Arial", size=9, italic=True, color="555555")
    piv.cell(note + 1, 1, "Applied pass cut per station (%): " + "  ".join(f"{stationTitle(sp['st'], sp['ck'])}={cutDisp(sp['ck'])}" for sp in colSpecs)).font = Font(name="Arial", size=9, italic=True, color="555555")
    piv.cell(note + 2, 1, "Mean-2SD per station (%): " + "  ".join(f"{stationTitle(sp['st'], sp['ck'])}={m2P[sp['ck']]}" for sp in colSpecs)).font = Font(name="Arial", size=9, italic=True, color="555555")

    # ---- OSCE Outcome (overall pass/fail across stations) --------------------
    # Rule (when allowedStationFailures is set): a student PASSES iff
    #   (a) counted station failures <= allowedStationFailures, AND
    #   (b) AVERAGE station score% >= AVERAGE station RAW BLR cut% over counting stations.
    # (Averaging vs summing gives the identical pass/fail since both divide by the same N;
    #  means are just easier to read on a 0-100 scale.)
    # inFailCount / inTotal (set above) decide each station's membership; excluded stations
    # (excludeFromPassFail) and Perio (countsToFailLimit=False) are handled there.
    outcome = {}
    if allowedStationFailures is not None:
        allowed = allowedStationFailures
        srow = {}                                          # student -> {ck: row}
        for s in specs:
            for r in s["rows"]:
                srow.setdefault(r["student"], {})[s["ck"]] = r
        for st, byck in srow.items():
            cf = sum(1 for ck, r in byck.items() if inFailCount.get(ck) and studentFails(ck, r))
            sScore = sCut = 0.0; nstn = 0
            for ck, r in byck.items():
                if inTotal.get(ck) and r["score"] is not None and blr[ck].get("cutPct") is not None:
                    sScore += pct1(r["score"]); sCut += blr[ck]["cutPct"]; nstn += 1
            avgScore = (sScore / nstn) if nstn else 0.0
            avgCut = (sCut / nstn) if nstn else 0.0
            failsOk, totalOk = (cf <= allowed), (avgScore >= avgCut)
            reason = "PASS" if (failsOk and totalOk) else " & ".join(
                ([] if failsOk else [f">{allowed} fails"]) + ([] if totalOk else ["avg<cut"]))
            outcome[st] = dict(cf=cf, avg=avgScore, tScore=round(avgScore, 1), tCut=round(avgCut, 1),
                               margin=round(avgScore - avgCut, 1), failsOk=failsOk, totalOk=totalOk,
                               result=("PASS" if (failsOk and totalOk) else "FAIL"), reason=reason, nstn=nstn)

        # Final-score scalings (pluggable) -> one /100 column per method (see resolveFinalScoreMethods).
        # Scalings are cohort-level funcs f(students, ctx)->{st:mark}; per-station methods need per-station data.
        scMethods = resolveFinalScoreMethods(finalScoreMethods)
        scHeaders = [hd for hd, _ in scMethods]
        totalCks = [s["ck"] for s in specs if inTotal.get(s["ck"]) and blr[s["ck"]].get("cutPct") is not None]
        stnMean, stnSD = {}, {}                                 # cohort per-station mean/SD (for per-station scalings)
        for s in specs:
            if s["ck"] in totalCks:
                vs = [pct1(r["score"]) for r in s["rows"] if r["score"] is not None]
                stnMean[s["ck"]] = (sum(vs) / len(vs)) if vs else 0.0
                stnSD[s["ck"]] = (statistics.stdev(vs) if len(vs) > 1 else 0.0)
        studentsData = {}                                      # st -> {"raw", "stn":[(score,cut,mean,sd)], "cks":[ck]}
        for st, byck in srow.items():
            cksOrdered = [ck for ck in totalCks if ck in byck and byck[ck]["score"] is not None]
            stn = [(pct1(byck[ck]["score"]), blr[ck]["cutPct"], stnMean[ck], stnSD[ck]) for ck in cksOrdered]
            studentsData[st] = {"raw": outcome[st]["avg"], "stn": stn, "cks": cksOrdered}
        rawAvgs = [outcome[st]["avg"] for st in outcome]
        cutVals = [blr[ck]["cutPct"] for ck in totalCks]
        ctx = {"meanCut": (sum(cutVals) / len(cutVals)) if cutVals else 0.0,
               "grandMean": (sum(rawAvgs) / len(rawAvgs)) if rawAvgs else 0.0,
               "rawSD": (statistics.stdev(rawAvgs) if len(rawAvgs) > 1 else 0.0),
               "nStn": len(cutVals),
               "stnTitleByCk": {s["ck"]: stationTitle(s["st"], s["ck"]) for s in specs}}
        colVals = {hd: fn(studentsData, ctx) for hd, fn in scMethods}   # {header: {st: mark}}
        for st in outcome:
            outcome[st]["finals"] = [(hd, round(colVals[hd].get(st, 0.0), 1)) for hd, _ in scMethods]

        oc = awb.create_sheet("OSCE Outcome", 1); oc.sheet_view.showGridLines = False; rp = 1
        oc.cell(rp, 1, f"{cohortLabel} OSCE — Overall Outcome").font = Font(name="Arial", size=13, bold=True, color=HEAD); rp += 1
        failCk = [stationTitle(s["st"], s["ck"]) for s in specs if inFailCount.get(s["ck"])]
        totCk = [stationTitle(s["st"], s["ck"]) for s in specs if inTotal.get(s["ck"])]
        exclCk = [stationTitle(s["st"], s["ck"]) for s in specs if s["ck"] in noPassFail]
        noCntCk = [stationTitle(s["st"], s["ck"]) for s in specs if s["ck"] not in noPassFail and not inFailCount.get(s["ck"])]
        for t in [
            f"PASS iff (counted station failures <= {allowed})  AND  (average station score% >= average station RAW BLR cut%).",
            f"Stations counting toward the failure limit ({len(failCk)}): perio and removed stations excluded.",
            (f"Excluded from OSCE entirely: {', '.join(exclCk)}." if exclCk else ""),
            (f"Score counts to total but NOT to the failure limit: {', '.join(noCntCk)}." if noCntCk else ""),
            f"Average score / average cut taken over {len(totCk)} counting stations (raw BLR cut per station).",
            (f"Final-score /100 columns: {', '.join(scHeaders)}.  Scaling constants: meanCut={ctx['meanCut']:.1f}%, "
             f"cohort mean={ctx['grandMean']:.1f}%, SD={ctx['rawSD']:.1f}. Cut-anchored: cut->50, cohort mean preserved."
             if len(scHeaders) > 1 or scHeaders != ["Avg % (raw)"] else ""),
        ]:
            if t:
                oc.cell(rp, 1, t).font = Font(name="Arial", size=9, italic=True, color="555555"); rp += 1
        rp += 1
        hdr = ["Student Name", "Student No", "Counted Fails", f"Allowed", "Fails OK?",
               "Avg Score %", "Avg Cut %", "Margin", "Avg>=Cut?", "OSCE Result", "Reason if FAIL"] + scHeaders
        for c, h in enumerate(hdr, 1):
            cc = oc.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctrW; cc.border = box
        hrow = rp; rp += 1
        ordered = sorted(outcome, key=lambda st: (outcome[st]["result"] == "PASS", outcome[st]["margin"], -outcome[st]["cf"]))
        GREEN, RED = "C6EFCE", "FFC7CE"; GREENF, REDF = "006100", "9C0006"
        for st in ordered:
            o = outcome[st]
            vals = [st, numOf.get(st, ""), o["cf"], allowed, "YES" if o["failsOk"] else "NO",
                    o["tScore"], o["tCut"], o["margin"], "YES" if o["totalOk"] else "NO",
                    o["result"], "" if o["result"] == "PASS" else o["reason"]] + [v for _, v in o["finals"]]
            for c, v in enumerate(vals, 1):
                cc = oc.cell(rp, c, v); cc.font = bFont; cc.border = box
                cc.alignment = Alignment(horizontal="left", vertical="center") if c in (1, 2, 11) else ctr
                if c > 11: cc.number_format = "0.0"
            if not o["failsOk"]:
                cc = oc.cell(rp, 3); cc.fill = PatternFill("solid", fgColor=RED); cc.font = Font(name="Arial", size=10, bold=True, color=REDF)
            if not o["totalOk"]:
                cc = oc.cell(rp, 8); cc.fill = PatternFill("solid", fgColor=RED); cc.font = Font(name="Arial", size=10, bold=True, color=REDF)
            rc = oc.cell(rp, 10); isPass = o["result"] == "PASS"
            rc.fill = PatternFill("solid", fgColor=GREEN if isPass else RED)
            rc.font = Font(name="Arial", size=10, bold=True, color=GREENF if isPass else REDF)
            rp += 1
        nFail = sum(1 for st in outcome if outcome[st]["result"] == "FAIL")
        oc.cell(rp + 1, 1, f"Overall: {len(outcome) - nFail} PASS, {nFail} FAIL of {len(outcome)} students.").font = Font(name="Arial", size=10, bold=True, color=HEAD)
        rp += 3
        # perStationWeighted station weights (100/cut), printed when that method is used
        if "perStationWeighted" in scHeaders or "Wtd 100/cut" in scHeaders:
            wrows = [(stationTitle(s["st"], s["ck"]), blr[s["ck"]]["cutPct"]) for s in specs
                     if s["ck"] in totalCks and blr[s["ck"]].get("cutPct")]
            wsum = sum(100.0 / c for _, c in wrows) or 1.0
            oc.cell(rp, 1, "perStationWeighted — station weights (weight = 100 / raw BLR cut):").font = Font(name="Arial", size=10, bold=True, color=HEAD); rp += 1
            for c, h in enumerate(["Station", "Cut %", "Weight (100/cut)", "Weight %"], 1):
                cc = oc.cell(rp, c, h); cc.font = hFont; cc.fill = hFill; cc.alignment = ctr; cc.border = box
            rp += 1
            for nm, ct in wrows:
                w = 100.0 / ct
                for c, v in enumerate([nm, round(ct, 1), round(w, 3), round(w / wsum * 100, 1)], 1):
                    cc = oc.cell(rp, c, v); cc.font = bFont; cc.border = box
                    cc.alignment = Alignment(horizontal="left", vertical="center") if c == 1 else ctr
                rp += 1
            oc.cell(rp, 1, "Higher weight = harder station (lower cut). Mark = sum(score x weight) / sum(weights).").font = Font(name="Arial", size=9, italic=True, color="555555")
        oc.column_dimensions["A"].width = 24; oc.column_dimensions["B"].width = 12
        for c in range(3, len(hdr) + 1):
            oc.column_dimensions[get_column_letter(c)].width = 13
        oc.column_dimensions[get_column_letter(11)].width = 18   # Reason if FAIL
        for c in range(12, len(hdr) + 1):                        # final-score /100 columns
            oc.column_dimensions[get_column_letter(c)].width = 16
        oc.freeze_panes = f"A{hrow + 1}"; oc.auto_filter.ref = f"A{hrow}:{get_column_letter(len(hdr))}{hrow + len(ordered)}"

    os.makedirs(os.path.dirname(analysisPath) or ".", exist_ok=True)
    awb.save(analysisPath)

    return {
        "stations": [{"station": s["st"], "checklist": s["ck"], "sheet": stationTitle(s["st"], s["ck"]),
                      "levels": s["levels"], "n": len(s["rows"]),
                      "blrCut": (blr[s["ck"]]["cutPct"] if blr[s["ck"]].get("valid") else None)} for s in specs],
        "skippedAnalysis": skippedAnalysis,
        "osceOutcome": ({"allowed": allowedStationFailures,
                         "pass": sum(1 for st in outcome if outcome[st]["result"] == "PASS"),
                         "fail": sum(1 for st in outcome if outcome[st]["result"] == "FAIL"),
                         "n": len(outcome)} if allowedStationFailures is not None else None),
        "recordsUsed": len(records),
        "osceComments": len(osceComments),
        "rtpPresent": hasRtp, "prebuiltForms": prebuiltForms,
        "stationWorkbook": stationPath, "analysisWorkbook": analysisPath, "imgDir": imgDir,
        "ignored": sorted(IGNORE_STUDENT_NUMBERS if ignoreStudentNumbers is None else ignoreStudentNumbers),
    }


# ══════════════════════════════════════════════════════════════════════════════
# STUDENT OSCE FEEDBACK PDFs  (added 2026-10-01)
# ──────────────────────────────────────────────────────────────────────────────
# Per-student PDF built to the "OSCE/OSCE Feedback Template.xlsx" layout (navy header + UniMelb
# logo, light-green panel), plus a STATION CUTOFF field carried over from the 2025 DDS2 reports.
# Inputs:
#   stationPath  : cleaned station workbook, e.g. OSCE/DDS4/DDS4 OSCE (2).xlsx
#                  (one sheet per checklist: Student Name, Student No, Score (%), GR, Feedback,
#                   Borderline/Fail Info)
#   analysisPath : BLR workbook, e.g. OSCE/DDS4/DDS4 BLR & Validity.xlsx — 'Standard Setting'
#                  supplies the APPLIED cut % (numeric / 'PASS ALL' / 'excluded').
# Station FAIL = round(score, 1) < applied cut (same rule as countBelow / pct1); PASS ALL -> PASS.
# 2 SDBM = score < cohort mean - 2 SD (sample SD over everyone on that sheet).
# Cohort average / range / SD are taken over EVERY student on the sheet, not just the reported ones.
# Public entry point: buildOsceFeedbackReports(...)
# ══════════════════════════════════════════════════════════════════════════════
import io as _io
import zipfile as _zipfile
from xml.sax.saxutils import escape as _xmlEscape

# Sheet title (in the station workbook) -> display metadata. Order = order in the PDF.
# Edit here when stations change; any sheet NOT listed is skipped (and reported).
DDS4_FEEDBACK_STATION_META = OrderedDict([
    ("S1 Ortho",         {"label": "1.1",  "domain": "Orthodontics",             "type": "Procedural",   "topic": "Assessment"}),
    ("S2 therapeutics",  {"label": "1.2",  "domain": "Therapeutics",             "type": "Procedural",   "topic": "Script Writing"}),
    ("S5 removable-pr",  {"label": "1.5",  "domain": "Removable Prosthodontics", "type": "Procedural",   "topic": "Design Analysis"}),
    ("S7 special-need",  {"label": "1.7",  "domain": "Special Needs Dentistry",  "type": "Consultation", "topic": "Medical History"}),
    ("S8 oral-surgery",  {"label": "1.8",  "domain": "Oral Surgery",             "type": "Consultation", "topic": "Extractions"}),
    ("S10 health-promo", {"label": "1.10", "domain": "Health Promotion",         "type": "Consultation", "topic": "Dietary Advice"}),
    ("S11 paediactrics", {"label": "1.11", "domain": "Paediatrics",              "type": "Procedural",   "topic": "Hand Hygiene & Separators"}),
    ("S2 sharps-manag",  {"label": "2.2",  "domain": "General Dentistry",        "type": "Procedural",   "topic": "Sharps Management"}),
    ("S1 endodontics",   {"label": "2.4",  "domain": "Endodontics",              "type": "Procedural",   "topic": "Trauma"}),
    ("S1+5 OralMed",     {"label": "2.5",  "domain": "Oral Medicine",            "type": "Consultation", "topic": "Ulcerations"}),
    ("S7 OrthoPaed",     {"label": "2.7",  "domain": "Paediatrics/Orthodontics", "type": "Consultation", "topic": "Impacted Teeth"}),
    ("S8 medical-emer",  {"label": "2.8",  "domain": "General Dentistry",        "type": "Procedural",   "topic": "Medical Emergencies"}),
    ("S10 extra-oral-e", {"label": "2.10", "domain": "General Dentistry",        "type": "Procedural",   "topic": "Hand Hygiene & Examination"}),
    ("S11 Perio",        {"label": "2.11", "domain": "Periodontics",             "type": "Procedural",   "topic": "Hand Hygiene & Subgingival Scaling", "counted": False}),
])
# Sheets never reported (removed from the OSCE by decision)
FEEDBACK_EXCLUDE_SHEETS = {"S1 diagnostics", "S4 fixed-prosth"}

# Station metadata workbook (preferred over the dict above when it exists): one row per station sheet.
STATION_META_PATH = "OSCE/OSCE Station Metadata.xlsx"
STATION_META_SHEET = "Stations"
STATION_META_COLUMNS = ["Cohort", "Year", "Report Order", "Station", "Sheet Name", "Domain",
                        "Station Type", "Topic", "Include", "Counts To Outcome", "Notes"]


def loadStationMeta(metaPath=STATION_META_PATH, cohort="DDS4", year=None, sheetName=STATION_META_SHEET):
    """
    Station metadata workbook -> (meta, excluded):
      meta     : OrderedDict sheetName -> {"label", "domain", "type", "topic"} for Include=Y rows, by Report Order
      excluded : set of sheet names with Include=N (never reported)
    Rows are filtered to `cohort` (and `year` when given). 'Sheet Name' must match the station workbook tab.
    """
    wb = openpyxl.load_workbook(metaPath, data_only=True, read_only=True)
    try:
        rows = list(wb[sheetName].iter_rows(values_only=True))
    finally:
        wb.close()
    hdr = [str(v).strip() if v is not None else "" for v in rows[0]]
    missing = [c for c in ("Cohort", "Station", "Sheet Name", "Domain", "Station Type", "Topic") if c not in hdr]
    if missing:
        raise ValueError(f"{metaPath} [{sheetName}] is missing columns {missing}")
    recs = [dict(zip(hdr, r)) for r in rows[1:] if r and any(v not in (None, "") for v in r)]
    recs = [r for r in recs if str(r.get("Cohort") or "").strip().upper() == str(cohort).upper()
            and (year is None or r.get("Year") in (None, "") or int(r["Year"]) == int(year))]
    if not recs:
        raise ValueError(f"No rows for cohort={cohort} year={year} in {metaPath}")
    recs.sort(key=lambda r: (float(r["Report Order"]) if r.get("Report Order") not in (None, "") else 1e9))
    meta, excluded = OrderedDict(), set()
    for r in recs:
        sheet = str(r["Sheet Name"]).strip()
        if str(r.get("Include") or "Y").strip().upper().startswith("N"):
            excluded.add(sheet)
            continue
        meta[sheet] = {"label": str(r["Station"]).strip(), "domain": str(r.get("Domain") or "").strip(),
                       "type": str(r.get("Station Type") or "").strip(), "topic": str(r.get("Topic") or "").strip(),
                       # 'Counts To Outcome' = N -> outcome/cutoff shown as N/A, not in pass/fail counts (blank = Y)
                       "counted": not str(r.get("Counts To Outcome") or "Y").strip().upper().startswith("N")}
    return meta, excluded


def writeStationMetaWorkbook(metaPath=STATION_META_PATH, cohort="DDS4", year=2026, stationMeta=None,
                             excludeSheets=None, overwrite=False):
    """Seed the metadata workbook from a dict (default DDS4_FEEDBACK_STATION_META); excluded sheets get Include=N."""
    if os.path.exists(metaPath) and not overwrite:
        raise FileExistsError(f"{metaPath} exists (pass overwrite=True to replace)")
    meta = DDS4_FEEDBACK_STATION_META if stationMeta is None else stationMeta
    excl = FEEDBACK_EXCLUDE_SHEETS if excludeSheets is None else set(excludeSheets)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = STATION_META_SHEET
    ws.append(STATION_META_COLUMNS)
    for i, (sheet, m) in enumerate(meta.items(), 1):
        ws.append([cohort, year, i, m["label"], sheet, m["domain"], m["type"], m["topic"], "Y",
                   "Y" if m.get("counted", True) else "N", ""])
    for sheet in sorted(excl):
        ws.append([cohort, year, None, "", sheet, "", "", "", "N", "N", "Removed from the OSCE by decision"])
    head = PatternFill("solid", fgColor=HEAD)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = head
        c.alignment = Alignment(horizontal="center", vertical="center")
    for col, w in zip("ABCDEFGHIJK", [9, 7, 13, 9, 18, 26, 14, 34, 9, 18, 34]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
    readme = wb.create_sheet("Read Me")
    for line in ["OSCE station metadata used by osce_utils.buildOsceFeedbackReports (student feedback PDFs).",
                 "One row per checklist sheet in the cleaned station workbook (e.g. OSCE/DDS4/DDS4 OSCE (2).xlsx).",
                 "Sheet Name must match the station workbook tab exactly; Station is the label printed on the PDF.",
                 "Report Order sets the order of station blocks; Include = N drops a station from the reports.",
                 "Add new cohorts/years as extra rows; the loader filters on Cohort (+ Year when given)."]:
        readme.append([line])
    readme.column_dimensions["A"].width = 110
    os.makedirs(os.path.dirname(metaPath) or ".", exist_ok=True)
    wb.save(metaPath)
    return metaPath


FB_NAVY = "#000F46"        # template header / bars
FB_PANEL = "#D8E4BC"       # template light-green panel
FB_FAIL = "#C00000"
FB_LOGO_MEDIA = "xl/media/image1.png"   # UniMelb logo inside the template workbook


def readStationSheet(ws, feedbackCol="Feedback", bfCol="Borderline/Fail Info"):
    """One station sheet -> list of {name, studentNo, score, gr, feedback, bfInfo} (rows with a Score only).
    feedbackCol : column read as the examiner comment (e.g. "Proofread comments"); must exist on the sheet
    bfCol       : column read as Borderline/Fail Info (None = not read)
    Rows whose Score (%) or Student No is not numeric (e.g. notes like 'Pass = 43.9' written below the
    table) are skipped and listed in a printed warning, so they never count as data."""
    hdr = [(str(c.value).strip() if c.value is not None else "") for c in ws[1]]
    col = {h: i for i, h in enumerate(hdr)}
    need = ["Student Name", "Student No", "Score (%)"]
    if any(h not in col for h in need):
        raise ValueError(f"Sheet '{ws.title}' is missing one of {need}")
    if feedbackCol and feedbackCol != "Feedback" and feedbackCol not in col:
        raise ValueError(f"Sheet '{ws.title}' has no '{feedbackCol}' column")
    def toNum(v):                                            # numeric value or None (text notes -> None)
        try:
            return float(str(v).strip().rstrip("%")) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    out, skippedRows = [], []
    for rowIdx, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        sc = r[col["Score (%)"]]
        if sc is None or str(sc).strip() == "":
            continue
        scNum, snNum = toNum(sc), toNum(r[col["Student No"]])
        if scNum is None or snNum is None:                    # note / footer row, not a student
            skippedRows.append(rowIdx)
            continue
        out.append({
            "name": str(r[col["Student Name"]] or "").strip(),
            "studentNo": str(int(snNum)),
            "score": scNum,
            "gr": r[col["GR"]] if "GR" in col else None,
            "feedback": str(r[col[feedbackCol]] or "").strip() if feedbackCol in col else "",
            "bfInfo": str(r[col[bfCol]] or "").strip() if bfCol and bfCol in col else "",
        })
    if skippedRows:
        print(f"[{ws.title}] ignored {len(skippedRows)} non-data row(s) (non-numeric Score/Student No): rows {skippedRows}")
    return out


def loadFeedbackStations(stationPath, stationMeta=None, excludeSheets=None, feedbackCol="Feedback",
                         bfCol="Borderline/Fail Info"):
    """
    Read the cleaned station workbook. Returns (stations, skipped):
      stations : OrderedDict sheetTitle -> {"meta": {...}, "rows": [...]}, in stationMeta order
      skipped  : sheet titles present but not reported (excluded or missing from stationMeta)
    """
    meta = DDS4_FEEDBACK_STATION_META if stationMeta is None else stationMeta
    excl = FEEDBACK_EXCLUDE_SHEETS if excludeSheets is None else set(excludeSheets)
    wb = openpyxl.load_workbook(stationPath, data_only=True, read_only=True)
    try:
        present = {ws.title: ws for ws in wb.worksheets}
        stations = OrderedDict()
        for title, m in meta.items():
            if title in excl:
                continue
            if title not in present:
                raise KeyError(f"Station sheet '{title}' (Station {m.get('label')}) not found in {stationPath}")
            stations[title] = {"meta": m, "rows": readStationSheet(present[title], feedbackCol=feedbackCol, bfCol=bfCol)}
        skipped = []
        for t, ws in present.items():
            if t in stations:
                continue
            hdr = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            if "Score (%)" in [str(v).strip() for v in hdr if v is not None]:
                skipped.append(t)          # a station sheet that is not reported
    finally:
        wb.close()
    return stations, skipped


def loadAnalysisScores(analysisPath):
    """BLR workbook 'Student x Station' -> {sheetTitle: {studentNo: score %}} (station columns only)."""
    wb = openpyxl.load_workbook(analysisPath, data_only=True, read_only=True)
    try:
        rows = list(wb["Student x Station"].iter_rows(values_only=True))
    finally:
        wb.close()
    hdr = [str(v).strip() if v is not None else "" for v in rows[0]]
    snCol = hdr.index("Student No")
    stCols = {i: h for i, h in enumerate(hdr) if re.match(r"^S[\d+]+ ", h)}
    out = {h: {} for h in stCols.values()}
    for r in rows[1:]:
        if not r or r[snCol] in (None, ""):
            continue
        sn = str(int(float(r[snCol])))
        for i, h in stCols.items():
            if isinstance(r[i], (int, float)):
                out[h][sn] = float(r[i])
    return out


def loadOutcomeMarks(analysisPath, markColumn="Per-stn cut /100", sheetName="OSCE Outcome"):
    """BLR workbook 'OSCE Outcome' -> {studentNo: mark} from `markColumn` (e.g. "Per-stn cut /100", "Avg % (raw)")."""
    wb = openpyxl.load_workbook(analysisPath, data_only=True, read_only=True)
    try:
        rows = list(wb[sheetName].iter_rows(values_only=True))
    finally:
        wb.close()
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "Student Name")
    hdr = [str(v).strip() if v is not None else "" for v in rows[hi]]
    if markColumn not in hdr:
        raise ValueError(f"'{markColumn}' not in {sheetName} columns {[h for h in hdr if h]}")
    sc, mc = hdr.index("Student No"), hdr.index(markColumn)
    return {str(int(float(r[sc]))): float(r[mc]) for r in rows[hi + 1:]
            if r and r[sc] not in (None, "") and isinstance(r[mc], (int, float))}


def applyAnalysisScores(stations, analysisScores):
    """Replace each station row's score with the analysis-workbook score (same student number).
    Returns {"changed": n, "missing": [(sheet, studentNo, name)]}; rows with no analysis score are dropped."""
    changed, missing = 0, []
    for title, st in stations.items():
        col = analysisScores.get(title)
        if col is None:
            raise KeyError(f"Station '{title}' not in the analysis workbook 'Student x Station'")
        keep = []
        for r in st["rows"]:
            v = col.get(r["studentNo"])
            if v is None:
                missing.append((title, r["studentNo"], r["name"]))
                continue
            changed += abs(v - r["score"]) > 1e-9
            r["score"] = v
            keep.append(r)
        st["rows"] = keep
    return {"changed": changed, "missing": missing}


def loadAppliedCuts(analysisPath):
    """
    BLR workbook -> {sheetTitle: {"cutPct": float|None, "passAll": bool, "excluded": bool, "mean2sdPct": float|None}}.
    'Standard Setting' rows are in the same order as the station columns of 'Student x Station' (both are
    written from the same spec list by buildOsceWorkbook); the station number on each row is cross-checked.
    """
    wb = openpyxl.load_workbook(analysisPath, data_only=True, read_only=True)
    try:
        sxs = list(wb["Student x Station"].iter_rows(min_row=1, max_row=1, values_only=True))[0]
        titles = [str(v).strip() for v in sxs[2:]
                  if v not in (None, "") and re.match(r"^S[\d+]+ ", str(v).strip())]   # station columns only
        ssRows, inTable = [], False
        for r in wb["Standard Setting"].iter_rows(values_only=True):
            if r and r[0] == "Station" and r[1] == "Checklist" and not inTable and not ssRows:
                hdr = [str(v).strip() if v is not None else "" for v in r]
                inTable = True
                continue
            if inTable:
                if r is None or r[0] in (None, "") or r[0] == "Station":
                    break
                ssRows.append(dict(zip(hdr, r)))
    finally:
        wb.close()
    if len(ssRows) != len(titles):
        raise ValueError(f"Standard Setting has {len(ssRows)} rows but Student x Station has {len(titles)} stations")
    cuts = {}
    for title, row in zip(titles, ssRows):
        stPrefix = title.split(" ", 1)[0].lstrip("S")
        if str(row["Station"]).strip() != stPrefix:
            raise ValueError(f"Station mismatch aligning '{title}' with Standard Setting row {row['Station']} {row['Checklist']}")
        ap = row.get("APPLIED cut %")
        apS = str(ap).strip().upper() if ap is not None else ""
        m2 = row.get("Mean-2SD %")
        cuts[title] = {
            "checklist": str(row["Checklist"]).strip(),
            "cutPct": float(ap) if isinstance(ap, (int, float)) else None,
            "passAll": apS == "PASS ALL",
            "excluded": apS == "EXCLUDED",
            "mean2sdPct": float(m2) if isinstance(m2, (int, float)) else None,
        }
    return cuts


def computeFeedbackStats(stations, cuts, passAllCutOffset=1.0, notCountedSheets=None):
    """
    Cohort stats per station + per-student results.
    Returns (stStats, students, examAvg):
      stStats  : sheet -> {n, mean, sd, min, max, sdbmPct, cutPct, passAll, displayCutPct}
                 displayCutPct = printed cutoff; for PASS ALL stations = lowest cohort score - passAllCutOffset
                 (so every student is at/above it, consistent with the forced PASS)
      notCountedSheets : stations whose pass/fail is NOT counted (also meta "counted": False) -> outcome "N/A",
                 excluded from nPass / nFail (and so from the overall outcome); score + 2 SDBM still shown
      students : studentNo -> {"name", "results": {sheet: {score, outcome, sdbm, feedback, bfInfo}},
                               "avg", "nPass", "nFail", "nSdbm"}
      examAvg  : cohort mean of each student's average station score (over the reported stations)
    """
    stStats, students = OrderedDict(), {}
    notCounted = set(notCountedSheets or []) | {t for t, st in stations.items() if not st["meta"].get("counted", True)}
    for title, st in stations.items():
        cut = cuts.get(title)
        if cut is None:
            raise KeyError(f"No applied cut for '{title}' in the BLR workbook")
        scs = [r["score"] for r in st["rows"]]
        m = statistics.mean(scs)
        sd = statistics.stdev(scs) if len(scs) > 1 else 0.0
        sdbm = m - 2 * sd
        stStats[title] = {"n": len(scs), "mean": m, "sd": sd, "min": min(scs), "max": max(scs),
                          "sdbmPct": sdbm, "cutPct": cut["cutPct"], "passAll": cut["passAll"],
                          "displayCutPct": (min(scs) - passAllCutOffset) if cut["passAll"] else cut["cutPct"],
                          "counted": title not in notCounted}
        for r in st["rows"]:
            if title in notCounted:
                outcome = "N/A"
            elif cut["passAll"] or cut["cutPct"] is None:
                outcome = "PASS"
            else:
                outcome = "FAIL" if round(r["score"], 1) < cut["cutPct"] else "PASS"
            s = students.setdefault(r["studentNo"], {"name": r["name"], "results": OrderedDict()})
            s["results"][title] = {"score": r["score"], "outcome": outcome, "sdbm": r["score"] < sdbm,
                                   "feedback": r["feedback"], "bfInfo": r["bfInfo"]}
    for s in students.values():
        res = s["results"].values()
        s["avg"] = statistics.mean(x["score"] for x in res)
        s["nPass"] = sum(x["outcome"] == "PASS" for x in res)
        s["nFail"] = sum(x["outcome"] == "FAIL" for x in res)
        s["nSdbm"] = sum(x["sdbm"] for x in res)
        s["complete"] = len(s["results"]) == len(stations)
    full = [s["avg"] for s in students.values() if s["complete"]]
    examAvg = statistics.mean(full) if full else None
    return stStats, students, examAvg


def loadTemplateLogo(templatePath, member=FB_LOGO_MEDIA):
    """UniMelb logo bytes from the template workbook (None if not found)."""
    try:
        with _zipfile.ZipFile(templatePath) as z:
            return z.read(member)
    except (FileNotFoundError, KeyError, _zipfile.BadZipFile):
        return None


def fmtNum(x, dp=1):
    """Number -> string with dp decimals, trailing '.0' dropped."""
    if x is None:
        return "—"
    s = f"{x:.{dp}f}"
    return s[:-2] if s.endswith(".0") else s


def commentHtml(text):
    """Plain comment text -> reportlab Paragraph markup (escaped, newlines kept)."""
    lines = [ln.rstrip() for ln in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "<br/>".join(_xmlEscape(ln) for ln in lines)


def buildStudentFeedbackPdf(outPath, student, stations, stStats, examAvg, cohortLabel="DDS4",
                            hideOverall=False, logoBytes=None, showCutoff=True, maxScore=100, stationGapCm=0.9,
                            bfHeading="failOnly", bfText="always", showSdbm=True):
    """
    One student's feedback PDF (A4). OVERALL EXAM OUTCOME = student["overallOutcome"].
    showSdbm=False hides every 2 SDBM item (summary count, per-station YES/NO, footnote).
    hideOverall=True withholds the student's overall MARK (outcome + station counts stay).
    bfHeading : "Borderline/Fail information:" heading — "always" | "failOnly" (only on FAILED stations) | "never"
    bfText    : the Borderline/Fail Info text itself — "always" | "failOnly" | "never"
                (when the heading is dropped the text is shown as a plain paragraph after the feedback)
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rlColors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth as _rlStringWidth
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, NextPageTemplate, Paragraph as RlPara, Table as RlTable,
                                    TableStyle as RlTableStyle, Spacer as RlSpacer, KeepTogether)

    navy, panel = rlColors.HexColor(FB_NAVY), rlColors.HexColor(FB_PANEL)
    failC, white = rlColors.HexColor(FB_FAIL), rlColors.white
    pageW, pageH = A4
    margin = 1.4 * cm
    headerH = 3.0 * cm
    contentW = pageW - 2 * margin
    padX = 0.4 * cm                                   # panel inner padding
    innerW = contentW - 2 * padX
    stationGap = stationGapCm * cm                    # vertical space between station blocks

    def ps(name, **kw):
        base = dict(fontName="Helvetica", fontSize=9, leading=11, textColor=rlColors.black)
        base.update(kw)
        return ParagraphStyle(name, **base)
    S = {
        "lab": ps("lab", fontName="Helvetica-Bold", fontSize=8, leading=9.5, alignment=TA_RIGHT, textColor=navy),
        "box": ps("box", fontSize=10, leading=12, alignment=TA_CENTER),
        "boxFail": ps("boxFail", fontName="Helvetica-Bold", fontSize=10, leading=12, alignment=TA_CENTER, textColor=failC),
        "stn": ps("stn", fontName="Helvetica-Bold", fontSize=11, leading=13, textColor=navy),
        "stnMeta": ps("stnMeta", fontSize=8.5, leading=10.5, textColor=navy),
        "max": ps("max", fontSize=7, leading=9, alignment=TA_RIGHT, textColor=rlColors.HexColor("#444444")),
        "barTxt": ps("barTxt", fontName="Helvetica-Bold", fontSize=8.5, leading=10, alignment=TA_CENTER, textColor=white),
        "cmt": ps("cmt", fontSize=9, leading=11.5),
        "sec": ps("sec", fontName="Helvetica-Bold", fontSize=11, leading=13, alignment=TA_CENTER, textColor=navy),
        "note": ps("note", fontSize=8, leading=10, textColor=navy),
    }

    def valBox(text, fail=False):
        return RlPara(_xmlEscape(str(text)), S["boxFail"] if fail else S["box"])

    def fieldGrid(cells, colW):
        """cells: list of rows; each row = list of (label, value, fail) triples (or None for blank)."""
        data, cmds = [], [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for ri, row in enumerate(cells):
            line = []
            for ci, item in enumerate(row):
                if item is None:
                    line += ["", ""]
                    continue
                lab, val, fail = item
                line += [RlPara(lab, S["lab"]), valBox(val, fail)]
                vc = 2 * ci + 1
                cmds += [("BOX", (vc, ri), (vc, ri), 0.6, rlColors.HexColor("#555555")),
                         ("BACKGROUND", (vc, ri), (vc, ri), white)]
            data.append(line)
        t = RlTable(data, colWidths=colW)
        t.setStyle(RlTableStyle(cmds))
        return t

    labW, valW = 0.19 * innerW, 0.143 * innerW        # 3 label/value pairs per row
    gridW = [labW, valW] * 3
    rule = RlTable([[""]], colWidths=[innerW], rowHeights=[2])
    rule.setStyle(RlTableStyle([("LINEABOVE", (0, 0), (-1, -1), 2, navy)]))

    flow = []
    # ── overall summary ──
    sumRows = []
    overallOutcome = student.get("overallOutcome")
    outcomeCell = ("OVERALL EXAM<br/>OUTCOME:", overallOutcome or "—", overallOutcome == "FAIL")
    if hideOverall:                                   # outcome shown, overall mark withheld
        sumRows.append([outcomeCell, None, None])
    else:
        sumRows.append([outcomeCell, ("MARK:", f"{fmtNum(student.get('mark', student['avg']))}%", False), None])
    ncLabels = [f"Station {stations[t]['meta'].get('label', '')} ({stations[t]['meta'].get('domain', '')})"
                for t in stations if not stStats[t].get("counted", True) and t in student["results"]]
    sumRows.append([("NUMBER OF<br/>STATIONS PASSED:", student["nPass"], False),
                    ("NUMBER OF<br/>STATIONS FAILED:", student["nFail"], student["nFail"] > 0),
                    ("NUMBER OF<br/>STATIONS 2 SDBM:", student["nSdbm"], student["nSdbm"] > 0) if showSdbm else None])
    flow += [fieldGrid(sumRows, gridW), RlSpacer(1, 3)]
    if ncLabels:
        flow += [RlPara("<b>Note:</b> " + _xmlEscape(", ".join(ncLabels)) +
                        (" is" if len(ncLabels) == 1 else " are") +
                        " not counted towards the number of stations passed/failed; "
                        + ("its" if len(ncLabels) == 1 else "their") + " outcome and cutoff are shown as N/A.",
                        S["note"]), RlSpacer(1, 3)]
    flow += [
             RlPara(f"maximum station score = {maxScore}" + (" &nbsp;&nbsp;·&nbsp;&nbsp; 2 SDBM = more than two standard "
                    "deviations below the cohort average for that station" if showSdbm else ""), S["max"]),
             RlSpacer(1, 0.25 * cm)]

    # ── one block per station ──
    for title, st in stations.items():
        res = student["results"].get(title)
        if res is None:
            continue
        m, ss = st["meta"], stStats[title]
        # TOPIC moves to its own line when domain + type + topic would not fit on one line
        # (otherwise the topic text wraps under DOMAIN mid-phrase)
        oneLineW = (_rlStringWidth("DOMAIN:  STATION TYPE:  TOPIC: ", "Helvetica-Bold", 8.5)
                    + _rlStringWidth(f"{m.get('domain', '')}{m.get('type', '')}{m.get('topic', '')}", "Helvetica", 8.5)
                    + 6 * _rlStringWidth(" ", "Helvetica", 8.5) * 3)
        topicSep = "<br/>" if oneLineW > 0.82 * innerW - 6 else " &nbsp;&nbsp;&nbsp; "
        metaTxt = (f"<b>DOMAIN:</b> {_xmlEscape(m.get('domain', ''))} &nbsp;&nbsp;&nbsp; "
                   f"<b>STATION TYPE:</b> {_xmlEscape(m.get('type', ''))}{topicSep}"
                   f"<b>TOPIC:</b> {_xmlEscape(m.get('topic', ''))}")
        head = RlTable([[RlPara(f"STATION {_xmlEscape(m.get('label', ''))}", S["stn"]), RlPara(metaTxt, S["stnMeta"])]],
                       colWidths=[0.18 * innerW, 0.82 * innerW])
        head.setStyle(RlTableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
        fail = res["outcome"] == "FAIL"
        cutTxt = (fmtNum(ss["displayCutPct"]) if ss.get("counted", True) else "N/A") if showCutoff else None
        row1 = [("OUTCOME:", res["outcome"], fail), ("SCORE:", fmtNum(res["score"]), fail),
                ("STATION CUTOFF:", cutTxt, False) if showCutoff else None]
        cohortCells = [("COHORT AVERAGE:", fmtNum(ss["mean"]), False),
                       ("COHORT RANGE:", f"{fmtNum(ss['min'])} - {fmtNum(ss['max'])}", False)]
        row2 = ([("2 SDBM:", "YES" if res["sdbm"] else "NO", res["sdbm"])] + cohortCells if showSdbm
                else cohortCells + [None])
        grid = fieldGrid([row1, row2], gridW)

        parts = []
        if res["feedback"]:
            parts.append(commentHtml(res["feedback"]))
        def showFor(mode):
            return mode == "always" or (mode == "failOnly" and fail)
        if res["bfInfo"] and showFor(bfText):
            bfHead = "<b>Borderline/Fail information:</b><br/>" if showFor(bfHeading) else ""
            parts.append(bfHead + commentHtml(res["bfInfo"]))
        cmtPara = RlPara("<br/><br/>".join(parts) if parts else "<i>No comments recorded.</i>", S["cmt"])
        cmt = RlTable([[RlPara("EXAMINER COMMENTS:", S["barTxt"])], [cmtPara]], colWidths=[innerW])
        cmt.setStyle(RlTableStyle([("BACKGROUND", (0, 0), (-1, 0), navy), ("BACKGROUND", (0, 1), (-1, 1), white),
                                   ("BOX", (0, 0), (-1, -1), 0.6, navy),
                                   ("TOPPADDING", (0, 0), (-1, 0), 2), ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                                   ("TOPPADDING", (0, 1), (-1, 1), 5), ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
                                   ("LEFTPADDING", (0, 1), (-1, 1), 6), ("RIGHTPADDING", (0, 1), (-1, 1), 6)]))
        # header + scores stay together; a very long comment box may still split across pages
        flow += [KeepTogether([rule, RlSpacer(1, 3), head, grid, RlSpacer(1, 4), cmt]), RlSpacer(1, stationGap)]

    title1 = f"{cohortLabel} OSCE FEEDBACK"
    logo = ImageReader(_io.BytesIO(logoBytes)) if logoBytes else None

    def decorate(canv, doc):
        canv.saveState()
        # light-green panel behind the content area
        canv.setFillColor(panel)
        canv.rect(margin, margin, contentW, pageH - 2 * margin - (headerH if doc.page == 1 else 0), stroke=0, fill=1)
        if doc.page == 1:
            canv.setFillColor(navy)
            canv.rect(margin, pageH - margin - headerH, contentW, headerH, stroke=0, fill=1)
            canv.setFillColor(white)
            canv.setFont("Helvetica-Bold", 22)
            canv.drawString(margin + 0.6 * cm, pageH - margin - 1.3 * cm, title1)
            canv.setFont("Helvetica", 14)
            canv.drawString(margin + 0.6 * cm, pageH - margin - 2.2 * cm,
                            f"{student['name']} ({student.get('studentNo', '')})" if student.get("studentNo") else student["name"])
            if logo:
                lh = headerH - 0.4 * cm
                canv.drawImage(logo, pageW - margin - lh - 0.3 * cm, pageH - margin - headerH + 0.2 * cm,
                               width=lh, height=lh, mask="auto")
        canv.setFillColor(rlColors.HexColor("#555555"))
        canv.setFont("Helvetica", 7)
        canv.drawRightString(pageW - margin, margin - 0.45 * cm, f"{student['name']} · {student.get('studentNo', '')} · page {doc.page}")
        canv.restoreState()

    os.makedirs(os.path.dirname(outPath) or ".", exist_ok=True)
    doc = BaseDocTemplate(outPath, pagesize=A4, leftMargin=margin + padX, rightMargin=margin + padX,
                            topMargin=margin + 0.35 * cm, bottomMargin=margin + 0.3 * cm,
                            title=f"{title1} - {student['name']}", author="Melbourne Dental School")

    # first page starts below the navy header; every later page uses 'rest' (green panel, no header)
    f1 = Frame(margin + padX, margin + 0.3 * cm, innerW, pageH - 2 * margin - headerH - 0.3 * cm - 0.4 * cm, id="f1",
               leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f2 = Frame(margin + padX, margin + 0.3 * cm, innerW, pageH - 2 * margin - 0.3 * cm - 0.35 * cm, id="f2",
               leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="first", frames=[f1], onPage=decorate, autoNextPageTemplate="rest"),
                          PageTemplate(id="rest", frames=[f2], onPage=decorate)])
    doc.build([NextPageTemplate("rest")] + flow)
    return outPath



# ══════════════════════════════════════════════════════════════════════════════
# STUDENT OSCE FEEDBACK PDF — V2 LAYOUT (2026-11-02)
#   page 1  : navy header, KPI tiles, rule note, "Results at a glance" table
#   page 2+ : one card per station (outcome strip, DOMAIN / STATION TYPE / TOPIC,
#             figures row, CBD-style score bar, old-style EXAMINER COMMENTS box)
#   colours : PASS = UniMelb blue, FAIL = CBD "N" grade burnt orange, cohort avg = CBD orange
# ══════════════════════════════════════════════════════════════════════════════
FB2_NAVY = "#000F46"        # header, headings, comments bar
FB2_PASS = "#094183"        # PASS badge / strip / marker
FB2_FAIL = "#A84300"        # FAIL (CBD report N-grade colour)
FB2_AVG = "#E07B00"         # cohort average line (CBD report orange)
FB2_NA = "#8A93A3"          # N/A (station not counted)
FB2_LIGHT = "#E8EEF7"       # tiles / figure rows
FB2_BELOW_CUT = "#F2DED0"   # bar zone below the station cutoff
FB2_PAGE_COLORS = {         # pageColor presets for the V2 PDF background (or pass any "#RRGGBB")
    "white": "#FFFFFF",
    "paper": "#F7F4EC",     # warm paper (default)
    "mist": "#F1F4F9",      # cool mist
    "sage": "#F0F4E6",      # soft sage (old template green, faint)
    "bluegrey": "#E9EDF3",  # blue-grey
}


def buildStudentFeedbackPdfV2(outPath, student, stations, stStats, examAvg=None, cohortLabel="DDS4",
                              hideOverall=False, logoBytes=None, showCutoff=True, maxScore=100,
                              bfHeading="failOnly", bfText="always", showSdbm=True, examLabel="OSCE",
                              ruleText=None, stationGapCm=0.35, pageColor="paper"):
    """
    One student's feedback PDF in the V2 layout (same inputs as buildStudentFeedbackPdf).
      hideOverall : withhold the OVERALL MARK tile (outcome + counts stay)
      showSdbm    : False hides every 2 SDBM item (tile, table column, card figure, note)
      showCutoff  : False hides cutoff column / figure / bar marker
      bfHeading / bfText : "always" | "failOnly" | "never" (Borderline/Fail Info, as V1)
      examLabel   : sub-heading under the student name (e.g. "2026 OSCE")
      ruleText    : sentence explaining the overall outcome rule (None = generic)
      pageColor   : page background — preset in FB2_PAGE_COLORS ("white", "paper", "mist", "sage",
                    "bluegrey") or a hex string "#RRGGBB"
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rlColors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth as rlStringWidth
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph as RlPara, Table as RlTable,
                                    TableStyle as RlTableStyle, Spacer as RlSpacer, KeepTogether, Flowable,
                                    PageBreak as RlPageBreak)

    hx = rlColors.HexColor
    navy, passC, failC, avgC, naC = hx(FB2_NAVY), hx(FB2_PASS), hx(FB2_FAIL), hx(FB2_AVG), hx(FB2_NA)
    light, grey, line, white = hx(FB2_LIGHT), hx("#5B6475"), hx("#C9D2E3"), rlColors.white
    outCol = lambda o: {"PASS": passC, "FAIL": failC}.get(o, naC)
    W, H = A4
    M, HDR = 1.5 * cm, 2.7 * cm
    CW = W - 2 * M

    def ps(name, **kw):
        base = dict(fontName="Helvetica", fontSize=9, leading=11, textColor=rlColors.black)
        base.update(kw)
        return ParagraphStyle(name, **base)
    S = {
        "lab": ps("lab", fontName="Helvetica-Bold", fontSize=6.8, leading=8.5, textColor=grey),
        "val": ps("val", fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=navy),
        "valF": ps("valF", fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=failC),
        "meta": ps("meta", fontSize=9, leading=11.5, textColor=navy),
        "kpi": ps("kpi", fontName="Helvetica-Bold", fontSize=20, leading=23, textColor=navy),
        "kpiF": ps("kpiF", fontName="Helvetica-Bold", fontSize=20, leading=23, textColor=failC),
        "stNo": ps("stNo", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=navy),
        "cmt": ps("cmt", fontSize=9, leading=12.5, textColor=hx("#1F2430")),
        "bar": ps("bar", fontName="Helvetica-Bold", fontSize=8.5, leading=10, alignment=TA_CENTER, textColor=white),
        "note": ps("note", fontSize=8, leading=10.5, textColor=grey),
        "sec": ps("sec", fontName="Helvetica-Bold", fontSize=11, leading=13, textColor=navy),
        "th": ps("th", fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=white),
        "thC": ps("thC", fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=white, alignment=TA_CENTER),
    }

    class OutcomeBadge(Flowable):
        """Rounded PASS / FAIL / N/A pill."""
        def __init__(self, text, w=2.0 * cm, h=0.65 * cm, size=9):
            super().__init__()
            self.text, self.w, self.h, self.size = text, w, h, size
        def wrap(self, *a):
            return self.w, self.h
        def draw(self):
            c = self.canv
            c.setFillColor(outCol(self.text))
            c.roundRect(0, 0, self.w, self.h, self.h / 2, stroke=0, fill=1)
            c.setFillColor(white)
            c.setFont("Helvetica-Bold", self.size)
            c.drawCentredString(self.w / 2, self.h / 2 - self.size * 0.35, self.text)

    class ScoreBar(Flowable):
        """CBD-style 0-100 bar: below-cut zone, cutoff (dashed navy), cohort avg (orange), student diamond.
        Labels sit above their marker; an overlapping label moves up one level."""
        def __init__(self, w, score, avg, cut, outcome, h=1.55 * cm):
            super().__init__()
            self.w, self.h, self.score, self.avg, self.cut, self.outcome = w, h, score, avg, cut, outcome
        def wrap(self, *a):
            return self.w, self.h
        def draw(self):
            c = self.canv
            x0, x1 = 1.6 * cm, self.w - 0.3 * cm
            X = lambda v: x0 + (x1 - x0) * max(0.0, min(100.0, v * 100.0 / maxScore)) / 100.0
            by, bh = 0.42 * cm, 0.36 * cm
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(navy)
            c.drawString(0, by + bh / 2 - 3, "Score %")
            c.setFillColor(hx("#F2F6FC"))
            c.rect(x0, by, x1 - x0, bh, stroke=0, fill=1)
            if self.cut is not None:
                c.setFillColor(hx(FB2_BELOW_CUT))
                c.rect(x0, by, X(self.cut) - x0, bh, stroke=0, fill=1)
            c.setStrokeColor(navy)
            c.setLineWidth(0.6)
            c.rect(x0, by, x1 - x0, bh, stroke=1, fill=0)
            c.setFont("Helvetica", 6.5)
            c.setFillColor(grey)
            c.setStrokeColor(grey)
            c.setLineWidth(0.4)
            for t in range(0, 101, 10):
                c.line(x0 + (x1 - x0) * t / 100, by, x0 + (x1 - x0) * t / 100, by - 2.5)
                c.drawCentredString(x0 + (x1 - x0) * t / 100, by - 9, str(round(t * maxScore / 100)))
            marks = []
            if self.cut is not None:
                c.setStrokeColor(navy)
                c.setLineWidth(1.3)
                c.setDash(2.2, 1.6)
                c.line(X(self.cut), by - 1, X(self.cut), by + bh + 1)
                c.setDash()
                marks.append((X(self.cut), f"Cutoff {fmtNum(self.cut)}", navy))
            c.setStrokeColor(avgC)
            c.setLineWidth(1.8)
            c.line(X(self.avg), by - 1, X(self.avg), by + bh + 1)
            marks.append((X(self.avg), f"Cohort avg {fmtNum(self.avg)}", avgC))
            sx, sy, d, col = X(self.score), by + bh / 2, 4.2, outCol(self.outcome)
            p = c.beginPath()
            p.moveTo(sx, sy + d); p.lineTo(sx + d, sy); p.lineTo(sx, sy - d); p.lineTo(sx - d, sy); p.close()
            c.setFillColor(col)
            c.setStrokeColor(white)
            c.setLineWidth(0.8)
            c.drawPath(p, stroke=1, fill=1)
            marks.append((sx, f"You {fmtNum(self.score)}", col))
            fs, gap, ly0, step, last = 7.5, 5, by + bh + 3, 9, []
            c.setFont("Helvetica-Bold", fs)
            for x, t, tc in sorted(marks, key=lambda m: m[0]):
                w = rlStringWidth(t, "Helvetica-Bold", fs)
                left = min(max(x - w / 2, x0 - 4), x1 + 4 - w)
                lvl = next((i for i, r in enumerate(last) if left >= r + gap), len(last))
                if lvl == len(last):
                    last.append(0)
                last[lvl] = left + w
                c.setFillColor(tc)
                c.drawString(left, ly0 + lvl * step, t)

    def showFor(mode, fail):
        return mode == "always" or (mode == "failOnly" and fail)

    order = [t for t in stations if t in student["results"]]
    flow = []

    # ── page 1: KPI tiles ──
    overall = student.get("overallOutcome") or "—"
    tiles = [("OVERALL OUTCOME", OutcomeBadge(overall, w=2.8 * cm, h=0.85 * cm, size=10.5))]
    if not hideOverall:
        tiles.append(("OVERALL MARK", RlPara(f"{fmtNum(student.get('mark', student['avg']))}%", S["kpi"])))
    tiles += [("STATIONS PASSED", RlPara(str(student["nPass"]), S["kpi"])),
              ("STATIONS FAILED", RlPara(str(student["nFail"]), S["kpiF"] if student["nFail"] else S["kpi"]))]
    if showSdbm:
        tiles.append(("STATIONS 2 SDBM", RlPara(str(student["nSdbm"]), S["kpiF"] if student["nSdbm"] else S["kpi"])))
    kpi = RlTable([[RlPara(l, S["lab"]) for l, _ in tiles], [v for _, v in tiles]],
                  colWidths=[CW / len(tiles)] * len(tiles), rowHeights=[0.55 * cm, 1.05 * cm])
    kpi.setStyle(RlTableStyle([("BACKGROUND", (0, 0), (-1, -1), light), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, 0), 8),
                               ("LINEAFTER", (0, 0), (-2, -1), 1, white), ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
                               ("LINEABOVE", (0, 0), (-1, 0), 2.5, navy)]))
    notes = f"All station scores are out of {maxScore}."
    if showCutoff:
        notes += " <b>Station cutoff</b> is the standard-set pass mark for that station."
    notes += " " + (ruleText or "The overall outcome is based on the number of stations failed.")
    if showSdbm:
        notes += " <b>2 SDBM</b> = more than two standard deviations below the cohort average for that station."
    nc = [f"Station {stations[t]['meta'].get('label', '')} ({stations[t]['meta'].get('domain', '')})"
          for t in order if not stStats[t].get("counted", True)]
    if nc:
        notes += (" " + _xmlEscape(", ".join(nc)) + (" is" if len(nc) == 1 else " are") +
                  " not counted towards the number of stations passed/failed; outcome and cutoff are shown as N/A.")
    flow += [kpi, RlSpacer(1, 7), RlPara(notes, S["note"]), RlSpacer(1, 18),
             RlPara("RESULTS AT A GLANCE", S["sec"]), RlSpacer(1, 6)]

    # ── page 1: overview table ──
    cols = [("Station", 1.5 * cm, "th"), ("Domain", None, "th"), ("Station Type", 3.6 * cm, "th"),
            ("Score", 1.3 * cm, "thC")]
    if showCutoff:
        cols.append(("Cutoff", 1.4 * cm, "thC"))
    cols += [("Cohort avg", 2.2 * cm, "thC"), ("Outcome", 2.0 * cm, "thC")]
    if showSdbm:
        cols.append(("2 SDBM", 1.8 * cm, "thC"))
    rows = [[RlPara(h, S[sty]) for h, _, sty in cols]]
    tsx = [("BACKGROUND", (0, 0), (-1, 0), navy), ("FONT", (0, 1), (-1, -1), "Helvetica", 9.5),
           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (3, 1), (-1, -1), "CENTER"),
           ("LINEBELOW", (0, 1), (-1, -1), 0.5, line), ("LEFTPADDING", (0, 0), (-1, -1), 7),
           ("FONT", (0, 1), (0, -1), "Helvetica-Bold", 9.5), ("TEXTCOLOR", (0, 1), (0, -1), navy),
           ("TEXTCOLOR", (2, 1), (2, -1), grey), ("FONT", (2, 1), (2, -1), "Helvetica", 8.5),
           ("BOX", (0, 0), (-1, -1), 0.6, navy)]
    for i, t in enumerate(order, 1):
        m, ss, res = stations[t]["meta"], stStats[t], student["results"][t]
        cutTxt = fmtNum(ss["displayCutPct"]) if ss.get("counted", True) and ss.get("displayCutPct") is not None else "N/A"
        r = [m.get("label", ""), m.get("domain", ""), m.get("type", ""), fmtNum(res["score"])]
        if showCutoff:
            r.append(cutTxt)
        r += [fmtNum(ss["mean"]), OutcomeBadge(res["outcome"], w=1.6 * cm, h=0.5 * cm, size=7.5)]
        if showSdbm:
            r.append("YES" if res["sdbm"] else "–")
        rows.append(r)
        if i % 2 == 0:
            tsx.append(("BACKGROUND", (0, i), (-1, i), hx("#F3F6FB")))
        if res["outcome"] == "FAIL":
            tsx += [("TEXTCOLOR", (3, i), (3, i), failC), ("FONT", (3, i), (3, i), "Helvetica-Bold", 9.5)]
        if showSdbm and res["sdbm"]:
            tsx += [("TEXTCOLOR", (-1, i), (-1, i), failC), ("FONT", (-1, i), (-1, i), "Helvetica-Bold", 9.5)]
    cw = [w for _, w, _ in cols]
    cw[1] = CW - sum(w for w in cw if w)
    rowH = 0.78 * cm if len(order) <= 16 else 0.6 * cm
    ov = RlTable(rows, colWidths=cw, rowHeights=[0.75 * cm] + [rowH] * len(order), repeatRows=1)
    ov.setStyle(RlTableStyle(tsx))
    flow += [ov, RlPageBreak(), RlPara("STATION FEEDBACK", S["sec"]), RlSpacer(1, 8)]

    # ── page 2+: one card per station ──
    inner = CW - 0.8 * cm - 5
    for t in order:
        m, ss, res = stations[t]["meta"], stStats[t], student["results"][t]
        fail = res["outcome"] == "FAIL"
        counted = ss.get("counted", True)
        cut = ss.get("displayCutPct") if (showCutoff and counted) else None
        top = RlTable([[RlPara(f"STATION {_xmlEscape(m.get('label', ''))}", S["stNo"]), OutcomeBadge(res["outcome"])]],
                      colWidths=[inner - 2.0 * cm, 2.0 * cm])
        top.setStyle(RlTableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        topic = m.get("topic", "")
        topic = topic[:1].upper() + topic[1:]
        meta = RlTable([[RlPara("DOMAIN", S["lab"]), RlPara("STATION TYPE", S["lab"]), RlPara("TOPIC", S["lab"])],
                        [RlPara(_xmlEscape(m.get("domain", "")), S["meta"]), RlPara(_xmlEscape(m.get("type", "")), S["meta"]),
                         RlPara(_xmlEscape(topic), S["meta"])]],
                       colWidths=[inner * 0.28, inner * 0.24, inner * 0.48])
        meta.setStyle(RlTableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        cells = [("SCORE", fmtNum(res["score"]), fail)]
        if showCutoff:
            cells.append(("STATION CUTOFF", fmtNum(ss["displayCutPct"]) if counted and ss.get("displayCutPct") is not None else "N/A", False))
        cells += [("COHORT AVERAGE", fmtNum(ss["mean"]), False),
                  ("COHORT RANGE", f"{fmtNum(ss['min'])} – {fmtNum(ss['max'])}", False)]
        if showSdbm:
            cells.append(("2 SDBM", "YES" if res["sdbm"] else "NO", res["sdbm"]))
        fig = RlTable([[RlPara(l, S["lab"]) for l, _, _ in cells],
                       [RlPara(v, S["valF"] if bad else S["val"]) for _, v, bad in cells]],
                      colWidths=[(inner - 16) / len(cells)] * len(cells))
        fig.setStyle(RlTableStyle([("BACKGROUND", (0, 0), (-1, -1), light), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                   ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
                                   ("TOPPADDING", (0, 1), (-1, 1), 1), ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                                   ("LINEAFTER", (0, 0), (-2, -1), 1, white)]))
        bar = ScoreBar(inner, res["score"], ss["mean"], cut, res["outcome"])
        parts = [commentHtml(res["feedback"])] if res.get("feedback") else []
        if res.get("bfInfo") and showFor(bfText, fail):
            parts.append(("<b>Borderline/Fail information:</b><br/>" if showFor(bfHeading, fail) else "")
                         + commentHtml(res["bfInfo"]))
        cmt = RlTable([[RlPara("EXAMINER COMMENTS:", S["bar"])],
                       [RlPara("<br/><br/>".join(parts) if parts else "<i>No comments recorded.</i>", S["cmt"])]],
                      colWidths=[inner])
        cmt.setStyle(RlTableStyle([("BACKGROUND", (0, 0), (-1, 0), navy), ("BACKGROUND", (0, 1), (-1, 1), white),
                                   ("BOX", (0, 0), (-1, -1), 0.6, navy),
                                   ("TOPPADDING", (0, 0), (-1, 0), 2), ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                                   ("TOPPADDING", (0, 1), (-1, 1), 5), ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
                                   ("LEFTPADDING", (0, 1), (-1, 1), 6), ("RIGHTPADDING", (0, 1), (-1, 1), 6)]))
        body = [top, RlSpacer(1, 4), meta, RlSpacer(1, 6), fig, RlSpacer(1, 4), bar, RlSpacer(1, 4), cmt]
        card = RlTable([["", body]], colWidths=[5, CW - 5])
        card.setStyle(RlTableStyle([("BACKGROUND", (0, 0), (0, 0), outCol(res["outcome"])),
                                    ("BACKGROUND", (1, 0), (1, 0), white), ("BOX", (0, 0), (-1, -1), 0.6, line),
                                    ("LEFTPADDING", (1, 0), (1, 0), 0.4 * cm), ("RIGHTPADDING", (1, 0), (1, 0), 0.4 * cm),
                                    ("TOPPADDING", (1, 0), (1, 0), 10), ("BOTTOMPADDING", (1, 0), (1, 0), 12),
                                    ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0)]))
        flow += [KeepTogether([card]), RlSpacer(1, stationGapCm * cm)]

    title1 = f"{cohortLabel} OSCE Feedback"
    logo = ImageReader(_io.BytesIO(logoBytes)) if logoBytes else None
    who = f"{student['name']}  ·  {student.get('studentNo', '')}" if student.get("studentNo") else student["name"]

    pageBg = hx(FB2_PAGE_COLORS.get(str(pageColor).lower(), pageColor)) if pageColor else None

    def decorate(canv, doc):
        canv.saveState()
        if pageBg is not None:
            canv.setFillColor(pageBg)
            canv.rect(0, 0, W, H, stroke=0, fill=1)
        if doc.page == 1:
            canv.setFillColor(navy)
            canv.rect(0, H - HDR, W, HDR, stroke=0, fill=1)
            canv.setFillColor(white)
            canv.setFont("Helvetica-Bold", 20)
            canv.drawString(M, H - 1.25 * cm, title1)
            canv.setFont("Helvetica", 12)
            canv.drawString(M, H - 1.95 * cm, who)
            canv.setFont("Helvetica", 8)
            canv.setFillColor(hx("#B8C0D8"))
            canv.drawString(M, H - 2.4 * cm, examLabel)
            if logo:
                canv.drawImage(logo, W - M - 2.1 * cm, H - HDR + 0.3 * cm, width=2.1 * cm, height=2.1 * cm, mask="auto")
        else:
            canv.setFillColor(navy)
            canv.rect(0, H - 0.35 * cm, W, 0.35 * cm, stroke=0, fill=1)
            canv.setFont("Helvetica", 7.5)
            canv.setFillColor(grey)
            canv.drawString(M, H - 0.95 * cm, f"{title1}  ·  {student['name']}")
        canv.setFont("Helvetica", 7)
        canv.setFillColor(grey)
        canv.drawRightString(W - M, 0.8 * cm, f"{student['name']} · {student.get('studentNo', '')} · page {doc.page}")
        canv.restoreState()

    os.makedirs(os.path.dirname(outPath) or ".", exist_ok=True)
    doc = BaseDocTemplate(outPath, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=1.4 * cm,
                          title=f"{title1} - {student['name']}", author="Melbourne Dental School")
    f1 = Frame(M, 1.4 * cm, CW, H - HDR - 0.6 * cm - 1.4 * cm, id="f1",
               leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f2 = Frame(M, 1.4 * cm, CW, H - 2.8 * cm, id="f2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="first", frames=[f1], onPage=decorate, autoNextPageTemplate="rest"),
                          PageTemplate(id="rest", frames=[f2], onPage=decorate)])
    doc.build(flow)
    return outPath


def buildOsceFeedbackReports(stationPath, analysisPath, outDir, studentNumbers=None, cohortLabel="DDS4",
                             hideOverallFor=None, templatePath="OSCE/OSCE Feedback Template.xlsx",
                             stationMeta=None, excludeSheets=None, showCutoff=True, overallOutcomes=None,
                             metaPath=STATION_META_PATH, year=None, passAllCutOffset=1.0, maxStationFails=4,
                             bfHeading="failOnly", bfText="always", stationGapCm=0.9, notCountedSheets=None,
                             feedbackCol="Feedback", bfCol="Borderline/Fail Info", scoresFrom="station",
                             showSdbm=True, requireAvgAboveCut=False, markColumn=None,
                             excludeStudentNumbers=None, markPath=None, pdfVersion=1, examLabel=None,
                             pageColor="paper"):
    """
    Build one feedback PDF per student.
      studentNumbers : iterable of student numbers to build (None = everyone on the sheets)
      hideOverallFor : True = withhold the overall MARK for everyone; or an iterable of student numbers
      maxStationFails: OVERALL EXAM OUTCOME = FAIL when stations failed > this (default 4), else PASS
                       (stations failed = every reported station below its cut, as printed on the PDF)
      bfHeading / bfText : "always" | "failOnly" | "never" — Borderline/Fail heading / text (see buildStudentFeedbackPdf)
      stationGapCm   : vertical gap between station blocks (cm)
      notCountedSheets : extra station sheet names whose pass/fail is not counted (on top of the metadata
                       workbook's 'Counts To Outcome' = N) -> N/A outcome + cutoff, excluded from counts
      overallOutcomes: optional {studentNo: "PASS"/"FAIL"} that overrides the computed outcome
      requireAvgAboveCut : also FAIL when the student's average station score < average applied cut of the
                       counted stations (the official 'OSCE Outcome' rule); default False = station count only
      feedbackCol / bfCol : comment columns on the station sheets (e.g. feedbackCol="Proofread comments")
      scoresFrom     : "station" = Score (%) on the station sheets; "analysis" = 'Student x Station' of
                       analysisPath (joined by Student No) — cohort stats then use those scores too
      showSdbm       : False hides all 2 SDBM info on the PDFs
      excludeStudentNumbers : student numbers dropped everywhere (no PDF, not in cohort avg/range/SD)
      markColumn     : None = MARK is the plain average station score; else a column of the analysis workbook's
                       'OSCE Outcome' sheet, e.g. "Per-stn cut /100" (official scaled /100 mark)
      pdfVersion     : 1 = original layout (buildStudentFeedbackPdf); 2 = V2 layout (buildStudentFeedbackPdfV2)
      pageColor      : V2 page background — "white" | "paper" | "mist" | "sage" | "bluegrey" | "#RRGGBB"
      examLabel      : V2 sub-heading under the name (default "<year> OSCE" or "OSCE")
      markPath       : workbook holding the 'OSCE Outcome' mark table (default = analysisPath), e.g. a
                       separately approved overall-score table
      passAllCutOffset : PASS ALL stations print cutoff = lowest cohort score - this (default 1)
      metaPath / year : station metadata workbook (rows for cohortLabel [+ year]); used when stationMeta is None
      stationMeta / excludeSheets : explicit overrides; fallback DDS4_FEEDBACK_STATION_META / FEEDBACK_EXCLUDE_SHEETS
                                    when the metadata workbook is absent
    Returns {"files": [...], "missing": [...], "incomplete": {...}, "skippedSheets": [...], "examAvg": x,
             "summary": [per-student rows]}.
    """
    metaSource = "argument"
    if stationMeta is None and metaPath and os.path.exists(metaPath):
        stationMeta, metaExcl = loadStationMeta(metaPath, cohort=cohortLabel, year=year)
        excludeSheets = set(excludeSheets or []) | metaExcl
        metaSource = metaPath
    elif stationMeta is None:
        if metaPath and str(cohortLabel).upper() != "DDS4":       # DDS4 dict fallback is wrong for other cohorts
            raise FileNotFoundError(f"Station metadata workbook not found: {metaPath}")
        metaSource = "DDS4_FEEDBACK_STATION_META (fallback)"
    stations, skipped = loadFeedbackStations(stationPath, stationMeta, excludeSheets, feedbackCol=feedbackCol, bfCol=bfCol)
    dropSet = {str(int(float(x))) for x in (excludeStudentNumbers or [])}
    for st in stations.values():
        st["rows"] = [r for r in st["rows"] if r["studentNo"] not in dropSet]
    scoreSwap = None
    if scoresFrom == "analysis":
        scoreSwap = applyAnalysisScores(stations, loadAnalysisScores(analysisPath))
    elif scoresFrom != "station":
        raise ValueError("scoresFrom must be 'station' or 'analysis'")
    cuts = loadAppliedCuts(analysisPath)
    stStats, students, examAvg = computeFeedbackStats(stations, cuts, passAllCutOffset=passAllCutOffset,
                                                      notCountedSheets=notCountedSheets)
    logoBytes = loadTemplateLogo(templatePath)
    marks = loadOutcomeMarks(markPath or analysisPath, markColumn) if markColumn else None

    cntCuts = [stStats[t]["cutPct"] for t in stStats if stStats[t]["counted"] and stStats[t]["cutPct"] is not None]
    avgCut = statistics.mean(cntCuts) if cntCuts else None          # for requireAvgAboveCut
    ruleText = (f"The overall outcome is FAIL when more than {maxStationFails} stations are failed"
                + (" or the average score is below the average cutoff." if requireAvgAboveCut else "."))
    want = [str(int(float(x))) for x in studentNumbers] if studentNumbers is not None else sorted(students, key=lambda k: students[k]["name"].lower())
    if hideOverallFor is True:
        hideSet = set(want)
    else:
        hideSet = {str(int(float(x))) for x in (hideOverallFor or [])}

    files, missing, incomplete, summary = [], [], {}, []
    for sn in want:
        s = students.get(sn)
        if s is None:
            missing.append(sn)
            continue
        if not s["complete"]:
            incomplete[sn] = [stations[t]["meta"]["label"] for t in stations if t not in s["results"]]
        autoOutcome = "FAIL" if s["nFail"] > maxStationFails else "PASS"
        if requireAvgAboveCut and avgCut is not None and round(s["avg"], 1) < round(avgCut, 1):
            autoOutcome = "FAIL"
        stu = dict(s, studentNo=sn, overallOutcome=(overallOutcomes or {}).get(sn, autoOutcome))
        if marks is not None:
            if sn not in marks:
                raise KeyError(f"Student {sn} has no '{markColumn}' in the OSCE Outcome sheet")
            stu["mark"] = marks[sn]
        safe = re.sub(r"[^A-Za-z0-9]+", "_", s["name"]).strip("_")
        path = os.path.join(outDir, f"{safe}_{sn}.pdf")
        if pdfVersion == 2:
            buildStudentFeedbackPdfV2(path, stu, stations, stStats, examAvg, cohortLabel=cohortLabel,
                                      hideOverall=sn in hideSet, logoBytes=logoBytes, showCutoff=showCutoff,
                                      bfHeading=bfHeading, bfText=bfText, showSdbm=showSdbm,
                                      examLabel=examLabel or (f"{year} OSCE" if year else "OSCE"), ruleText=ruleText,
                                      pageColor=pageColor)
        else:
            buildStudentFeedbackPdf(path, stu, stations, stStats, examAvg, cohortLabel=cohortLabel,
                                    hideOverall=sn in hideSet, logoBytes=logoBytes, showCutoff=showCutoff,
                                    bfHeading=bfHeading, bfText=bfText, stationGapCm=stationGapCm, showSdbm=showSdbm)
        files.append(path)
        summary.append({"name": s["name"], "studentNo": sn, "avg": round(s["avg"], 1),
                        "mark": round(stu.get("mark", s["avg"]), 1), "passed": s["nPass"],
                        "failed": s["nFail"], "sdbm": s["nSdbm"], "overallOutcome": stu["overallOutcome"],
                        "markHidden": sn in hideSet, "file": path})
    return {"metaSource": metaSource, "files": files, "missing": missing, "incomplete": incomplete, "skippedSheets": skipped,
            "examAvg": examAvg, "avgCut": avgCut, "scoreSwap": scoreSwap, "stationStats": stStats, "summary": summary}
