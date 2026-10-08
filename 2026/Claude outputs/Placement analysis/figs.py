import sys,pickle,os;sys.path.insert(0,'.')
from analysis import *
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
import warnings;warnings.filterwarnings('ignore')
BLUE='#2A6EBB';ORANGE='#D9711C';GREY='#9AA3AD';NAVY='#094183';INK='#222222';MUTED='#666666'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.edgecolor':'#BBBBBB','axes.labelcolor':INK,'xtick.color':MUTED,'ytick.color':MUTED,
  'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.color':'#EEEEEE','grid.linewidth':0.8,'axes.titleweight':'bold','axes.titlesize':10,'axes.titlecolor':INK,'axes.axisbelow':True})
OUT=os.path.expanduser('~/mnt/2026/Claude outputs/Placement analysis/figures'); os.makedirs(OUT,exist_ok=True)
X=pickle.load(open('extra.pkl','rb')); S=pickle.load(open('sheets.pkl','rb')); a=pd.read_pickle('assessors.pkl'); r2=pd.read_pickle('rated_adj.pkl')
def save(fig,name): fig.savefig(f'{OUT}/{name}.png',dpi=170,bbox_inches='tight'); plt.close(fig)
def sc(e): return np.where(e< -0.15,ORANGE,np.where(e>0.15,BLUE,GREY))
short=lambda s: s.replace(' Community Health','').replace(' (Wyndham Vale)','').replace('Community ','Comm. ')

# F1 rotation trend
fig,ax=plt.subplots(figsize=(7,3.2))
for coh,c in [('DDS4',NAVY),('BOH3',ORANGE)]:
    t=X['rotTrend'][X['rotTrend'].cohort==coh]; ax.plot(t.rotNum,t.ent,'-o',color=c,lw=2,ms=6,label=coh)
    ax.text(t.rotNum.iloc[-1]+0.15,t.ent.iloc[-1],coh,color=c,va='center',fontweight='bold')
ax.set_xlabel('Rotation'); ax.set_ylabel('Mean entrustment (1–4)'); ax.set_title('Entrustment rises through the year — every comparison is adjusted for rotation stage')
ax.legend(frameon=False,loc='lower right'); save(fig,'f01_rotation_trend')

# F2/F3 placement forest (raw stage-adjusted vs student-adjusted), All period
adj=S['Placement Adjusted']; raw=S['Placement Raw']
for i,coh in enumerate(['DDS4','BOH3']):
    e=adj[(adj.cohort==coh)&(adj.period=='All')].sort_values('entEffect')
    rw=raw[(raw.cohort==coh)&(raw.period=='All')].set_index('placement')
    rwc=rw.stageAdjDev-np.average(rw.stageAdjDev,weights=rw.forms)
    fig,ax=plt.subplots(figsize=(7.2,0.32*len(e)+1.3)); y=np.arange(len(e))
    ax.hlines(y,e.entCiLow,e.entCiHigh,color=sc(e.entEffect),lw=2)
    ax.scatter(rwc.reindex(e.placement),y,facecolors='white',edgecolors=MUTED,s=34,zorder=3,label='Raw (stage-adjusted only)')
    ax.scatter(e.entEffect,y,color=sc(e.entEffect),s=46,zorder=4,edgecolors='white',linewidths=1.5,label='Same-student adjusted (95% CI)')
    ax.axvline(0,color=INK,lw=0.8); ax.set_yticks(y); ax.set_yticklabels([f'{short(p)} (n={n})' for p,n in zip(e.placement,e.nForms)],fontsize=8)
    ax.set_xlabel('Entrustment vs average placement (levels)   ← harder | easier →'); ax.set_title(f'{coh}: placement effect on entrustment, Jan–Oct 2026')
    ax.legend(frameon=False,fontsize=7.5,loc='lower right'); save(fig,f'f0{2+i}_placement_forest_{coh}')

# F4 FHY vs SHY placement effect (dumbbell)
fig,axs=plt.subplots(1,2,figsize=(10,5.6))
for ax,coh in zip(axs,['DDS4','BOH3']):
    f=adj[(adj.cohort==coh)&(adj.period=='FHY')].set_index('placement').entEffect; s=adj[(adj.cohort==coh)&(adj.period=='SHY')].set_index('placement').entEffect
    pl=f.index.intersection(s.index); order=adj[(adj.cohort==coh)&(adj.period=='All')].set_index('placement').entEffect.reindex(pl).sort_values().index
    y=np.arange(len(order)); ax.hlines(y,f[order],s[order],color='#DDDDDD',lw=2)
    ax.scatter(f[order],y,color=NAVY,s=40,zorder=3,label='FHY',edgecolors='white'); ax.scatter(s[order],y,color=ORANGE,s=40,zorder=3,label='SHY',marker='D',edgecolors='white')
    ax.axvline(0,color=INK,lw=0.8); ax.set_yticks(y); ax.set_yticklabels([short(p) for p in order],fontsize=7.5); ax.set_title(f'{coh}'); ax.set_xlabel('Adjusted effect (levels)')
    ax.legend(frameon=False,fontsize=8)
fig.suptitle('Placement effects by half-year (same-student adjusted)',fontweight='bold',fontsize=10); fig.tight_layout(); save(fig,'f04_placement_fhy_shy')

# F5 IPC within-student slope
fig,axs=plt.subplots(1,2,figsize=(8,3.8),sharey=True)
for ax,coh in zip(axs,['DDS4','BOH3']):
    g=r2[r2.cohort==coh]; s=g.groupby(['studentNumber',g.isIPC]).agg(n=('ent','size'),dev=('entDev','mean')).unstack()
    s=s[(s[('n',True)]>=3)&(s[('n',False)]>=3)]
    for _,row in s.iterrows():
        lower=row[('dev',True)]<row[('dev',False)]
        ax.plot([0,1],[row[('dev',False)],row[('dev',True)]],color=ORANGE if lower else BLUE,alpha=0.55,lw=1.2,marker='o',ms=3)
    ax.plot([0,1],[s[('dev',False)].mean(),s[('dev',True)].mean()],color=INK,lw=3,marker='o',ms=7,label='Mean')
    ax.set_xticks([0,1]); ax.set_xticklabels(['Other placements','IPC']); ax.set_xlim(-0.3,1.3)
    ax.set_title(f'{coh}: {int((s[("dev",True)]<s[("dev",False)]).sum())} of {len(s)} students lower at IPC'); ax.axhline(0,color='#CCCCCC',lw=0.8)
axs[0].set_ylabel('Entrustment vs cohort mean\nat same rotation (levels)'); axs[0].legend(frameon=False,fontsize=8)
fig.tight_layout(); save(fig,'f05_ipc_within_student')

# F6 IPC assessor entrustment distributions
dist=X['entDist']; ipcA=r2[r2.isIPC].groupby(['cohort','assessorId']).size().rename('ipcN').reset_index()
dd=dist.merge(ipcA,on=['cohort','assessorId']); dd=dd[dd.ipcN>=10]
fig,axs=plt.subplots(1,2,figsize=(10,3.6))
cols={'L1':'#8C2D04','L2':ORANGE,'L3':'#B8C4D0','L4':BLUE}
for ax,coh in zip(axs,['DDS4','BOH3']):
    t=dd[dd.cohort==coh].sort_values('adjEffect'); y=np.arange(len(t)); left=np.zeros(len(t))
    for L in ['L1','L2','L3','L4']:
        v=t[L].fillna(0).values if L in t else np.zeros(len(t)); ax.barh(y,v,left=left,color=cols[L],edgecolor='white',linewidth=1.5,label=L,height=0.7); left+=v
    ax.grid(axis='y',visible=False); ax.set_yticks(y); ax.set_yticklabels([f'{n} [{i}] (IPC n={k})' for n,i,k in zip(t.assessorName,t.assessorId,t.ipcN)],fontsize=7.5)
    ax.set_xlim(0,1); ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1)); ax.set_title(f'{coh}: entrustment levels given by IPC assessors (harshest first)',fontsize=9); ax.invert_yaxis()
axs[1].legend(frameon=False,ncol=4,fontsize=8,loc='upper center',bbox_to_anchor=(0.5,-0.12)); axs[0].legend(frameon=False,ncol=4,fontsize=8,loc='upper center',bbox_to_anchor=(0.5,-0.12))
fig.tight_layout(); save(fig,'f06_ipc_assessor_distribution')

# F7 assessor caterpillar (two columns)
for i,coh in enumerate(['DDS4','BOH3']):
    t=a[(a.cohort==coh)&(a.n>=15)].sort_values('adjEffect').reset_index(drop=True); half=(len(t)+1)//2
    fig,axs=plt.subplots(1,2,figsize=(11,0.155*half+1.6),sharex=True)
    for ax,part in zip(axs,[t.iloc[:half],t.iloc[half:]]):
        y=np.arange(len(part)); c=np.where(part.status=='Harsher',ORANGE,np.where(part.status=='More lenient',BLUE,GREY))
        ax.hlines(y,part.ciLow,part.ciHigh,color=c,lw=1.5); ax.scatter(part.adjEffect,y,color=c,s=16,zorder=3)
        ipc=part.mainClinic.str.startswith('IPC').values
        ax.scatter(part.adjEffect[ipc],y[ipc],facecolors='none',edgecolors=INK,s=60,lw=1.2,zorder=4,label='Main site = IPC')
        ax.set_yticks(y); ax.set_yticklabels([f'{n} [{i}] · {short(m)} · n={k}' for n,i,m,k in zip(part.assessorName,part.assessorId,part.mainClinic,part.n)],fontsize=6)
        ax.axvline(0,color=INK,lw=0.8); ax.invert_yaxis(); ax.set_ylim(half-0.5,-0.5); ax.set_xlabel('Adjusted effect (levels)   ← harsher | lenient →',fontsize=8)
    axs[0].legend(frameon=False,fontsize=7,loc='lower right')
    fig.suptitle(f'{coh}: assessor effects, harshest first (≥15 rated forms; orange = harsher, blue = more lenient, 95% interval)',fontweight='bold',fontsize=10)
    fig.tight_layout(); save(fig,f'f0{7+i}_assessor_caterpillar_{coh}')

# F9 within-site spread strip
ws=a[a.n>=15].copy(); ws=ws[ws.groupby(['cohort','mainClinic']).assessorId.transform('size')>=3]
fig,axs=plt.subplots(1,2,figsize=(10,4.6))
for ax,coh in zip(axs,['DDS4','BOH3']):
    t=ws[ws.cohort==coh]; order=t.groupby('mainClinic').adjEffect.mean().sort_values().index
    for j,p in enumerate(order):
        v=t[t.mainClinic==p]; ax.scatter(v.adjEffect,np.full(len(v),j)+np.random.uniform(-0.12,0.12,len(v)),c=sc(v.adjEffect),s=np.clip(v.n/4,10,120),alpha=0.85,edgecolors='white',lw=0.8)
        ax.hlines(j,v.adjEffect.min(),v.adjEffect.max(),color='#DDDDDD',lw=1,zorder=0)
    ax.set_yticks(range(len(order))); ax.set_yticklabels([short(p) for p in order],fontsize=8); ax.axvline(0,color=INK,lw=0.8)
    ax.set_title(coh); ax.set_xlabel('Assessor effect (levels); dot size = forms')
fig.suptitle('Assessors at the same site differ widely (sites with ≥3 assessors with ≥15 forms)',fontweight='bold',fontsize=10); fig.tight_layout(); save(fig,'f09_within_site_spread')

# F10 variance decomposition
vd=S['Variance Decomposition']; vd=vd[~vd.step.str.startswith('(check)')]
fig,ax=plt.subplots(figsize=(7,2.6)); comp=['Rotation stage','+ Student','+ Placement','+ Assessor']; cc=[GREY,NAVY,ORANGE,BLUE]; lab=['Rotation stage','Student','Placement','Assessor']
for j,coh in enumerate(['DDS4','BOH3']):
    left=0
    for k,(st,c,l) in enumerate(zip(comp,cc,lab)):
        v=vd[(vd.cohort==coh)&(vd.step==st)].addedR2.iloc[0]; ax.barh(j,v,left=left,color=c,edgecolor='white',lw=2,label=l if j==0 else None)
        ax.text(left+v/2,j,f'{v:.0%}',ha='center',va='center',color='white',fontsize=8,fontweight='bold'); left+=v
    ax.text(left+0.01,j,f'Unexplained {1-left:.0%}',va='center',fontsize=8,color=MUTED)
ax.set_yticks([0,1]); ax.set_yticklabels(['DDS4','BOH3']); ax.set_xlim(0,0.7); ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1))
ax.set_title('Share of entrustment variation explained (added in this order)'); ax.legend(frameon=False,ncol=4,fontsize=8,loc='upper center',bbox_to_anchor=(0.45,-0.18)); save(fig,'f10_variance_decomposition')

# F11 stability
fig,axs=plt.subplots(1,2,figsize=(9,3.8))
for ax,coh in zip(axs,['DDS4','BOH3']):
    t=X['stability'][X['stability'].cohort==coh]; rr=X['stabilityR'][coh]
    ax.scatter(t.adjEffectFHY,t.adjEffectSHY,c=sc(t.adjEffectFHY),s=40,edgecolors='white'); lim=[-1,1]; ax.plot(lim,lim,color='#CCCCCC',lw=1,ls='--')
    ax.axhline(0,color='#DDD',lw=0.8); ax.axvline(0,color='#DDD',lw=0.8); ax.set_xlim(-1,1); ax.set_ylim(-1,1)
    ax.set_title(f'{coh}: r = {rr.statistic:.2f} ({len(t)} assessors)'); ax.set_xlabel('Assessor effect FHY'); ax.set_ylabel('Assessor effect SHY')
fig.suptitle('Assessor stringency is stable across the year',fontweight='bold',fontsize=10); fig.tight_layout(); save(fig,'f11_assessor_stability')

# F12 weakness vs entrustment
fig,axs=plt.subplots(1,2,figsize=(9,3.8))
for ax,coh in zip(axs,['DDS4','BOH3']):
    t=X['weakVsEnt'][X['weakVsEnt'].cohort==coh]; rr=X['weakVsEntR'][coh]; ipc=t.mainClinic.str.startswith('IPC')
    ax.scatter(t.adjEffect,t.weakAdj,c=sc(t.adjEffect),s=np.clip(t.n/4,10,120),edgecolors='white',alpha=0.85)
    ax.scatter(t.adjEffect[ipc],t.weakAdj[ipc],facecolors='none',edgecolors=INK,s=90,lw=1.2,label='Main site = IPC')
    for _,row in t[ipc&(t.n>=40)].iterrows(): ax.annotate(row.assessorId,(row.adjEffect,row.weakAdj),xytext=(5,3),textcoords='offset points',fontsize=7)
    ax.axhline(0,color='#DDD');ax.axvline(0,color='#DDD'); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1))
    ax.set_title(f'{coh}: r = {rr.statistic:.2f}'); ax.set_xlabel('Entrustment effect (levels)'); ax.set_ylabel('Weakness-tag rate vs same students elsewhere')
axs[0].legend(frameon=False,fontsize=8); fig.suptitle('Stricter raters tend to tag more weaknesses',fontweight='bold',fontsize=10); fig.tight_layout(); save(fig,'f12_weakness_vs_entrustment')

# F13 self vs assessor at IPC
sv=X['selfVsEnt']; fig,ax=plt.subplots(figsize=(7,2.8)); y=0; ticks=[]
for coh in ['DDS4','BOH3']:
    for m,c in [('Assessor entrustment',ORANGE),('Student self-rated readiness',BLUE)]:
        row=sv[(sv.cohort==coh)&(sv.measure==m)].iloc[0]; ax.hlines(y,row.ciLow,row.ciHigh,color=c,lw=2); ax.scatter(row.withinStudentDiff,y,color=c,s=50,zorder=3)
        ax.text(row.ciHigh+0.02,y,f'{row.withinStudentDiff:+.2f}',va='center',fontsize=8,color=INK); ticks.append(f'{coh} · {m}'); y+=1
    y+=0.5
ax.set_yticks([0,1,2.5,3.5]); ax.set_yticklabels(ticks,fontsize=8); ax.axvline(0,color=INK,lw=0.8); ax.invert_yaxis()
ax.set_xlabel('At IPC minus elsewhere, same student, stage-adjusted (levels)'); ax.set_title('Assessors rate students lower at IPC; students rate themselves only slightly lower'); save(fig,'f13_self_vs_assessor_ipc')

# F14 exposure
ex=X['exposure']; fig,axs=plt.subplots(1,2,figsize=(9,3.2))
for ax,coh in zip(axs,['DDS4','BOH3']):
    t=ex[(ex.cohort==coh)&(ex.forms>=20)]; ax.hist(t.exposureBias,bins=20,color=NAVY,edgecolor='white')
    ax.set_title(f'{coh}: assessors seen per student median {t.assessors.median():.0f}'); ax.set_xlabel('Average stringency of assessors a student drew (levels)'); ax.set_ylabel('Students')
fig.suptitle('Across the whole year the "luck of the draw" largely evens out',fontweight='bold',fontsize=10); fig.tight_layout(); save(fig,'f14_exposure_bias')

# F15 volume
v=S['Volume by Placement']; pc='placement (main clinic in rotation)'
fig,axs=plt.subplots(1,2,figsize=(10,4.8))
for ax,coh in zip(axs,['DDS4','BOH3']):
    t=v[v.cohort==coh].sort_values('patientsPerRotationVsCohort'); y=np.arange(len(t))
    ax.barh(y-0.2,t.formsPerRotationVsCohort,height=0.38,color=NAVY,label='Forms / rotation'); ax.barh(y+0.2,t.patientsPerRotationVsCohort,height=0.38,color=ORANGE,label='Patients / rotation')
    ax.axvline(1,color=INK,lw=0.8); ax.set_yticks(y); ax.set_yticklabels([short(p) for p in t[pc]],fontsize=7.5); ax.set_title(coh); ax.set_xlabel('× cohort average')
axs[0].legend(frameon=False,fontsize=8); fig.suptitle('Activity per student-rotation by placement',fontweight='bold',fontsize=10); fig.tight_layout(); save(fig,'f15_volume')

# F16 flag impact
fw=S['Flag Impact Windows']; fw=fw[fw.windowDefinition.str.startswith('Flagging')]
fig,axs=plt.subplots(1,2,figsize=(9,3.4),sharey=True); bands=['No IPC','1-34% IPC','>34% IPC']; meth=['Raw entrustment (as flagged now)','Placement-adjusted','Assessor-adjusted']; mc=[ORANGE,BLUE,GREY]
for ax,coh in zip(axs,['DDS4','BOH3']):
    for k,(m,c) in enumerate(zip(meth,mc)):
        t=fw[(fw.cohort==coh)&(fw.entrustmentUsed==m)].set_index('ipcBand').reindex(bands)
        b=ax.bar(np.arange(3)+(k-1)*0.27,t.lowWindowRate,width=0.25,color=c,label=m.replace(' (as flagged now)',' (current)'),edgecolor='white')
        for xx,vv,nn in zip(np.arange(3)+(k-1)*0.27,t.lowWindowRate,t.windows): ax.text(xx,vv+0.01,f'{vv:.0%}',ha='center',fontsize=7)
    ax.set_xticks(range(3)); ax.set_xticklabels([f'{b}\n(n={int(fw[(fw.cohort==coh)&(fw.ipcBand==b)].windows.iloc[0])} windows)' for b in bands],fontsize=8)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1)); ax.set_title(coh)
axs[0].set_ylabel('Windows judged LOW (z ≤ −1)'); axs[0].legend(frameon=False,fontsize=7.5)
fig.suptitle('Flagging windows (R1-3 / R4-6 / R7+) judged low, by time spent at IPC',fontweight='bold',fontsize=10); fig.tight_layout(); save(fig,'f16_flag_impact')

# F17 monthly IPC vs rest
m=X['monthly']; fig,axs=plt.subplots(1,2,figsize=(9,3.2),sharey=True)
for ax,coh in zip(axs,['DDS4','BOH3']):
    for site,c in [('All other placements',GREY),('IPC',ORANGE)]:
        t=m[(m.cohort==coh)&(m.site==site)&(m.n>=10)]; ax.plot(t.month.str[5:],t.dev,'-o',color=c,lw=2,ms=5,label=site)
    ax.axhline(0,color='#CCC',lw=0.8); ax.set_title(coh); ax.set_xlabel('Month (2026)')
axs[0].set_ylabel('Entrustment vs stage mean'); axs[0].legend(frameon=False,fontsize=8); fig.suptitle('IPC gap by month (months with ≥10 forms)',fontweight='bold',fontsize=10); fig.tight_layout(); save(fig,'f17_monthly_ipc')
print(sorted(os.listdir(OUT)))
