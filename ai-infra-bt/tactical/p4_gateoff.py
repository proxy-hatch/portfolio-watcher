"""Buying a theme the month its v3 gate turns DEFENSIVE (month close < 10-mo SMA AND vol32 > 20%).
Control set = themes/sectors people 'believed in long term', incl. ones that broke (QQQ 2000, XLE 2014,
EEM/EWZ 2011+, XBI 2015, KRE 2007/2023, ITB 2006). Compares forward returns from the gate-off close
vs. the asset's unconditional forward return, and vs. waiting for the gate to turn back ON."""
import sys; sys.path.insert(0, sys.argv[1]); from common import *
import alloc
U=["QQQ","SPY","IWM","EEM","EWZ","XBI","IBB","SMH","SOXX","XLE","OIH","XME","KRE","ITB","IYR","XLK","XLF","XRT","XLB","XLI","SLV","USO"]
def series(sym):
    if sym=="AI_BLEND":
        a=alloc.basket_series("AIS"); b=alloc.basket_series("AIPO"); ds=sorted(set(a)&set(b))
        px={}; l=1.0
        for d in ds: l*=1+0.5*a[d]+0.5*b[d]; px[d]=l
        return px
    return load(sym)
rows=[]; allpool={21:[],63:[],126:[]}; basepool={21:[],63:[],126:[]}
print(f"{'sym':<9}{'ev':>3}{'fwd1m':>8}{'fwd3m':>8}{'fwd6m':>8}{'base6m':>8}{'worst6m':>9}{'avgMAE6m':>9}{'wait:missed':>12}{'wait:avoidDD':>13}")
for sym in ["AI_BLEND"]+U:
    try: px=series(sym)
    except Exception as e: continue
    ds=sorted(px); c=[px[d] for d in ds]; n=len(c)
    lr=[0]+[math.log(c[i]/c[i-1]) for i in range(1,n)]
    def vol(i):
        if i<33: return None
        s=lr[i-31:i+1]; mu=sum(s)/32; return math.sqrt(sum((x-mu)**2 for x in s)/31*252)
    me={}; 
    for i,d in enumerate(ds): me[d[:7]]=(i,c[i])
    months=sorted(me)
    # gate state per month (evaluated at that month's last session, as the next month's first run would)
    state={}
    for k in range(10,len(months)):
        i,cl=me[months[k]]; sma=sum(me[months[j]][1] for j in range(k-9,k+1))/10
        v=vol(i); state[months[k]]= not (cl<sma and v and v>0.20)
    ev=[]; prev=True
    for m in months[10:]:
        on=state[m]
        if prev and not on: ev.append(me[m][0])
        prev=on
    if not ev: continue
    f={h:[c[i+h]/c[i]-1 for i in ev if i+h<n] for h in (21,63,126)}
    for h in f: allpool[h]+=f[h]
    base6=[c[i+126]/c[i]-1 for i in range(n-126)]; basepool[126]+= [sum(base6)/len(base6)]*len(f[126])
    mae=[min(c[i:i+127])/c[i]-1 for i in ev if i+126<n]
    # waiting: from gate-off to next gate-on month-end; what did buy-now earn by then, and the min in between
    missed=[];avoid=[]
    for i in ev:
        m0=ds[i][:7]; k0=months.index(m0); j=None
        for k in range(k0+1,len(months)):
            if state.get(months[k]): j=me[months[k]][0]; break
        if j: missed.append(c[j]/c[i]-1); avoid.append(min(c[i:j+1])/c[i]-1)
    avg=lambda x: sum(x)/len(x) if x else float('nan')
    print(f"{sym:<9}{len(ev):>3}{avg(f[21]):>8.1%}{avg(f[63]):>8.1%}{avg(f[126]):>8.1%}{avg(base6):>8.1%}{min(f[126]) if f[126] else 0:>9.1%}{avg(mae):>9.1%}{avg(missed):>12.1%}{avg(avoid):>13.1%}")
avg=lambda x: sum(x)/len(x)
med=lambda x: sorted(x)[len(x)//2]
print(f"\nPOOLED  n={len(allpool[126])}  fwd1m {avg(allpool[21]):.1%}  fwd3m {avg(allpool[63]):.1%}  fwd6m mean {avg(allpool[126]):.1%} median {med(allpool[126]):.1%}  vs unconditional 6m {avg(basepool[126]):.1%}")
print(f"  share of 6m outcomes worse than -10%: {sum(1 for x in allpool[126] if x<-0.10)/len(allpool[126]):.0%};  worse than -25%: {sum(1 for x in allpool[126] if x<-0.25)/len(allpool[126]):.0%}")
