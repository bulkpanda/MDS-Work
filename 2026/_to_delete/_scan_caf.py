import ijson, collections, sys, json
PATH = "temp 2026 caf.json"
def has(v):
    if v is None: return False
    if isinstance(v, (list, dict, str)): return len(v) > 0
    return True
byMonth = collections.defaultdict(lambda: collections.Counter())
textsKeys = collections.defaultdict(collections.Counter)
msKeys = collections.defaultdict(collections.Counter)
adKeys = collections.Counter()
samples = []
nrec = 0
with open(PATH, "rb") as f:
    for rec in ijson.items(f, "item"):
        if rec.get("cohort") != "BOH3": continue
        dt = str(rec.get("datetime") or ""); month = dt[:7]
        for form in (rec.get("forms") or []):
            ad = form.get("assessor_data") or {}
            sub_a = form.get("submitted_by_assessor")
            rot = ((form.get("form_context") or {}).get("placement") or {}).get("rotation")
            rotn = "".join(ch for ch in str(rot or "") if ch.isdigit())
            c = byMonth[month]; c["forms"] += 1
            if sub_a: c["submitted_by_assessor"] += 1
            for k in ad.keys(): adKeys[k] += 1
            texts = ad.get("texts") or {}
            for k, v in texts.items():
                if has(v): textsKeys[month][k] += 1
            ms = ad.get("multi-select") or {}
            for k, v in ms.items():
                if has(v): msKeys[month][k] += 1
            if has(ms.get("weakness-other")): c["weakness-other"] += 1
            if has(ms.get("strengths")): c["strengths"] += 1
            if has(ms.get("clinical-incident")): c["clinical-incident"] += 1
            if has(texts.get("additional-concerns")): c["additional-concerns"] += 1
            if month >= "2026-06" and rotn in ("4","5","6","7") and sub_a and len(samples) < 6:
                samples.append({"month": month,"rotation": rot,
                    "assessor_data_keys": sorted(ad.keys()),
                    "texts_keys": sorted(texts.keys()),
                    "texts_nonempty": {k:(str(v)[:60]) for k,v in texts.items() if has(v)},
                    "multiselect_keys": sorted(ms.keys()),
                    "multiselect_nonempty": {k:len(v) for k,v in ms.items() if has(v)}})
        nrec += 1
print("BOH3 records scanned:", nrec)
print("assessor_data top-level keys seen (count):", dict(adKeys))
print("\n=== per-month BOH3 ===")
for m in sorted(byMonth):
    c=byMonth[m]
    print(f"{m}: forms={c['forms']:4d} subA={c['submitted_by_assessor']:4d} wOther={c['weakness-other']:4d} strengths={c['strengths']:4d} incident={c['clinical-incident']:3d} addConcern={c['additional-concerns']:3d}")
print("\n=== texts keys populated per month ===")
for m in sorted(textsKeys): print(m, dict(textsKeys[m]))
print("\n=== multi-select keys populated per month ===")
for m in sorted(msKeys): print(m, dict(msKeys[m]))
print("\n=== June+ R4-7 samples ===")
for s in samples: print(json.dumps(s, ensure_ascii=False))
