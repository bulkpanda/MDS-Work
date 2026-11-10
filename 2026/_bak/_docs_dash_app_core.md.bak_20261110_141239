# `dash_app_core.py`

> Engine + rendering for [`dash_app.py`](dash_app.md): `.env`/token, DASH fetch, per-exam `ExamCache`, generic template/section discovery, item scoring, section/overall aggregation, overrides, filters, and the HTML for stat cards, table, comment modal and on-demand form view.
> Hand-written 2026-11-06 with an `ast` pass on that date (counts, signatures, line numbers).

| | |
|---|---|
| **Lines of code** | 1,120 |
| **Top-level functions** | 52 |
| **Classes** | 2 (`OverrideStore`, `ExamCache`) |
| **Module constants** | 14 |
| **Imports from this codebase** | `dash_app_config` (as `cfg`) |
| **Imported by** | `dash_app`, `dash_app_export`. |
| **Run how** | Imported only — run `python dash_app.py`. |

Overview, scoring rules, data model, how-to recipes and gotchas: see **[`dash_app.md`](dash_app.md)**.

## Functions


### 1. Environment + auth

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 21 | `readEnvFile` | `(path: Path)` | KEY=VALUE lines from .env; file values win over stale shell/Windows env vars. |
| 38 | `envVal` | `(key: str)` | .env value, else OS env, quotes stripped. |
| 50 | `getToken` | `(force: bool=False)` | POST /accounts/login with DASH_EMAIL/DASH_PASSWORD; cached; force=True re-logs in. Never logs credentials. |
| 67 | `fetchAll` | `(endpoint: str, cohorts: list, token: str)` | GET /assessment/<endpoint>/get, all pages (DRF Token auth). |
| 84 | `loadRaw` | `(examKey: str)` | All cohorts of one exam: live API (re-login once on 400/401/403), or LOCAL_JSON_DIR file for offline tests. |
| 101 | `httpErrorMsg` | `(e, endpoint: str)` | HTTPError → friendly status-bar message (401/403/404). |

### 2. Generic form reading

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 109 | `esc` | `(s)` | HTML-escape any value for the table / modal. |
| 113 | `cleanText` | `(s)` | Strip HTML tags + collapse whitespace. |
| 118 | `natKey` | `(k)` | Natural sort key: MC2 < MC10, d1-dds4 < d2-dds4. |
| 123 | `slotNum` | `(o: str)` | 'O3' → 3 (99 when not an O-slot). |
| 127 | `isSlot` | `(k)` | True for keys like O1…O9. |
| 131 | `optionLabels` | `(meta: dict)` | {O1: label, …} from extra_config.options.assessor (student as fallback). |
| 138 | `rubricOf` | `(meta: dict, mc: str)` | The rubric dict for one MC ({O1: label, …, label: html}). |
| 142 | `enabledSlots` | `(meta: dict, mc: str)` | Options shown for this item (non-empty rubric slots; all options when there is no rubric), best first. |
| 151 | `findSlot` | `(value: str, optLbl: dict, rub: dict)` | Stored answer → O-slot (matches option label, then rubric label, then a literal O-code). |
| 163 | `slotPoints` | `(slot: str, enabled: list, optLbl: dict, rub: dict, profile: dict)` | Points for a slot under the profile's points method. |
| 184 | `scoreItem` | `(value, meta: dict, mc: str, profile: dict)` | (points \| None, itemMax \| None, display label, slot). Display = stored label + rubric wording when it differs. |
| 211 | `headerTitles` | `(meta: dict, mc: str)` | Clean header titles attached to one MC (may be [top, sub]). |
| 217 | `sectionMap` | `(meta: dict, mcs: list, fallback: str)` | {mc: (section, subsection)} from checklist headers. Multi-level headers ([top, sub]) → sections = tops. |
| 236 | `shortLabel` | `(title: str, idx: int)` | Compact column label: 'DOMAIN 2: …'→D2, 'Oral Medicine – Case Scenario 1'→OM1, '3. Treatment…'→S3. |
| 253 | `itemShort` | `(profile: dict, text: str, mc: str)` | Column label for an item-as-section: first itemShorts regex matching the question text, else the MC key. |
| 261 | `shortList` | `(names: list)` | Unique short labels for an ordered list of section names. |
| 270 | `headerTops` | `(meta: dict, mcs: list, fallback: str)` | Ordered distinct section names of one checklist. |
| 275 | `mcKeysOf` | `(meta: dict, answers: dict)` | Item keys of a checklist from its fields (fallback: answered keys), natural-sorted. |
| 281 | `isRichMeta` | `(meta: dict)` | Checklist meta has options + fields (used to pick the best template meta). |

### 3. Templates (which checklists belong together) + profile choice

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 286 | `chooseProfile` | `(exam: dict, metas: dict)` | First matching profileRule on the template's checklist metadata, else the exam default. |
| 299 | `templateLabel` | `(keys: list, metas: dict)` | Display name of a template: the key, or the common prefix/suffix + '(n parts)'. |
| 308 | `buildTemplates` | `(raw: list, examKey: str)` | Group checklist keys that appear on the same forms (union-find) → templates; richest meta per key. |

### 4. Aggregation

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 356 | `aggregate` | `(items: list, unansweredAsZero: bool, method: str)` | Section/overall maths over item dicts {points, max}. |
| 371 | `sectionMethod` | `(profile: dict, sectionName: str)` | % method for one section: its group's method when the profile uses groups, else profile['sectionPct']. |
| 379 | `isUnsafe` | `(it: dict, profile: dict)` | Safety item answered with an option whose rubric wording matches the matrix unsafeRegex. |
| 385 | `matrixResult` | `(items: list, profile: dict)` | (%, info) for overall='matrix': row item × column item lookup; unsafe safety answer caps below the pass mark. |
| 407 | `overallPct` | `(sections: OrderedDict, items: list, profile: dict)` | (Overall %, {group: %}, info) per profile['overall']; info carries the matrix outcome / unsafe flag. |

### 5. Parse

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 437 | `meaningful` | `(txt)` | Text is not blank / None / No / N/A — used for critical-error and incident fields. |
| 442 | `readScales` | `(ad: dict, scales: dict, exam: dict)` | Primary GR (preferred scale keys first) + other scales. Labels come from the form's own scale fields. |
| 460 | `buildComments` | `(ad: dict, tpl, shortOf: dict)` | '[Label] text' lines: general, per-checklist, other *_comments, critical fields. |
| 483 | `parseRecord` | `(r: dict, examKey: str, templates: dict, keyToTid: dict)` | One raw DASH record → flat row (private keys start with _). |
| 605 | `parseRecords` | `(raw: list, examKey: str)` | Raw list → (rows, templates) for one exam. |

### 6. Manual overrides (<exam>_overrides.json, re-read live)

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 612 | `normName` | `(s: str)` | Case/space-insensitive; drops bracketed nicknames: 'Yue Heng Xu (Kevin)' → 'yue heng xu'. |
| 617 | **class `OverrideStore`** | | Penalties per student/form + ignoreAssessors, reloaded when the file's mtime changes. |
| 620 | `OverrideStore.__init__` | `(self, examKey: str)` | Path = <exam>_overrides.json next to the app. |
| 624 | `OverrideStore.load` | `(self)` | Re-read the file only when its mtime changes; bad JSON keeps the last good set. |
| 642 | `OverrideStore.matches` | `(o: dict, r: dict)` | Override targets a row by student and/or formId (both must match when both given). |
| 650 | `OverrideStore.apply` | `(self, rows: list)` | Reset each row to its computed % then apply penalties (idempotent); returns unmatched labels. |

### 7. Shared per-exam cache

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 679 | **class `ExamCache`** | | One DASH pull per CACHE_TTL for ALL browser tabs; re-parse only when the payload hash changes. |
| 682 | `ExamCache.__init__` | `(self, examKey: str)` | Empty cache + its OverrideStore. |
| 688 | `ExamCache.get` | `(self, force: bool=False)` | (rows, version, message); fetches only when stale/forced. |
| 718 | `ExamCache.asOf` | `(self)` | '<exam> data as of HH:MM:SS' status text. |

### 8. Filters

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 727 | `parseDateTs` | `(s: str, endOfDay: bool=False)` | 'YYYY-MM-DD' → timestamp (end of day when asked); None if blank/invalid. |
| 735 | `isExcluded` | `(name: str, hideTest: bool)` | Exact EXCLUDE names always; dummy/test substrings only when Hide dummy/test is ticked. |
| 740 | `applyFilters` | `(rows, cohorts, checklist, submittedOnly, unsubmittedOnly, ccOnly, hideTest, search, sortOpt=cfg.DEFAULT_SORT, dateFrom='', dateTo='')` | Filter + sort cached rows (no API call). |
| 770 | `selectedChecklists` | `(checklist)` | Multi-select value → set of checklist labels; empty / 'All' = no restriction. |
| 778 | `describeFilters` | `(cohorts, checklist, so, uo, cco, ht, q, srt, df, dt)` | Human-readable filter summary written into exports. |

### 9. HTML rendering

| Line | Function | Signature | Purpose |
|---:|---|---|---|
| 787 | `pctColor` | `(p)` | Colour for a % (green ≥ 85, blue ≥ 65, amber ≥ 40, red). |
| 791 | `statCard` | `(label, value, color='#0f172a', tip='')` | One stat card div. |
| 799 | `statsHtml` | `(rows: list)` | The row of nine stat cards for the filtered rows. |
| 880 | `grBadge` | `(r: dict)` | Coloured GR pill with scale name + label tooltip. |
| 889 | `statusCell` | `(r: dict)` | ✓ / ✓! (incomplete) / x-of-y in progress / ✗ cell. |
| 903 | `commentsCell` | `(text: str)` | Scrollable comments cell; double-click opens the full-comment modal. |
| 919 | `tableHtml` | `(rows: list, templates: dict, grouped: bool=False)` | Styled table. Section columns appear when the view holds a single checklist template. |
| 1022 | `formHtml` | `(row: dict, examKey: str)` | Full-form view for the modal (built on demand). |

## Module constants

`APP_DIR` (L17), `ENV_FILE` (L35), `DASH_EMAIL` (L43), `DASH_PASSWORD` (L43), `ENV_TOKEN` (L43), `LOGIN_USER` (L44), `LOGIN_PASS` (L45), `tokenState` (L47), `tokenLock` (L47), `caches` (L723), `COMMENT_MODAL_HANDLER` (L824), `FORM_JS` (L847), `DASH` (L877), `CSS` (L1108)
