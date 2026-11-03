import json, copy, statistics, importlib
import osce_utils as ou
importlib.reload(ou)
import openpyxl

SRC="temp 2026 osce.json"
STATION_WB="OSCE/DDS2/DDS2 OSCE.xlsx"
ANALYSIS_WB="OSCE/DDS2/DDS2 BLR & Validity.xlsx"

MAP={
 'spec-cons-radiography':'radiography',
 'spec-cons-medical-emergency':'medical-emergency',
 'spec-cons-infection-control':'infection-control',
 'spec-cons-referral':'referral',
 'spec-cons-conservative-dentistry':'conservative-dentistry',
 'spec-cons-local-anaesthesia':'local-anaesthetic',
 'spec-cons-periodontics':'periodontics',
 'spec-cons-communication-with-staff':'communication-with-staff',
 'spec-cons-occlusal-assessment':'occlusal-assessment-note-to-markers-student-must-write-no-nil-no-marks-awarded-for-blank-boxes',
 'spec-cons-communication-with-a-patient':'communication-with-a-patient',
 'spec-cons-medical-history':'medical-history',
 'spec-cons-risk-and-recall':'risk-and-recall',
 'spec-cons-informed-consent':'informed-consent',
}

recs=json.load(open(SRC,encoding='utf-8'))
her=[r for r in recs if r.get('round_label')=='2026 DDS2 Spec Cons OSCE']
print("her raw records:",len(her),"student:",her[0]['student'], her[0]['student_number'])

# rename checklist keys in a deep copy (form_data + form_config)
her2=[]
for r in her:
    r=copy.deepcopy(r)
    fd=r['form_data'].get('checklists',{})
    fc=r['form_config'].get('checklists',{})
    for sk,ck in MAP.items():
        if sk in fd: fd[ck]=fd.pop(sk)
        if sk in fc: fc[ck]=fc.pop(sk)
    her2.append(r)

specs=ou.buildStationSpecs(her2, reverseGr="auto", scoreConfig=None, stationOverrides=None)
print("specs built:",len(specs))

# hand recompute per checklist to cross-check buildStationSpecs
def hand_score(r, ck):
    cfg=r['form_config']['checklists'][ck]
    scales=ou.checklistItemScales(cfg)  # {i:(keyPoints,max,level,order)}
    cv=r['form_data']['checklists'][ck]
    fracs=[]
    for i,(kp,mx,lvl,order) in scales.items():
        if lvl<2: continue
        c=cv.get(f"MC{i}")
        key=c.get('key') if isinstance(c,dict) else None
        if key in kp and mx:
            fracs.append(kp[key]/mx)
    return (sum(fracs)/len(fracs)*100) if fracs else None

byck_hand={}
for r in her2:
    for ck in r['form_data']['checklists']:
        byck_hand[ck]=round(hand_score(r,ck),2)

# frozen cohort data from existing workbooks
swb=openpyxl.load_workbook(STATION_WB,data_only=True,read_only=True)
ss=swb['Station Summary']
rows=list(ss.iter_rows(values_only=True))
hdr=list(rows[0])
ci={h:i for i,h in enumerate(hdr)}
disp2cut={}; disp2station={}; disp2mean={}
for row in rows[1:]:
    if row[ci['Checklist']] is None: continue
    disp=str(row[ci['Checklist']]).strip()
    disp2cut[disp]=row[ci['BLR Cut %']]
    disp2station[disp]=row[ci['Station']]
    disp2mean[disp]=row[ci['Mean %']]

awb=openpyxl.load_workbook(ANALYSIS_WB,data_only=True,read_only=True)
stds=awb['Standard Setting']
srows=list(stds.iter_rows(values_only=True))
# find the cut table header row
disp2m2sd={}
for i,row in enumerate(srows):
    if row and row[0]=='Station' and 'Mean-2SD %' in [str(c) for c in row]:
        shdr=[str(c) for c in row]; j=shdr.index('Mean-2SD %'); cj=shdr.index('Checklist')
        for r2 in srows[i+1:]:
            if not r2 or r2[0] in (None,'Station'): break
            if str(r2[0]).startswith('Number'): break
            disp2m2sd[str(r2[cj]).strip()]=r2[j]
        break

print("\n%-26s %6s %6s %5s %7s %6s  %s"%("Checklist","Score%","Cut%","Pass","GR","M2SD%","hand✓"))
her_scores={}  # ck-> (score1dp, cut, pass, gr, disp, station)
for s in sorted(specs, key=lambda s: s['ck']):
    ck=s['ck']; r=s['rows'][0]
    sc=r['score']; pp=ou.pct1(sc) if sc is not None else None
    disp=s['cfg']['name'].split('.')[0][:40].strip()
    cut=disp2cut.get(disp); m2=disp2m2sd.get(disp)
    passed = (pp is not None and cut is not None and pp>=cut)
    hand=byck_hand.get(ck)
    ok = (abs(round(pp,2)-hand)<0.01) if (pp is not None and hand is not None) else False
    her_scores[ck]=dict(score=pp, cut=cut, passed=passed, gr=r['gr'], disp=disp, station=disp2station.get(disp), m2=m2)
    print("%-26s %6.1f %6s %5s %5s %6s  %s"%(disp[:26], pp, cut, 'Y' if passed else 'N', r['gr'], m2, 'ok' if ok else f'MISMATCH hand={hand}'))

vals=[v['score'] for v in her_scores.values()]
fails=sum(1 for v in her_scores.values() if v['cut'] is not None and v['score']<v['cut'])
below2=sum(1 for v in her_scores.values() if v['m2'] is not None and v['score']<v['m2'])
print("\nMean %% (13): %.1f  | Fails(BLR): %d  | <M-2SD: %d"%(statistics.mean(vals), fails, below2))
