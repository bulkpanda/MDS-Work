"""
Merge flat per-student columns from one sheet (e.g. Perio, one row per student, no merged cells)
into a block-structured sheet (e.g. Consolidated_merged, one block of task rows per student,
student number only on the block's first row, block cells vertically merged).

Usage (notebook):
    from dds1_cd_perio_merge import mergeCdPerio
    mergeCdPerio()                                   # defaults = DDS1 CD workbook -> DDS1/DDS1_CD_Perio_merged.xlsx

Usage (terminal):
    python dds1_cd_perio_merge.py "DDS1/<src>.xlsx" "DDS1/<out>.xlsx"
"""
import copy
import warnings
import openpyxl
from openpyxl.styles import Alignment as _XlAlignment, Border as _XlBorder, Font as _XlFont
from openpyxl.styles import PatternFill as _XlPatternFill, Side as _XlSide
from openpyxl.comments import Comment as _XlComment
from openpyxl.utils import get_column_letter as _colL

__all__ = ["mergeCdPerio", "buildPerioSpec", "findBlocks", "failsDiff"]   # keeps `import *` clean

DEFAULT_SRC = "DDS1/DDS1_CD_section_scores (Task 7+Task 8+Mock assessment).xlsx"
DEFAULT_OUT = "DDS1/DDS1_CD_Perio_merged.xlsx"
HEADER_FILL = {"hand": "375623", "dash": "1F4E79", "diff": "7F6000", "note": "595959"}   # green = hand, blue = DASH, amber = diff, grey = notes
DIFF_ALERT = 15                                                        # |diff| >= this -> orange bold
NOTE_AUTHOR = "MDS Analytics"                                          # author shown on header notes


def buildPerioSpec(sessions=(3, 6, 9)):
    """Column spec: (output header, kind, source header(s), header group, header note).
    kind: copy = value + style from source; numDiff = src[1] - src[0]; failsDiff = session-set comparison.
    The note is attached to the header cell as an Excel note (hover to read)."""
    cut = ("BLR cut = predicted % at DASH GR 2 (Emerging) from a regression of % on DASH Global Rating, "
           "per session; fail = strictly below the cut.")
    spec = []
    for s in sessions:
        sess = f"PE-0{s}" if s < 10 else f"PE-{s}"
        draft = " Session 9 DASH values include unsubmitted (draft) assessor forms." if s == 9 else ""
        hand = "raw Debridement score / 15 × 100." if s == 3 else "hand-marked total out of 100."
        spec += [(f"Session {s} % (hand)", "copy", f"Session {s} %", "hand",
                  f"Hand-marked Perio Session {s} % (Perio sheet). {hand}\nRed = below the hand-marked BLR cut.\n{cut}"),
                 (f"Session {s} DASH %", "copy", f"Session {s} DASH %", "dash",
                  f"DASH {sess} weighted % — item weights from the Weighting sheet "
                  f"({'lenient O-level conversion' if s <= 4 else 'strict O-level conversion'}).{draft}\n"
                  f"Red = below the DASH BLR cut; italic = from an unsubmitted draft form; grey = no DASH form."),
                 (f"Session {s} Diff (DASH − hand)", "numDiff", (f"Session {s} %", f"Session {s} DASH %"), "diff",
                  f"DASH % − hand %, recalculated by the script (not copied from Perio).\n"
                  f"Negative = DASH lower than hand marking. Orange bold = |diff| ≥ {DIFF_ALERT}."),
                 (f"Session {s} GR (DASH)", "copy", f"Session {s} GR", "dash",
                  "DASH assessor Global Rating 1–5: 1 Starting, 2 Emerging, 3 Developing, 4 Competent, 5 Exemplary.\n"
                  "DASH only — the hand-marked sheets have no GR, so there is no hand counterpart or diff.")]
    spec += [("Fails (hand)", "copy", "Fails (hand)", "hand",
              f"Sessions where the hand-marked % is below that session's hand-marked BLR cut (e.g. S3, S6).\n{cut}"),
             ("Fails (DASH)", "copy", "Fails (DASH)", "dash",
              f"Sessions where the DASH % is below that session's DASH BLR cut.\n{cut}"),
             ("Fails Diff", "failsDiff", ("Fails (hand)", "Fails (DASH)"), "diff",
              "Compares the two fail lists.\nSame = both methods fail the same sessions; "
              "'DASH only: S6' = fails on DASH but not hand; 'hand only: S3' = the reverse; blank = no fails either way.\n"
              "Orange bold = the methods disagree."),
             ("Weighted % (hand)", "copy", "Weighted %", "hand",
              "Hand-marked weighted Perio %: (10 × S3 + 20 × S6 + 25 × S9) / 55.\n"
              "From the Perio sheet formula — a blank session counts as 0."),
             ("Weighted DASH %", "copy", "Weighted DASH %", "dash",
              "DASH weighted Perio %: (10 × S3 + 20 × S6 + 25 × S9) / 55 using the DASH session %.\n"
              "From the Perio sheet formula — a blank session counts as 0."),
             ("Weighted Diff (DASH − hand)", "numDiff", ("Weighted %", "Weighted DASH %"), "diff",
              f"Weighted DASH % − Weighted % (hand), recalculated by the script.\nOrange bold = |diff| ≥ {DIFF_ALERT}."),
             ("Notes", "copy", "Notes", "note",
              "Free-text notes from the Perio sheet's notes column (unlabelled last column in Perio).")]
    return spec


def toKey(v):
    """Normalise a student number (int / float / '1234567' / '1234567.0') -> int, else None."""
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def findBlocks(ws, keyCol, firstDataRow=2, lastCol=None):
    """Student blocks in a block-structured sheet -> {studentNumber: (startRow, endRow)}.
    Block = key row down to the row before the next key row; a merged range on the key column
    (if present) extends it. Trailing rows with no data in any column are dropped."""
    lastCol = lastCol or ws.max_column
    hasData = lambda r: any(ws.cell(r, c).value not in (None, "") for c in range(1, lastCol + 1))
    lastRow = max((r for r in range(firstDataRow, ws.max_row + 1) if hasData(r)), default=firstDataRow - 1)
    mergedEnd = {m.min_row: m.max_row for m in ws.merged_cells.ranges if m.min_col <= keyCol <= m.max_col}
    starts = [r for r in range(firstDataRow, lastRow + 1) if toKey(ws.cell(r, keyCol).value) is not None]
    blocks = {}
    for i, s in enumerate(starts):
        e = starts[i + 1] - 1 if i + 1 < len(starts) else lastRow
        blocks[toKey(ws.cell(s, keyCol).value)] = (s, max(e, mergedEnd.get(s, s)))
    return blocks


def failSet(v):
    """'S3, S6' -> {'S3', 'S6'}."""
    return {t.strip() for t in str(v or "").split(",") if t.strip()}


def failsDiff(hand, dash):
    """Compare hand vs DASH failed sessions -> None (no fails) / 'Same' / 'DASH only: S6; hand only: S3'."""
    h, d = failSet(hand), failSet(dash)
    if h == d:
        return "Same" if h else None
    parts = []
    if d - h: parts.append("DASH only: " + ", ".join(sorted(d - h)))
    if h - d: parts.append("hand only: " + ", ".join(sorted(h - d)))
    return "; ".join(parts)


def mergeCdPerio(srcPath=DEFAULT_SRC, outPath=DEFAULT_OUT, targetSheet="Consolidated_merged",
                 sourceSheet="Perio", targetKeyCol=2, sourceKeyHeader="Student No",
                 spec=None, keepSheets=(None,), freeze="D2", headerNotes=False):
    """
    Append source-sheet columns to the target sheet, matched on student number, one value per block
    (written on the block's first row and merged down the block).

    srcPath / outPath : workbook to read / file to write (never overwrites srcPath unless you pass it)
    targetSheet       : block-structured sheet (merged cells)          -> receives the new columns
    sourceSheet       : flat sheet (one row per student, no merges)    -> provides the values
    targetKeyCol      : column index of the student number in targetSheet (B = 2; its header is blank)
    sourceKeyHeader   : header of the student-number column in sourceSheet
    spec              : column spec (default buildPerioSpec()); 5th item = header note (optional)
    keepSheets        : (None,) = keep only target + source; "all" = keep every sheet; or a list of names
    headerNotes       : True = attach each spec note to its header cell as an Excel hover note
    Re-runnable: if the output columns already exist in targetSheet they are overwritten, not duplicated.
    Returns dict with counts and unmatched student numbers.
    """
    spec = spec or buildPerioSpec()
    wb = openpyxl.load_workbook(srcPath)                                  # formulas + styles
    wbVal = openpyxl.load_workbook(srcPath, data_only=True)               # cached values (source has formulas)
    tgt, src, srcV = wb[targetSheet], wb[sourceSheet], wbVal[sourceSheet]

    # ── sheets to keep ──
    if keepSheets != "all":
        keep = {targetSheet, sourceSheet} | (set(keepSheets) - {None})
        for name in list(wb.sheetnames):
            if name not in keep:
                del wb[name]

    # ── source lookup: header -> col, student -> row ──
    srcCol = {src.cell(1, c).value: c for c in range(1, src.max_column + 1) if src.cell(1, c).value}
    if "Notes" not in srcCol:                                             # Perio's notes column has no header:
        for c in range(src.max_column, 0, -1):                            # use the last blank-header column holding text
            if src.cell(1, c).value in (None, "") and any(isinstance(src.cell(r, c).value, str)
                                                          for r in range(2, src.max_row + 1)):
                srcCol["Notes"] = c
                break
    needed = {h for _, _, s, *_ in spec for h in ((s,) if isinstance(s, str) else s)} | {sourceKeyHeader}
    missingHdr = needed - set(srcCol)
    if missingHdr:
        raise KeyError(f"{sourceSheet} missing headers: {sorted(missingHdr)}")
    srcRow = {}
    for r in range(2, src.max_row + 1):
        k = toKey(src.cell(r, srcCol[sourceKeyHeader]).value)
        if k is not None:
            if k in srcRow: warnings.warn(f"duplicate {k} in {sourceSheet}; using first row")
            srcRow.setdefault(k, r)

    def val(r, hdr):                                                      # cached value; warn if formula never calculated
        v = srcV.cell(r, srcCol[hdr]).value
        f = src.cell(r, srcCol[hdr]).value
        if v is None and isinstance(f, str) and f.startswith("="):
            warnings.warn(f"{sourceSheet}!{_colL(srcCol[hdr])}{r} is an uncalculated formula — open/save in Excel first")
        return v

    # ── target: existing headers -> reuse columns on re-run, else append ──
    tgtHdr = {tgt.cell(1, c).value: c for c in range(1, tgt.max_column + 1) if tgt.cell(1, c).value}
    origLastCol = min([tgtHdr[h] for h, *_ in spec if h in tgtHdr], default=tgt.max_column + 1) - 1
    blocks = findBlocks(tgt, targetKeyCol, lastCol=origLastCol)
    first = origLastCol + 1
    lastNew = first + len(spec) - 1

    for m in list(tgt.merged_cells.ranges):                               # clear old merges in the output span
        if m.min_col >= first and m.max_col <= lastNew:
            tgt.unmerge_cells(str(m))

    # ── headers ──
    thin = _XlSide(style="thin", color="BFBFBF")
    box = _XlBorder(left=thin, right=thin, top=thin, bottom=thin)
    mid = _XlAlignment(horizontal="center", vertical="center", wrap_text=True)
    hdrStyle = tgt.cell(1, origLastCol)._style                           # match existing header look
    for j, (hdr, kind, s, grp, *note) in enumerate(spec):
        c = first + j
        cell = tgt.cell(1, c, hdr)
        cell.comment = None
        if headerNotes and note and note[0]:                              # optional header hover note
            cell.comment = _XlComment(note[0], NOTE_AUTHOR, width=320, height=40 + 15 * (len(note[0]) // 45 + note[0].count("\n")))
        cell._style = copy.copy(hdrStyle)
        cell.fill = _XlPatternFill("solid", fgColor=HEADER_FILL[grp])
        cell.alignment = mid
        tgt.column_dimensions[_colL(c)].width = 45 if grp == "note" else 14 if "Fails" in hdr else 11.5

    # ── values, one per block ──
    unmatched = []
    for sn, (s, e) in blocks.items():
        r = srcRow.get(sn)
        if r is None:
            unmatched.append(sn)
        for j, (hdr, kind, srcHdr, grp, *_) in enumerate(spec):
            c = first + j
            for rr in range(s, e + 1):                                    # reset block cells (re-run safe)
                tgt.cell(rr, c).value = None
                tgt.cell(rr, c).border = box
            cell = tgt.cell(s, c)
            cell.font, cell.fill = _XlFont(), _XlPatternFill()
            if r is not None:
                if kind == "copy":                                        # value + source highlight (fail red, draft italic…)
                    cell.value = val(r, srcHdr)
                    cell.font = copy.copy(src.cell(r, srcCol[srcHdr]).font)
                    cell.fill = copy.copy(src.cell(r, srcCol[srcHdr]).fill)
                elif kind == "numDiff":                                   # DASH − hand, 1 dp
                    a, b = val(r, srcHdr[0]), val(r, srcHdr[1])
                    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                        cell.value = round(b - a, 1)
                        if abs(cell.value) >= DIFF_ALERT:
                            cell.font = _XlFont(bold=True, color="C55A11")
                elif kind == "failsDiff":
                    cell.value = failsDiff(val(r, srcHdr[0]), val(r, srcHdr[1]))
                    if cell.value not in (None, "Same"):
                        cell.font = _XlFont(bold=True, color="C55A11")
            if "%" in hdr or "Diff (" in hdr:
                cell.number_format = "0.0"
            cell.alignment = _XlAlignment(horizontal="left", vertical="center", wrap_text=True) if grp == "note" else mid
            if e > s:
                tgt.merge_cells(start_row=s, start_column=c, end_row=e, end_column=c)

    notInTarget = sorted(set(srcRow) - set(blocks))
    if freeze: tgt.freeze_panes = freeze
    wb.calculation.fullCalcOnLoad = True                                 # openpyxl drops cached formula values; Excel recalcs on open
    wb.save(outPath)
    res = dict(out=outPath, students=len(blocks), columns=f"{_colL(first)}-{_colL(lastNew)}",
               unmatchedInSource=unmatched, missingFromTarget=notInTarget)
    print(res)
    return res


if __name__ == "__main__":
    import sys
    mergeCdPerio(*sys.argv[1:3]) if len(sys.argv) > 1 else mergeCdPerio()
