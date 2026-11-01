"""Portfolio-level test of a tactical QLD dip-buy overlay on top of the v3 core.
Base = 45% managed core (v3 §1.2c) + 15% BRK.B + 40% cash (sleeve treated as cash so the window
can start in 2007). Overlay: k% NAV of QLD funded from cash when QQQ is >=X below its 63d high AND the
v3 trend leg is ON; exits tested: time-only, hard stop, trailing stop, gate-off. One bet at a time."""
import sys; sys.path.insert(0, sys.argv[1]); from common import *
import alloc, sleeve_engine as SE
q=load("QQQ"); qld=load("QLD"); brk=load("BRK_B"); bil=load("BIL")
cr,_=alloc.core_ret("2007-06-01","2026-08-24")
ds=sorted(set(cr)&set(qld)&set(brk)&set(bil)&set(q))
qd=sorted(q); qi={d:i for i,d in enumerate(qd)}; qc=[q[d] for d in qd]
me={}
for d in qd: me[d[:7]]=q[d]
months=sorted(me); mi={m:i for i,m in enumerate(months)}
def gate(d):
    k=mi[d[:7]]; prev=months[k-1]; sma=sum(me[months[j]] for j in range(k-10,k))/10
    return me[prev]>=sma
def r(px,a,b): return px[b]/px[a]-1
def run(k,X,H,exit_rule,stop,lo,hi):
    D=[d for d in ds if lo<=d<=hi]
    eq=[1.0]; pos=None; trades=[]
    for t in range(1,len(D)):
        a,b=D[t-1],D[t]
        base=.45*cr[b]+.15*r(brk,a,b)+.40*r(bil,a,b)
        ov=0.0
        if pos:
            pos['v']*=1+r(qld,a,b); pos['pk']=max(pos['pk'],pos['v']); pos['age']+=1
            ov=pos['w']*(r(qld,a,b)-r(bil,a,b))   # funded from cash
            pos['w']*=(1+r(qld,a,b))/(1+base)       # drift weight
            out = pos['age']>=H
            if exit_rule=="stop" and pos['v']<=1-stop: out=True
            if exit_rule=="trail" and pos['v']<=pos['pk']*(1-stop): out=True
            if exit_rule=="gate" and not gate(b): out=True
            if out: trades.append(pos['v']-1); pos=None
        eq.append(eq[-1]*(1+base+ov))
        if pos is None:
            i=qi[b]; hi63=max(qc[i-63:i+1])
            if qc[i]/hi63-1<=-X and gate(b): pos=dict(w=k,v=1.0,pk=1.0,age=0)
    c,v,s,m,mar=SE.metrics(eq)
    avg=sum(trades)/len(trades) if trades else 0
    return c,v,s,m,len(trades),avg,(min(trades) if trades else 0)
P=[("IS ","2007-06-01","2016-12-31"),("OOS","2017-01-01","2026-08-24"),("ALL","2007-06-01","2026-08-24")]
print(f"{'config':<34}"+"".join(f"| {p}: CAGR  Shrp  maxDD  n  avgTr worstTr " for p,_,_ in P))
cfgs=[("BASE (no overlay)",0,0.1,63,"time",0)]
for k in [0.05,0.10]:
  for X in [0.075,0.10]:
    for ex,st in [("time",0),("stop",0.15),("stop",0.25),("trail",0.15),("trail",0.20),("gate",0)]:
      cfgs.append((f"k{k:.0%} X{X:.1%} H63 {ex}{'' if not st else f'{st:.0%}'}",k,X,63,ex,st))
for name,k,X,H,ex,st in cfgs:
    row=f"{name:<34}"
    for p,lo,hi in P:
        c,v,s,m,n,avg,w=run(k,X,H,ex,st,lo,hi)
        row+=f"| {c:6.2%} {s:5.2f} {m:6.1%} {n:2d} {avg:6.1%} {w:6.1%} "
    print(row)
