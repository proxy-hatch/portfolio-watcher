"""Build long-history proxies for AIS and AIPO, validated on their actual short history."""
import json, os, math, itertools
D="data_adj"
def load(s):
    p=f"{D}/{s}.json"
    if not os.path.exists(p): return None
    j=json.loads(open(p).read()[open(p).read().index("{"):])
    return {str(x["date"])[:10]: x["close"] for x in j["rows"] if x["close"]}
def rets(px, dates):
    return [px[dates[i]]/px[dates[i-1]]-1 for i in range(1,len(dates))]
def common(syms):
    s=None
    for x in syms:
        p=load(x)
        if p is None: return []
        s = set(p) if s is None else (s & set(p))
    return sorted(s)

def fit(target, basket, start=None):
    """Non-negative weights summing to 1, grid-searched to maximise R^2 vs target."""
    ds = common([target]+basket)
    if start: ds=[d for d in ds if d>=start]
    if len(ds)<60: return None
    t = rets(load(target), ds)
    B = [rets(load(b), ds) for b in basket]
    n=len(t); mt=sum(t)/n
    best=None
    step=0.1
    grid=[x*step for x in range(int(1/step)+1)]
    for combo in itertools.product(grid, repeat=len(basket)):
        if abs(sum(combo)-1.0)>1e-9: continue
        p=[sum(c*B[j][i] for j,c in enumerate(combo)) for i in range(n)]
        mp=sum(p)/n
        cov=sum((t[i]-mt)*(p[i]-mp) for i in range(n))/(n-1)
        vt=sum((x-mt)**2 for x in t)/(n-1); vp=sum((x-mp)**2 for x in p)/(n-1)
        if vp<=0 or vt<=0: continue
        r2=(cov/math.sqrt(vt*vp))**2
        te=math.sqrt(sum((t[i]-p[i])**2 for i in range(n))/n)*math.sqrt(252)
        if best is None or r2>best[0]: best=(r2,combo,te,len(ds))
    return best

print("PROXY FITS (non-negative weights, grid 0.1)\n")
CAND = {
 "AIS":  ["SOXX","MU","VRT","XLK"],
 "AIPO": ["GRID","XLU","PWR","ETN"],
}
FITS={}
for tgt, basket in CAND.items():
    r=fit(tgt,basket)
    if not r: print(f"{tgt}: fit failed"); continue
    r2,w,te,n=r
    FITS[tgt]=dict(basket=basket,w=w)
    print(f"{tgt:<6} R2={r2:.3f}  tracking-error={te*100:.1f}%/yr  n={n} obs")
    print(f"       " + "  ".join(f"{b} {x:.0%}" for b,x in zip(basket,w) if x>0))
json.dump(FITS, open("out/proxy_fits.json","w"), indent=1)
