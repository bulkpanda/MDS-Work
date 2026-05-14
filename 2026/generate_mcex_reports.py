"""
generate_mcex_reports.py  –  DENT90148 OMed per-student PDF reports
Banner matches getBannerDrawer() in Utils.py (uniColor #010d44).
"""

import os, re
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle,
)

# ── Paths ─────────────────────────────────────────────────────────────────────
EXCEL_PATH = "2026\\mcex\\DDS2\\mcex apr 15 scores.xlsx"
OUT_DIR    = "2026\\mcex\\DDS2\\mcex_reports 2"
os.makedirs(OUT_DIR, exist_ok=True)

# ── Palette — matches variableUtils.py ───────────────────────────────────────
UNI_COLOR = "#010d44"
TEXT_COLOR = "#4f5fb2"

C_UNI      = colors.HexColor(UNI_COLOR)
C_TEXT     = colors.HexColor(TEXT_COLOR)
C_GREY     = colors.HexColor("#404040")
C_LBLUE    = colors.HexColor("#DEEAF1")
C_GREEN    = colors.HexColor("#375623")   # dark green text
C_RED      = colors.HexColor("#c00000")   # dark red text
C_AMBER    = colors.HexColor("#bf8f00")   # dark amber text
C_GREEN_BG = colors.HexColor("#E2EFDA")   # pastel green badge bg
C_RED_BG   = colors.HexColor("#FCE4D6")   # pastel red badge bg
C_AMBER_BG = colors.HexColor("#FFF2CC")   # pastel amber badge bg
C_RED      = colors.HexColor("#c00000")   # solid dark red    (white text readable)
C_AMBER    = colors.HexColor("#bf8f00")   # solid dark amber  (white text readable)

# ── Page geometry ─────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
LEFT_MARGIN = RIGHT_MARGIN = 0.5 * inch   # matches variableUtils.leftMargin
TOP_MARGIN  = BOTTOM_MARGIN = 0.5 * inch
CONTENT_W   = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN   # 523.3 pt

BANNER_H      = 110                            # height of navy bar
BANNER_TOP    = PAGE_H - BANNER_H
# Spacer to push story below banner: banner overlaps first (TOP_MARGIN) of page
BANNER_SPACER = BANNER_H - TOP_MARGIN          # 110 - 36 = 74 pt

# ── Checklist ─────────────────────────────────────────────────────────────────
CHECKLIST = [
    ("MC1",  "Introduces self and explains purpose of consultation."),
    ("MC2",  "Uses open-ended question to allow patient to explain main concern/reason."),
    ("MC3",  "Site: Asks patient to point WHERE they feel the pain and where it extends."),
    ("MC4",  "Onset: Asks WHEN did the pain start and if there was a triggering event."),
    ("MC5",  "Timing/Duration: Asks if the pain is continuous or episodic and HOW LONG it lasts."),
    ("MC6",  "Character: Asks the patient to describe WHAT their pain FEELS LIKE."),
    ("MC7",  "Triggers, Aggravating & Relieving Factors: What BRINGS ON, WORSENS or STOPS the pain."),
    ("MC8",  "Severity: Uses a pain scale (e.g. 0-10) to gauge subjective intensity."),
    ("MC9",  "Associated Symptoms: Asks about swelling, numbness, fever, headache, nasal congestion, joint noises."),
    ("MC10", "Other body pain: Asks if the patient experiences pain elsewhere in their body."),
    ("MC11", "Impact: Is this affecting your eating, sleeping or daily activities?"),
    ("MC12", "Recount history item 1."),
    ("MC13", "Recount history item 2."),
    ("MC14", "Recount history item 3."),
    ("MC15", "Recount history item 4."),
    ("MC16", "Makes a decision: presenting complaint likely / unlikely / unclear to be within scope of practice."),
    ("MC17", "Communicates whether a referral is necessary to the patient and why (lay-terms)."),
    ("MC18", "Communicates a summary of relevant findings in technical terms."),
]
SECTION_HEADERS = {
    "MC1":  "History Taking",
    "MC12": "Recount of History Items",
    "MC16": "Clinical Decision Making",
}
GR_LABELS = {1:"Unsatisfactory", 2:"Borderline", 3:"Satisfactory", 4:"Good", 5:"Excellent"}
PR_LABELS = {
    1: "Level 1 - Not ready to practice in a clinical setting.",
    2: "Level 2 - Ready with continuous direct supervision.",
    3: "Level 3 - Ready with periodic direct supervision.",
    4: "Level 4 - Ready with indirect supervision.",
}


# ── Banner (matches getBannerDrawer in Utils.py) ───────────────────────────────
def getBannerDrawer(title, subtitle):
    def drawBanner(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_UNI)
        canvas.rect(0, BANNER_TOP, PAGE_W, BANNER_H, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        x = LEFT_MARGIN
        try:    canvas.setFont("Calibri-Bold", 22)
        except: canvas.setFont("Helvetica-Bold", 22)
        canvas.drawString(x, PAGE_H - 48, title)
        try:    canvas.setFont("Calibri-Bold", 15)
        except: canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(x, PAGE_H - 78, subtitle)
        canvas.restoreState()
    return drawBanner


# ── Styles ─────────────────────────────────────────────────────────────────────
def build_styles():
    base = getSampleStyleSheet()
    s = {}
    def ps(name, **kw):
        s[name] = ParagraphStyle(name, parent=base["Normal"], **kw)

    ps("meta_label", fontSize=8,  fontName="Helvetica-Bold",   textColor=colors.HexColor("#aabbdd"), alignment=TA_CENTER, spaceAfter=3)
    ps("meta_value", fontSize=12, fontName="Helvetica-Bold",   textColor=colors.white, alignment=TA_CENTER, spaceAfter=0)
    ps("badge_val",  fontSize=26, fontName="Helvetica-Bold",   textColor=colors.white, alignment=TA_CENTER, spaceAfter=2)
    ps("badge_sub",  fontSize=8,  fontName="Helvetica",        textColor=colors.white, alignment=TA_CENTER, leading=10, spaceAfter=0)
    ps("subheading", fontSize=14, fontName="Helvetica-Bold",   textColor=C_UNI,  alignment=TA_CENTER, spaceAfter=6, spaceBefore=2)
    ps("subheading_l",fontSize=13,fontName="Helvetica-Bold",   textColor=C_UNI,  alignment=TA_LEFT,   spaceAfter=5, spaceBefore=2)
    ps("cl_section", fontSize=10, fontName="Helvetica-Bold",   textColor=C_UNI,  spaceBefore=8, spaceAfter=3)
    ps("cl_pass",    fontSize=9,  fontName="Helvetica",        textColor=colors.HexColor("#1a5c1a"), leading=13, leftIndent=8, spaceAfter=2)
    ps("cl_fail",    fontSize=9,  fontName="Helvetica",        textColor=C_RED,  leading=13, leftIndent=8, spaceAfter=2)
    ps("pr_desc",    fontSize=9,  fontName="Helvetica",        textColor=C_GREY, spaceAfter=10)
    ps("comment",    fontSize=10, fontName="Helvetica-Oblique",textColor=C_GREY, leading=14, alignment=TA_JUSTIFY)
    ps("footer",     fontSize=8,  fontName="Helvetica-Oblique",textColor=colors.grey, alignment=TA_CENTER)
    return s


def _badge_color(val, max_val):
    """Map a value to (bg_color, text_color) using original pastel backgrounds."""
    ratio = val / max_val if max_val else 0
    if ratio < 0.6:   return C_RED_BG,   C_RED
    if ratio < 0.8:  return C_AMBER_BG, C_AMBER
    return C_GREEN_BG, C_GREEN


def _meta_strip(student, assessor, date_str, styles):
    """Three equal-width cells, navy background, matching banner colour."""
    col_w = CONTENT_W / 3

    def cell(label, value):
        return [Paragraph(label, styles["meta_label"]),
                Paragraph(value, styles["meta_value"])]

    tbl = Table(
        [[cell("STUDENT", student), cell("ASSESSOR", assessor), cell("DATE", date_str)]],
        colWidths=[col_w, col_w, col_w],
        rowHeights=[52],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_UNI),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
        ("LINEAFTER",     (0,0), (1,-1),  0.5, colors.HexColor("#2a3a7a")),
    ]))
    return tbl


def _scale_badges(gr, pr, score, pct, styles):
    """Three coloured badges — pastel backgrounds with matching dark text."""
    col_w = CONTENT_W / 3

    gr_bg, gr_fg = _badge_color(gr, 5)
    sc_bg, sc_fg = _badge_color(score, 18)

    def badge(big_text, small_text, bg, fg):
        val_style = ParagraphStyle("bv", parent=styles["badge_val"], textColor=fg)
        sub_style = ParagraphStyle("bs", parent=styles["badge_sub"], textColor=fg)
        cell = Table(
            [[Paragraph(big_text,   val_style)],
             [Paragraph(small_text, sub_style)]],
        )
        cell.setStyle(TableStyle([
            ("ALIGN",  (0,0),(-1,-1), "CENTER"),
            ("VALIGN", (0,0),(-1,-1), "MIDDLE"),
            ("BACKGROUND", (0,0),(-1,-1), bg),
            ("TOPPADDING",    (0,0),(-1,-1), 8),
            ("BOTTOMPADDING", (0,0),(-1,-1), 8),
            ("LEFTPADDING",   (0,0),(-1,-1), 6),
            ("RIGHTPADDING",  (0,0),(-1,-1), 6),
        ]))
        return cell

    row = Table(
        [[badge(str(gr),       f"Global Rating: {gr}/5 - {GR_LABELS.get(gr,'')}", gr_bg, gr_fg),
          badge(str(pr),       f"Practice Readiness: Level {pr}",                 *_badge_color(pr, 4)),
          badge(f"{score}/18", f"{pct:.0f}%  Score",                              sc_bg,   sc_fg)]],
        colWidths=[col_w, col_w, col_w],
    )
    row.setStyle(TableStyle([
        ("VALIGN",      (0,0),(-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0),(-1,-1), 0),
        ("RIGHTPADDING",(0,0),(-1,-1), 4),
        ("TOPPADDING",  (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1), 0),
    ]))
    return row


def generate_pdf(row, styles, out_path):
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        topMargin=TOP_MARGIN, bottomMargin=BOTTOM_MARGIN,
        leftMargin=LEFT_MARGIN, rightMargin=RIGHT_MARGIN,
    )

    assessor = row["assessorname2"] if pd.notna(row.get("assessorname2")) else row["assessorname"]
    if pd.notna(row["datetimeutc"]):
        dt = pd.to_datetime(row["datetimeutc"])
        date_str = f"{dt.day} {dt.strftime('%B %Y')}"
    else:
        date_str = ""

    gr    = int(row["GR"])
    pr    = int(row["PR"])
    pct   = float(row["%Score"])
    score = int(row["Score"])
    comments = str(row["comments"]).strip() if pd.notna(row["comments"]) else ""

    story = []
    story.append(Spacer(1, BANNER_SPACER))

    # Metadata strip
    story.append(_meta_strip(row["studentname"], assessor, date_str, styles))
    story.append(Spacer(1, 10))

    # Scale badges
    story.append(_scale_badges(gr, pr, score, pct, styles))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Practice Readiness:</b> {PR_LABELS.get(pr, f'Level {pr}')}", styles["pr_desc"]))
    story.append(HRFlowable(width="100%", thickness=1, color=C_LBLUE, spaceAfter=10))

    # Checklist
    story.append(Paragraph("OMed Checklist", styles["subheading"]))
    for code, label in CHECKLIST:
        if code in SECTION_HEADERS:
            story.append(Paragraph(SECTION_HEADERS[code], styles["cl_section"]))
        val  = int(row.get(code, 0))
        sty  = styles["cl_pass"] if val == 1 else styles["cl_fail"]
        mark = "[Yes]" if val == 1 else "[No] "
        story.append(Paragraph(f"{mark}  <b>{code}</b>  {label}", sty))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=C_LBLUE, spaceAfter=8))

    # Comments
    if comments:
        story.append(Paragraph("Assessor Comments", styles["subheading_l"]))
        story.append(Paragraph(f'"{comments}"', styles["comment"]))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=C_UNI, spaceAfter=6))
    # story.append(Paragraph("This report is intended for the individual student only.", styles["footer"]))

    doc.build(story, onFirstPage=getBannerDrawer(
        "DENT90148 Oral Medicine Clinical Examination",
        f"OMed History Taking Assessment",
    ))


def main():
    df = pd.read_excel(EXCEL_PATH)
    styles = build_styles()
    for _, row in df.iterrows():
        name_clean = re.sub(r'[^\w\s-]', '', str(row["studentname"])).strip()
        generate_pdf(row, styles, os.path.join(OUT_DIR, f"{name_clean}.pdf"))
    print(f"Done - {len(df)} PDFs written to: {OUT_DIR}")

if __name__ == "__main__":
    main()