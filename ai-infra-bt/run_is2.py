import engine, universe as U
def M(**kw):
    t=[]
    for s in U.IS_NAMES:
        try: t+=engine.simulate(s,*U.IS_PERIOD,**kw)
        except Exception: pass
    return engine.metrics(t)
def imp(kw, base):
    n=0
    for s in U.IS_NAMES:
        a=engine.metrics(engine.simulate(s,*U.IS_PERIOD,**kw))
        if a and base.get(s) is not None and a["exp_R"]>base[s]: n+=1
    return n
base={s:(engine.metrics(engine.simulate(s,*U.IS_PERIOD)) or {}).get("exp_R") for s in U.IS_NAMES}
print("ROUND 2 — ENTRY QUALITY (the win-rate problem)\n"); print(engine.HDR)
print(engine.fmt(M(),"A0  v2 as specified"))
for lab,kw in [
  ("B1  higher-high tol 0.95",      dict(hh_tol=0.95)),
  ("B1  higher-high tol 0.97",      dict(hh_tol=0.97)),
  ("B2  require SMA50>SMA200",      dict(gc=True)),
  ("B3  require 60d momentum +10%", dict(mom=0.10)),
  ("B3  require 60d momentum +25%", dict(mom=0.25)),
  ("B4  gc + hh0.95",               dict(gc=True,hh_tol=0.95)),
  ("B5  gc + hh0.95 + mom10",       dict(gc=True,hh_tol=0.95,mom=0.10)),
]:
    print(engine.fmt(M(**kw),lab), f"  [{imp(kw,base)}/22]")

print("\nROUND 3 — COMBINATIONS (round-1 winners + entry quality)\n"); print(engine.HDR)
CAND={
 "C1  slope-B3":                       dict(b3="slope"),
 "C2  slope-B3 + clear2.0":            dict(b3="slope",clear=2.0),
 "C3  slope-B3 + clear2.0 + m1=3.5":   dict(b3="slope",clear=2.0,m1=3.5),
 "C4  C3 + shock2.0":                  dict(b3="slope",clear=2.0,m1=3.5,shock=2.0),
 "C5  C4 + gc":                        dict(b3="slope",clear=2.0,m1=3.5,shock=2.0,gc=True),
 "C6  C5 + hh0.95":                    dict(b3="slope",clear=2.0,m1=3.5,shock=2.0,gc=True,hh_tol=0.95),
 "C7  C6 + reclaim50 n=3":             dict(b3="slope",clear=2.0,m1=3.5,shock=2.0,gc=True,hh_tol=0.95,reentry="reclaim50",n_cool=3),
 "C8  confirm2-B3 + gc + hh0.95":      dict(b3="confirm2",gc=True,hh_tol=0.95,clear=2.0,m1=3.5,shock=2.0),
}
for lab,kw in CAND.items(): print(engine.fmt(M(**kw),lab), f"  [{imp(kw,base)}/22]")
print("\n"+engine.fmt(U.bench(),"BENCHMARK (accidental v1)"))
