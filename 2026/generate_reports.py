"""
generate_reports.py
====================
Generates one PDF feedback report per student for Class Test 1 (DENT90112 Cariology).

Usage:
    python generate_reports.py

Inputs (edit paths below):
    EXCEL_PATH  – Canvas quiz export (.xlsx)
    OUT_DIR     – Folder where per-student PDFs are written

Logic:
    • Multiple attempts per student are resolved by keeping the highest-scoring
      attempt (ties broken by highest attempt number).
    • Class % correct per question is calculated across those best attempts.
    • Class average % is also computed from best attempts.
"""

import os
import re
import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether
)

# ── Paths ─────────────────────────────────────────────────────────────────────
EXCEL_PATH = r"2026\Extra\dds1 test feedback\Class Test 1_ Cariology_DENT90112.xlsx"
OUT_DIR    = r"2026\Extra\dds1 test feedback\student_reports"
os.makedirs(OUT_DIR, exist_ok=True)

# ── Question feedback texts (Q1–Q20, in order) ────────────────────────────────
# These are the explanations copied from the Word template.
FEEDBACK = [
    # Q1
    "To answer this question correctly, you needed to recognise that proteins and "
    "glycoproteins are the primary source of nutrients in saliva for oral bacteria. "
    "While fatty acids and lysozyme are found in saliva, they are not the main source "
    "of nutrients for bacteria.",

    # Q2
    "To answer this question correctly, you needed to recognise that both "
    "<i>Streptococcus mutans</i> and <i>Veillonella dispar</i> are well adapted to the "
    "pH drop in dental plaque that follows the breakdown of dietary sugar into acids, "
    "but that not both bacterial species can break down dietary sugars to form acid. "
    "Many other bacteria in dental plaque in addition to <i>S. mutans</i> can break down "
    "sugar. <i>V. dispar</i> however does not break dietary sugars into acid. This organism "
    "takes lactate from the plaque environment and converts this into weaker acids.",

    # Q3
    "This question was testing your knowledge of the factors that influence the microbial "
    "composition of the oral microbiome at different stages of life. While both birth mode "
    "and infant feeding practices are thought to influence the composition of the oral "
    "microbiota in babies, the oral microbiota from the saliva of the main caregiver "
    "(in published literature this is usually the mother) is likely to have a greater "
    "influence over the composition of the oral microbiota of a young child.",

    # Q4
    "This question was referring to Koch's postulates. To answer this question correctly, "
    "you needed to recognise that plaque-related diseases are polymicrobial, which means "
    "we cannot apply these criteria to them. The causative microorganisms of oral diseases "
    "are not exogenous pathogens but are considered opportunistic pathogens and are part "
    "of our normal oral microbiota. Multiple species of bacteria, and sometimes fungi, "
    "work together to cause the tissue damage that is seen in both dental caries and "
    "periodontal diseases.",

    # Q5
    "This question was about glucosyltransferase enzymes, one of the major virulence "
    "factors of <i>Streptococcus mutans</i>. To answer this question correctly you needed "
    "to recognise that these enzymes produce extracellular polysaccharides from sucrose.",

    # Q6
    "This question was asking you to consider the advantages and disadvantages of two "
    "different laboratory techniques which are commonly used to characterise oral microbial "
    "communities. Both 16S rRNA gene sequencing and bacterial culture techniques enable "
    "assessment of biodiversity and require both technical expertise. To answer this "
    "question correctly, you needed to recognise that DNA sequencing does not require "
    "viable microorganisms, whereas these are essential for bacterial culture techniques.",

    # Q7
    "To answer this question correctly, you needed to recognise that while many factors "
    "such as age, geographic location and genetics may contribute to differences in "
    "microbial communities, the primary factor that influences the site-specific "
    "colonisation of microorganisms in the human body is the local environment at "
    "different sites.",

    # Q8
    "This question was testing your knowledge of the role of extracellular DNA (eDNA) "
    "in the biofilm matrix. To answer this question correctly you needed to recognise "
    "that eDNA is thought to play an important role in maintaining the structural "
    "integrity of dental plaque.",

    # Q9
    "Knowledge of the Ecological Plaque Hypothesis was tested here. You needed to be "
    "able to recognise which lifestyle factor would have the greatest influence on dental "
    "caries via its relationship to the environment in dental plaque. The most common "
    "misconceptions with this question are that the presence of dental plaque or maternal "
    "transfer of <i>Streptococcus mutans</i> would have the greatest influence.",

    # Q10
    "This question was asking you to demonstrate your understanding of the term "
    "'aciduricity'. The most common error students make is to confuse aciduricity – "
    "the ability of a microorganism to withstand acidic environmental conditions and "
    "continue to metabolise and replicate – and acidurance – the ability of a "
    "microorganism to produce acid as a metabolic by-product.",

    # Q11
    "This question tested your ability to name and differentiate the proteins involved "
    "in biomineralisation of enamel and dentine, as well as not confuse the names of "
    "proteins with cell types involved in biomineralisation of these tissues.",

    # Q12
    "This question tested your understanding of the critical pH, and how it relates to "
    "enamel, dentine, as well as the degree of saturation. It was important to understand "
    "there are differences in the critical pH of enamel and dentine, and be able to "
    "associate the critical pH to your understanding of the degree of saturation concepts.",

    # Q13
    "This question tested your understanding of the composition of the dental hard tissues "
    "in terms of organic, inorganic and water composition.",

    # Q14
    "This question required selection of the correct statement. It required an understanding "
    "of kinetics vs. thermodynamics in terms of crystal formation (phase transformation), "
    "the effect of ion substitution in apatite, as well as the differences and similarities "
    "between the common calcium phosphate phases.",

    # Q15
    "This question tested your understanding of fluoride reactivity and concentration "
    "within the dental hard tissues, both enamel and dentine.",

    # Q16
    "This question tested your understanding of fluoride in terms of the chemistry of "
    "apatite crystals. You were required to know how fluoride might affect solubility and "
    "stability of apatite crystals depending on its concentration in the apatite, as well "
    "as basic definitions.",

    # Q17
    "This question required a sound understanding of the order of events in dentine "
    "demineralisation. Selection of a true statement was required, and illogical scenarios "
    "were presented to test your logic of the biochemistry of caries, specifically as it "
    "relates to dentine: bacterial invasion, reactive dentine formation, dentine sclerosis "
    "and degradation of the organic matrix.",

    # Q18
    "This question tested your understanding of the changes in plaque and enamel fluid in "
    "terms of calcium, phosphate and hydroxide concentration under different conditions "
    "during the caries process. You were required to know what increases/decreases these "
    "concentrations at various points in the sequence of events, in relation to specific "
    "locations in the microenvironment.",

    # Q19
    "This question required you to know the path of demineralisation in enamel in relation "
    "to the structure of enamel.",

    # Q20
    "This question required you to understand the structure of a specific biological cell. "
    "The cell could be determined from its shape and function in the diagram.",
]

assert len(FEEDBACK) == 20, "Must have exactly 20 feedback entries"

# ── Colour palette ────────────────────────────────────────────────────────────
DARK_BLUE   = colors.HexColor("#1F3864")
MID_BLUE    = colors.HexColor("#2E75B6")
LIGHT_BLUE  = colors.HexColor("#DEEAF1")
GREEN       = colors.HexColor("#375623")
RED         = colors.HexColor("#C00000")
GREY_TEXT   = colors.HexColor("#404040")
LIGHT_GREY  = colors.HexColor("#F2F2F2")


def build_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["title"] = ParagraphStyle(
        "title", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=14,
        textColor=DARK_BLUE, spaceAfter=4,
    )
    styles["subtitle"] = ParagraphStyle(
        "subtitle", parent=base["Normal"],
        fontName="Helvetica", fontSize=10,
        textColor=MID_BLUE, spaceAfter=12,
    )
    styles["salutation"] = ParagraphStyle(
        "salutation", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=11,
        textColor=DARK_BLUE, spaceAfter=6,
    )
    styles["body"] = ParagraphStyle(
        "body", parent=base["Normal"],
        fontName="Helvetica", fontSize=10,
        textColor=GREY_TEXT, leading=15,
        alignment=TA_JUSTIFY, spaceAfter=8,
    )
    styles["score_label"] = ParagraphStyle(
        "score_label", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=11,
        textColor=DARK_BLUE, spaceAfter=4,
    )
    styles["score_value"] = ParagraphStyle(
        "score_value", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=20,
        textColor=MID_BLUE, spaceAfter=12,
    )
    styles["q_header_correct"] = ParagraphStyle(
        "q_header_correct", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=10,
        textColor=GREEN, spaceAfter=2,
    )
    styles["q_header_incorrect"] = ParagraphStyle(
        "q_header_incorrect", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=10,
        textColor=RED, spaceAfter=2,
    )
    styles["q_feedback"] = ParagraphStyle(
        "q_feedback", parent=base["Normal"],
        fontName="Helvetica", fontSize=9,
        textColor=GREY_TEXT, leading=13,
        leftIndent=12, spaceAfter=6,
    )
    styles["closing"] = ParagraphStyle(
        "closing", parent=base["Normal"],
        fontName="Helvetica-Oblique", fontSize=10,
        textColor=GREY_TEXT, spaceBefore=12, spaceAfter=4,
    )
    return styles


def generate_pdf(student_row, class_avg_pct: float, class_pct: list[float],
                 styles: dict, out_path: str):
    """Build one student's PDF report."""
    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        topMargin=2*cm, bottomMargin=2*cm,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
    )

    first_name   = str(student_row["name"]).split()[0]
    total_score  = int(student_row["total_score"])

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("DENT90112 Plaque Related Diseases", styles["title"]))
    story.append(Paragraph("Class Test 1 – Cariology: Individual Feedback Report", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=DARK_BLUE, spaceAfter=12))

    # ── Salutation ────────────────────────────────────────────────────────────
    story.append(Paragraph(f"Dear {first_name},", styles["salutation"]))
    story.append(Paragraph(
        f"The results for Class Test 1 for DENT90112 Plaque Related Diseases have been "
        f"finalised. Overall, the class scored an average of <b>{class_avg_pct:.0f}%</b>.",
        styles["body"]
    ))
    story.append(Paragraph(
        "To provide you with personal feedback on your performance, we are sending you "
        "the details of your results on Class Test 1.",
        styles["body"]
    ))

    # ── Score box ─────────────────────────────────────────────────────────────
    story.append(Paragraph("Your Class Test 1 score:", styles["score_label"]))
    story.append(Paragraph(f"{total_score} / 20", styles["score_value"]))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_BLUE, spaceAfter=10))

    # ── Intro to question breakdown ───────────────────────────────────────────
    story.append(Paragraph(
        "Below are the concepts covered in the MCQ section, with your score (0/1 or 1/1) "
        "marked for each question and the class % correct.",
        styles["body"]
    ))

    # ── Per-question feedback ─────────────────────────────────────────────────
    for q in range(20):
        q_score = int(student_row[f"q{q+1}_score"])
        pct     = class_pct[q]
        result  = "Correct" if q_score == 1 else "Incorrect"
        hdr_style = styles["q_header_correct"] if q_score == 1 else styles["q_header_incorrect"]

        header_text = (
            f"Q{q+1}: {result} &nbsp; {q_score}/1 &nbsp; "
            f"<font color='#2E75B6'>({pct:.0f}% of the class answered correctly)</font>"
        )

        block = KeepTogether([
            Paragraph(header_text, hdr_style),
            Paragraph(FEEDBACK[q], styles["q_feedback"]),
        ])
        story.append(block)

    # ── Closing ───────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_BLUE, spaceBefore=8, spaceAfter=8))
    story.append(Paragraph(
        "We hope you found this feedback useful in guiding your study,",
        styles["closing"]
    ))
    story.append(Paragraph("<b>Samantha Byrne and James Fernando</b>", styles["body"]))

    doc.build(story)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # 1. Load raw Excel (header in row 0)
    df_raw = pd.read_excel(EXCEL_PATH, header=None)
    header = df_raw.iloc[0].tolist()
    df = df_raw.iloc[1:].reset_index(drop=True)

    N_QUESTIONS = 20
    META        = 8  # first 8 cols are metadata

    # Rename columns for clarity
    col_names = (
        ["name", "id", "sis_id", "section", "section_id",
         "section_sis_id", "submitted", "attempt"]
        + [item for i in range(N_QUESTIONS)
           for item in (f"q{i+1}_ans", f"q{i+1}_score")]
        + ["n_correct", "n_incorrect", "total_score", "%_score"]
    )
    df.columns = col_names

    # Coerce numeric cols
    for col in ["attempt", "total_score", "%_score"] + [f"q{i+1}_score" for i in range(N_QUESTIONS)]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 2. Best attempt per student (highest score, then highest attempt number)
    best = (
        df.sort_values(["total_score", "attempt"], ascending=[False, False])
          .drop_duplicates(subset=["id"])
          .reset_index(drop=True)
    )

    # 3. Class statistics (across best attempts)
    class_avg_pct = best["total_score"].mean() / 20 * 100
    class_pct = [
        best[f"q{q+1}_score"].mean() * 100
        for q in range(N_QUESTIONS)
    ]

    # 4. Build styles once
    styles = build_styles()

    # 5. Generate one PDF per student
    styles_built = build_styles()
    generated = 0
    for _, row in best.iterrows():
        ssid = row["sis_id"]
        name_clean = re.sub(r'[^\w\s-]', '', str(row["name"])).strip().replace(" ", "_")
        out_path   = os.path.join(OUT_DIR, f"{name_clean} ({ssid}) Feedback.pdf")
        generate_pdf(row, class_avg_pct, class_pct, styles_built, out_path)
        generated += 1

    print(f"Done — {generated} PDFs written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
