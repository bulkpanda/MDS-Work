"""
Sort a sheet made of vertically-merged student blocks (key on the block's first row, merged down the block)
by that key — Excel refuses ("merged cells must be the same size"), this moves whole blocks instead.

Keeps: values, styles, number formats, merges, row heights, formulas (each reference follows the row it pointed at;
formulas reading another block are kept as-is and reported),
conditional formatting (ranges remapped with the rows), comments, hyperlinks.

Usage (notebook):
    from sort_merged_blocks import sortMergedBlocks
    sortMergedBlocks("DDS1/DDS1_CD_section_scores (Task 7+Task 8+Mock assessment).xlsx", "CD_Perio_Merged")
Usage (terminal):
    python sort_merged_blocks.py "<workbook>.xlsx" "<sheet>" [keyCol] [outPath]
"""
import copy
import os
import re
import shutil
import warnings
from datetime import datetime
import openpyxl
from openpyxl.formatting.rule import Rule as _XlRule
from openpyxl.formula.tokenizer import Tokenizer as _XlTokenizer, Token as _XlToken
from openpyxl.formula.translate import Translator as _XlTranslator
from openpyxl.utils import get_column_letter as _colL, column_index_from_string as _colIdx
from openpyxl.worksheet.cell_range import CellRange as _XlCellRange

__all__ = ["sortMergedBlocks", "findKeyBlocks"]


def toKey(v):
    """Student number (int / float / '1234567') -> int, else None."""
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def findKeyBlocks(ws, keyCol=2, firstRow=2):
    """Blocks = rows from a key row to the row before the next key row.
    Returns (blocks [(key, startRow, endRow)], headRows [rows before first key], lastRow)."""
    lastRow = max((r for r in range(firstRow, ws.max_row + 1)
                   if any(ws.cell(r, c).value not in (None, "") for c in range(1, ws.max_column + 1))),
                  default=firstRow - 1)
    starts = [r for r in range(firstRow, lastRow + 1) if toKey(ws.cell(r, keyCol).value) is not None]
    blocks = [(toKey(ws.cell(s, keyCol).value), s, (starts[i + 1] - 1) if i + 1 < len(starts) else lastRow)
              for i, s in enumerate(starts)]
    headRows = list(range(firstRow, starts[0])) if starts else []
    return blocks, headRows, lastRow


def compressRows(cells):
    """{(row, col)} -> sqref string of vertical runs per column, e.g. 'L2:L9 L15 M2:M9'."""
    parts = []
    for col in sorted({c for _, c in cells}):
        rows = sorted(r for r, c in cells if c == col)
        start = prev = rows[0]
        for r in rows[1:] + [None]:
            if r != (prev + 1 if prev is not None else None):
                parts.append(f"{_colL(col)}{start}" + (f":{_colL(col)}{prev}" if prev != start else ""))
                start = r
            prev = r
    return " ".join(parts)


_REF = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")


def remapFormula(formula, rowMap, sheetName):
    """Point every cell reference at the row its data moved to (refs to other sheets untouched).
    Returns (newFormula, referencedOldRows)."""
    tok = _XlTokenizer(formula)
    out, rows = ["="], set()
    for t in tok.items:
        v = t.value
        if t.type == _XlToken.OPERAND and t.subtype == _XlToken.RANGE:
            sheet, ref = (v.rsplit("!", 1) if "!" in v else (None, v))
            if sheet is None or sheet.strip("'") == sheetName:
                def sub(m):
                    r = int(m.group(4)); rows.add(r)
                    return f"{m.group(1)}{m.group(2)}{m.group(3)}{rowMap.get(r, r)}"
                ref = _REF.sub(sub, ref)
                v = f"{sheet}!{ref}" if sheet else ref
        out.append(v)
    return "".join(out), rows


def sortMergedBlocks(path, sheetName, keyCol=2, outPath=None, ascending=True, firstRow=2):
    """
    Sort `sheetName` by the key in `keyCol` (1-based; B = 2), moving each block intact.
    outPath : None -> '<name> (sorted).xlsx' next to the source (source untouched);
              outPath == path -> overwrite in place after a backup in _bak/.
    Rows before the first key row and after the data stay where they are.
    """
    wb = openpyxl.load_workbook(path)
    ws = wb[sheetName]
    blocks, headRows, lastRow = findKeyBlocks(ws, keyCol, firstRow)
    order = sorted(blocks, key=lambda b: b[0], reverse=not ascending)

    # ── old row -> new row map ──
    rowMap, nxt = {r: r for r in headRows}, firstRow + len(headRows)
    for _, s, e in order:
        for r in range(s, e + 1):
            rowMap[r] = nxt
            nxt += 1
    region = range(firstRow, lastRow + 1)
    maxCol = ws.max_column

    # ── snapshot cells + row heights ──
    snap = {}
    for r in region:
        for c in range(1, maxCol + 1):
            cell = ws.cell(r, c)
            snap[(r, c)] = (cell.value, copy.copy(cell._style), cell.hyperlink, cell.comment)
    heights = {r: ws.row_dimensions[r].height for r in region}

    # ── merges inside the region: drop, remap later ──
    oldMerges = [m for m in ws.merged_cells.ranges if m.min_row >= firstRow and m.max_row <= lastRow]
    for m in oldMerges:
        ws.unmerge_cells(str(m))

    # ── write cells in new order; formulas follow the data they reference ──
    blockOf = {r: (s, e) for _, s, e in blocks for r in range(s, e + 1)}
    crossRefs = []
    for (r, c), (v, style, link, note) in snap.items():
        nr = rowMap[r]
        cell = ws.cell(nr, c)
        if isinstance(v, str) and v.startswith("="):
            newV, refRows = remapFormula(v, rowMap, sheetName)
            outside = [x for x in refRows if x in blockOf and blockOf.get(r) and blockOf[x] != blockOf[r]]
            if outside:                                               # formula reads another student's block
                crossRefs.append(f"{_colL(c)}{r}->{_colL(c)}{nr} ({snap[(r, 1)][0]}): {v} -> {newV}")
            v = newV
        cell.value, cell._style = v, style
        cell.hyperlink = link
        cell.comment = copy.copy(note) if note else None
    for r, h in heights.items():
        ws.row_dimensions[rowMap[r]].height = h

    # ── re-merge at new rows (a block's merge stays inside the block, so it moves as one piece) ──
    for m in oldMerges:
        top = rowMap[m.min_row]
        ws.merge_cells(start_row=top, start_column=m.min_col,
                       end_row=top + (m.max_row - m.min_row), end_column=m.max_col)

    # ── conditional formatting: remap each rule's cells, keep relative formulas anchored to the new top-left ──
    oldCf = [(cf.sqref, list(cf.rules)) for cf in ws.conditional_formatting]
    ws.conditional_formatting = type(ws.conditional_formatting)()
    for sqref, rules in oldCf:
        cells = set()
        for rng in str(sqref).split():
            cr = _XlCellRange(rng)
            for r in range(cr.min_row, cr.max_row + 1):
                for c in range(cr.min_col, cr.max_col + 1):
                    cells.add((rowMap.get(r, r), c))
        newRef = compressRows(cells)
        oldTl = str(sqref).split()[0].split(":")[0]
        newTl = newRef.split()[0].split(":")[0]
        for rule in rules:
            rule = copy.copy(rule)
            if rule.formula and oldTl != newTl:
                rule.formula = [_XlTranslator("=" + f, origin=oldTl).translate_formula(newTl)[1:] for f in rule.formula]
            ws.conditional_formatting.add(newRef, rule)

    # ── save ──
    if outPath is None:
        root, ext = os.path.splitext(path)
        outPath = f"{root} (sorted){ext}"
    if os.path.abspath(outPath) == os.path.abspath(path):
        os.makedirs("_bak", exist_ok=True)
        shutil.copy(path, os.path.join("_bak", f"{os.path.basename(path)}.bak_{datetime.now():%Y%m%d_%H%M%S}"))
    wb.calculation.fullCalcOnLoad = True          # openpyxl drops cached formula results; Excel recalculates on open
    wb.save(outPath)
    for x in crossRefs:
        warnings.warn("formula references another block (kept pointing at the same data): " + x)
    res = dict(out=outPath, sheet=sheetName, blocks=len(blocks), rows=f"{firstRow}-{lastRow}",
               merges=len(oldMerges), firstKeys=[b[0] for b in order[:3]], crossBlockFormulas=crossRefs)
    print(res)
    return res


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    sortMergedBlocks(a[0], a[1], keyCol=int(a[2]) if len(a) > 2 else 2, outPath=a[3] if len(a) > 3 else None)
