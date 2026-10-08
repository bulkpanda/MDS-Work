import pickle,os,sys;sys.path.insert(0,'.')
import pandas as pd,numpy as np
from docx import Document
from docx.shared import Pt,Cm,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
S=pickle.load(open('sheets.pkl','rb'));X=pickle.load(open('extra.pkl','rb'));a=pd.read_pickle('assessors.pkl');d=pd.read_pickle('forms.pkl')
BASE=os.path.expanduser('~/mnt/2026/Claude outputs/Placement analysis'); FIG=BASE+'/figures'
NAVY=RGBColor(0x09,0x41,0x83); MUTED=RGBColor(0x55,0x55,0x55)
doc=Document(); sec=doc.sections[0]; sec.left_margin=sec.right_margin=Cm(2); sec.top_margin=sec.bottom_margin=Cm(1.8)
st=doc.styles['Normal']; st.font.name='Arial'; st.font.size=Pt(10); st.element.rPr.rFonts.set(qn('w:eastAsia'),'Arial')
for h,sz in [('Heading 1',15),('Heading 2',12),('Heading 3',10.5)]:
    s=doc.styles[h]; s.font.name='Arial'; s.font.size=Pt(sz); s.font.color.rgb=NAVY; s.font.bold=True; s.element.rPr.rFonts.set(qn('w:eastAsia'),'Arial')
def shade(cell_or_par,hexc):
    el=cell_or_par._tc.get_or_add_tcPr() if hasattr(cell_or_par,'_tc') else cell_or_par._p.get_or_add_pPr()
    sh=OxmlElement('w:shd'); sh.set(qn('w:val'),'clear'); sh.set(qn('w:color'),'auto'); sh.set(qn('w:fill'),hexc); el.append(sh)
def P(text='',bold=False,size=None,color=None,italic=False,align=None,space=4):
    p=doc.add_paragraph(); p.paragraph_format.space_after=Pt(space)
    if text:
        for i,part in enumerate(str(text).split('**')):
            r=p.add_run(part); r.bold=bold or i%2==1; r.italic=italic
            if size: r.font.size=Pt(size)
            if color: r.font.color.rgb=color
    if align: p.alignment=align
    return p
def B(text): 
    p=doc.add_paragraph(style='List Bullet'); p.paragraph_format.space_after=Pt(2)
    for i,part in enumerate(text.split('**')): r=p.add_run(part); r.bold=i%2==1
def box(label,text,fill='EEF2FF'):
    t=doc.add_table(rows=1,cols=1); t.alignment=WD_TABLE_ALIGNMENT.CENTER; c=t.cell(0,0); shade(c,fill)
    p=c.paragraphs[0]; r=p.add_run(label+'  '); r.bold=True; r.font.color.rgb=NAVY
    for i,part in enumerate(text.split('**')): rr=p.add_run(part); rr.bold=i%2==1
    doc.add_paragraph().paragraph_format.space_after=Pt(2)
def finding(text): box('▶ Finding:',text,'FFF4E5')
def fig(name,caption,w=16.5):
    doc.add_picture(f'{FIG}/{name}.png',width=Cm(w)); doc.paragraphs[-1].alignment=WD_ALIGN_PARAGRAPH.CENTER
    P(caption,italic=True,size=8.5,color=MUTED,align=WD_ALIGN_PARAGRAPH.CENTER,space=8)
def table(df,cols,headers,fmts=None,widths=None,colorCol=None,size=8):
    t=doc.add_table(rows=1,cols=len(cols)); t.style='Table Grid'; t.alignment=WD_TABLE_ALIGNMENT.CENTER; t.autofit=False if widths else True
    for j,h in enumerate(headers):
        c=t.rows[0].cells[j]; shade(c,'094183'); c.text=''; r=c.paragraphs[0].add_run(h); r.bold=True; r.font.size=Pt(size); r.font.color.rgb=RGBColor(255,255,255)
    for _,row in df.iterrows():
        cells=t.add_row().cells
        for j,col in enumerate(cols):
            v=row[col]; f=(fmts or {}).get(col)
            s=('' if pd.isna(v) else (f(v) if callable(f) else (f.format(v) if f else str(v))))
            cells[j].text=''; rr=cells[j].paragraphs[0].add_run(s); rr.font.size=Pt(size)
        if colorCol:
            v=str(row[colorCol]); fill='FBE3D0' if v.startswith(('Harsh','Harder')) else ('DCE8F6' if v.startswith(('More lenient','Easier')) else None)
            if fill:
                for c in cells: shade(c,fill)
    if widths:
        for j,w in enumerate(widths):
            for row in t.rows: row.cells[j].width=Cm(w)
    doc.add_paragraph().paragraph_format.space_after=Pt(2)
pct=lambda v:f'{v:.0%}'; f2='{:.2f}'; sgn=lambda v:f'{v:+.2f}'
# ---------- key numbers ----------
adj=S['Placement Adjusted']; pw=S['IPC Within-Student']; vd=S['Variance Decomposition']; fw=S['Flag Impact Windows']; fs=S['Flag Impact Students']
def gp(coh,per,excl='None'): return pw[(pw.cohort==coh)&(pw.period==per)&(pw.assessorsExcluded.str.startswith(excl[:4]))].iloc[0]
def ae(coh,per,pl='IPC (Wyndham Vale)'): return adj[(adj.cohort==coh)&(adj.period==per)&(adj.placement==pl)].iloc[0]
def vr(coh,step): return vd[(vd.cohort==coh)&(vd.step==step)].addedR2.iloc[0]
def fwv(coh,meth,band): return fw[(fw.windowDefinition.str.startswith('Flagging'))&(fw.cohort==coh)&(fw.entrustmentUsed.str.startswith(meth))&(fw.ipcBand==band)].lowWindowRate.iloc[0]
D_all,D_f,D_s,D_x=gp('DDS4','All'),gp('DDS4','FHY'),gp('DDS4','SHY'),gp('DDS4','All','Asse')
B_all,B_f,B_s=gp('BOH3','All'),gp('BOH3','FHY'),gp('BOH3','SHY')
ipcD=d[(d.cohort=='DDS4')&d.isIPC&d.rated]; share2=ipcD.assessorId.isin(['710','835']).mean()
A=lambda coh,i: a[(a.cohort==coh)&(a.assessorId==i)].iloc[0]
a710,a835=A('DDS4','710'),A('DDS4','835')
w=X['weakVsEnt']; w710=w[(w.cohort=='DDS4')&(w.assessorId=='710')].iloc[0]; w835=w[(w.cohort=='DDS4')&(w.assessorId=='835')].iloc[0]
sv=X['selfVsEnt']; svD=sv[(sv.cohort=='DDS4')&sv.measure.str.startswith('Student')].iloc[0]; svB=sv[(sv.cohort=='BOH3')&sv.measure.str.startswith('Student')].iloc[0]
rD,rB=X['stabilityR']['DDS4'].statistic,X['stabilityR']['BOH3'].statistic
ipcS=fs[(fs.cohort=='DDS4')&(fs.ratedFormsAtIPC>=10)]; cleared=ipcS[(ipcS.lowWindowsRaw>0)&(ipcS.lowWindowsPlacementAdj==0)]
nForms=len(d); nRated=int(d.rated.sum()); nStud=d.studentNumber.nunique(); nAss=d.assessorId.nunique(); nPl=d[~d.clinic.isin(['Unknown/Other'])].clinic.nunique()
# ---------- title ----------
P('DDS4 & BOH3 2026',bold=True,size=24,color=NAVY,space=2)
P('Assessor & Clinic Placement Differences',bold=True,size=18,color=NAVY,space=2)
P('Clinical Assessment Forms (CAF) · 15 Jan – 5 Oct 2026 · FHY and SHY',size=11,color=MUTED,space=2)
P('DASH Analytics · Melbourne Dental School · University of Melbourne · Report date 6 Oct 2026',size=9,color=MUTED,space=10)
t=doc.add_table(rows=2,cols=4); t.alignment=WD_TABLE_ALIGNMENT.CENTER
stats_=[('CAF forms',f'{nForms:,}'),('Assessor-rated forms',f'{nRated:,}'),('Students',f'{nStud}  (DDS4 108 · BOH3 45)'),('Assessors / placements',f'{nAss} / {nPl}')]
for j,(k,v) in enumerate(stats_):
    c1,c2=t.cell(0,j),t.cell(1,j); shade(c1,'F5F6FA'); shade(c2,'F5F6FA')
    r=c1.paragraphs[0].add_run(k); r.font.size=Pt(8); r.font.color.rgb=MUTED
    r=c2.paragraphs[0].add_run(v); r.bold=True; r.font.size=Pt(12); r.font.color.rgb=NAVY
doc.add_paragraph()
box('CONFIDENTIAL — For Faculty Use Only.','This report is a reflective tool for coordinators. It identifies **differences** in rating standards between placements and assessors; it cannot say which standard is "correct". All adjusted figures compare each student with **themselves** at the same stage of the year, so differences in student ability are removed as far as the data allows.','FDE8E8')
doc.add_heading('Summary',1)
for s in [
 f"**IPC is the hardest DDS4 placement.** The same DDS4 student receives entrustment **{abs(D_all.meanEntDiff):.2f} levels lower** at IPC than at their other placements at the same rotation stage ({int(D_all.studentsLowerAtIPC)} of {int(D_all.students)} students lower). The gap is present in **FHY ({D_f.meanEntDiff:+.2f}, {int(D_f.studentsLowerAtIPC)}/{int(D_f.students)} students)** and SHY ({D_s.meanEntDiff:+.2f}, {int(D_s.studentsLowerAtIPC)}/{int(D_s.students)}).",
 f"**Two IPC assessors account for most of it.** Assessors {a710.assessorName} [710] and {a835.assessorName} [835] completed {share2:.0%} of DDS4 IPC forms and are among the most stringent raters in the cohort. Without them the IPC gap falls to {D_x.meanEntDiff:+.2f}: smaller but still present.",
 f"**This directly drives the flags.** Under the flagging tool's windows (R1-3 / R4-6 / R7+), DDS4 windows with more than a third of forms at IPC are judged LOW **{fwv('DDS4','Raw','>34% IPC'):.0%}** of the time, vs **{fwv('DDS4','Raw','No IPC'):.0%}** with no IPC time. Adjusting for placement brings this to {fwv('DDS4','Placement','>34% IPC'):.0%} vs {fwv('DDS4','Placement','No IPC'):.0%}. {len(cleared)} DDS4 students with an IPC rotation have every low window disappear once placement is adjusted for.",
 f"**BOH3:** small IPC effect in FHY ({B_f.meanEntDiff:+.2f}) and none in SHY ({B_s.meanEntDiff:+.2f}).",
 f"**Who assesses matters more than where or who is assessed.** After rotation stage, the assessor explains **{vr('DDS4','+ Assessor'):.0%}** of DDS4 entrustment variation (BOH3 {vr('BOH3','+ Assessor'):.0%}), against {vr('DDS4','+ Student'):.0%} for the student (BOH3 {vr('BOH3','+ Student'):.0%}). Assessors are mostly tied to one site, so a placement's difficulty is largely the stringency of its assessors.",
 f"**Assessor stringency is a stable personal standard:** FHY vs SHY correlation r = {rD:.2f} (DDS4), {rB:.2f} (BOH3). Harsh raters exist at most sites (DTC, MDC, RDHM PC, Link Health); IPC stands out because its two harsh raters carry most of its volume.",
 "**Data issue:** BOH3 and DDS4 forms use different clinic code lists; the current DB pipeline decodes BOH3 codes with the DDS4 list, so some BOH3 clinic-level reports show the wrong clinic (Section 10)."]: B(s)
# ---------- 1 background ----------
doc.add_heading('1.  Background & Purpose',1)
P('Coordinators reviewing DASH noticed that students who had a placement at IPC (Wyndham Vale) were being flagged as lagging, in SHY and also in FHY. They asked for a placement difficulty analysis and for any available evidence on how different placements and assessors influence results.')
P('Each CAF records the placement (rotation number and clinic), the assessor, the assessor\'s **entrustment** rating (L1 "cannot be trusted" to L4 "independent"), any weakness categories tagged, concerns/incidents, and the student\'s self-rated practice readiness. The flagging tool judges each student\'s entrustment against the cohort in each window, so anything that systematically lowers ratings in a window, such as a stricter placement or assessor, can produce a flag that reflects the placement rather than the student.')
doc.add_heading('2.  Data & Methods',1)
P(f'Source: DASH CAF export for DDS4 (DENT90124) and BOH3 (ORAL30001/30002), {nForms:,} forms, of which {nRated:,} were submitted by the assessor with an entrustment rating. FHY = forms dated before 1 July 2026; SHY = from 1 July. Clinic codes (EC01…) were decoded **per form from that form\'s own template** (Section 10), and free-text clinic names normalised.')
meth=pd.DataFrame([
 ('Rotation-stage adjustment','Entrustment rises through the year; each form is compared with the cohort mean for its rotation','Placements visited early would otherwise look harder'),
 ('Same-student placement effects (fixed effects)','Placement effect after removing each student\'s own level and the rotation stage; 95% CI clustered by assessor','Removes "weaker students were sent there" explanation'),
 ('IPC within-student comparison','Each student\'s stage-adjusted entrustment at IPC minus elsewhere; paired tests','Most direct test of the IPC question'),
 ('Assessor effects (empirical Bayes)','Assessor mean after removing student and stage, shrunk toward 0 for low-volume assessors','Student mix; small-n noise'),
 ('Variance decomposition','How much rating variation is due to stage, student, placement and assessor','Places site and assessor effects in proportion'),
 ('Flag impact re-run','Re-runs the entrustment trajectory flag on raw, placement-adjusted and assessor-adjusted ratings','Shows how much of the flagging is placement-driven'),
],columns=['m','w','l'])
table(meth,['m','w','l'],['Method','What it shows','Limitation addressed'],widths=[4.5,7,5.5])
# ---------- 3 stage ----------
doc.add_heading('3.  Rotation Stage: Why Every Comparison Is Adjusted',1)
rt=X['rotTrend']
fig('f01_rotation_trend','Figure 1. Mean assessor entrustment by rotation, all placements.',14)
finding(f"Entrustment climbs from {rt[(rt.cohort=='DDS4')&(rt.rotNum==1)].ent.iloc[0]:.2f} (R1) to {rt[(rt.cohort=='DDS4')&(rt.rotNum==8)].ent.iloc[0]:.2f} (R8) in DDS4 and from {rt[(rt.cohort=='BOH3')&(rt.rotNum==1)].ent.iloc[0]:.2f} to {rt[(rt.cohort=='BOH3')&(rt.rotNum==8)].ent.iloc[0]:.2f} in BOH3, as expected under the stage benchmarks. A placement visited mostly in early rotations would look harder unless stage is controlled; all results below control for it.")
# ---------- 4 placements ----------
doc.add_heading('4.  Placement Differences',1)
P('Each line shows a placement\'s effect on entrustment relative to the average placement. The hollow circle is the raw (stage-adjusted only) difference; the filled point with its 95% interval removes student ability too. Orange = significantly harder, blue = significantly easier, grey = not distinguishable from average.')
fig('f02_placement_forest_DDS4','Figure 2. DDS4 placement effects on entrustment (all of 2026).',15)
L=ae('DDS4','All','Link Health (Clayton)')
finding(f"IPC ({ae('DDS4','All').entEffect:+.2f}) and Link Health (Clayton) ({L.entEffect:+.2f}) are the only DDS4 placements significantly harder than average. Congress (Alice Springs), Health Ability (Box Hill), VAHS (Fitzroy) and Northwest Health are more lenient. Raw and student-adjusted values are almost identical, so the IPC gap is **not** explained by which students were placed there. At IPC, the share of L1–2 ratings is {ae('DDS4','All').lowShareEffect*100:+.0f} percentage points above the average placement.")
fig('f03_placement_forest_BOH3','Figure 3. BOH3 placement effects on entrustment (all of 2026).',15)
finding(f"For BOH3 no placement is significantly harder over the whole year; IPC is {ae('BOH3','All').entEffect:+.2f} (n.s.). North Richmond, Your Community (Preston) and GV Health are more lenient.")
fig('f04_placement_fhy_shy','Figure 4. Placement effects estimated separately for FHY (circle) and SHY (diamond).')
finding(f"The DDS4 IPC effect is present in both halves ({ae('DDS4','FHY').entEffect:+.2f} FHY, {ae('DDS4','SHY').entEffect:+.2f} SHY), confirming the coordinators' observation that FHY was affected too. BOH3 IPC was harder in FHY ({ae('BOH3','FHY').entEffect:+.2f}) but not in SHY ({ae('BOH3','SHY').entEffect:+.2f}).")
# ---------- 5 IPC ----------
doc.add_heading('5.  IPC (Wyndham Vale) Deep-Dive',1)
doc.add_heading('5.1  Same students, at IPC vs elsewhere',2)
fig('f05_ipc_within_student','Figure 5. Each line is one student (≥3 rated forms at IPC and ≥3 elsewhere): stage-adjusted entrustment elsewhere (left) vs at IPC (right). Orange = lower at IPC.',15)
pt=pw.copy(); pt['label']=pt.period+' · '+pt.assessorsExcluded.str.replace('Assessors 710 & 835','excl. 710 & 835').str.replace('None','all assessors')
table(pt.sort_values(['cohort','assessorsExcluded','period']),['cohort','label','students','meanEntDiff','ciLow','ciHigh','studentsLowerAtIPC','pWilcoxon','meanLowShareDiff'],
  ['Cohort','Period / assessors','Students','IPC − elsewhere','CI low','CI high','Students lower at IPC','p (Wilcoxon)','Δ L1–2 share'],
  fmts={'meanEntDiff':sgn,'ciLow':sgn,'ciHigh':sgn,'pWilcoxon':lambda v:'<0.001' if v<0.001 else f'{v:.3f}','meanLowShareDiff':lambda v:f'{v*100:+.0f} pts'})
finding(f"In DDS4, **{int(D_all.studentsLowerAtIPC)} of {int(D_all.students)} students** were rated lower at IPC, by {abs(D_all.meanEntDiff):.2f} levels on average, with {D_all.meanLowShareDiff*100:.0f} percentage points more L1–2 ratings. In FHY every DDS4 student with enough IPC forms was rated lower there.")
doc.add_heading('5.2  Over the year',2)
fig('f17_monthly_ipc','Figure 6. Monthly stage-adjusted entrustment at IPC vs all other placements (months with ≥10 forms).',15)
finding('The DDS4 IPC gap appears in every month: about −0.5 to −0.7 levels from January to June, narrowing to about −0.15 in August–September. It is not a single bad period. BOH3 IPC sits 0.1–0.4 below other placements through FHY and is level with them from July.')
doc.add_heading('5.3  Who assesses at IPC',2)
fig('f06_ipc_assessor_distribution','Figure 7. Entrustment levels given at IPC by each IPC assessor (≥10 IPC forms), ordered by overall stringency.',16.5)
ia=S['IPC by Assessor']; ia=ia[ia.period.isin(['FHY','SHY'])]
ia2=ia.groupby(['cohort','assessorId']).agg(assessorName=('assessorName','first'),forms=('forms','sum'),entMean=('entMean',lambda s: np.average(s,weights=ia.loc[s.index,'forms'])),
   lowShare=('lowShare',lambda s: np.average(s,weights=ia.loc[s.index,'forms'])),effect=('assessorEffectAllSites','first'),status=('status','first')).reset_index()
ia2['share']=ia2.forms/ia2.groupby('cohort').forms.transform('sum'); ia2=ia2[ia2.forms>=10].sort_values(['cohort','forms'],ascending=[False,False])
table(ia2,['cohort','assessorName','assessorId','forms','share','entMean','lowShare','effect','status'],['Cohort','Assessor','ID','IPC forms','Share of IPC','Mean entrust.','L1–2 share','Adjusted effect','Status'],
   fmts={'share':pct,'entMean':f2,'lowShare':pct,'effect':sgn},colorCol='status')
finding(f"For DDS4, **{a710.assessorName} [710]** (raw mean {a710.rawEnt:.2f}, {a710.lowShare:.0%} L1–2, adjusted {a710.adjEffect:+.2f}) and **{a835.assessorName} [835]** ({a835.rawEnt:.2f}, {a835.lowShare:.0%} L1–2, {a835.adjEffect:+.2f}) completed {share2:.0%} of IPC forms. The other DDS4 IPC assessors are close to typical. With 710 and 835 removed the DDS4 IPC gap shrinks from {D_all.meanEntDiff:+.2f} to {D_x.meanEntDiff:+.2f}, so most of the IPC effect is these two raters and a smaller part is site-wide. For BOH3, IPC volume is spread over several assessors (699 typical; 700, 1031, 1033 mildly harsher), which is why the BOH3 effect is small.")
doc.add_heading('5.4  Do students feel weaker at IPC?',2)
fig('f13_self_vs_assessor_ipc','Figure 8. Within-student difference at IPC vs elsewhere: assessor entrustment (orange) vs the student\'s own self-rated practice readiness (blue), with 95% CI.',15)
finding(f"DDS4 students rate their own readiness slightly lower at IPC ({svD.withinStudentDiff:+.2f}), about a quarter of the assessor gap ({D_all.meanEntDiff:+.2f}). BOH3 students rate themselves no differently ({svB.withinStudentDiff:+.2f}). The case mix or setting at IPC may be somewhat more demanding, but most of the gap sits in the assessors' ratings.")
doc.add_heading('5.5  Weaknesses and workload at IPC',2)
P(f"At site level, IPC forms do not carry significantly more weakness tags than the same students receive elsewhere (DDS4 {ae('DDS4','All').anyWeakEffect*100:+.0f} pts, n.s.; BOH3 {ae('BOH3','All').anyWeakEffect*100:+.0f} pts). This average hides a split. Assessors 710 and 835 tag a weakness on {a710.anyWeak:.0%} and {a835.anyWeak:.0%} of their forms ({w710.weakAdj*100:+.0f} and {w835.weakAdj*100:+.0f} pts vs the same students elsewhere), while the other IPC assessors tag fewer than average. So the two stringent raters are consistent: they rate lower **and** document more weaknesses. Whether this reflects higher expectations or closer scrutiny cannot be told from DASH data alone.")
P("IPC is not a low-activity placement: DDS4 students log more forms and patients per rotation at IPC than the cohort average (Section 9), so IPC students are not being flagged for volume.")
# ---------- 6 assessors ----------
doc.add_heading('6.  Assessor Differences',1)
P('An assessor\'s effect is the average difference between the entrustment they give and what the same students receive from other assessors at the same rotation stage. Estimates are shrunk toward zero according to how many forms the assessor completed, so a few unusual forms cannot make an assessor look extreme. "Harsher" / "More lenient" = at least 15 forms and a 95% interval that excludes zero. Circled points are assessors whose main site is IPC.')
fig('f07_assessor_caterpillar_DDS4','Figure 9. DDS4 assessor effects (assessors with ≥15 rated forms), continuing from left column to right.',17)
nb=a[(a.cohort=='DDS4')&(a.n>=15)].status.value_counts()
finding(f"Of {int(nb.sum())} DDS4 assessors with ≥15 forms, {nb.get('Harsher',0)} are significantly harsher and {nb.get('More lenient',0)} more lenient than average. The spread is large: the harshest and most lenient assessors differ by about 1.6 entrustment levels for the same students. Harsh raters are found at most sites; 710 is the 5th harshest DDS4 assessor and the highest-volume one among the harshest ten.")
fig('f08_assessor_caterpillar_BOH3','Figure 10. BOH3 assessor effects (assessors with ≥15 rated forms), continuing from left column to right.',17)
nb=a[(a.cohort=='BOH3')&(a.n>=15)].status.value_counts()
finding(f"Of {int(nb.sum())} BOH3 assessors with ≥15 forms, {nb.get('Harsher',0)} are harsher and {nb.get('More lenient',0)} more lenient. The highest-volume IPC assessor ({A('BOH3','699').assessorName} [699], {int(A('BOH3','699').n)} forms) is typical.")
doc.add_heading('6.1  Stability across the year',2)
fig('f11_assessor_stability','Figure 11. Each assessor\'s effect in FHY vs SHY (assessors with ≥15 forms in both halves). Dashed line = identical.',15)
finding(f"Assessor effects are highly consistent between halves (DDS4 r = {rD:.2f}, BOH3 r = {rB:.2f}). Stringency is a stable personal standard rather than random variation, which is why calibration is likely to help more than waiting for it to average out.")
doc.add_heading('6.2  Ratings vs documented weaknesses',2)
fig('f12_weakness_vs_entrustment','Figure 12. Assessor entrustment effect vs their weakness-tag rate relative to the same students elsewhere. Circled = IPC assessors.',15)
finding(f"Stricter raters tend to tag more weaknesses (DDS4 r = {X['weakVsEntR']['DDS4'].statistic:.2f}, BOH3 r = {X['weakVsEntR']['BOH3'].statistic:.2f}), but the link is moderate. Some assessors rate low without documenting why, which is the pattern most worth a calibration conversation because the student gets little actionable feedback.")
doc.add_heading('6.3  Assessors at the same site differ',2)
fig('f09_within_site_spread','Figure 13. Assessor effects grouped by main site (sites with ≥3 assessors with ≥15 forms). Dot size = forms.',16.5)
finding("Within almost every site there are both stringent and lenient assessors, e.g. assessors at DTC and RDHM PC span about 1.4–1.7 levels. 'Placement difficulty' is therefore mostly 'which assessors carry that placement's volume'. Where a site's volume is concentrated in one or two stringent raters, as at DDS4 IPC, the whole placement looks hard.")
doc.add_heading('6.4  How much do student, placement and assessor matter?',2)
fig('f10_variance_decomposition','Figure 14. Incremental share of entrustment variation explained, adding rotation stage, student, placement and assessor in turn.',15)
mob=X['mobility'].set_index('cohort')
finding(f"In DDS4, student identity explains {vr('DDS4','+ Student'):.0%} of variation beyond stage, placement a further {vr('DDS4','+ Placement'):.0%}, and assessor a further **{vr('DDS4','+ Assessor'):.0%}**. BOH3: {vr('BOH3','+ Student'):.0%}, {vr('BOH3','+ Placement'):.0%} and **{vr('BOH3','+ Assessor'):.0%}**. Once the assessor is known, placement adds ~0%. Because {mob.loc['DDS4','oneSiteShare']:.0%} of DDS4 and {mob.loc['BOH3','oneSiteShare']:.0%} of BOH3 assessors work at a single site, site and assessor cannot be fully separated, but the within-site spread (Fig. 13) shows assessors vary far more than sites. As in the DDS2 and BOH1 assessor reports, **who assesses explains more than how well the student performed**.")
# ---------- 7 fairness ----------
doc.add_heading('7.  Fairness to Students: Assessor Exposure',1)
ex=X['exposure']; exD=ex[(ex.cohort=='DDS4')&(ex.forms>=20)]
fig('f14_exposure_bias','Figure 15. For each student, the average stringency of the assessors they happened to draw across the year.',15)
finding(f"Over a full year students see many assessors (DDS4 median {exD.assessors.median():.0f}), so the 'luck of the draw' largely evens out: the spread of exposure is small (SD {exD.exposureBias.std():.2f} levels). Within a single rotation window, however, a student may see only one or two assessors, which is where placement and assessor effects reach the flags (Section 8). Exposure to stringent assessors is correlated with IPC time in DDS4.")
# ---------- 8 flags ----------
doc.add_heading('8.  Impact on Lagging-Student Flags',1)
P('The entrustment trajectory flag (boh3_dds4_flagging.py) splits the year into windows (R1-3, R4-6, R7+), computes each student\'s mean entrustment per window, and marks a window LOW when it is ≥1 SD below the cohort. This logic was re-run on (a) raw ratings as used now, (b) placement-adjusted ratings and (c) assessor-adjusted ratings. This is an offline mirror of the tool, so counts may differ slightly from the live workbook.')
fig('f16_flag_impact','Figure 16. Share of student windows judged LOW, by how much of the window was spent at IPC.',16)
finding(f"For DDS4, windows with >34% of forms at IPC are judged LOW **{fwv('DDS4','Raw','>34% IPC'):.0%}** of the time, against {fwv('DDS4','Raw','No IPC'):.0%} with no IPC time. Placement adjustment brings this to {fwv('DDS4','Placement','>34% IPC'):.0%} vs {fwv('DDS4','Placement','No IPC'):.0%}, close to parity. Assessor adjustment alone leaves {fwv('DDS4','Assessor','>34% IPC'):.0%}, consistent with a residual site-wide effect beyond 710 and 835. BOH3 shows only a small difference.")
P(f'DDS4 students with ≥10 rated IPC forms whose LOW windows change under placement adjustment. "Catching up" and "Low recently" states created by an IPC rotation largely disappear:',space=4)
ch=ipcS[(ipcS.lowWindowsRaw!=ipcS.lowWindowsPlacementAdj)|(ipcS.stateRaw!=ipcS.statePlacementAdj)].sort_values('ratedFormsAtIPC',ascending=False)
table(ch,['studentNumber','studentName','ratedFormsAtIPC','stateRaw','lowWindowsRaw','statePlacementAdj','lowWindowsPlacementAdj'],
  ['Student no.','Student','IPC forms','State (current)','Low windows','State (placement-adj.)','Low windows (adj.)'],fmts={'ratedFormsAtIPC':'{:.0f}'})
finding(f"**{len(cleared)} DDS4 students** with an IPC rotation have **all** their low windows disappear once placement is accounted for. Coordinators should read IPC-period low windows with this in mind before acting on them.")
# ---------- 9 volume ----------
doc.add_heading('9.  Activity and Case Mix by Placement',1)
fig('f15_volume','Figure 17. Forms and patients per student-rotation at each placement, relative to the cohort average (placements with ≥5 student-rotations).',16.5)
v=S['Volume by Placement']; vi=v[(v.cohort=='DDS4')&v.iloc[:,1].str.startswith('IPC')].iloc[0]
finding(f"DDS4 IPC rotations log {vi.formsPerRotationVsCohort:.2f}× the cohort average forms and {vi.patientsPerRotationVsCohort:.2f}× the patients, so IPC students are not disadvantaged on count-based flags. MDC and DTC rotations carry fewer patients and items per rotation for both cohorts, and Link Health (Clayton) has the fewest DDS4 forms per rotation. These are worth knowing when reading low-volume flags.")
# ---------- 10 data ----------
doc.add_heading('10.  Data Quality Notes',1)
B('**Clinic code lists differ by cohort.** BOH3 forms use one EC-code list (EC05 = IPC, EC08 = MDC, EC11 = North Richmond…) and DDS4 forms another (EC08 = IPC, EC11 = MDC…). `processDds4BohForms` (main.ipynb) applies the DDS4 `CLINIC_DICT` to every row, so the 1,998 BOH3 forms stored as codes are given the wrong clinic name in database-driven clinic reports (e.g. BOH3 MDC forms appear as IPC, BOH3 IPC forms as EACH). This analysis decodes each form from its own `context_schema_snapshot`. Entrustment flags do not use clinic and are unaffected; clinic-level summaries for BOH3 should be regenerated after a fix.')
B('Free-text clinic entries were normalised (e.g. "pc", "Primary Care", "RDHM PC Emergency" → RDHM PC; "moe" → La Trobe (Moe); Gove spelling variants → Gove / NT). 38 entries that were numbers or a subject code were excluded.')
B('FHY forms label rotations "Rotation 1–5" and SHY forms "R4–R8"; both were merged by rotation number.')
B(f'{nForms-nRated} forms had no assessor entrustment (unsubmitted or blank) and are excluded from rating analyses but kept for activity counts.')
# ---------- 11 recs ----------
doc.add_heading('11.  Key Findings & Recommendations',1)
for s in [f"**Review IPC-period flags before acting.** For DDS4, low entrustment windows spent at IPC are mostly placement-driven (Section 8). The students listed in Section 8 should be judged on their non-IPC windows and qualitative evidence.",
 "**Calibration with assessors 710 and 835**, and benchmarking of IPC rating against other sites using shared cases or co-assessment. Their stringency is consistent over the year and accompanied by many weakness tags, so the conversation is about shared anchors for each entrustment level rather than about errors.",
 "**Wider calibration is warranted.** Assessor effects of 0.5–0.9 levels in either direction exist at DTC, MDC, RDHM PC, Link Health and Peninsula Health as well (Figs. 9–10, 13). They are diluted where many assessors share a site, but they shape individual students' rotation windows.",
 "**Optional tool change:** add a placement- or assessor-adjusted entrustment option to the flagging tool (method in this report), or show alongside each LOW window the share of forms from stringent assessors.",
 "**Fix BOH3 clinic decoding** (per-form snapshot decoding) and regenerate BOH3 clinic summaries.",
 "**Allocation:** where possible, avoid a student's whole rotation window being assessed by a single stringent assessor; more assessors per window reduces the luck-of-the-draw effect."]: B(s)
doc.add_heading('12.  Limitations',1)
for s in ["Observational data: students are not randomly allocated, but student fixed effects and within-student comparisons remove stable differences in ability. Students who improve or decline in step with a placement change cannot be fully separated.",
 "Most assessors work at one site, so site and assessor effects are partly confounded; within-site spread and the analysis excluding 710/835 are used to separate them as far as possible.",
 "Entrustment (L1–L4) is treated as a numeric scale; low-share (L1–2) results give the same picture.",
 "Assessor 'harshness' means difference from colleagues, not error. A stringent assessor may be applying the intended benchmark more faithfully.",
 "Flag re-run is an offline mirror of the live tool (rotation windows, z ≤ −1, ≥5 rated forms per window); small differences from the live workbook are expected."]: B(s)
# ---------- appendices ----------
ns=doc.add_section(WD_SECTION.NEW_PAGE); ns.orientation=WD_ORIENT.LANDSCAPE; ns.page_width,ns.page_height=sec.page_height,sec.page_width
ns.left_margin=ns.right_margin=Cm(1.5)
doc.add_heading('Appendix A.  Placement Effects (whole year)',1)
for coh in ['DDS4','BOH3']:
    doc.add_heading(coh,2); t=adj[(adj.cohort==coh)&(adj.period=='All')].sort_values('entEffect')
    rw=S['Placement Raw']; rw=rw[(rw.cohort==coh)&(rw.period=='All')][['placement','students','assessors','entMean','lowShare','anyWeak']]
    t=t.merge(rw,on='placement',how='left')
    table(t,['placement','nForms','students','assessors','entMean','lowShare','anyWeak','entEffect','entCiLow','entCiHigh','verdict'],
      ['Placement','Rated forms','Students','Assessors','Raw mean','L1–2','Any weakness','Adj. effect','CI low','CI high','Verdict'],
      fmts={'entMean':f2,'lowShare':pct,'anyWeak':pct,'entEffect':sgn,'entCiLow':sgn,'entCiHigh':sgn,'students':'{:.0f}','assessors':'{:.0f}'},colorCol='verdict',size=7.5,widths=[5.2,1.8,1.7,1.8,1.8,1.6,2,1.8,1.6,1.6,4.2])
doc.add_page_break(); doc.add_heading('Appendix B.  Assessor Rankings (≥15 rated forms, harshest first)',1)
for coh in ['DDS4','BOH3']:
    doc.add_heading(coh,2); t=a[(a.cohort==coh)&(a.n>=15)].sort_values('adjEffect')
    table(t,['assessorName','assessorId','mainClinic','n','students','rawEnt','lowShare','anyWeak','adjEffect','ciLow','ciHigh','status'],
      ['Assessor','ID','Main site','Forms','Students','Raw mean','L1–2','Any weakness','Adj. effect','CI low','CI high','Status'],
      fmts={'rawEnt':f2,'lowShare':pct,'anyWeak':pct,'adjEffect':sgn,'ciLow':sgn,'ciHigh':sgn},colorCol='status',size=7,widths=[4.2,1.3,4.6,1.4,1.7,1.6,1.4,1.8,1.7,1.5,1.5,2.4])
P('Full tables (all assessors, by period, flag-impact detail) are in DDS4_BOH3_Placement_Assessor_Analysis 06-10-2026.xlsx in the same folder.',italic=True,size=8.5,color=MUTED)
# footer page numbers
fp=sec.footer.paragraphs[0]; fp.alignment=WD_ALIGN_PARAGRAPH.CENTER
r=fp.add_run('DDS4 & BOH3 Assessor & Placement Differences · Confidential · page '); r.font.size=Pt(8); r.font.color.rgb=MUTED
for t_ in ['begin',None,'end']:
    if t_ is None:
        it=OxmlElement('w:instrText'); it.text='PAGE'; rr=fp.add_run(); rr._r.append(it)
    else:
        fc=OxmlElement('w:fldChar'); fc.set(qn('w:fldCharType'),t_); rr=fp.add_run(); rr._r.append(fc)
out=BASE+'/DDS4_BOH3_Assessor_Placement_Report 06-10-2026.docx'; doc.save(out); print(out, len(cleared), list(cleared.studentNumber))
