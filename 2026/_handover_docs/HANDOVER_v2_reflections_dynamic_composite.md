# Handover — V2 report comments dropped (DDS2 clinic) + dynamic reflection composite

**Date:** 2026-09-15
**Cohorts:** DDS2 Clinic was the reported symptom; the fix is cohort-generic (BOH1/BOH2/DDS1/DDS2/DDS3, Sim + Clinic).
**Main code file:** `boh2_dds2_dds3_utils.py`
**Backup taken before work:** `boh2_dds2_dds3_utils.py.bak_comments_20260915_051750`
**Related:** [[HANDOVER_student_report_v2_redesign.md]] (the V2 report this fixes), [[HANDOVER_v3_comments_and_summary_labels.md]] (the original composite that recovered non-`reflection` comment keys).

---

## 0. TL;DR

Two problems, one file:

1. **V2 "new comments" section dropped comments** — the redesigned reflection block (`_addReflectionCardsV2`) decided *card vs collapsed-log* using only the plain `student_reflection` column (a single `texts->>'reflection'` key). On DDS2 clinic the student writes into the **structured** keys (`reflection-what-did-well` / `-what-differently` / `-how-prepare`) and the assessor comment lives in `reflection-student-did-well` / `-improve` / `additional-comments`. Any form with an empty plain `reflection` was mis-classified as a trivial "assist/support" row and dumped into the collapsed log, with the real comment truncated to 110 chars from the plain `assessor_reflection`. **1,801 of 4,776 DDS2 clinic forms** were affected.

2. **The composite was hardcoded, not dynamic** — `getDataDf` built `student_reflection_full` / `assessor_reflection_full` from two fixed key lists in SQL. It happened to cover today's keys (so it *looked* complete) but a new DASH key would silently vanish — one already does: an assessor `feedback` key appears in BOH1 and neither list had it.

Both fixed. The composite is now built dynamically in Python from **every** comment key present, and the V2 gate now measures substance from that composite (both sides), collapsing to the log only when both sides are genuinely trivial.

**Follow-up (2026-09-15):** the composite dropped raw reflection text into a reportlab `Paragraph` unescaped, so a DDS2 reflection containing `<`/`&`/a tag-like fragment crashed the parser (`paraparser: syntax error: parse ended with 1 unclosed tags`). Now escaped at source — see §7.

Run to eyeball:
```python
import importlib, boh2_dds2_dds3_utils as bu; importlib.reload(bu)
bu.buildEntireCohortStudentReportsV2(engine, "DDS2", onlyStudents=["<student no.>"])
```

---

## 1. Root cause (with the data that proves it)

`getDataDf` (`boh2_dds2_dds3_utils.py`) returns per-form columns including:
- `student_reflection` / `assessor_reflection` — DB columns = **only** `*_data->'texts'->>'reflection'` (one key). See `general_utils.py` loader (`(studentJson...->>'reflection') AS student_reflection`).
- `student_reflection_full` / `assessor_reflection_full` — the **composite** of all known comment keys (bold-labelled).

`_addReflectionCardsV2` did:
```python
rawStudentCol = "student_reflection" ...          # the single plain key
if _v2IsMinorReflection(row.get(rawStudentCol), minorMaxChars):   # <=25 chars → "minor"
    note = plain assessor_reflection or plain student_reflection  # composite ignored
    minorRows.append(...)                                          # → collapsed log
    continue
# else → full card (card DID use the composite)
```

So the classification and the log note both read the **single `reflection` key**, not the composite. On DDS2 clinic that key is empty ~half the time even when the form is full of structured student text and assessor feedback.

**Text-key census across all 24,362 CAF assessments (2026 pull, `temp 2026 caf.json`):**

Student `texts` keys (key — count — cohorts):
```
reflection                    23313  all
reflection-what-did-well       1461  DDS2
reflection-what-differently    1460  DDS2
reflection-how-prepare         1459  DDS2
assessor_signature              772  BOH2, DDS3     <- NOT a comment
so-reflection                   501  DDS2
procedures-observed             257  DDS3
```
Assessor `texts` keys:
```
reflection                    20073  all
reflection-student-did-well    1173  DDS2
reflection-student-improve     1168  DDS2
additional-comments             594  DDS1
so-assessor-reflection          443  DDS2
clinical-incident               117  all           <- handled by clinicalIncidentSqlExpr
clinical-incident-additional-details 117  all      <- not a comment
needs-additional-support          4  DDS2
feedback                          1  BOH1          <- MISSED by the old hardcoded list
```

**DDS2 Clinic (4,876 forms):** 2,290 had an empty/short plain `reflection` (<=25 chars) but substantive text elsewhere — of those, 329 assessor-only. Example forms with empty plain reflection but real assessor comment: id 10811 ("Going well. Had to cease procedure due to compliance…"), 10951 ("Please review infection control procedures…").

---

## 2. The fix — architecture

### 2a. Dynamic composite in `getDataDf` (serves V1 **and** V2)

`getDataDf` still runs the SQL composite (columns exist), then **overwrites** the two `_full` columns in Python, from the parsed `student_data` / `assessor_data` JSONB, **before** `applySmileSquadSwap`:

```python
if "clinical_incident_resolved" in df.columns:
    df["clinical_incident"] = df.pop("clinical_incident_resolved")
df = _applyDynamicReflectionComposites(df)     # NEW — rebuild *_reflection_full dynamically
if smileSquadSwap:
    df = applySmileSquadSwap(df, cohort)
return df
```

Ordering matters: reflections are read from the **pre-swap** `student_data` / `assessor_data`. The Smile Squad swap deliberately does **not** swap the reflection (the SS reflection is the student's own — see [[smile-squad-boh2-swap-v3]]); rebuilding before the swap keeps that behaviour identical.

New functions (near `STUDENT_REFLECTION_TEXT_KEYS`):

```python
REFLECTION_TEXT_DENY = {"clinical-incident", "clinical-incident-additional-details",
                        "clinical-incident-occurred"}

def _isReflectionTextKey(key):
    """A *_data->'texts' key that is a free-text comment (not a signature,
    clinical-incident field, or other non-comment key)."""
    k = str(key).strip().lower()
    if not k or "signature" in k:            return False
    if k.startswith("clinical-incident") or k in REFLECTION_TEXT_DENY: return False
    return True

def _humanizeTextKey(key):
    """'reflection-what-did-well' -> 'Reflection What Did Well' (label for a new key)."""
    s = re.sub(r"[-_]+", " ", str(key)).strip()
    return s[:1].upper() + s[1:] if s else str(key)

def _buildReflectionComposite(textsDict, knownPairs, bold=True):
    """Concatenate every non-empty comment key. Known keys use their label from
    knownPairs and come first in that order; unknown keys follow alphabetically
    with a humanised label. Returns None when nothing substantive is present.
      bold=True  -> '<b>Label: </b>value'   (reportlab Paragraph)
      bold=False -> 'Label: value'          (Excel/CSV)"""
    ...

def _applyDynamicReflectionComposites(df):
    """Overwrite student_reflection_full / assessor_reflection_full from every
    comment key in *_data['texts']. Call BEFORE the Smile Squad swap."""
    ...
```

**Behaviour (worked example).** Assessor `texts = {"reflection": "Good aseptic technique.", "reflection-student-improve": "Speed up impressions."}` with `ASSESSOR_REFLECTION_TEXT_KEYS` →
```
<b>Feedback: </b>Good aseptic technique.

<b>To Improve: </b>Speed up impressions.
```
A future key `texts = {"clinical-reasoning": "..."}` (unknown) → auto-included as `<b>Clinical Reasoning: </b>...`. A `assessor_signature` or `clinical-incident` key → **excluded**.

**Ordering rule:** known keys in the order of `STUDENT_/ASSESSOR_REFLECTION_TEXT_KEYS`; unknown keys after, alphabetical. Deterministic output.

### 2b. V2 gate fix (`_addReflectionCardsV2`)

New helper:
```python
def _v2VisibleReflection(html):
    """Visible text with the bold <b>Label: </b> headings stripped, so
    'Reflection: ' / 'Feedback: ' don't count as written content."""
    s = re.sub(r"<b>.*?</b>", " ", str(html), flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()
```

New gate:
```python
studentFull, assessorFull = row.get(studentCol), row.get(assessorCol)   # the composites
studentVisible  = _v2VisibleReflection(studentFull)
assessorVisible = _v2VisibleReflection(assessorFull)
# collapse to the log ONLY when BOTH sides are trivial; any substantive comment → a card
if len(studentVisible) <= minorMaxChars and len(assessorVisible) <= minorMaxChars:
    note = assessorVisible or studentVisible or "—"
    minorRows.append((dateStr, _v2LogTag(studentVisible, assessorVisible), truncateText(note, 110)))
    continue
sHtml = truncateText(studentFull).replace("\n", "<br/>") if studentFull else ""
aHtml = truncateText(assessorFull).replace("\n", "<br/>") if assessorFull else ""
cards.append(_v2ReflectionCard(dateStr, codeStr, sHtml, aHtml, row.get("global_rating")))
```
`_v2VisibleReflection` strips the bold labels so a form whose only student text is the label prefix doesn't read as "written". The card body already rendered the composite — no change there; only the **classification** and the **log note** moved off the plain key. `minorMaxChars` default stays 25.

---

## 3. Architectural decisions

- **Dynamic in `getDataDf`, not in the report.** The report receives a post-swap df; for Smile Squad rows `student_data`/`assessor_data` are swapped, so building the composite there would read the wrong dict for SS. Building it in `getDataDf` before the swap is the single correct place, and it feeds **both** V1 (`_addReflectionsTable`) and V2.
- **Denylist, not allowlist.** To be future-proof, unknown keys are *included* by default; only known non-comment keys are excluded (`*signature`, `clinical-incident*`). This is the opposite of the old hardcoded allowlist and is why a new DASH field now appears automatically.
- **SQL composite left in place.** `_reflectionCompositeSqlExpr` still runs (cheap) so the columns exist even if `_applyDynamicReflectionComposites` is ever skipped; the Python step overwrites them. The **flagged-forms Excel export** (`_reflectionCompositeSqlExpr(..., bold=False)`, ~line 677) was **not** changed — it keeps the hardcoded SQL list (still complete for current keys). If future keys must show there too, port it to `_buildReflectionComposite(..., bold=False)`.
- **Collapse rule = both sides trivial.** The log is for genuine assist/DA/FTA/support sessions. Requiring *both* student and assessor to be trivial means an assessor-only comment (329 DDS2 clinic forms) now correctly becomes a card.

---

## 4. Verification (against the real 2026 CAF pull, no DB needed)

Logic re-run on `temp 2026 caf.json`, DDS2 Clinic (4,776 assessments scanned):
- **now CARDS: 4,268**  |  still collapsed-log (both sides trivial): 608
- **RECLASSIFIED old-log → now-card: 1,801**
- Denylist audit — keys with content that are **correctly excluded** from composites: `assessor_signature` (772), `clinical-incident` (117), `clinical-incident-additional-details` (117). No comment key excluded; no denied key leaks a segment.
- `python -m py_compile boh2_dds2_dds3_utils.py` → OK.

NOT run end-to-end against the live DB (no DB access in the session) — user runs the cell.

---

## 5. Traps / notes

- `student_reflection` / `assessor_reflection` DB columns are the single `reflection` key only — never use them to judge "did the student comment?"; use the `_full` composites (now dynamic).
- The composite carries bold `<b>Label: </b>` headings; when measuring "how much was written", strip them (`_v2VisibleReflection`) or the label inflates the length.
- Rebuild must stay **before** `applySmileSquadSwap` in `getDataDf`.
- Denylist matches on the **key** (`*signature`, `clinical-incident*`); the words "clinical"/"signature" appearing inside a reflection **value** are fine and stay (they're real comments).

---

## 6. Open items

- Flagged-forms Excel export still uses the hardcoded SQL composite (§3) — port to the dynamic builder if new keys must appear there.
- End-to-end PDF not regenerated here — user to run `buildEntireCohortStudentReportsV2` and confirm a DDS2 clinic student's Reflections section now shows the recovered cards.

---

## 7. Escaping fix (2026-09-15) — reportlab paraparser crash

**Symptom.** `buildEntireCohortStudentReportsV2(engine, "DDS2", ...)` raised
`ValueError: paraparser: syntax error: parse ended with 1 unclosed tags` from
`_v2ReflectionCard` → `Paragraph(assessorHtml ...)`.

**Cause.** `_buildReflectionComposite` emitted `<b>Label: </b>value` with the
**value unescaped**. reportlab parses a Paragraph as mini-XML, so a reflection
containing `<` (e.g. `"monitor <45deg"`), `&`, or a stray tag-like fragment is
read as markup and the parse fails. The dynamic composite surfaced more text
keys (DDS2 structured student keys + assessor feedback), which is why it began
tripping on DDS2.

**Fix.** In `_buildReflectionComposite`, for the reportlab path (`bold=True`)
escape both the label and the value with `xml.sax.saxutils.escape`, keeping only
our own `<b>` tags; the Excel path (`bold=False`) stays raw:
```python
if bold:
    segments.append(f"<b>{escape(label)}: </b>{escape(v.strip())}")
else:
    segments.append(f"{label}: {v.strip()}")
```
`
` in the value is untouched, so the card's later `.replace("\n", "<br/>")`
still works. Because the escaping is in the shared composite builder it protects
**both** the V2 cards and the V1 `_addReflectionsTable`, for every cohort.
`createTable`/`_v2ReflectionCard` pass these strings as Paragraph markup (no
second escape), so labels still render bold and values are literal.

**Verified.** `<b>Feedback: </b>Occlusion a &lt; b, monitor &lt;45deg &amp; review`
parses in a reportlab `Paragraph` without error; `py_compile` clean. Backup
`.bak_reflescape_20260915_*`.

