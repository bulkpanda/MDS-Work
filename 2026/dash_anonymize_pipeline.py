import re, time, pickle
import pandas as pd, spacy
from wordfreq import zipf_frequency

INFILE='/mnt/user-data/uploads/_unimelb_dash_all_data.xlsx'
MAPFILE='/mnt/project/RE__Student_List_Anonymized.xlsx'
FREE=['assessor_feedback','student_feedback','clinical_incident']
TOKEN='[NAME]'
DICT_ZIPF_MAX=5.5     # dictionary names with zipf >= this are treated as common words, not redacted context-free

A=pickle.load(open('artifacts.pkl','rb'))   # reuse structured mappings
roster=pd.read_excel(MAPFILE)
sup_vals=set(A['sup'].keys())

# ---- expanded stoplists ----
CLINICAL_STOP=set('''ortho endo perio prostho paedo resto restoration caries molar incisor canine premolar
buccal lingual labial mesial distal occlusal palatal gingival mesio disto bucco linguo
radiograph radiographs bitewing bws pa opg scaler curette gracey sickle hoe chisel explorer probe elevator luxator forceps handpiece bur burs blade
matrix clamp dam composite amalgam resin vitrebond calcium hydroxide glass ionomer gic rmgic bonding etch primer adhesive
crown bridge denture implant anaesthetic anaesthesia la infiltration block floss fissure sealant plaque calculus debridement
photograph photographs upload consent review operator assistant supervisor patient student clinic clinical session
tooth teeth quadrant surface margin isolation positioning reflection feedback assessment rubber needle bevel
anterior posterior maxillary mandibular pulp root enamel dentine dentin soft tissue support da srd oht dds boh
prep preparation cavity restoration angulation activation activated aim slight learnt felt need needed done well
labial lingual perio srp resto mes mesio dist bucco linguo occ inc'''.split())
ROLE_STOP={'operator','assistant','supervisor','patient','student','clinician','tutor','educator',
           'demonstrator','examiner','assessor','support','observer','nurse','dentist','therapist'}
# capitalised-at-sentence-start common words spaCy mis-tags as PERSON
COMMON_START={'my','to','do','he','she','we','see','may','will','felt','slight','aim','learnt','need','tried',
              'assisted','good','great','well','consider','ensure','patient','overall','today','also','use','used'}
COMBINED=CLINICAL_STOP|ROLE_STOP|COMMON_START

TITLE_RE=re.compile(r'\b(?:Dr|Drs|Mr|Mrs|Ms|Miss|Prof|A/?Prof|Assoc\.?\s*Prof|Professor|Doctor)\.?\s+[A-Z][a-zA-Z\u2019\'.\-]*(?:\s+[A-Z][a-zA-Z\u2019\'.\-]*)?')

def known():
    s=set()
    srcs=[roster['First Name'].dropna().astype(str), roster['Last Name'].dropna().astype(str),
          pd.Series(list(sup_vals))]
    for series in srcs:
        for v in series:
            for tok in re.split(r'[\s\-]+',str(v).strip()):
                tok=tok.strip(".'\u2019")
                low=tok.lower()
                if len(tok)>=2 and tok[0].isupper() and low not in COMBINED \
                   and zipf_frequency(low,'en')<DICT_ZIPF_MAX:
                    s.add(tok)
    return s
KNOWN=known()
DICT_RE=re.compile(r'\b('+'|'.join(sorted(map(re.escape,KNOWN),key=len,reverse=True))+r')\b') if KNOWN else None

def ner_ok(ent):
    if ent.label_!='PERSON': return None
    t=ent.text.strip()
    if t==TOKEN: return None
    if not re.match(r"^[A-Z][a-zA-Z\u2019'.\-]*(?:\s+[A-Z][a-zA-Z\u2019'.\-]*)*$",t): return None
    toks=[w.strip(".'\u2019").lower() for w in re.split(r'\s+',t)]
    toks=[w for w in toks if w]
    if not toks: return None
    if all(w in COMBINED for w in toks): return None      # pure clinical/role/common phrase
    if len(toks)==1 and zipf_frequency(toks[0],'en')>=DICT_ZIPF_MAX: return None  # lone common word
    return t

# unique strings
nd=pd.read_excel(INFILE,sheet_name='all_data_nested',dtype=str,usecols=FREE)
fd=pd.read_excel(INFILE,sheet_name='all_data_flat',dtype=str,usecols=FREE)
uniq=set()
for df in (nd,fd):
    for c in FREE: uniq|={u for u in df[c].dropna().astype(str) if u.strip()}
uniq=list(uniq)
print('unique strings:',len(uniq),'| dict names:',len(KNOWN))

nlp=spacy.load('en_core_web_sm',disable=['tagger','parser','lemmatizer','attribute_ruler'])
def pre(s):
    ch=[]
    def _t(m): ch.append(('title',m.group(0))); return TOKEN
    s=TITLE_RE.sub(_t,s)
    if DICT_RE:
        def _d(m): ch.append(('dict',m.group(0))); return TOKEN
        s=DICT_RE.sub(_d,s)
    return s,ch

cache={}; log=[]; t=time.time()
pretexts=[pre(u) for u in uniq]
for orig,(s,ch),doc in zip(uniq,pretexts,nlp.pipe([p[0] for p in pretexts],batch_size=256)):
    out=[]; last=0
    for ent in doc.ents:
        nm=ner_ok(ent)
        if nm is None: continue
        out.append(s[last:ent.start_char]); out.append(TOKEN); last=ent.end_char
        ch.append(('ner',nm))
    out.append(s[last:]); cache[orig]=''.join(out)
    for kind,rm in ch: log.append((orig,kind,rm))
print('NER %.1fs'%(time.time()-t),'| replacements:',len(log))

A['cache']=cache; A['log']=log
pickle.dump(A,open('artifacts.pkl','wb'))
print('by layer:', pd.DataFrame(log,columns=['o','layer','r'])['layer'].value_counts().to_dict())
import os, time, pickle
import pandas as pd

INFILE='/mnt/user-data/uploads/_unimelb_dash_all_data.xlsx'
OUTDIR='/mnt/user-data/outputs'; os.makedirs(OUTDIR,exist_ok=True)
A=pickle.load(open('artifacts.pkl','rb'))
anon,sup_map,pt_map,cache=A['anon'],A['sup'],A['pt'],A['cache']
FREE=['assessor_feedback','student_feedback','clinical_incident']

def apply(df):
    df['student_number']=df['student_number'].map(lambda x: anon.get(str(x),x) if pd.notna(x) else x)
    df['student_name']=[num if pd.notna(nm) else nm for nm,num in zip(df['student_name'],df['student_number'])]
    df['assessor_name']=df['assessor_name'].map(lambda x: sup_map.get(str(x),x) if pd.notna(x) else x)
    df['patient_drn']=df['patient_drn'].map(lambda x: pt_map.get(str(x),x) if pd.notna(x) else x)
    for c in FREE:
        if c in df.columns:
            df[c]=[cache.get(v,v) if (pd.notna(v) and str(v).strip()) else v for v in df[c]]
    return df

t=time.time()
nd=pd.read_excel(INFILE,sheet_name='all_data_nested',dtype=str); print('read nested %.1fs'%(time.time()-t))
t=time.time()
fd=pd.read_excel(INFILE,sheet_name='all_data_flat',dtype=str);   print('read flat %.1fs'%(time.time()-t))
nd=apply(nd); fd=apply(fd)

out=os.path.join(OUTDIR,'_unimelb_dash_all_data_anonymized.xlsx')
t=time.time()
with pd.ExcelWriter(out,engine='xlsxwriter') as xw:
    nd.to_excel(xw,sheet_name='all_data_nested',index=False,na_rep='')
    fd.to_excel(xw,sheet_name='all_data_flat',index=False,na_rep='')
print('write xlsx %.1fs'%(time.time()-t))

# side files
import pandas as pd
pd.DataFrame(A['log'],columns=['original_text','layer','removed_text']).to_csv(
    os.path.join(OUTDIR,'dash_redaction_review_log.csv'),index=False)
pd.DataFrame(sorted(sup_map.items()),columns=['assessor_name','anon']).to_csv(
    os.path.join(OUTDIR,'dash_supervisor_mapping.csv'),index=False)
pd.DataFrame(sorted(pt_map.items()),columns=['patient_drn','anon']).to_csv(
    os.path.join(OUTDIR,'dash_patient_drn_mapping.csv'),index=False)
print('OUTPUT',out)
