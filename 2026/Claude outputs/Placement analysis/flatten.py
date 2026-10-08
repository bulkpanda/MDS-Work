import ijson,json,csv,collections
out=open('/sessions/'+__import__('os').environ['HOME'].split('/sessions/')[1]+'/work/forms.csv' if False else __import__('os').path.expanduser('~/work/forms.csv'),'w',newline='')
w=None; keyc=collections.Counter();sigC=collections.Counter(); scaleOpts={}
with open('temp 2026 caf dds4_boh3.json','rb') as f:
  for rec in ijson.items(f,'item',use_float=True):
    for fm in rec.get('forms',[]):
      fc=fm.get('form_context') or {}; ad=fm.get('assessor_data') or {}; sd=fm.get('student_data') or {}
      for k in fc: keyc['fc.'+k]+=1
      for k in (fc.get('placement') or {}): keyc['pl.'+k]+=1
      for sec,v in ad.items():
        if isinstance(v,dict):
          for k in v: keyc['ad.%s.%s'%(sec,k)]+=1
      rawClinic=(fc.get('placement') or {}).get('external_clinic')
      opts={}
      for sc in fm.get('context_schema_snapshot') or []:
        if sc.get('key')=='placement.external_clinic': opts=sc.get('options') or {}
      decoded=opts.get(rawClinic,rawClinic) if isinstance(rawClinic,str) else rawClinic
      optSig='|'.join('%s=%s'%kv for kv in sorted(opts.items()))
      sigC[(rec.get('cohort'),optSig)]+=1
      pats=fc.get('patients') or []
      ms=ad.get('multi-select') or {}
      ent=((ad.get('scales') or {}).get('scale-entrustment') or {})
      if ent.get('key'): scaleOpts[ent['key']]=ent.get('value','')[:90]
      smc=((sd.get('checklists') or {}).get('checklist-caf-final-eval') or {})
      row=dict(recId=rec['id'],datetime=rec['datetime'],type=rec.get('type'),cohort=rec.get('cohort'),subject=rec.get('subject'),
        studentNumber=(rec.get('student') or {}).get('student_number'),
        studentName=' '.join(filter(None,[(rec.get('student') or {}).get('first_name'),(rec.get('student') or {}).get('last_name')])),
        formId=fm['id'],assessorId=fm.get('assessor'),assessorName=fm.get('assessor_name'),assessorEmail=fm.get('assessor_email'),
        rotation=(fc.get('placement') or {}).get('rotation'),clinicRaw=rawClinic,clinic=decoded,hasSnapshot=bool(opts),
        placementJson=json.dumps(fc.get('placement')),
        nPatients=len(pats),nAttended=sum(1 for p in pats if p.get('patient_attended')),
        nItems=sum(int(c.get('quantity') or 1) for p in pats for c in (p.get('item_codes') or [])),
        itemCodes='|'.join(c.get('code','') for p in pats for c in (p.get('item_codes') or [])),
        ages='|'.join(str(p.get('patient_age','')) for p in pats),
        entKey=ent.get('key'),
        selfPr=(((sd.get('scales') or {}).get('scale-practice-readiness')) or {}).get('key'),
        selfMc='|'.join('%s=%s'%(k,(v or {}).get('key') if isinstance(v,dict) else v) for k,v in smc.items()),
        strengths='|'.join(x.get('key','') for x in (ms.get('strengths') or [])),
        weaknesses='|'.join(x.get('key','') for x in (ms.get('weaknesses') or ms.get('areas-for-improvement') or [])),
        msJson=json.dumps({k:[x.get('key') for x in v] if isinstance(v,list) else v for k,v in ms.items()}),
        incident=(ad.get('radio') or {}).get('clinical-incident-occurred'),
        concern=(ad.get('radio') or {}).get('additional-concerns-occurred'),
        radioJson=json.dumps(ad.get('radio')),
        subStudent=fm.get('submitted_by_student'),subAssessor=fm.get('submitted_by_assessor'),createdAt=fm.get('created_at'))
      if w is None: w=csv.DictWriter(out,fieldnames=list(row)); w.writeheader()
      w.writerow(row)
out.close()
import pickle;pickle.dump(sigC,open(__import__('os').path.expanduser('~/work/sig.pkl'),'wb')); print(scaleOpts)
