

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


def buildStudentFeedbackPdfV2(outPath, student, stations, stStats, examAvg=None, cohortLabel="DDS4",
                              hideOverall=False, logoBytes=None, showCutoff=True, maxScore=100,
                              bfHeading="failOnly", bfText="always", showSdbm=True, examLabel="OSCE",
                              ruleText=None, stationGapCm=0.35):
    """
    One student's feedback PDF in the V2 layout (same inputs as buildStudentFeedbackPdf).
      hideOverall : withhold the OVERALL MARK tile (outcome + counts stay)
      showSdbm    : False hides every 2 SDBM item (tile, table column, card figure, note)
      showCutoff  : False hides cutoff column / figure / bar marker
      bfHeading / bfText : "always" | "failOnly" | "never" (Borderline/Fail Info, as V1)
      examLabel   : sub-heading under the student name (e.g. "2026 OSCE")
      ruleText    : sentence explaining the overall outcome rule (None = generic)
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
        cols.append(("2 SDBM", 1.5 * cm, "thC"))
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

    def decorate(canv, doc):
        canv.saveState()
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
