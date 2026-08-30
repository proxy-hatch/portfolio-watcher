"""Step 2 — OUT-OF-SAMPLE. No selection here. Three frozen configs only."""
import engine, universe as U

CONFIGS = {
 "v2  as specified":  dict(),
 "v3-simple":         dict(gc=True, hh_tol=0.95, mom=0.10),
 "v3-full":           dict(gc=True, hh_tol=0.95, clear=2.0, m1=3.5,
                           b3="confirm2", shock=2.0),
}
def bh(sym,a,b):
    x=[y for y in engine.bars(sym) if a<=y["d"]<=b]
    return (x[-1]["c"]/x[0]["c"]-1) if len(x)>1 else None

print("OUT-OF-SAMPLE EVALUATION — configs frozen from the in-sample study, no refitting\n")
agg={k:[] for k in CONFIGS}
for setname,(names,a,b) in U.EVAL.items():
    print(f"\n### {setname}   [{a} -> {b}]   {len(names)} name(s)")
    bhs=[bh(s,a,b) for s in names]; bhs=[x for x in bhs if x is not None]
    print(f"    buy&hold mean over window: {sum(bhs)/len(bhs)*100:+.1f}%" if bhs else "")
    print("   "+engine.HDR)
    for cname,kw in CONFIGS.items():
        t=[]
        for s in names:
            try: t+=engine.simulate(s,a,b,**kw)
            except Exception: pass
        agg[cname]+=t
        print("   "+engine.fmt(engine.metrics(t),cname))

print("\n\n"+"="*118); print("POOLED OUT-OF-SAMPLE (all six evaluation sets)"); print("="*118)
print(engine.HDR)
for cname in CONFIGS: print(engine.fmt(engine.metrics(agg[cname]),cname))
print(engine.fmt(U.bench(),"BENCHMARK (accidental v1, n=4)"))
