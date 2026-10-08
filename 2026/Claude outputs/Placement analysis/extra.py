import sys,pickle;sys.path.insert(0,'.')
from analysis import *
import warnings;warnings.filterwarnings('ignore')
a=pd.read_pickle('assessors.pkl'); r2=pd.read_pickle('rated_adj.pkl'); dAll=pd.read_pickle('forms.pkl')
X={}
X['rotTrend']=r.groupby(['cohort','rotNum']).agg(ent=('ent','mean'),low=('low','mean'),n=('ent','size')).reset_index()
# assessor stability FHY vs SHY
af=assessorEffects(r[r.period=='FHY'])[['cohort','assessorId','n','adjEffect']]; ash=assessorEffects(r[r.period=='SHY'])[['cohort','assessorId','n','adjEffect']]
st=af.merge(ash,on=['cohort','assessorId'],suffixes=('FHY','SHY')); st=st[(st.nFHY>=15)&(st.nSHY>=15)]
st=st.merge(a[['cohort','assessorId','assessorName','mainClinic']],on=['cohort','assessorId'])
X['stability']=st; X['stabilityR']={c:stats.pearsonr(g.adjEffectFHY,g.adjEffectSHY) for c,g in st.groupby('cohort')}
# exposure bias per student
r2['asEffF']=r2.asEff.fillna(0)
harshIds=set(zip(a[a.status=='Harsher'].cohort,a[a.status=='Harsher'].assessorId))
r2['byHarsh']=[(c,x) in harshIds for c,x in zip(r2.cohort,r2.assessorId)]
ex=r2.groupby(['cohort','studentNumber']).agg(forms=('ent','size'),assessors=('assessorId','nunique'),exposureBias=('asEffF','mean'),
    shareHarsh=('byHarsh','mean'),maxAssessorShare=('assessorId',lambda s:s.value_counts(normalize=True).iloc[0]),
    rawEnt=('ent','mean'),ipcForms=('isIPC','sum')).reset_index()
ex['studentName']=ex.studentNumber.map(dAll.groupby('studentNumber').studentName.first())
X['exposure']=ex
# self-rating vs entrustment
r2['selfR']=r2.selfPr.str.extract(r'S(\d)')[0].astype(float)
r2['selfDev']=r2.selfR-r2.groupby(['cohort','rotNum']).selfR.transform('mean')
sv=[]
for coh,g in r2.dropna(subset=['selfR']).groupby('cohort'):
    s=g.groupby(['studentNumber',g.isIPC]).agg(n=('ent','size'),entDev=('entDev','mean'),selfDev=('selfDev','mean'),
        ent=('ent','mean'),selfR=('selfR','mean')).unstack()
    s=s[(s[('n',True)]>=3)&(s[('n',False)]>=3)]
    for m in ['ent','selfR']:
        dv=m.replace('selfR','self')+'Dev'; dd=s[(dv,True)]-s[(dv,False)]
        sv.append(dict(cohort=coh,measure='Assessor entrustment' if m=='ent' else 'Student self-rated readiness',students=len(s),
            atIPC=s[(m,True)].mean(),elsewhere=s[(m,False)].mean(),withinStudentDiff=dd.mean(),ciLow=dd.mean()-1.96*dd.std()/np.sqrt(len(s)),
            ciHigh=dd.mean()+1.96*dd.std()/np.sqrt(len(s)),p=stats.ttest_1samp(dd,0).pvalue))
X['selfVsEnt']=pd.DataFrame(sv)
# within-placement assessor spread
big=a[a.n>=15]
X['withinSite']=big.groupby(['cohort','mainClinic']).agg(assessors=('assessorId','size'),minEff=('adjEffect','min'),maxEff=('adjEffect','max'),
    sdEff=('adjEffect','std'),forms=('n','sum')).reset_index().query('assessors>=2')
X['withinSite']['range']=X['withinSite'].maxEff-X['withinSite'].minEff
# entrustment distribution per assessor
dist=r2.groupby(['cohort','assessorId','ent']).size().unstack(fill_value=0); dist=dist.div(dist.sum(1),axis=0)
dist.columns=[f'L{int(c)}' for c in dist.columns]; X['entDist']=dist.reset_index().merge(a[['cohort','assessorId','assessorName','n','mainClinic','adjEffect','status']],on=['cohort','assessorId'])
# weakness vs entrustment per assessor (student-adjusted weakness residual)
wk=[]
for coh,g in r2.groupby('cohort'):
    g=g.copy(); g['wres']=smf.ols('anyWeak ~ C(studentNumber)+C(rotNum)',data=g).fit().resid
    wk.append(g.groupby('assessorId').wres.mean().rename('weakAdj').reset_index().assign(cohort=coh))
wk=pd.concat(wk).merge(a[['cohort','assessorId','assessorName','n','adjEffect','anyWeak','concernRate','mainClinic','status']],on=['cohort','assessorId'])
X['weakVsEnt']=wk[wk.n>=15]; X['weakVsEntR']={c:stats.pearsonr(g.adjEffect,g.weakAdj) for c,g in X['weakVsEnt'].groupby('cohort')}
# monthly
r2['month']=r2.dt.dt.to_period('M').astype(str)
X['monthly']=r2.groupby(['cohort','month',r2.isIPC.map({True:'IPC',False:'All other placements'})]).agg(dev=('entDev','mean'),n=('ent','size')).reset_index().rename(columns={'isIPC':'site'})
X['monthly'].columns=['cohort','month','site','dev','n']
# co-occurrence: assessors per student, students per assessor
X['assessorsPerStudent']=ex[['cohort','assessors','maxAssessorShare']]
X['mobility']=a.groupby('cohort').apply(lambda x: pd.Series({'assessors':len(x),'oneSiteShare':(x.mainClinicShare>=0.9).mean(),'formsBySingleSiteAssessors':x[x.mainClinicShare>=0.9].n.sum()/x.n.sum()})).reset_index()
pickle.dump(X,open('extra.pkl','wb'))
pd.set_option('display.width',250)
print(X['stabilityR']); print(X['selfVsEnt'].round(3)); print(X['weakVsEntR']); print(X['mobility'])
print(ex.groupby('cohort').exposureBias.describe().round(3)); print(ex.groupby('cohort').assessors.describe().round(1))
print(X['withinSite'].sort_values('range',ascending=False).round(2).head(12).to_string(index=False))
print(stats.pearsonr(ex[ex.cohort=='DDS4'].exposureBias,ex[ex.cohort=='DDS4'].ipcForms))
