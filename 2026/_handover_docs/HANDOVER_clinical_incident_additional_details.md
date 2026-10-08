# HANDOVER — Clinical incident: surface category + additional-details (2026-09-22)

## Scope

`boh2_dds2_dds3_utils.py` (`clinicalIncidentSqlExpr()` rewrite) and `flagging_utils.py` (Clinical Incidents sheet now sorted **date descending**, newest first — was student-name then date; backup `_bak/flagging_utils.py.bak_20260922_061557`). No
notebook change; the existing `getDataDf` / `getCriticalIncidentDf` call sites are
untouched, so **re-run `main.ipynb` cell 15** (flagging) and the cohort-report
cells to pick it up. Backup: `_bak/boh2_dds2_dds3_utils.py.bak_20260922_055048`.
Verified statically (`ast.parse` + `sqlglot` PostgreSQL parse, both alias forms)
and by replaying the SQL COALESCE semantics in Python over the whole
`temp 2026 caf.json` (816 MB, streamed with `ijson`). Not run against live
Postgres — the Cowork VM can't reach `localhost`.

Builds on and supersedes part of `HANDOVER_dds2_clinic_flagging_fhy.md` §7
(the 2026-08-18 clinical-incident fix). See also
`_docs/boh2_dds2_dds3_utils.md` §5 (`clinicalIncidentSqlExpr`).

## The problem

The flagging Clinical Incidents sheet and the cohort report's Critical Incident
sheet both read one resolved value, `clinical_incident`, produced by
`clinicalIncidentSqlExpr()`. The 2026-08-18 version read the incident **detail**
only from `assessor_data->'texts'->>'clinical-incident'`. But the current 2026
BOH2/DDS2 template does **not** use that key. It records an incident in THREE
complementary fields at once:

- `assessor_data->'radio'->>'clinical-incident-occurred'` = `"yes"` / `"no"`
- `assessor_data->'multi-select'->'clinical-incident'` = the **category** (CI codes)
- `assessor_data->'texts'->>'clinical-incident-additional-details'` = the **detail** text

Because the old expression's radio branch fired on `occurred='yes'`, looked up the
empty `clinical-incident` text key, and returned the `"Yes (no details recorded)"`
fallback, it **short-circuited before the multi-select branch** and dropped both
the category and the real detail.

### Worked example — the sample Kunal flagged

BOH2 Clinic, 14 Sep 2026, student Chelsea Pham (session 52124, form 56108,
assessor Abella Huynh). Raw payload:

```jsonc
"assessor_data": {
  "radio":        { "clinical-incident-occurred": "yes" },
  "multi-select": { "clinical-incident": [
                      { "key": "CI14",
                        "value": "Sharps injuries and/or blood and bodily fluid exposures" } ] },
  "texts":        { "reflection": "...",
                    "clinical-incident-additional-details":
                      "Poked LA needle into patient's upper lip, aiming for 22\nEducated student to turn the patient's head position towards them to improve vision." }
}
```

- **Before:** `clinical_incident` = `"Yes (no details recorded)"` — category and detail both lost.
- **After:** `clinical_incident` = `"Sharps injuries and/or blood and bodily fluid exposures — Poked LA needle into patient's upper lip, aiming for 22\nEducated student to turn the patient's head position towards them to improve vision."`

## Measured shapes across the 2026 CAF pull

243 forms carry any clinical-incident signal. Tuple = (occurred=yes, has
`texts.clinical-incident`, has `texts.clinical-incident-additional-details`, has
multi-select category):

| Shape | Forms | Old output | New output |
|---|---|---|---|
| (yes, –, ✓, ✓) modern BOH2/DDS2 | 117 | "Yes (no details recorded)" | **Category — detail** |
| (yes, ✓, –, –) older radio+text | 95 | text | text *(unchanged)* |
| (no, ✓, –, –) "Nil"/"N/A", occurred=no | 22 | NULL | NULL *(unchanged — see gate)* |
| (yes, –, –, –) ticked, nothing typed | 5 | "Yes (no details recorded)" | "Yes (no details recorded)" |
| (no, –, ✓, ✓) category+detail, occurred=no | 2 | category only | **Category — detail** |
| (no, –, ✓, –) detail only, occurred=no | 1 | NULL | NULL *(gate)* |
| (no, –, –, ✓) category only | 1 | category | category |

**Net effect: identical set of flagged forms (220 non-NULL), pure content
enrichment.** The change never turns a non-incident into an incident; it only
fills in the category + detail that were being discarded.

## The fix

New `clinicalIncidentSqlExpr(alias="f")` generates:

```sql
COALESCE(
    NULLIF(concat_ws(' — ',
        (SELECT string_agg(x->>'value', '; ' ORDER BY x->>'value')             -- category
           FROM jsonb_array_elements(
                COALESCE(f.assessor_data->'multi-select'->'clinical-incident','[]'::jsonb)) x),
        CASE WHEN lower(COALESCE(f.assessor_data->'radio'->>'clinical-incident-occurred',''))='yes'
                  OR (SELECT string_agg(...) ...) IS NOT NULL                   -- gate
             THEN COALESCE(                                                      -- detail
                    NULLIF(TRIM(COALESCE(f.assessor_data->'texts'->>'clinical-incident','')),''),
                    NULLIF(TRIM(COALESCE(f.assessor_data->'texts'->>'clinical-incident-additional-details','')),''))
        END
    ), ''),
    CASE WHEN lower(COALESCE(f.assessor_data->'radio'->>'clinical-incident-occurred',''))='yes'
         THEN 'Yes (no details recorded)' END,                                  -- tick-only marker
    NULLIF(TRIM(COALESCE(f.clinical_incident, '')), '')                         -- stored fallback
)
```

### Design decisions

1. **Compose, don't short-circuit.** `Category — detail` via `concat_ws(' — ', …)`
   (em dash, U+2014, emitted from the Python source as `—`). `concat_ws` skips
   NULL args, so a category-only form shows just the category and a detail-only
   (older) form shows just the detail.
2. **Detail precedence** `clinical-incident` → `clinical-incident-additional-details`
   (COALESCE). They never co-occur in the 2026 pull, so this just picks whichever
   key the template used.
3. **Gate the detail on evidence of an incident** — `occurred='yes'` OR a
   multi-select category is present. This is what keeps the 22 `occurred='no'`
   forms that typed "Nil"/"None"/"N/A" in the free-text box out of the sheet,
   exactly as before. A category is itself evidence, so the 2 `occurred='no'`
   forms that *selected* a category still surface (with their detail).
4. **Composed value beats the stored column.** The stored `clinical_incident`
   column was derived from this same JSON by the loader, so it can never hold more
   than we can recompute; putting the composed value first repairs the current
   table with **no reload**. Stored is kept only as a last-ditch fallback.
5. **`Yes (no details recorded)` marker** (`CLINICAL_INCIDENT_NO_DETAILS`) is the
   third branch — reached only when the assessor ticked yes but no category/detail
   exists (5 forms), so a genuine tick is never mistaken for "no incident".

## Consumers (unchanged call sites, all benefit)

- `getDataDf` → `clinical_incident_resolved` swapped over the raw column in Python
  → flagging `getFlagDf` (`ci_count`, `flag_clinical_incident`) and
  `_build_clinical_incidents_sheet` ("Clinical Incidents" sheet, "Incident Details").
- `getCriticalIncidentDf` (`incidentExpr = clinicalIncidentSqlExpr("")`, in both the
  SELECT and the WHERE) → cohort report "Critical Incident" sheet.

`clinical-incident-additional-details` stays in `REFLECTION_TEXT_DENY`, so it is
NOT duplicated into the reflection composite — it belongs to the clinical-incident
field only.

## Verification

- `sqlglot.parse_one(..., dialect="postgres")` on `SELECT <expr> FROM t f` and the
  no-alias form — both valid.
- Python replay of the COALESCE precedence over every clinical-incident form in
  `temp 2026 caf.json`: the seven shapes resolve exactly as the table above; Chelsea
  Pham's 14-Sep form yields the category + detail string quoted above; 220 forms
  non-NULL (same count as before the change).

## Open

- Not run against live Postgres (Cowork VM can't reach `localhost`). First real run:
  re-run cell 15 for BOH2 Clinic and confirm the "Clinical Incidents" sheet shows
  `Category — detail` for the September forms (Chelsea Pham 14-Sep is the check row).
- The memory/handover note that says the detail lives in `texts.clinical-incident`
  described the older template only; the 2026 template's detail key is
  `clinical-incident-additional-details` with the category in multi-select.
