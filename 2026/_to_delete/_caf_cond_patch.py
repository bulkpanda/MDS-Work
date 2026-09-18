import json, io, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
NB = os.path.join(HERE, "main.ipynb")
nb = json.load(io.open(NB, encoding="utf-8"))

def lines(s):
    parts = s.split("\n")
    return [p + "\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] != "" else [])

MD = "### Conditional / flagged combined report\n\nOne PDF containing only the forms that meet chosen conditions (low entrustment, a clinical incident, or an additional concern), across one or more students. Uses `buildStudentConditionalReport` in `boh3_dds4_utils.py`."

CODE = '''# Conditional / flagged combined report — one PDF of ONLY the forms meeting conditions.
# buildStudentConditionalReport lives in boh3_dds4_utils.py (imported via `from boh3_dds4_utils import *`).
studentNumber = 1402035  # Rachel Micay  (pass a list e.g. [1402035, 1082018] for several students in one PDF)

result = buildStudentConditionalReport(
    engine,
    studentNumber,
    f"BOH3_DDS4/Flagged_Report_{studentNumber}.pdf",
    entrustmentMax=2,        # Level 1–2 entrustment  (use entrustmentLevels=[2] for EXACTLY Level 2)
    clinicalIncident=True,   # any form with a clinical incident
    additionalConcern=True,  # any form with a staff-only additional concern
    match="any",             # "any" = include if ANY condition holds;  "all" = only if ALL hold
    title="Flagged Assessments",
    # predicate=lambda r: ...,   # optional: custom rule, receives the entry row
)
print(result)  # {'outPath': ..., 'matched': {studentNumber: n}, 'total': n}'''

MD_ID, CODE_ID = "cafcond_md", "cafcond_code"
md_cell   = {"cell_type": "markdown", "id": MD_ID, "metadata": {}, "source": lines(MD)}
code_cell = {"cell_type": "code", "id": CODE_ID, "metadata": {}, "execution_count": None,
             "outputs": [], "source": lines(CODE)}

cells = nb["cells"]
# idempotent: if already present, just refresh their source
existing = {c.get("id"): idx for idx, c in enumerate(cells)}
if CODE_ID in existing:
    cells[existing[CODE_ID]]["source"] = lines(CODE)
    if MD_ID in existing:
        cells[existing[MD_ID]]["source"] = lines(MD)
    print("refreshed existing conditional cells")
else:
    anchor = existing.get("ff349421")
    if anchor is None:
        print("ERROR: anchor cell ff349421 not found"); sys.exit(1)
    cells[anchor+1:anchor+1] = [md_cell, code_cell]
    print("inserted conditional cells after ff349421 at index", anchor+1)

json.dump(nb, io.open(NB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("total cells:", len(cells))
