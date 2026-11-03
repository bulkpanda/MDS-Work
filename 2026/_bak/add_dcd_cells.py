"""Append the DCD skills-report cells to DCD.ipynb (run on the device). Backs up to _bak/ first."""
import json, shutil, sys, os, datetime
nbPath = sys.argv[1]
os.makedirs('_bak', exist_ok=True)
stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
shutil.copy2(nbPath, f'_bak/DCD.ipynb.bak_{stamp}')
nb = json.load(open(nbPath, encoding='utf-8'))
MARK = 'dcd_skills_utils'
if any(MARK in ''.join(c['source']) for c in nb['cells']):
    print('cells already present - nothing added'); sys.exit()

def md(src):   return {'cell_type': 'markdown', 'metadata': {}, 'source': src}
def code(src): return {'cell_type': 'code', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': src}

cells = [
md("""### Case Report / Lit Review / Seminar Skills — cleaned workbooks + per-student PDFs
Code lives in `dcd_skills_utils.py` (project root). Pipeline:
1. `loadAllDcdSkillsForms()` — reads the three Qualtrics exports (or the live `dfCaseReport` / `dfLitReview` / `dfSeminarSkills` from the cells above), parses domain ratings (`4-Very good` → 4), overall %, bands, normalises assessor names, harmonises DCD Year (modal per student) and tags excluded rows (survey previews, `Finished = False`, pre-25 Feb 2026 form-build tests). Nothing is deleted — excluded rows sit in the `Excluded` sheet.
2. `buildDcdSkillsWorkbooks()` — one styled workbook per form in `DCD/Skills/` (Summary / Forms / Comments / Excluded / Colour Key).
3. `buildDcdSkillsReports()` — per-student PDFs: `combined=True` → `DCD/Skills/Combined/<name>.pdf` (overview page + one section per form, page-break separated); `separate=True` → `DCD/Skills/<Form>/<name>.pdf`.

Tweak cleaning with `cleanConfig=dict(minDate='2026-02-25', testAssessors=(...), placeholderAssessors=('ABC',))`.
"""),
code("""from dcd_skills_utils import *

# Source: saved exports (default) — or pass the live frames pulled above:
# formDfs = loadAllDcdSkillsForms({'Case Report': dfCaseReport, 'Lit Review': dfLitReview, 'Seminar Skills': dfSeminarSkills})
formDfs = loadAllDcdSkillsForms()

# Quick look at the cleaned Case Report rows
display(keptRows(formDfs['Case Report']).head())
"""),
code("""# 1) Cleaned + colour-coded workbooks, one per form -> DCD/Skills/DCD_<Form>_cleaned.xlsx
workbookPaths = buildDcdSkillsWorkbooks(formDfs, outFolder='DCD/Skills')
"""),
code("""# 2) Per-student PDFs
#    combined=True  -> DCD/Skills/Combined/<student>.pdf  (overview + Case Report / Lit Review / Seminar Skills sections)
#    separate=True  -> DCD/Skills/<Form>/<student>.pdf    (one PDF per form)
#    students=['Adam Saker'] to limit; None = everyone with at least one completed form
pdfPaths = buildDcdSkillsReports(formDfs, outFolder='DCD/Skills', combined=True, separate=False, students=None)
"""),
code("""# Cross-form summary table (handy for Clare / coordinators)
summaryAll = pd.concat([studentSummary(df).assign(Form=k) for k, df in formDfs.items()], ignore_index=True)
display(summaryAll.pivot_table(index=['Student Name', 'DCD Year'], columns='Form',
                               values=['Forms', 'Overall Mean', 'Latest Overall'], aggfunc='first'))
"""),
]
nb['cells'].extend(cells)
json.dump(nb, open(nbPath, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print(f'added {len(cells)} cells; backup -> _bak/DCD.ipynb.bak_{stamp}')
