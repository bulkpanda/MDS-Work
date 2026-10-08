import pandas as pd, numpy as np, statsmodels.formula.api as smf
from scipy import stats
IPC='IPC (Wyndham Vale)'; MINF=30
d=pd.read_pickle('forms.pkl')
d=d[d.clinic.ne('Unknown/Other')]
r=d[d.rated].copy()
# small clinics lumped per cohort
def lump(df):
    cnt=df.groupby(['cohort','clinic']).size()
    small={k for k,v in cnt.items() if v<MINF}
    df['clinicM']=[ 'Other (small)' if (c,k) in small else k for c,k in zip(df.cohort,df.clinic)]
    return df
r=lump(r)
# rotation-stage expected value within cohort (used for residual-based views)
r['entStage']=r.groupby(['cohort','rotNum']).ent.transform('mean')
r['entDev']=r.ent-r.entStage

def rawTable(df,keys):
    g=df.groupby(keys)
    t=g.agg(forms=('formId','size'),students=('studentNumber','nunique'),assessors=('assessorId','nunique'),
            entMean=('ent','mean'),lowShare=('low','mean'),anyWeak=('anyWeak','mean'),weakCats=('nWeakCat','mean'),
            techWeak=('weakness-technical-skills','mean'),timeWeak=('weakness-timeliness','mean'),
            concernRate=('concern','mean'),incidentRate=('incident','mean'),
            patientsPerForm=('nAttended','mean'),itemsPerForm=('nItems','mean'),paedPerForm=('nPaed','mean'),
            stageAdjDev=('entDev','mean'),meanRotation=('rotNum','mean'))
    return t.reset_index()

def feModel(df,outcome):
    """outcome ~ student FE + rotation FE + clinic (sum-to-zero, form-weighted centring); SE clustered by assessor"""
    df=df.dropna(subset=[outcome]).copy()
    ref=df.clinicM.value_counts().index[0]
    m=smf.ols(f'{outcome} ~ C(studentNumber) + C(rotNum) + C(clinicM, Treatment(reference="{ref}"))',data=df)\
        .fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(df.assessorId)[0]})
    names=[n for n in m.params.index if n.startswith('C(clinicM')]
    lab=[n.split('[T.')[1][:-1] for n in names]
    b=pd.Series(0.0,index=[ref]+lab); b[lab]=m.params[names].values
    V=pd.DataFrame(0.0,index=b.index,columns=b.index); V.loc[lab,lab]=m.cov_params().loc[names,names].values
    w=df.clinicM.value_counts().reindex(b.index).values; w=w/w.sum()
    C=np.eye(len(b))-np.outer(np.ones(len(b)),w)   # effect vs form-weighted average placement
    eff=C@b.values; se=np.sqrt(np.clip(np.diag(C@V.values@C.T),0,None))
    out=pd.DataFrame({'clinic':b.index,'adjEffect':eff,'se':se})
    out['ciLow']=out.adjEffect-1.96*out.se; out['ciHigh']=out.adjEffect+1.96*out.se
    out['p']=2*stats.norm.sf(abs(out.adjEffect/out.se.replace(0,np.nan)))
    out['nForms']=df.clinicM.value_counts().reindex(out.clinic).values
    return out,m

def pairedIPC(df,minEach=3):
    rows=[]
    for (coh),g in df.groupby('cohort'):
        s=g.groupby(['studentNumber',g.clinicM.eq(IPC)]).agg(n=('entDev','size'),dev=('entDev','mean'),low=('low','mean')).unstack()
        s=s[(s[('n',True)]>=minEach)&(s[('n',False)]>=minEach)]
        diff=s[('dev',True)]-s[('dev',False)]; dlow=s[('low',True)]-s[('low',False)]
        t=stats.ttest_1samp(diff,0); wx=stats.wilcoxon(diff)
        rows.append(dict(cohort=coh,students=len(s),meanEntDiff=diff.mean(),ciLow=diff.mean()-1.96*diff.std()/np.sqrt(len(s)),
            ciHigh=diff.mean()+1.96*diff.std()/np.sqrt(len(s)),studentsLowerAtIPC=int((diff<0).sum()),
            pT=t.pvalue,pWilcoxon=wx.pvalue,meanLowShareDiff=dlow.mean()))
    return pd.DataFrame(rows)

def assessorEffects(df):
    """Residual after student FE + rotation FE (no clinic), averaged per assessor with empirical-Bayes shrinkage."""
    out=[]
    for coh,g in df.groupby('cohort'):
        g=g.copy()
        m=smf.ols('ent ~ C(studentNumber) + C(rotNum)',data=g).fit()
        g['res']=m.resid
        a=g.groupby('assessorId').agg(n=('res','size'),resMean=('res','mean'),resVar=('res','var'))
        sig2=g.res.var()
        # method-of-moments between-assessor variance
        big=a[a.n>=5]; tau2=max(np.average(big.resMean**2,weights=big.n)-sig2*np.average(1/big.n,weights=big.n),0.0)
        a['shrink']=tau2/(tau2+sig2/a.n); a['adjEffect']=a.shrink*a.resMean
        a['se']=np.sqrt(a.shrink*sig2/a.n)  # posterior sd
        a['ciLow']=a.adjEffect-1.96*a.se; a['ciHigh']=a.adjEffect+1.96*a.se
        info=g.groupby('assessorId').agg(assessorName=('assessorName','first'),students=('studentNumber','nunique'),
            mainClinic=('clinicM',lambda s:s.value_counts().index[0]),mainClinicShare=('clinicM',lambda s:s.value_counts(normalize=True).iloc[0]),
            clinics=('clinicM',lambda s:'; '.join(f'{k} ({v})' for k,v in s.value_counts().items())),
            rawEnt=('ent','mean'),lowShare=('low','mean'),anyWeak=('anyWeak','mean'),concernRate=('concern','mean'))
        a=info.join(a).reset_index(); a.insert(0,'cohort',coh); a['tau']=np.sqrt(tau2); a['sigma']=np.sqrt(sig2)
        a['status']=np.select([(a.n>=15)&(a.ciHigh<0),(a.n>=15)&(a.ciLow>0)],['Harsher','More lenient'],np.where(a.n<15,'Too few forms','Typical'))
        out.append(a)
    return pd.concat(out)

def varianceDecomp(df):
    rows=[]
    for coh,g in df.groupby('cohort'):
        fits={}
        for name,f in [('Rotation stage','ent ~ C(rotNum)'),('+ Student','ent ~ C(rotNum)+C(studentNumber)'),
                       ('+ Placement','ent ~ C(rotNum)+C(studentNumber)+C(clinicM)'),
                       ('+ Assessor','ent ~ C(rotNum)+C(studentNumber)+C(clinicM)+C(assessorId)')]:
            fits[name]=smf.ols(f,data=g).fit()
        prev=0
        for k,m in fits.items():
            rows.append(dict(cohort=coh,step=k,R2=m.rsquared,adjR2=m.rsquared_adj,addedR2=m.rsquared-prev,params=int(m.df_model))); prev=m.rsquared
        # reverse order: assessor before placement -> how much placement adds beyond assessor
        m2=smf.ols('ent ~ C(rotNum)+C(studentNumber)+C(assessorId)',data=g).fit()
        rows.append(dict(cohort=coh,step='(check) Rotation+Student+Assessor, no placement',R2=m2.rsquared,adjR2=m2.rsquared_adj,
                         addedR2=fits['+ Assessor'].rsquared-m2.rsquared,params=int(m2.df_model)))
    return pd.DataFrame(rows)

def ipcWithoutAssessors(df,drop):
    s=df[~df.assessorId.isin(drop)]
    return pairedIPC(s)

ENT_FLAG_STATES=('Consistently low','Falling behind')
def trajectoryStates(df,col,k=1.0,minForms=5,drop=1.0):
    """Mirror of boh3_dds4_flagging.evaluateEntrustmentTrajectory with each rotation as a window."""
    res=[]
    for coh,g in df.groupby('cohort'):
        w=g.groupby(['studentNumber','rotNum']).agg(n=(col,'size'),avg=(col,'mean'),
            ipcShare=('clinicM',lambda s:(s==IPC).mean()),mainClinic=('clinicM',lambda s:s.value_counts().index[0])).reset_index()
        ok=w[w.n>=minForms]
        st=ok.groupby('rotNum').avg.agg(['mean','std'])
        w=w.join(st,on='rotNum'); w['z']=np.where(w.n>=minForms,(w.avg-w['mean'])/w['std'],np.nan)
        w['lowWindow']=w.z<=-k; w.insert(0,'cohort',coh)
        for sn,s in w.dropna(subset=['z']).sort_values('rotNum').groupby('studentNumber'):
            zs=s.z.values; low=zs<=-k
            if len(zs)<2: state='Insufficient data'
            elif low.all(): state='Consistently low'
            elif low[-1] and zs[0]-zs[-1]>=drop: state='Falling behind'
            elif low[-1]: state='Low recently'
            elif low[0]: state='Catching up'
            else: state='On track'
            res.append(dict(cohort=coh,studentNumber=sn,state=state,lowWindows=int(low.sum()),judged=len(zs),
                            lowWindowsAtIPC=int((low&(s.ipcShare.values>=0.5)).sum()),hadIPC=bool((s.ipcShare>=0.5).any())))
        yield w
    trajectoryStates.students=pd.DataFrame(res)
