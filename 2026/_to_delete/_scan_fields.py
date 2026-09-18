import ijson, collections, json
PATH="temp 2026 caf.json"
atx=collections.Counter(); stx=collections.Counter(); ams=collections.Counter(); sms=collections.Counter()
ex_atx={}; ex_stx={}
def has(v):
    return v is not None and (not isinstance(v,(list,dict,str)) or len(v)>0)
n=0
with open(PATH,"rb") as f:
    for rec in ijson.items(f,"item"):
        if rec.get("cohort") not in ("BOH3","DDS4"): continue
        m=str(rec.get("datetime") or "")[:7]
        if m < "2026-07": continue          # current structure only
        for form in (rec.get("forms") or []):
            ad=form.get("assessor_data") or {}; sd=form.get("student_data") or {}
            for k,v in (ad.get("texts") or {}).items():
                if has(v): atx[k]+=1; ex_atx.setdefault(k,str(v)[:70])
            for k,v in (sd.get("texts") or {}).items():
                if has(v): stx[k]+=1; ex_stx.setdefault(k,str(v)[:70])
            for k,v in (ad.get("multi-select") or {}).items():
                if has(v): ams[k]+=1
            for k,v in (sd.get("multi-select") or {}).items():
                if has(v): sms[k]+=1
        n+=1
print("records (BOH3+DDS4, Jul+):", n)
print("\nASSESSOR texts.* (free-text):")
for k,c in atx.most_common(): print(f"  {k:38s} {c:5d}   e.g. {ex_atx[k]!r}")
print("\nSTUDENT texts.* (free-text):")
for k,c in stx.most_common(): print(f"  {k:38s} {c:5d}   e.g. {ex_stx[k]!r}")
print("\nASSESSOR multi-select.* (tag/select, some carry free text):")
for k,c in ams.most_common(): print(f"  {k:42s} {c:5d}")
print("\nSTUDENT multi-select.*:")
for k,c in sms.most_common(): print(f"  {k:42s} {c:5d}")
