import json, re, os, openpyxl
import buildPeSheets as b
roster = b.roster
def toks(s): return set(t for t in re.split(r"[^a-z]+", (s or "").lower()) if t)
rt = {sn: (toks(v["last"]), toks(v["first"]) ) for sn, v in roster.items()}
def best(c1, c2):
    a, bb = toks(c1), toks(c2); allT = a | bb
    scored = []
    for sn, (ln, fn) in rt.items():
        lastHit = bool(ln & allT); firstHit = len(fn & allT)
        s = (2 if lastHit else 0) + firstHit
        if s: scored.append((s, sn))
    scored.sort(reverse=True)
    return scored[:3]
wb = openpyxl.load_workbook(os.path.expanduser('~/mnt/2026/DDS1/pe03_06_09.xlsx'))
for ws in wb:
    for r in range(2, ws.max_row + 1):
        c1, c2 = ws.cell(r, 2).value, ws.cell(r, 3).value
        if not c1: continue
        top = best(c1, c2)
        tag = "OK" if top and top[0][0] >= 3 and (len(top) == 1 or top[1][0] < top[0][0]) else "CHECK"
        print(ws.title, r, c1, c2, tag, [(s, sn, roster[sn]["last"], roster[sn]["first"]) for s, sn in top])
