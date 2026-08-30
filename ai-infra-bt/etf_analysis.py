"""How much does each ETF add BEYOND the QLD/QQQ core the user already owns?"""
import json, math, os
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_adj")
def load(s):
    p=os.path.join(D,f"{s}.json")
    if not os.path.exists(p): return None
    j=json.loads(open(p).read()[open(p).read().index("{"):])
    return {str(x["date"])[:10]: x["close"] for x in j["rows"] if x["close"]}
def stats(sym, bench="QQQ", start="2015-01-01"):
    a, b = load(sym), load(bench)
    if not a: return None
    ds = sorted(set(a) & set(b)); ds = [d for d in ds if d >= start]
    if len(ds) < 260: 
        ds = sorted(set(a) & set(b))
        if len(ds) < 150: return None
    ra=[a[ds[i]]/a[ds[i-1]]-1 for i in range(1,len(ds))]
    rb=[b[ds[i]]/b[ds[i-1]]-1 for i in range(1,len(ds))]
    n=len(ra); ma,mb=sum(ra)/n,sum(rb)/n
    cov=sum((ra[i]-ma)*(rb[i]-mb) for i in range(n))/(n-1)
    va=sum((x-ma)**2 for x in ra)/(n-1); vb=sum((x-mb)**2 for x in rb)/(n-1)
    corr=cov/math.sqrt(va*vb); beta=cov/vb
    alpha=(ma-beta*mb)*252
    yrs=n/252; cagr=(a[ds[-1]]/a[ds[0]])**(1/yrs)-1
    bcagr=(b[ds[-1]]/b[ds[0]])**(1/yrs)-1
    pk=1; eq=1; mdd=0
    for i in range(n):
        eq*=(1+ra[i]); pk=max(pk,eq); mdd=min(mdd,eq/pk-1)
    return dict(sym=sym,n=n,start=ds[0],corr=corr,beta=beta,r2=corr*corr,alpha=alpha,
                cagr=cagr,bcagr=bcagr,vol=math.sqrt(va*252),mdd=mdd,yrs=yrs)
NAMES={"AIQ":"Global X AI & Technology","IGPT":"Invesco AI & Next Gen Software",
 "ARTY":"iShares Future AI & Tech","THNQ":"ROBO Global AI","GRID":"First Trust Smart Grid Infra",
 "PAVE":"Global X US Infrastructure","POWR":"iShares US Power Infrastructure",
 "AIPO":"Defiance AI & Power Infra","SMH":"VanEck Semiconductor","SOXX":"iShares Semiconductor",
 "XLU":"Utilities Select Sector","NLR":"VanEck Uranium+Nuclear","AINF":"iShares AI Infrastructure",
 "IGF":"iShares Global Infrastructure","QQQM":"Invesco Nasdaq-100","VRT":"Vertiv (stock)",
 "PWR":"Quanta Services (stock)","ETN":"Eaton (stock)"}
print("Correlation / overlap vs QQQ — the core you already own")
print(f"{'sym':<6}{'name':<32}{'yrs':>5}{'corr':>7}{'R2':>7}{'beta':>6}{'CAGR':>8}{'QQQ':>8}{'vol':>7}{'maxDD':>8}{'alpha':>8}")
rows=[]
for s in NAMES:
    m=stats(s)
    if m: rows.append(m)
for m in sorted(rows,key=lambda x:x["r2"]):
    print(f"{m['sym']:<6}{NAMES[m['sym']][:31]:<32}{m['yrs']:>5.1f}{m['corr']:>7.2f}{m['r2']:>7.2f}"
          f"{m['beta']:>6.2f}{m['cagr']*100:>7.1f}%{m['bcagr']*100:>7.1f}%{m['vol']*100:>6.1f}%{m['mdd']*100:>7.1f}%{m['alpha']*100:>7.1f}%")
