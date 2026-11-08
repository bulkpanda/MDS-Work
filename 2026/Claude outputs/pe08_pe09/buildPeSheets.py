"""Build DDS1 PE-08 / PE-09 strict marking sheets (incl. unsubmitted assessor drafts) + data-completeness audit."""
import json, math, os, re, sys
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
sys.path.insert(0, os.path.expanduser('~/mnt/2026'))
os.chdir(os.path.expanduser('~/mnt/2026'))
import dds1_pe_utils as pe
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, PatternFill, Side, Font
from openpyxl.comments import Comment
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter as colL

MELB = ZoneInfo("Australia/Melbourne")
SESS = {  # code: (title, weightage, expectedDates)
    "PE-06": ("Session 6: Preclinical Test", "20%", {"2026-09-18"}),
    "PE-08": ("Session 8: Exam Preparation Session", "10%", {"2026-10-15", "2026-10-16"}),
    "PE-09": ("Session 9: Final Preclinical Test", "25%", {"2026-10-23"}),
}
GR = {1: "Starting", 2: "Emerging", 3: "Developing", 4: "Competent", 5: "Exemplary"}
NAVY, BLUE, LHEAD, LSEC = "1F3864", "2E75B6", "D6E4F0", "EBF3FB"
GREEN, YELLOW, RED, ORANGE, RES, GREY, AMBER = "C6EFCE", "FFEB9C", "FFC7CE", "F4B183", "FFF2CC", "D9D9D9", "FCE4D6"
thin = Side(style="thin", color="BFBFBF"); BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
fill = lambda c: PatternFill("solid", fgColor=c)

def put(ws, r, c, v, bold=False, sz=10, color=None, bg=None, fmt=None, wrap=False, h="center"):
    cell = ws.cell(r, c, v)
    cell.font = Font(bold=bold, size=sz, color=color); cell.border = BOX
    cell.alignment = Alignment(horizontal=h, vertical="center", wrap_text=wrap)
    if bg: cell.fill = fill(bg)
    if fmt: cell.number_format = fmt
    return cell

def fmtTs(s):
    if not s: return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(MELB).strftime("%d %b %H:%M")

# ── t-distribution p-value (no scipy) ──
def betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1; c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-30 else 1e-30); h = d
    for m in range(1, 300):
        m2 = 2 * m; aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30); c = 1 + aa / c; h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30); c = 1 + aa / c; de = d * c; h *= de
        if abs(de - 1) < 1e-12: break
    return h
def betai(a, b, x):
    if x <= 0 or x >= 1: return 0.0 if x <= 0 else 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    return bt * betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * betacf(b, a, 1 - x) / b
def tPval(t, df): return betai(df / 2, 0.5, df / (df + t * t))

# ── load ──
JSON_PATH = os.environ.get("PE_JSON", os.path.expanduser("~/mnt/2026/temp 2026 caf dds1.json"))
recs = json.load(open(JSON_PATH, encoding="utf-8"))
excl = pe._excludedStudents(None)
roster, forms = {}, defaultdict(list)
for r in recs:
    if r.get("cohort") != "DDS1": continue
    st = r.get("student") or {}; sn = str(st.get("student_number", "")).strip()
    if not sn or sn in excl or pe._isTestAccount(st): continue
    roster[sn] = dict(sn=sn, last=(st.get("last_name") or "").strip(), first=(st.get("first_name") or "").strip())
    for f in r.get("forms") or []:
        fc = f.get("form_context") or {}
        for c in fc.get("checklists") or []:
            if c.get("code") in SESS:
                d = pe._localDate(fc.get("datetime") or r.get("datetime"))
                forms[(sn, c["code"])].append(dict(f=f, date=str(d) if d else "",
                                                   subject=r.get("subject"), recId=r.get("id")))
weights = pe.loadPeWeights()

def buildSession(code):
    title, weightage, expDates = SESS[code]; w = weights[code]
    # meta from any form's assessor config
    meta, cfgCounts = None, defaultdict(int)
    for k, fl in forms.items():
        if k[1] != code: continue
        for x in fl:
            m = pe._checklistMeta(x["f"], code, "assessor") or {}
            cfgCounts[len(m)] += 1
            if meta is None or len(m) > len(meta): meta = m
    mcs = sorted(meta, key=lambda m: int(m[2:]))
    mcInfo = {}
    for mc in mcs:
        n = len(meta[mc]["valid"]); _, mx = pe.peLevelPoints(n, n, True)
        mcInfo[mc] = dict(name=meta[mc]["name"], item=meta[mc]["itemId"], n=n, max=mx,
                          sec=pe.PE_ITEMS[meta[mc]["itemId"]][1], w=w.get(meta[mc]["itemId"]))
    rows, issues, adjust, dups = [], [], [], []
    def issue(stu, cat, detail, sev="Amber"):
        issues.append(dict(last=stu["last"], first=stu["first"], sn=stu["sn"], cat=cat, detail=detail, sev=sev))
    for sn, stu in roster.items():
        fl = forms.get((sn, code), [])
        if not fl:
            issue(stu, "No form", f"No {code} form exists for this student", "Red"); continue
        def nAns(x): return len(pe._peAnswers(x["f"].get("assessor_data"), code))
        fl = sorted(fl, key=lambda x: (bool(x["f"].get("submitted_by_assessor")), nAns(x) > 0,
                                        bool(x["f"].get("submitted_by_student")), x["f"].get("created_at") or ""), reverse=True)
        keep = fl[0]; f = keep["f"]
        for x in fl[1:]:
            dups.append(dict(sn=sn, last=stu["last"], first=stu["first"], kept=f["id"], dropped=x["f"]["id"],
                             droppedSubA=x["f"].get("submitted_by_assessor"), droppedAns=nAns(x)))
            issue(stu, "Duplicate form", f"{len(fl)} forms; kept id {f['id']}, ignored id {x['f']['id']} "
                  f"(assessor-submitted={bool(x['f'].get('submitted_by_assessor'))}, answers={nAns(x)})")
        ad, sd = f.get("assessor_data") or {}, f.get("student_data") or {}
        subA, subS = bool(f.get("submitted_by_assessor")), bool(f.get("submitted_by_student"))
        ans = pe._peAnswers(ad, code)
        scores, adjCells, num, den = {}, {}, 0.0, 0.0
        for mc in mcs:
            key = ans.get(mc)
            if key is None: scores[mc] = None; continue
            rank, n, adj = pe._scoreOption(key, meta[mc]["valid"], "down")
            pts, mx = pe.peLevelPoints(rank, n, True)
            scores[mc] = pts
            if adj != key:
                raw = (pe._asDict(ad.get("checklists")).get(code) or {}).get(mc) or {}
                orig = f"{key} · {raw.get('value') if isinstance(raw, dict) else ''}"
                adjCells[mc] = orig
                adjust.append(dict(last=stu["last"], first=stu["first"], crit=meta[mc]["name"], mc=mc, orig=orig,
                                   applied=f"{adj} · {meta[mc]['labels'].get(adj, adj)} → {pts}/{mx}"))
            if mcInfo[mc]["w"]:
                num += pts / mx * mcInfo[mc]["w"]; den += mcInfo[mc]["w"]
        missing = [mc for mc in mcs if scores[mc] is None]
        raw = round(100 * num / den, 2) if den else None          # re-weighted over answered items
        rawScoreFull = round(num, 2) if den else None             # Σ with unanswered items = 0 (out of 100)
        formCfg = len(pe._checklistMeta(f, code, "assessor") or {})
        gr = pe._scale(ad, "scale-global-rating"); pr = pe._scale(ad, "scale-practice-readiness")
        aRef = ((ad.get("texts") or {}).get("reflection") or "").strip()
        sRef = ((sd.get("texts") or {}).get("reflection") or "").strip()
        status = "Submitted" if subA else ("Draft – not submitted" if ans else "Opened – blank")
        rows.append(dict(stu=stu, f=f, assessor=(f.get("assessor_name") or "").strip(), opened=fmtTs(f.get("created_at")),
                         submitted=fmtTs(f.get("updated_at")) if subA else None, status=status, subS=subS,
                         scores=scores, adj=adjCells, raw=raw, rawAnswered=rawScoreFull, missing=missing,
                         gr=gr, pr=pr, aRef=aRef, sRef=sRef, date=keep["date"]))
        # completeness checks
        if not subA:
            issue(stu, "Assessor not submitted", f"Form id {f['id']} is an assessor DRAFT — scored from saved answers" if ans
                  else f"Form id {f['id']} opened but assessor checklist is blank", "Amber" if ans else "Red")
        if missing and len(missing) == len(mcs):
            issue(stu, "Checklist blank", "No assessor checklist answers saved", "Red")
        elif missing:
            secs = sorted({mcInfo[mc]["sec"] for mc in missing}, key=pe.PE_SECTIONS.index)
            why = f"form's DASH checklist config has only {formCfg} of {len(mcs)} items" if formCfg < len(mcs) else "assessor left items blank"
            issue(stu, "Missing checklist answers", f"{len(missing)}/{len(mcs)} items unanswered ({', '.join(secs)}; {why}). "
                  f"% re-weighted over answered = {raw}; with unanswered = 0 → {rawScoreFull}/100", "Red")
        if gr is None: issue(stu, "Missing Global Rating", "GR blank", "Red")
        if pr is None: issue(stu, "Missing Practice Readiness", "PR blank")
        if pe._scale(ad, "scale-professionalism") is None: issue(stu, "Missing Professionalism", "Professionalism scale blank")
        if not aRef: issue(stu, "Missing assessor comment", "Assessor reflection blank")
        if not subS: issue(stu, "Student not submitted", "Student side not submitted")
        elif not sRef: issue(stu, "Missing student reflection", "Student submitted with blank reflection")
        if not (f.get("assessor_name") or "").strip(): issue(stu, "Missing assessor", "No assessor name on form", "Red")
        if keep["date"] not in expDates:
            issue(stu, "Unexpected session date", f"Form dated {keep['date']} (expected {', '.join(sorted(expDates))}) — check correct checklist code")
    rows.sort(key=lambda x: (x["stu"]["last"].lower(), x["stu"]["first"].lower()))
    return dict(cfgCounts=dict(cfgCounts), code=code, title=title, weightage=weightage, mcs=mcs, mcInfo=mcInfo, rows=rows, issues=issues,
                adjust=adjust, dups=dups, meta=meta)

def writeWorkbook(S, path):
    code, title, mcs, mcInfo, rows = S["code"], S["title"] + " (STRICT scoring)", S["mcs"], S["mcInfo"], S["rows"]
    dateStr = sorted({r["date"] for r in rows}, key=lambda d: -sum(1 for x in rows if x["date"] == d))[0]
    dateLong = datetime.strptime(dateStr, "%Y-%m-%d").strftime("%-d %B %Y")
    nSub = sum(r["status"] == "Submitted" for r in rows); nDraft = len(rows) - nSub
    wb = Workbook(); ws = wb.active; ws.title = "Marking Sheet"
    nInfo, nMc = 8, len(mcs); cRes = nInfo + nMc + 1; lastC = cRes + 4 + 1
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=lastC)
    put(ws, 1, 1, title, True, 13, "FFFFFF", NAVY)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=lastC)
    put(ws, 2, 1, f"Date: {dateLong}   |   Cohort: DDS1   |   Subject: DENT90141   |   Total: 100   |   Weightage: {S['weightage']}   |   "
        f"Source: {code}   |   n={len(rows)}   |   Assessor-submitted: {nSub}   |   Drafts (unsubmitted, included): {nDraft}   |   Data pulled: {datetime.now(MELB):%d %b %Y %H:%M}",
        False, 9, "FFFFFF", BLUE)
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=nInfo); put(ws, 3, 1, "Student Information", True, 10, None, LHEAD)
    c = nInfo + 1
    for sec in pe.PE_SECTIONS:
        cols = [mc for mc in mcs if mcInfo[mc]["sec"] == sec]
        if not cols: continue
        ws.merge_cells(start_row=3, start_column=c, end_row=3, end_column=c + len(cols) - 1); put(ws, 3, c, sec, True, 10, None, LSEC)
        for i, mc in enumerate(cols): put(ws, 4, c + i, f"/{mcInfo[mc]['max']}", False, 8, None, LSEC)
        c += len(cols)
    ws.merge_cells(start_row=3, start_column=cRes, end_row=3, end_column=cRes + 3); put(ws, 3, cRes, "Results", True, 10, None, LHEAD)
    ws.merge_cells(start_row=4, start_column=cRes, end_row=4, end_column=cRes + 1); put(ws, 4, cRes, "Weighted (DASH Proportional, STRICT)", False, 8, None, LHEAD)
    ws.merge_cells(start_row=3, start_column=cRes + 4, end_row=3, end_column=cRes + 5); put(ws, 3, cRes + 4, "Reflections", True, 10, None, LHEAD)
    for cc in range(1, lastC + 1):
        if ws.cell(4, cc).value is None: put(ws, 4, cc, None, bg=LHEAD if cc <= nInfo or cc >= cRes else LSEC)
    heads = ["#", "Last Name", "First Name", "Student No", "Assessor", "Form Opened", "Submitted", "Status"] + \
            [mc for sec in pe.PE_SECTIONS for mc in mcs if mcInfo[mc]["sec"] == sec] + ["Raw", "%", "PR", "GR", "Assessor Reflection", "Student Reflection"]
    mcOrder = heads[nInfo:nInfo + nMc]
    for i, h in enumerate(heads, 1): put(ws, 5, i, h, True, 9, None, LHEAD, wrap=True)
    for i, mc in enumerate(mcOrder): ws.cell(5, nInfo + 1 + i).comment = Comment(f"{mcInfo[mc]['name']} (weight {mcInfo[mc]['w']})", "DASH")
    r0 = 6
    for i, r in enumerate(rows):
        rr = r0 + i; s = r["stu"]
        draft = r["status"] != "Submitted"
        for j, v in enumerate([i + 1, s["last"], s["first"], s["sn"], r["assessor"], r["opened"], r["submitted"], r["status"]], 1):
            put(ws, rr, j, v, sz=10, h="left" if j in (2, 3, 5) else "center", bg=(AMBER if draft and j == 8 else None))
        for j, mc in enumerate(mcOrder):
            v = r["scores"][mc]; mx = mcInfo[mc]["max"]
            bg = GREY if v is None else (GREEN if v == mx else RED if v == 0 else YELLOW)
            cell = put(ws, rr, nInfo + 1 + j, v, True, 10, None, bg)
            if mc in r["adj"]:
                cell.fill = fill(ORANGE); cell.comment = Comment(f"Original: {r['adj'][mc]}", "DASH")
            if v is None: cell.comment = Comment("No assessor answer saved", "DASH")
        put(ws, rr, cRes, r["raw"], True, 10, None, RES, "0.00")
        put(ws, rr, cRes + 1, None if r["raw"] is None else r["raw"] / 100, False, 10, None, RES, "0.0%")
        put(ws, rr, cRes + 2, None if r["pr"] is None else str(r["pr"]), bg=RES if r["pr"] is not None else GREY)
        put(ws, rr, cRes + 3, None if r["gr"] is None else str(r["gr"]), bg=RES if r["gr"] is not None else GREY)
        put(ws, rr, cRes + 4, r["aRef"] or None, sz=9, wrap=True, h="left")
        put(ws, rr, cRes + 5, r["sRef"] or None, sz=9, wrap=True, h="left")
        if r["missing"]:
            ws.cell(rr, cRes).comment = Comment(f"Missing {', '.join(r['missing'])}: % re-weighted over answered items. "
                                                f"With missing scored 0 = {r['rawAnswered']}", "DASH")
    rEnd = r0 + len(rows)
    notes = ["Score colour: green = top (score = max), red = bottom (score = 0), yellow = middle, GREY = no assessor answer. Max per criterion shown in row 4.",
             "ORANGE cell = value adjusted from an out-of-rubric selection (see cell comment / \"Flagged Adjustments\" sheet).",
             "Raw = Σ (score / max) × weight ÷ Σ weight of ANSWERED criteria × 100 (DASH Perio Forms Weighting sheet; see Criterion Summary). Scored out of 100; equals the plain weighted sum when every criterion is answered.",
             "Status: Submitted = assessor submitted;  Draft – not submitted = assessor answers SAVED but form not submitted (INCLUDED in scores, may still change).",
             "PR = Practice Readiness,  GR = Global Rating.",
             "STRICT scale: 5-level criteria score 0/2/3/4/5 out of 5 (Starting=0); 3-level score 0/1/2 out of 2; 2-level score 0/1 out of 1.",
             "Incomplete / missing data is itemised on the \"Data Completeness\" sheet."]
    for k, t in enumerate(notes):
        ws.merge_cells(start_row=rEnd + 1 + k, start_column=1, end_row=rEnd + 1 + k, end_column=lastC)
        ws.cell(rEnd + 1 + k, 1, t).font = Font(size=9, italic=True)
    widths = [5, 15, 13, 12, 18, 13, 13, 16] + [6] * nMc + [9, 8, 5, 5, 45, 45]
    for i, wd in enumerate(widths, 1): ws.column_dimensions[colL(i)].width = wd
    ws.freeze_panes = ws.cell(6, nInfo + 1)
    ws.auto_filter.ref = f"A5:{colL(lastC)}{rEnd - 1}"

    # ── Criterion Summary ──
    cs = wb.create_sheet("Criterion Summary")
    cs.merge_cells("A1:H1"); put(cs, 1, 1, f"Criterion Summary — {title}", True, 13, "FFFFFF", NAVY)
    cs.merge_cells("A2:H2"); put(cs, 2, 1, f"{dateLong}  |  DDS1  |  DENT90141  |  n={len(rows)} ({nSub} submitted, {nDraft} drafts)  |  Weightage {S['weightage']}", False, 9, "FFFFFF", BLUE)
    for j, h in enumerate(["Criterion", "Section", "Denom", "Weight", "Avg Score", "% Top Level", "% Bottom Level", "n answered"], 1): put(cs, 4, j, h, True, 9, None, LHEAD, wrap=True)
    for i, mc in enumerate(mcOrder):
        vals = [r["scores"][mc] for r in rows if r["scores"][mc] is not None]; mx = mcInfo[mc]["max"]
        rr = 5 + i
        for j, v in enumerate([mcInfo[mc]["name"], mcInfo[mc]["sec"], f"/{mx}", mcInfo[mc]["w"],
                               round(float(np.mean(vals)), 2) if vals else None,
                               round(100 * sum(v == mx for v in vals) / len(vals), 1) if vals else None,
                               round(100 * sum(v == 0 for v in vals) / len(vals), 1) if vals else None, len(vals)], 1):
            put(cs, rr, j, v, h="left" if j <= 2 else "center")
    pcts = [r["raw"] for r in rows if r["raw"] is not None]
    rr = 5 + nMc
    put(cs, rr, 1, "Overall Class Average (/100)", True, bg=RES); put(cs, rr, 5, round(float(np.mean(pcts)), 2), True, bg=RES)
    subP = [r["raw"] for r in rows if r["raw"] is not None and r["status"] == "Submitted"]
    drP = [r["raw"] for r in rows if r["raw"] is not None and r["status"] != "Submitted"]
    if subP and drP:
        put(cs, rr + 1, 1, f"  Submitted only (n={len(subP)})"); put(cs, rr + 1, 5, round(float(np.mean(subP)), 2))
        put(cs, rr + 2, 1, f"  Drafts only (n={len(drP)})"); put(cs, rr + 2, 5, round(float(np.mean(drP)), 2))
    for col, wd in zip("ABCDEFGH", [32, 20, 8, 8, 10, 11, 12, 10]): cs.column_dimensions[col].width = wd

    # ── Flagged Adjustments ──
    fa = wb.create_sheet("Flagged Adjustments")
    fa.merge_cells("A1:F1"); put(fa, 1, 1, "Flagged Adjustments — Out-of-Rubric Selections", True, 13, "FFFFFF", NAVY)
    fa.merge_cells("A2:F2"); fa.cell(2, 1, "These cells held a rating outside the criterion’s configured levels. Adjusted per agreed rule (mapped to nearest valid level at or below the selection); originals shown here and highlighted orange in the Marking Sheet.").alignment = Alignment(wrap_text=True)
    fa.row_dimensions[2].height = 30
    for j, h in enumerate(["Last Name", "First Name", "Criterion", "Item", "Original Value", "Adjustment Applied"], 1): put(fa, 4, j, h, True, 9, None, LHEAD)
    if not S["adjust"]: put(fa, 5, 1, "(none)")
    for i, a in enumerate(S["adjust"]):
        for j, v in enumerate([a["last"], a["first"], a["crit"], a["mc"], a["orig"], a["applied"]], 1): put(fa, 5 + i, j, v, h="left")
    for col, wd in zip("ABCDEF", [16, 16, 30, 8, 30, 40]): fa.column_dimensions[col].width = wd

    # ── BLR & BGM ──
    bl = wb.create_sheet("BLR & BGM Cutoff")
    bl.merge_cells("A1:H1"); put(bl, 1, 1, f"Standard Setting — BLR & BGM Cutoff  ({title})", True, 12, "FFFFFF", NAVY)
    bl.merge_cells("A2:H2"); bl.cell(2, 1, "Borderline Regression (BLR) and Borderline Group (BGM) methods on the Weighted % (strict) vs Global Rating. Borderline group = GR 2 (Emerging). Includes assessor DRAFT forms.").font = Font(size=9, italic=True)
    bl.merge_cells("A3:H3"); bl.cell(3, 1, "BGM cut = mean score of candidates rated Borderline.  BLR cut = (slope × GR) + intercept evaluated at the Borderline GR, from the regression of score on Global Rating.").font = Font(size=9, italic=True)
    pts = [(r["gr"], r["raw"]) for r in rows if r["gr"] is not None and r["raw"] is not None]
    x = np.array([p[0] for p in pts], float); y = np.array([p[1] for p in pts], float); n = len(pts)
    slope, icpt = np.polyfit(x, y, 1); yhat = slope * x + icpt
    ssr, sst = ((y - yhat) ** 2).sum(), ((y - y.mean()) ** 2).sum(); r2 = 1 - ssr / sst
    se = math.sqrt(ssr / (n - 2) / ((x - x.mean()) ** 2).sum()); pval = tPval(slope / se, n - 2)
    blr = slope * 2 + icpt; bgm = y[x == 2]
    coreMcs = [mc for mc in mcOrder if sum(r["scores"][mc] is not None for r in rows) >= 0.8 * len(rows)]   # items most forms answered
    coreRows = [r for r in rows if all(r["scores"][mc] is not None for mc in coreMcs)]
    mat = np.array([[r["scores"][mc] / mcInfo[mc]["max"] for mc in coreMcs] for r in coreRows])
    k = mat.shape[1]; alpha = k / (k - 1) * (1 - mat.var(axis=0, ddof=1).sum() / mat.sum(axis=1).var(ddof=1))
    put(bl, 4, 1, "Cut-Score Summary", True, bg=LHEAD); bl.merge_cells("A4:B4"); put(bl, 4, 4, "Score by Global Rating", True, bg=LHEAD); bl.merge_cells("D4:H4")
    summ = [("Candidates with a Global Rating (n)", n), ("Borderline group (GR 2, Emerging) n", int(len(bgm))),
            ("BGM cut-score (mean of borderline)", round(float(bgm.mean()), 2) if len(bgm) else None),
            ("BGM median / SD", f"{np.median(bgm):.2f} / {bgm.std(ddof=1) if len(bgm) > 1 else 0:.2f}" if len(bgm) else "n/a"),
            ("BLR cut-score (regression @ GR 2)", round(blr, 2)), ("BLR slope (marks per GR level)", round(slope, 3)),
            ("BLR intercept", round(icpt, 2)), ("BLR R² (score explained by GR)", round(r2, 3)), ("BLR p-value (slope ≠ 0)", "<0.0001" if pval < 1e-4 else round(pval, 4)),
            ("Cohort mean / SD", f"{np.mean(pcts):.2f} / {np.std(pcts, ddof=1):.2f}"),
            (f"Cronbach's alpha ({k} criteria, complete forms n={mat.shape[0]})", round(float(alpha), 3)),
            ("Candidates below BLR cut", int(sum(p < blr for p in pcts))),
            ("Candidates below BGM cut", int(sum(p < bgm.mean() for p in pcts)) if len(bgm) else None)]
    for i, (a, b) in enumerate(summ): put(bl, 5 + i, 1, a, h="left"); put(bl, 5 + i, 2, b)
    for j, h in enumerate(["GR", "Rating", "n", "Mean %", "SD %"]): put(bl, 5, 4 + j, h, True, bg=LHEAD)
    grRows = []
    for i, g in enumerate(sorted(set(x.astype(int)))):
        yy = y[x == g]; grRows.append(g)
        for j, v in enumerate([g, GR[g], len(yy), round(float(yy.mean()), 2), round(float(yy.std(ddof=1)), 2) if len(yy) > 1 else 0]): put(bl, 6 + i, 4 + j, v)
    if not len(bgm):
        lo = min(grRows); bl.cell(5 + len(summ), 1, f"No candidates rated Borderline (GR 2): BGM unavailable. Lowest observed = {GR[lo]} (GR {lo}). BLR cut at GR 2 is an EXTRAPOLATION.").font = Font(size=9, italic=True, color="C00000")
    ch = BarChart(); ch.title = "Mean weighted % by Global Rating"; ch.y_axis.title = "Mean %"; ch.x_axis.title = "GR"
    ch.add_data(Reference(bl, min_col=7, min_row=5, max_row=5 + len(grRows)), titles_from_data=True)
    ch.set_categories(Reference(bl, min_col=5, min_row=6, max_row=5 + len(grRows))); ch.height, ch.width = 7, 12; ch.legend = None
    bl.add_chart(ch, "J4")
    ra = 7 + len(summ)
    put(bl, ra, 1, "Item Analysis (criterion level)", True, bg=LHEAD); bl.merge_cells(start_row=ra, start_column=1, end_row=ra, end_column=5)
    for j, h in enumerate(["Criterion", "Max", "Mean score", "Borderline mean", "Item–total r"], 1): put(bl, ra + 1, j, h, True, bg=LHEAD)
    wv = np.array([mcInfo[mc]["w"] or 0 for mc in coreMcs]); tot = mat @ wv
    for i, mc in enumerate(coreMcs):
        col = mat[:, i]; mx = mcInfo[mc]["max"]
        rest = tot - col * wv[i]
        rit = float(np.corrcoef(col, rest)[0, 1]) if col.std() > 0 else None
        bvals = [r["scores"][mc] for r in rows if r["gr"] == 2 and r["scores"][mc] is not None]
        for j, v in enumerate([mcInfo[mc]["name"], f"/{mx}", round(float(col.mean() * mx), 2),
                               round(float(np.mean(bvals)), 2) if bvals else "n/a", round(rit, 3) if rit is not None else "n/a"], 1):
            put(bl, ra + 2 + i, j, v, h="left" if j == 1 else "center")
    if len(coreMcs) < nMc:
        bl.cell(ra + 2 + len(coreMcs), 1, f"Item analysis / alpha limited to the {len(coreMcs)} criteria answered on ≥80% of forms (others mostly unanswered — see Data Completeness).").font = Font(size=9, italic=True, color="C00000")
    rb = ra + 3 + nMc
    put(bl, rb, 1, f"Candidates at or below the BLR cut-score ({blr:.2f})", True, bg=LHEAD); bl.merge_cells(start_row=rb, start_column=1, end_row=rb, end_column=6)
    for j, h in enumerate(["Last Name", "First Name", "Student No", "Weighted % (strict)", "Global Rating", "Status"], 1): put(bl, rb + 1, j, h, True, bg=LHEAD)
    low = sorted([r for r in rows if r["raw"] is not None and r["raw"] <= blr], key=lambda r: r["raw"])
    for i, r in enumerate(low):
        for j, v in enumerate([r["stu"]["last"], r["stu"]["first"], r["stu"]["sn"], r["raw"], GR.get(r["gr"], "—"), r["status"]], 1):
            put(bl, rb + 2 + i, j, v, h="left" if j <= 2 else "center")
    for col, wd in zip("ABCDEFGH", [44, 14, 12, 18, 13, 20, 9, 9]): bl.column_dimensions[col].width = wd

    # ── Data Completeness ──
    dc = wb.create_sheet("Data Completeness")
    dc.merge_cells("A1:F1"); put(dc, 1, 1, f"Data Completeness — {code}", True, 13, "FFFFFF", NAVY)
    cats = defaultdict(int)
    for it in S["issues"]: cats[(it["sev"], it["cat"])] += 1
    put(dc, 3, 1, "Issue", True, bg=LHEAD); put(dc, 3, 2, "Severity", True, bg=LHEAD); put(dc, 3, 3, "Students", True, bg=LHEAD)
    for i, ((sev, cat), cnt) in enumerate(sorted(cats.items(), key=lambda kv: (kv[0][0] != "Red", kv[0][1]))):
        put(dc, 4 + i, 1, cat, h="left"); put(dc, 4 + i, 2, sev, bg=RED if sev == "Red" else AMBER); put(dc, 4 + i, 3, cnt)
    rd = 6 + len(cats)
    for j, h in enumerate(["Last Name", "First Name", "Student No", "Issue", "Severity", "Detail"], 1): put(dc, rd, j, h, True, bg=LHEAD)
    for i, it in enumerate(sorted(S["issues"], key=lambda t: (t["sev"] != "Red", t["cat"], t["last"].lower()))):
        for j, v in enumerate([it["last"], it["first"], it["sn"], it["cat"], it["sev"], it["detail"]], 1):
            put(dc, rd + 1 + i, j, v, h="left", wrap=(j == 6), bg=(RED if v == "Red" else AMBER if v == "Amber" else None) if j == 5 else None)
    dc.auto_filter.ref = f"A{rd}:F{rd + len(S['issues'])}"
    for col, wd in zip("ABCDEF", [30, 14, 12, 28, 10, 90]): dc.column_dimensions[col].width = wd
    wb.move_sheet("Data Completeness", offset=-(len(wb.sheetnames) - 2))
    wb.save(path)
    return dict(n=len(rows), nSub=nSub, nDraft=nDraft, mean=np.mean(pcts), blr=blr, bgm=bgm.mean() if len(bgm) else None, cats=dict(cats), date=dateStr)

if __name__ == "__main__":
    for code in (sys.argv[1:] or list(SESS)):
        S = buildSession(code)
        out = f"DDS1/DDS1_{code.replace('-', '')}_strict.xlsx"
        info = writeWorkbook(S, out)
        print(code, out, {k: v for k, v in info.items() if k != "cats"})
        for k, v in sorted(info["cats"].items()): print("   ", k, v)
        print("   cfg field counts", S["cfgCounts"]); print("   roster", len(roster), "adjustments", len(S["adjust"]), "dups", len(S["dups"]))
