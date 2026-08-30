"""Step 2b — OOS with trend-capture (%) and an anti-survivorship CONTROL set."""
import engine, universe as U

CONFIGS = {"v2  as specified": dict(),
           "v3-simple": dict(gc=True,hh_tol=0.95,mom=0.10),
           "v3-full":   dict(gc=True,hh_tol=0.95,clear=2.0,m1=3.5,b3="confirm2",shock=2.0)}

# CONTROL: names that trended then died and did NOT recover, same period as E2.
CONTROL = (["PLUG","SPCE","FCEL","AI","NIO","SEDG","ENPH","ROKU","SHOP","NET","TSLA","SMCI","MSTR","IONQ","RGTI"],
           "2025-01-01","2026-08-24")
SETS = dict(U.EVAL); SETS["E7 ANTI-SURVIVORSHIP CONTROL"]=CONTROL

def bh(sym,a,b):
    x=[y for y in engine.bars(sym) if a<=y["d"]<=b]
    return (x[-1]["c"]/x[0]["c"]-1) if len(x)>1 else None

def capture(names,a,b,**kw):
    """Compound each name's trade returns; compare to that name's buy&hold."""
    sr=[]; br=[]
    for s in names:
        try: t=engine.simulate(s,a,b,**kw)
        except Exception: continue
        h=bh(s,a,b)
        if h is None: continue
        eq=1.0
        for x in t: eq*= (1+x["ret"])
        sr.append(eq-1); br.append(h)
    return (sum(sr)/len(sr) if sr else 0), (sum(br)/len(br) if br else 0), len(sr)

print(f"{'set':<34}{'config':<20}{'strat%':>9}{'B&H%':>9}{'capture':>9}{'expR':>8}{'totR':>9}{'n':>5}{'win':>6}")
print("-"*109)
pool={k:[] for k in CONFIGS}
for setname,(names,a,b) in SETS.items():
    for i,(cname,kw) in enumerate(CONFIGS.items()):
        s_,b_,n_=capture(names,a,b,**kw)
        t=[]
        for s in names:
            try: t+=engine.simulate(s,a,b,**kw)
            except Exception: pass
        pool[cname]+=t; m=engine.metrics(t) or {}
        cap = (s_/b_*100) if b_>0 else float('nan')
        print(f"{(setname if i==0 else ''):<34}{cname:<20}{s_*100:>+8.0f}%{b_*100:>+8.0f}%"
              f"{cap:>8.0f}%{m.get('exp_R',0):>8.2f}{m.get('total_R',0):>9.1f}{m.get('n',0):>5}{m.get('win',0)*100:>5.0f}%")
    print()
print("="*109); print("POOLED (incl. control)"); print(engine.HDR)
for c in CONFIGS: print(engine.fmt(engine.metrics(pool[c]),c))
print(engine.fmt(U.bench(),"BENCHMARK (accidental v1)"))
