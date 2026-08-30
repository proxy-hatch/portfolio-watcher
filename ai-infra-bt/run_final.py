"""Step 4 — frozen v3-FINAL report. Regenerates every number quoted in the v3 spec."""
import engine, universe as U
V2 = dict()
V3 = dict(gc=True, hh_tol=0.95, clear=2.0, m1=3.5, m2=5.25, b3="buffer", b3_buf=0.5)
CTRL = (["PLUG","SPCE","FCEL","AI","NIO","SEDG","ENPH","ROKU","SHOP","NET",
         "TSLA","SMCI","MSTR","IONQ","RGTI"], "2025-01-01", "2026-08-24")
def runset(names,a,b,**kw):
    t=[]
    for s in names:
        try: t+=engine.simulate(s,a,b,**kw)
        except Exception: pass
    return t
def bh(names,a,b):
    v=[]
    for s in names:
        x=[y for y in engine.bars(s) if a<=y["d"]<=b]
        if len(x)>1: v.append(x[-1]["c"]/x[0]["c"]-1)
    return sum(v)/len(v) if v else 0
def cap(names,a,b,**kw):
    sr=[]
    for s in names:
        try: t=engine.simulate(s,a,b,**kw)
        except Exception: continue
        eq=1.0
        for x in t: eq*=(1+x["ret"])
        sr.append(eq-1)
    return sum(sr)/len(sr) if sr else 0

print("## IN-SAMPLE (selection set — 22 names, 2020-08-26 → 2023-12-31)\n")
print(engine.HDR)
print(engine.fmt(engine.metrics(runset(U.IS_NAMES,*U.IS_PERIOD,**V2)),"v2 as specified"))
print(engine.fmt(engine.metrics(runset(U.IS_NAMES,*U.IS_PERIOD,**V3)),"v3-FINAL"))

print("\n\n## OUT-OF-SAMPLE — per evaluation set\n")
print(f"{'set':<32}{'cfg':<10}{'n':>4}{'win':>6}{'payoff':>8}{'expR':>7}{'totR':>8}{'PF':>6}{'whip':>6}{'strat%':>8}{'B&H%':>8}{'cap%':>6}")
SETS=dict(U.EVAL); SETS["E7 anti-survivorship CONTROL"]=CTRL
pool={"v2":[],"v3":[]}
for name,(nm,a,b) in SETS.items():
    h=bh(nm,a,b)
    for lab,kw,key in (("v2",V2,"v2"),("v3",V3,"v3")):
        t=runset(nm,a,b,**kw); pool[key]+=t; m=engine.metrics(t) or {}
        s_=cap(nm,a,b,**kw)
        print(f"{(name if lab=='v2' else ''):<32}{lab:<10}{m.get('n',0):>4}{m.get('win',0)*100:>5.0f}%"
              f"{m.get('payoff',0):>8.2f}{m.get('exp_R',0):>7.2f}{m.get('total_R',0):>8.1f}{m.get('pf',0):>6.2f}"
              f"{m.get('whipsaw',0)*100:>5.0f}%{s_*100:>+7.0f}%{h*100:>+7.0f}%{(s_/h*100 if h>0 else 0):>5.0f}%")
print("\n\n## POOLED OUT-OF-SAMPLE (7 sets incl. control)\n")
print(engine.HDR)
print(engine.fmt(engine.metrics(pool["v2"]),"v2 as specified"))
print(engine.fmt(engine.metrics(pool["v3"]),"v3-FINAL"))
print(engine.fmt(U.bench(),"BENCHMARK — accidental v1 (n=4)"))
