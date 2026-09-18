import ijson, json
PATH="temp 2026 caf.json"
ex_wo=[]; ex_ac=[]; ex_ac_early=[]
with open(PATH,"rb") as f:
    for rec in ijson.items(f,"item"):
        if rec.get("cohort")!="BOH3": continue
        m=str(rec.get("datetime") or "")[:7]
        for form in (rec.get("forms") or []):
            ad=form.get("assessor_data") or {}
            ms=ad.get("multi-select") or {}; tx=ad.get("texts") or {}
            wo=ms.get("weakness-other"); ac=tx.get("additional_comments")
            if m<="2026-05" and wo and len(ex_wo)<3:
                ex_wo.append((m, wo))
            if m<="2026-05" and ac and len(ex_ac_early)<3:
                ex_ac_early.append((m, ac))
            if m>="2026-07" and ac and len(ex_ac)<4:
                ex_ac.append((m, form.get("assessor_name"), ac))
        if len(ex_wo)>=3 and len(ex_ac)>=4 and len(ex_ac_early)>=3: break
print("=== <=May weakness-other (multi-select) examples ===")
for m,v in ex_wo: print(m, json.dumps(v, ensure_ascii=False)[:300])
print("\n=== <=May texts.additional_comments examples ===")
for m,v in ex_ac_early: print(m, json.dumps(v, ensure_ascii=False)[:300])
print("\n=== >=July texts.additional_comments examples ===")
for m,n,v in ex_ac: print(m, "|", json.dumps(v, ensure_ascii=False)[:300])
