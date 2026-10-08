import shutil, datetime, os
p = "_handover_docs/INDEX.md"
os.makedirs("_bak", exist_ok=True)
shutil.copy(p, f"_bak/INDEX.md.bak_{datetime.datetime.now():%Y%m%d_%H%M%S}")
s = open(p, encoding="utf-8").read()
row = ("| 2026-09-24 | [HANDOVER_dds1_pe_progress_report.md](HANDOVER_dds1_pe_progress_report.md) | "
       "**DDS1 Periodontics coordinator progress report (new)** — new `dds1_pe_utils.py` reads `temp 2026 caf.json` and builds "
       "`DDS1/DDS1 PE Progress Report.xlsx`: Overview, Progress Grid (session % + GR/PR per session, z-trend, flag), Flags "
       "(RED 27 / AMBER 18 of 105), **Student Tracker** (dropdown → item × session pivot, raw levels, one line chart per section "
       "with a line per checklist item, comments), Item Pivot, Criterion × Session, Self vs Assessor, Adjustments. Scoring "
       "reproduces the PE0x marking sheets exactly (S1/S3/S4/S5 0 per-student diffs; S1 uses map-UP rule). Found PE forms saved "
       "as clinic_type CD → route by checklist code. `main.ipynb` not edited | DDS1 | `dds1_pe_utils.py` (new) |\n")
anchor = "|---|---|---|---|---|\n"
i = s.index(anchor) + len(anchor)
s = s[:i] + row + s[i:]
detail = """### 2026-09-24 · HANDOVER_dds1_pe_progress_report.md

**Scope.** New module `dds1_pe_utils.py` (no existing file touched); output `DDS1/DDS1 PE Progress Report.xlsx`. Source `temp 2026 caf.json`, PE-01…PE-06, DENT90141.

- Item level = rank among valid options (`options − row_config.disabled_options`); out-of-rubric → nearest valid **at/below** (S2–S6) or **at/above** (S1, as the published S1 sheet did). Equal % and Proportional % with the weights copied from the PE0x Criterion Summary sheets — validated to 0 per-student differences on S1, S3, S4, S5; S2 differs only by 3 late submissions.
- Trends use within-session z (sessions differ in content; S3 practice test mean 59%). Flags tiered: RED = low in ≥2 sessions / safety bottom level (Infection control, Instrument use) / Major damage in ≥2 sessions / ≥2 missed marked sessions / no PE forms; AMBER = decline, latest-session low or damage, GR ≤2, PR 1, self over-rating ≥15 pts.
- Student Tracker: dropdown-driven INDEX/MATCH over hidden TrackerData + Item Pivot; `NA()` for gaps; 4 section charts (line per checklist item) + student vs cohort chart.

**Gotchas.** PE forms saved with `clinic_type: "CD"` (≥4 PE-02) — route by checklist code, never clinic type. 17 duplicate student×session forms: keep assessor-submitted, then latest **created_at** (updated_at picked stale duplicates). Test account 1234567 in DDS1. pandas ≥3 NaN in object columns. LibreOffice plots `#N/A` as 0 (Excel gaps).

**Open.** PE-06 scheme/weightage assumed = S4/S5 and 0 forms scored yet; 3 DDS1 students with no PE forms (Ang, Gupta, Molon); thresholds need coordinator review; notebook cell not yet added.

"""
anchor2 = "## Detail by document\n\n"
j = s.index(anchor2) + len(anchor2)
s = s[:j] + detail + s[j:]
open_items = """
- **DDS1 PE report (2026-09-24):** PE-06 scoring scheme/weightage unconfirmed (assumed = S4/S5); re-run once assessors submit PE-06. Three DDS1 students have no PE forms (1268191, 1313675, 1682850). Flag thresholds (`PE_FLAG_CONFIG`) awaiting coordinator review. Cell not yet in `main.ipynb`.
"""
k = s.find("## Open items across all sessions")
if k >= 0:
    nl = s.index("\n\n", k) + 2
    s = s[:nl] + open_items.lstrip("\n") + "\n" + s[nl:]
open(p, "w", encoding="utf-8").write(s)
print("ok", k)
