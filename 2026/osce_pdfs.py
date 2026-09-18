import os
from collections import defaultdict

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, PageBreak, KeepTogether)
from reportlab.lib.enums import TA_CENTER

# -- Colour palette ------------------------------------------------------------
UNI    = colors.HexColor("#010d44")
WHITE  = colors.white
LIGHT  = colors.HexColor("#F2F7FC")
BORDER = colors.HexColor("#C5D5E8")
MUTED  = colors.HexColor("#A8C4E0")
TOTAL  = colors.HexColor("#DDE8F4")
PAGE_W = 17.4 * cm          # usable width (A4 - 2 x 1.8 cm margins)

GR_COL = {
    1: colors.HexColor("#FFC7CE"),
    2: colors.HexColor("#FFEB9C"),
    3: colors.HexColor("#C6EFCE"),
    4: colors.HexColor("#9DC3E6"),
    5: colors.HexColor("#92D050"),
}
SC_COL = {
    1.00: colors.HexColor("#C6EFCE"),
    0.80: colors.HexColor("#DDEBF7"),
    0.60: colors.HexColor("#FFEB9C"),
    0.40: colors.HexColor("#FFC7CE"),
    0.00: colors.HexColor("#FF4444"),
}

# -- Checklist response mapping ------------------------------------------------
OPTION_KEYS = {
    "Done well":      "O1",
    "Done":           "O2",
    "Mostly done":    "O3",
    "Sometimes done": "O4",
    "Not done":       "O5",
}
OPTION_SCORES = {"O1": 1.00, "O2": 0.80, "O3": 0.60, "O4": 0.40, "O5": 0.00}
GR_LABELS     = {1: "Fail", 2: "Borderline Fail", 3: "Pass", 4: "Very Good", 5: "Excellent"}

SCALE_NAMES = {
    "scale-global-rating":       "Global Rating",
    "scale-time-mgmt":           "Time Management",
    "scale-communication":       "Communication",
    "scale-professionalism":     "Professionalism",
    "scale-practice-readiness":  "Readiness to Progress",
    "scale-position-ergonomics": "Position & Ergonomics",
}

# -- Defaults (override per cohort in the notebook if station structure differs)
DEFAULT_STATION_SCALES = {
    1: [
        "scale-global-rating",
        "scale-time-mgmt",
        "scale-communication",
        "scale-professionalism",
        "scale-practice-readiness",
    ],
    2: [
        "scale-global-rating",
        "scale-time-mgmt",
        "scale-professionalism",
        "scale-practice-readiness",
        "scale-position-ergonomics",
    ],
}

DEFAULT_STATION_MC_COLS = {
    1: [f"MC{i}" for i in range(1, 9)],   # MC1-MC8
    2: [f"MC{i}" for i in range(1, 7)],   # MC1-MC6
}

# -- Paragraph styles ----------------------------------------------------------
ST = {
    # Page header banner
    "name":    ParagraphStyle("name",    fontName="Helvetica-Bold", fontSize=20,
                               textColor=WHITE, leading=24),
    "hdr_sub": ParagraphStyle("hdr_sub", fontName="Helvetica",      fontSize=9,
                               textColor=MUTED, leading=13),
    "hdr_r1":  ParagraphStyle("hdr_r1",  fontName="Helvetica-Bold", fontSize=13,
                               textColor=WHITE, alignment=TA_CENTER, leading=17),
    "hdr_r2":  ParagraphStyle("hdr_r2",  fontName="Helvetica",      fontSize=8,
                               textColor=MUTED, alignment=TA_CENTER, leading=11),
    # Station banner
    "stn":     ParagraphStyle("stn",     fontName="Helvetica-Bold", fontSize=10,
                               textColor=WHITE, leading=14),
    "stn_r":   ParagraphStyle("stn_r",   fontName="Helvetica",      fontSize=8,
                               textColor=MUTED, alignment=TA_CENTER, leading=11),
    # Section labels
    "sec_lbl": ParagraphStyle("sec_lbl", fontName="Helvetica-Bold", fontSize=11,
                               textColor=UNI, leading=14, spaceBefore=10, spaceAfter=4),
    # Table header cells - WHITE text (must be set here, not via TableStyle)
    "th_l":    ParagraphStyle("th_l",    fontName="Helvetica-Bold", fontSize=9,
                               textColor=WHITE, leading=12),
    "th_c":    ParagraphStyle("th_c",    fontName="Helvetica-Bold", fontSize=9,
                               textColor=WHITE, alignment=TA_CENTER, leading=12),
    # Table body cells
    "td_l":    ParagraphStyle("td_l",    fontName="Helvetica",      fontSize=9,
                               textColor=colors.black, leading=12),
    "td_c":    ParagraphStyle("td_c",    fontName="Helvetica",      fontSize=9,
                               textColor=colors.black, alignment=TA_CENTER, leading=12),
    "td_b":    ParagraphStyle("td_b",    fontName="Helvetica-Bold", fontSize=9,
                               textColor=colors.black, leading=12),
    "td_bc":   ParagraphStyle("td_bc",   fontName="Helvetica-Bold", fontSize=9,
                               textColor=colors.black, alignment=TA_CENTER, leading=12),
    "td_sm":   ParagraphStyle("td_sm",   fontName="Helvetica",      fontSize=8,
                               textColor=colors.HexColor("#333333"), leading=10),
    "td_wrap": ParagraphStyle("td_wrap", fontName="Helvetica",      fontSize=8,
                               textColor=colors.black, leading=10),
    "comment": ParagraphStyle("comment", fontName="Helvetica-Oblique", fontSize=8,
                               textColor=colors.HexColor("#333333"), leading=11,
                               leftIndent=4),
}

# -- Internal table style helpers ----------------------------------------------
_NO_INNER = [
    ("INNERGRID", (0, 0), (-1, -1), 0, UNI),
    ("BOX",       (0, 0), (-1, -1), 0, UNI),
]

_TBL_BASE = [
    ("BACKGROUND",    (0, 0), (-1,  0),  UNI),
    ("VALIGN",        (0, 0), (-1, -1),  "MIDDLE"),
    ("GRID",          (0, 0), (-1, -1),  0.4, BORDER),
    ("TOPPADDING",    (0, 0), (-1, -1),  4),
    ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
    ("LEFTPADDING",   (0, 0), (-1, -1),  6),
    ("RIGHTPADDING",  (0, 0), (-1, -1),  6),
    ("ROWBACKGROUNDS",(0, 1), (-1, -1),  [WHITE, LIGHT]),
]


# -- Helpers -------------------------------------------------------------------
def textScore(lbl):
    ok = OPTION_KEYS.get(lbl)
    return OPTION_SCORES.get(ok) if ok else None


def scBg(v):
    if v is None:
        return None
    return SC_COL.get(round(v, 2))


def p(text, style="td_l"):
    safe = (str(text) if text is not None else "-") \
           .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, ST[style])


# -- Layout components ---------------------------------------------------------
def headerBanner(student, cohort, subject, date, course_code="ORAL10005", year=2026):
    left  = [p(student, "name"), p(f"{cohort}  .  {subject}  .  {date}", "hdr_sub")]
    right = [p(course_code, "hdr_r1"), p(f"OSCE Assessment  .  {year}", "hdr_r2")]
    t = Table([[left, right]], colWidths=[12 * cm, PAGE_W - 12 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), UNI),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (0,  0),  14),
        ("RIGHTPADDING",  (0, 0), (0,  0),   6),
        ("LEFTPADDING",   (1, 0), (1,  0),   6),
        ("RIGHTPADDING",  (1, 0), (1,  0),  14),
    ] + _NO_INNER))
    return t


def stationBanner(station, ck_name, assessor):
    t = Table(
        [[p(f"Station {station}", "stn"), p(f"Assessor: {assessor}", "stn_r")]],
        colWidths=[12 * cm, PAGE_W - 12 * cm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), UNI),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ] + _NO_INNER))
    return t


# Cols: Scale(4.5) | Score(1.5) | Your Level(9.5) | Cohort Avg(1.9) = 17.4
SCALE_COLS = [4.5 * cm, 1.5 * cm, 9.5 * cm, 1.9 * cm]


def scalesTable(st_scale_keys, student_scales, cohort_scale_avgs, sc_fields):
    hdr = [p("Scale", "th_l"), p("Score", "th_c"),
           p("Your Level", "th_l"), p("Cohort Avg", "th_c")]
    rows = [hdr]
    for sk in st_scale_keys:
        name  = SCALE_NAMES.get(sk, sk)
        val   = student_scales.get(sk)
        c_avg = cohort_scale_avgs.get(sk)
        label = (sc_fields.get(sk) or {}).get(str(val), "-") if val else "-"
        if len(label) > 80:
            label = label[:78] + "..."
        rows.append([
            p(name, "td_l"),
            p(str(val) if val else "-", "td_c"),
            p(label, "td_sm"),
            p(f"{c_avg:.1f}" if c_avg is not None else "-", "td_c"),
        ])

    style = list(_TBL_BASE)
    for ri, sk in enumerate(st_scale_keys, 1):
        if sk == "scale-global-rating":
            val = student_scales.get(sk)
            if val and val in GR_COL:
                style.append(("BACKGROUND", (0, ri), (-1, ri), GR_COL[val]))
    t = Table(rows, colWidths=SCALE_COLS)
    t.setStyle(TableStyle(style))
    return t


# Cols: #(1.2) | Description(12.3) | Score(1.95) | Cohort Avg(1.95) = 17.4
CK_COLS = [1.2 * cm, 12.3 * cm, 1.95 * cm, 1.95 * cm]


def checklistTable(mc_cols, ck_data, ck_fields, cohort_mc_avgs):
    hdr = [p("#", "th_c"), p("Description", "th_l"),
           p("Score (/1)", "th_c"), p("Cohort Avg (/1)", "th_c")]
    rows = [hdr]
    student_scores = []
    for mc in mc_cols:
        desc  = ck_fields.get(mc, "")
        resp  = ck_data.get(mc)
        score = textScore(resp) if resp else None
        if score is not None:
            student_scores.append(score)
        c_avg = cohort_mc_avgs.get(mc)
        rows.append([
            p(mc, "td_c"),
            Paragraph(
                desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
                ST["td_wrap"],
            ),
            p(f"{score:.2f}" if score is not None else "-", "td_c"),
            p(f"{c_avg:.2f}" if c_avg is not None else "-", "td_c"),
        ])

    st_avg  = round(sum(student_scores) / len(student_scores), 3) if student_scores else None
    c_avgs  = [cohort_mc_avgs.get(mc) for mc in mc_cols if cohort_mc_avgs.get(mc) is not None]
    c_avg_t = round(sum(c_avgs) / len(c_avgs), 3) if c_avgs else None
    rows.append([
        p("", "td_c"),
        p("Overall Average", "td_b"),
        p(f"{st_avg * 100:.1f}%" if st_avg is not None else "-", "td_bc"),
        p(f"{c_avg_t * 100:.1f}%" if c_avg_t is not None else "-", "td_bc"),
    ])

    style = list(_TBL_BASE) + [
        ("BACKGROUND", (0, -1), (-1, -1), TOTAL),
        ("LINEABOVE",  (0, -1), (-1, -1),  1, UNI),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [WHITE, LIGHT]),
    ]
    for ri, mc in enumerate(mc_cols, 1):
        resp  = ck_data.get(mc)
        sc    = textScore(resp) if resp else None
        c_avg = cohort_mc_avgs.get(mc)
        if sc is not None:
            bg = scBg(sc)
            if bg:
                style.append(("BACKGROUND", (2, ri), (2, ri), bg))
            if sc == 0.0:
                style.append(("TEXTCOLOR", (2, ri), (2, ri), WHITE))
        # if c_avg is not None:
        #     bg = scBg(c_avg)
        #     if bg:
        #         style.append(("BACKGROUND", (3, ri), (3, ri), bg))
    for col, avg in [(2, st_avg), (3, c_avg_t)]:
        if avg is not None:
            bg = scBg(avg)
            if bg:
                style.append(("BACKGROUND", (col, -1), (col, -1), bg))

    t = Table(rows, colWidths=CK_COLS)
    t.setStyle(TableStyle(style))
    return t


# -- Cohort stats --------------------------------------------------------------
def computeCohortStats(data, station_mc_cols=None):
    """Compute cohort-level averages from a list of submitted assessment records.

    Args:
        data:             list of filtered, submitted OSCE records.
        station_mc_cols:  dict mapping station int -> list of MC column names.
                          Defaults to DEFAULT_STATION_MC_COLS.

    Returns:
        cohort_scale_avgs  - {station: {scale_key: avg}}
        cohort_mc_avgs     - {station: {mc_key: avg}}
        ck_fields          - {station: {mc_key: description}}
        sc_fields          - {scale_key: {str(value): label}}
        by_student         - {student_name: {station: record}}
    """
    if station_mc_cols is None:
        station_mc_cols = DEFAULT_STATION_MC_COLS

    stations = sorted(station_mc_cols.keys())

    # Scale averages
    cohort_scale_avgs = {s: {} for s in stations}
    for r in data:
        st = r.get("station")
        if st not in cohort_scale_avgs:
            continue
        ad = (r.get("form") or {}).get("data", {}).get("assessor", {}) or {}
        for k, v in ad.items():
            if k.startswith("scale-") and isinstance(v, dict):
                rv = v.get("scale")
                if rv:
                    try:
                        cohort_scale_avgs[st].setdefault(k, []).append(int(rv))
                    except (TypeError, ValueError):
                        pass
    for st in stations:
        cohort_scale_avgs[st] = {
            k: round(sum(v) / len(v), 2)
            for k, v in cohort_scale_avgs[st].items() if v
        }

    # MC / checklist averages
    cohort_mc_avgs = {s: {} for s in stations}
    for r in data:
        st = r.get("station")
        if st not in cohort_mc_avgs:
            continue
        ad = (r.get("form") or {}).get("data", {}).get("assessor", {}) or {}
        ck_data = None
        for k, v in ad.items():
            if k != "comments" and not k.startswith("scale-") and isinstance(v, dict):
                ck_data = v
                break
        if not ck_data:
            continue
        for mc, lbl in ck_data.items():
            sc = textScore(lbl)
            if sc is not None:
                cohort_mc_avgs[st].setdefault(mc, []).append(sc)
    for st in stations:
        cohort_mc_avgs[st] = {
            k: round(sum(v) / len(v), 3)
            for k, v in cohort_mc_avgs[st].items() if v
        }

    # Field label lookups
    ck_fields, sc_fields = {}, {}
    for r in data:
        st   = r.get("station")
        form = r.get("form") or {}
        if st not in ck_fields:
            for ck, cv in (form.get("checklists") or {}).items():
                ck_fields[st] = cv.get("fields", {})
                break
        for sk, sv in (form.get("scales") or {}).items():
            if sk not in sc_fields:
                sc_fields[sk] = sv.get("fields", {})

    # Group by student
    by_student = defaultdict(dict)
    for r in data:
        by_student[r["student"]][r["station"]] = r

    return cohort_scale_avgs, cohort_mc_avgs, ck_fields, sc_fields, by_student


# -- PDF builder ---------------------------------------------------------------
def buildPdf(student, st_data, out_dir,
             cohort_scale_avgs, cohort_mc_avgs, ck_fields, sc_fields,
             station_mc_cols=None, station_scales=None,
             year=2026, course_code="ORAL10005"):
    """Build one student's OSCE feedback PDF.

    Args:
        student:           student name string.
        st_data:           dict of {station: record} for this student.
        out_dir:           output directory path.
        cohort_scale_avgs: from computeCohortStats().
        cohort_mc_avgs:    from computeCohortStats().
        ck_fields:         from computeCohortStats().
        sc_fields:         from computeCohortStats().
        station_mc_cols:   station -> MC columns override (default: DEFAULT_STATION_MC_COLS).
        station_scales:    station -> scale keys override (default: DEFAULT_STATION_SCALES).
        year:              assessment year shown in the header banner.
        course_code:       course code shown in the header banner (e.g. "ORAL10005").
    """
    if station_mc_cols is None:
        station_mc_cols = DEFAULT_STATION_MC_COLS
    if station_scales is None:
        station_scales = DEFAULT_STATION_SCALES

    path    = os.path.join(out_dir, f"{student.replace('/', '_')}.pdf")
    doc     = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.8 * cm,  bottomMargin=1.8 * cm,
        title=f"OSCE Report - {student}",
    )
    cohort  = next((st_data[s]["cohort"]  for s in st_data), "")
    subject = next((st_data[s]["subject"] for s in st_data), "")
    date    = next(
        (st_data[s]["datetime"][:10] for s in st_data if st_data[s].get("datetime")), ""
    )

    story = [
        headerBanner(student, cohort, subject, date, course_code=course_code, year=year),
        Spacer(1, 14),
    ]

    for idx, station in enumerate(sorted(st_data.keys())):
        if idx > 0:
            story.append(PageBreak())

        r  = st_data[station]
        ad = (r.get("form") or {}).get("data", {}).get("assessor", {}) or {}

        student_scales = {}
        for k, v in ad.items():
            if k.startswith("scale-") and isinstance(v, dict):
                rv = v.get("scale")
                if rv:
                    try:
                        student_scales[k] = int(rv)
                    except (TypeError, ValueError):
                        pass

        ck_data, ck_key = {}, None
        for k, v in ad.items():
            if k != "comments" and not k.startswith("scale-") and isinstance(v, dict):
                ck_data = v
                ck_key  = k
                break

        form_ck  = (r.get("form") or {}).get("checklists", {}) or {}
        ck_name  = form_ck.get(ck_key, {}).get("name", "") if ck_key else ""
        comments = (ad.get("comments") or "").strip()

        st_scale_keys = station_scales.get(station, [])
        mc_cols       = station_mc_cols.get(station, [])

        story.append(KeepTogether([stationBanner(station, ck_name, r.get("assessor", "-"))]))
        story.append(p("Scales", "sec_lbl"))
        story.append(scalesTable(
            st_scale_keys, student_scales,
            cohort_scale_avgs.get(station, {}), sc_fields,
        ))
        story.append(p("Checklist", "sec_lbl"))
        story.append(checklistTable(
            mc_cols, ck_data,
            ck_fields.get(station, {}), cohort_mc_avgs.get(station, {}),
        ))
        if comments:
            story.append(p("Assessor Comments", "sec_lbl"))
            story.append(p(comments, "comment"))

    doc.build(story)
