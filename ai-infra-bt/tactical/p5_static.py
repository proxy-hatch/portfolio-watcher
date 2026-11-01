import sys; sys.path.insert(0, sys.argv[1]); from common import *
import alloc, sleeve_engine as SE
qld=load("QLD"); brk=load("BRK_B"); bil=load("BIL")
cr,_=alloc.core_ret("2007-06-01","2026-08-24")
ds=sorted(set(cr)&set(qld)&set(brk)&set(bil))
r=lambda p,a,b:p[b]/p[a]-1
for k in [0,0.02,0.03,0.05]:
    eq=[1.0]
    for t in range(1,len(ds)):
        a,b=ds[t-1],ds[t]
        eq.append(eq[-1]*(1+.45*cr[b]+.15*r(brk,a,b)+(.40-k)*r(bil,a,b)+k*r(qld,a,b)))
    c,v,s,m,mar=SE.metrics(eq); print(f"static +{k:.0%} QLD: CAGR {c:.2%} Sharpe {s:.2f} maxDD {m:.1%}")
