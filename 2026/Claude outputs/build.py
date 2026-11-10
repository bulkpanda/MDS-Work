import json, re, sys, openpyxl

src = sys.argv[1]
ws = openpyxl.load_workbook(src).active

skipRows = {75, 131}                       # superseded 3(a) wording; examiner note
headingOverride = {5: "Justification"}     # strip examiner note from heading
typoFix = {"invovement": "involvement", "involvment": "involvement", "profesional": "professional",
           "Recomends": "Recommends", " placed .": " placed.", "initallly": "initially", "futher": "further",
           "Consult with GP is BP": "Consult with GP if BP", "w SSRI": "with SSRI",
           "may effect": "may affect", "fluoride a part": "fluoride as part", "documents social": "document social"}

def clean(t):
    t = re.sub(r"\s+", " ", str(t).replace("\xa0", " ")).strip().rstrip(",").strip()
    for a, b in typoFix.items():
        t = t.replace(a, b)
    return t

# 1. Read rows -> (row, depth, text, bold)
rows = []
for r in ws.iter_rows():
    for c in r:
        if c.value not in (None, "") and str(c.value).strip():
            if c.row not in skipRows:
                rows.append({"row": c.row, "depth": c.column - 1, "text": clean(c.value), "bold": bool(c.font.b)})
            break

# 2. Group col-A rows with their indented supports (col B/C/D)
nodes = []
for x in rows:
    nodes.append({**x, "supports": []})  # all columns are items; no label supports

def toHtml(sup):  # each support line -> <p>, deeper columns prefixed with "– "
    import html
    return "".join(f"<p>{'– ' * (x['depth'] - 1)}{html.escape(x['text'], quote=False)}</p>" for x in sup)

def nest(sup):  # (unused) B items with their C/D children in brackets
    out, i = [], 0
    while i < len(sup):
        base = sup[i]; kids = []; j = i + 1
        while j < len(sup) and sup[j]["depth"] > base["depth"]:
            kids.append(sup[j]); j += 1
        txt = base["text"].rstrip(". ")
        if kids: txt += " (" + nest(kids) + ")"
        out.append(txt); i = j
    return "; ".join(out)

# 3. Classify: heading if bold & no supports, or "Answer:" row; else checklist item
mcMap, rubricMc, headers, pending, n = {}, {}, {}, [], 0
yesNo = {"O1": "Yes", "O2": "No"}
for nd in nodes:
    t = nd["text"]
    isAnswer = t.lower().startswith("answer:")
    if nd["row"] in headingOverride:
        pending.append(headingOverride[nd["row"]]); continue
    if isAnswer or (nd["bold"] and not nd["supports"]):
        pending.append(re.sub(r"^answer:\s*", "", t, flags=re.I).rstrip(":").strip()); continue
    n += 1; key = f"MC{n}"
    label = t.rstrip(":").strip()
    mcMap[key] = label
    rubricMc[key] = {**yesNo, "label": toHtml(nd["supports"])} if nd["supports"] else dict(yesNo)
    if pending:
        headers[key] = [{"title": h} for h in pending]; pending = []

# 4. Communication & Presentation carried over from original form
comm = ["Information presented is relevant to the case",
        "Speaks clearly and audibly, at an appropriate pace",
        "Presents information in a well-organised sequence with logical reasoning",
        "Uses accurate clinical terminology throughout"]
for i, t in enumerate(comm):
    n += 1; mcMap[f"MC{n}"] = t; rubricMc[f"MC{n}"] = dict(yesNo)
    if i == 0: headers[f"MC{n}"] = [{"title": "Communication and Presentation"}]

rubric = {"rubric": rubricMc, "headers": headers, "options": {"assessor": {"O1": "Yes", "O2": "No"}}}
json.dump(mcMap, open("boh2VivaChecklist_mc.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(rubric, open("boh2VivaChecklist_rubric.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
for k, v in mcMap.items():
    for h in headers.get(k, []): print("   ##", h["title"])
    print(k, v); lbl = rubricMc[k].get("label")
    if lbl: print("      label:", lbl)
