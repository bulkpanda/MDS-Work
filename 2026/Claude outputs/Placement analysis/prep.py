import pandas as pd, numpy as np, json, re
CANON = {
 'ipc (wyndham vale)':'IPC (Wyndham Vale)','dtc':'DTC','dtc yeah':'DTC','dtc snd':'DTC','mdc':'MDC',
 'pc':'RDHM PC','primary care':'RDHM PC','primary care rdhm':'RDHM PC','rdhm pc':'RDHM PC','rdhm pc emergency':'RDHM PC',
 'moe':'La Trobe Community Health (Moe)','la trobe community health (moe)':'La Trobe Community Health (Moe)',
 'preston':'Your Community (Preston)','your community (preston)':'Your Community (Preston)','your community (preston)313':'Your Community (Preston)','panch':'Your Community (Preston)',
 'clayton':'Link Health (Clayton)','link health (clayton)':'Link Health (Clayton)','link health (claytonove':'Link Health (Clayton)',
 'cohealth (footscray)':'Cohealth (Footscray)','cohealth footscray':'Cohealth (Footscray)',
 'boxhill':'Health Ability (Box Hill)','health ability (box hill)':'Health Ability (Box Hill)',
 'gvh':'GV Health (Shepparton)','gv health (shepparton)':'GV Health (Shepparton)',
 'banyule':'Holstep (Banyule)','holstep (banyule)':'Holstep (Banyule)',
 'eyes, ears and mouth':'Eyes, Ears and Mouth','eyes ears and mouth':'Eyes, Ears and Mouth',
 'beaufort and skipton':'Beaufort and Skipton','beaufort and skipton clinic':'Beaufort and Skipton',
}
def canon(x):
    if not isinstance(x,str) or not x.strip(): return 'Unknown'
    k=re.sub(r'\s+',' ',x.strip()).lower()
    if k.startswith('gove') or k.startswith('yirrkala'): return 'Gove / NT (Yirrkala)'
    if k in CANON: return CANON[k]
    if re.fullmatch(r'\d+|dent\d+|other',k): return 'Unknown/Other'
    return re.sub(r'\s+',' ',x.strip())
WEAK=['weakness-technical-skills','weakness-knowledge-clinical-reasoning','weakness-timeliness','weakness-communication',
      'weakness-professional-behaviour','weakness-risk-management','weakness-person-centered-care','weakness-other']
def load():
    d=pd.read_csv('forms.csv',dtype=str)
    d['clinic']=d.clinic.map(canon)
    d['dt']=pd.to_datetime(d.datetime,utc=True).dt.tz_convert('Australia/Melbourne')
    d['period']=np.where(d.dt<pd.Timestamp('2026-07-01',tz='Australia/Melbourne'),'FHY','SHY')
    d['rotNum']=d.rotation.str.extract(r'(\d+)')[0].astype(float)
    d['ent']=d.entKey.str.extract(r'S(\d)')[0].astype(float)
    d['low']=(d.ent<=2).astype(float).where(d.ent.notna())
    ms=d.msJson.map(json.loads)
    for w in WEAK: d[w]=ms.map(lambda m: int(bool(m.get(w))))
    d['nWeakCat']=d[WEAK[:-1]].sum(1)
    d['anyWeak']=(d[WEAK].sum(1)>0).astype(int)
    rad=d.radioJson.map(lambda s: json.loads(s) if isinstance(s,str) else None)
    d['concern']=(d.concern=='yes').astype(int)
    d['incident']=((d.incident=='yes')|ms.map(lambda m: bool(m.get('clinical-incident')))).astype(int)
    for c in ['nPatients','nAttended','nItems']: d[c]=d[c].astype(int)
    d['ages']=d.ages.fillna('')
    d['nPaed']=d.ages.map(lambda s: sum(1 for a in s.split('|') if a.strip().isdigit() and int(a)<18))
    d['rated']=(d.subAssessor=='True')&d.ent.notna()
    d['isIPC']=d.clinic.eq('IPC (Wyndham Vale)')
    return d
