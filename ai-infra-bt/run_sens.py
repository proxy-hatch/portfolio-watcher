"""Step 3 — parameter sensitivity. An overfit config sits on a knife-edge."""
import engine, universe as U
CONTROL=(["PLUG","SPCE","FCEL","AI","NIO","SEDG","ENPH","ROKU","SHOP","NET","TSLA","SMCI","MSTR","IONQ","RGTI"],"2025-01-01","2026-08-24")
SETS=dict(U.EVAL); SETS["E7 control"]=CONTROL
BASE=dict(gc=True,hh_tol=0.95,clear=2.0,m1=3.5,b3="confirm2",shock=2.0)
def pooled(**kw):
    t=[]
    for names,a,b in SETS.values():
        for s in names:
            try: t+=engine.simulate(s,a,b,**kw)
            except Exception: pass
    return engine.metrics(t)
print("SENSITIVITY AROUND v3-full (pooled OOS incl. control)\n"); print(engine.HDR)
print(engine.fmt(pooled(**BASE),"v3-full (chosen)"))
for lab,d in [("m1 3.0 (was 3.5)",dict(m1=3.0)),("m1 4.0",dict(m1=4.0)),
              ("clear 1.5 (was 2.0)",dict(clear=1.5)),("clear 2.5",dict(clear=2.5)),
              ("hh_tol 0.93",dict(hh_tol=0.93)),("hh_tol 0.97",dict(hh_tol=0.97)),
              ("shock 1.75",dict(shock=1.75)),("shock 2.5",dict(shock=2.5)),("shock off",dict(shock=0.0)),
              ("b3 strict",dict(b3="strict")),("b3 buffer",dict(b3="buffer")),("b3 slope",dict(b3="slope")),
              ("gc off",dict(gc=False)),("cost 50bps",dict(cost=0.005))]:
    kw=dict(BASE); kw.update(d)
    print(engine.fmt(pooled(**kw),"  "+lab))
