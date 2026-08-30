import alloc, math
ds,S=alloc.build('2018-01-01','2026-08-24',use_proxy=True)
R={k:[S[k][d] for d in ds] for k in ['CORE','BRK','SLEEVE','CASH']}
def port(w, sub=None):
    idx=range(len(ds)) if sub is None else [i for i,d in enumerate(ds) if sub[0]<=d<=sub[1]]
    return [sum(w[k]*R[k][i] for k in R) for i in idx]
def M(w,sub=None): return alloc.metrics(port(w,sub))

CAND={
 "A  today-ish (no sleeve)":      dict(CORE=.40,BRK=.10,SLEEVE=.00,CASH=.50),
 "B  balanced":                   dict(CORE=.45,BRK=.15,SLEEVE=.15,CASH=.25),
 "C  growth-tilted":              dict(CORE=.55,BRK=.10,SLEEVE=.20,CASH=.15),
 "D  equal-risk-ish":             dict(CORE=.25,BRK=.30,SLEEVE=.20,CASH=.25),
 "E  conservative":               dict(CORE=.35,BRK=.15,SLEEVE=.10,CASH=.40),
 "F  core-heavy, small sleeve":   dict(CORE=.55,BRK=.15,SLEEVE=.10,CASH=.20),
}
print("FULL WINDOW 2018-2026 (8.0 yrs)")
print(f"  {'allocation':<30}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>9}{'MAR':>7}{'QLD%NAV':>9}")
for k,w in CAND.items():
    c,v,s,m,mar=M(w)
    print(f"  {k:<30}{c*100:>7.1f}%{v*100:>6.1f}%{s:>8.2f}{m*100:>8.1f}%{mar:>7.2f}{w['CORE']*0.71*100:>8.0f}%")

print("\nSTRESS WINDOWS (CAGR / maxDD)")
SUB=[("2020-02-01","2020-04-30","covid crash"),
     ("2022-01-01","2022-12-31","2022 bear"),
     ("2018-10-01","2018-12-31","Q4-18 selloff"),
     ("2026-06-01","2026-08-24","this summer")]
print(f"  {'allocation':<30}"+"".join(f"{l:>22}" for _,_,l in SUB))
for k,w in CAND.items():
    row=f"  {k:<30}"
    for a,b,_ in SUB:
        c,v,s,m,mar=M(w,(a,b))
        row+=f"{c*100:>11.1f}%{m*100:>10.1f}%"
    print(row)

print("\nROBUSTNESS — what if the sleeve does NOT repeat its 30.4% CAGR?")
print("  (haircut the sleeve's daily return; everything else unchanged)")
print(f"  {'allocation':<30}{'as-is':>10}{'-1/3':>10}{'-1/2':>10}{'sleeve=core':>13}")
core_mu=sum(R['CORE'])/len(ds)
for k,w in CAND.items():
    row=f"  {k:<30}"
    for lab,adj in [("as-is",1.0),("-1/3",2/3),("-1/2",0.5),("=core",None)]:
        sl=R['SLEEVE']
        if adj is None:
            mu=sum(sl)/len(sl); sl=[x-mu+core_mu for x in sl]
        else:
            mu=sum(sl)/len(sl); sl=[(x-mu)+mu*adj for x in sl]
        p=[w['CORE']*R['CORE'][i]+w['BRK']*R['BRK'][i]+w['SLEEVE']*sl[i]+w['CASH']*R['CASH'][i] for i in range(len(ds))]
        row+=f"{alloc.metrics(p)[0]*100:>9.1f}%"
    print(row)
