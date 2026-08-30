"""
Allocation study: §1.2c QLD core  x  BRK.B  x  AI-infra sleeve (50% AIS + 50% AIPO)  x  cash.
Long history uses validated proxies for AIS/AIPO; short window uses the real funds.
"""
import json, os, math, core_opt as C
D="data_adj"
def load(s):
    j=json.loads(open(f"{D}/{s}.json").read()[open(f"{D}/{s}.json").read().index("{"):])
    return {str(x["date"])[:10]: x["close"] for x in j["rows"] if x["close"]}
FITS=json.load(open("out/proxy_fits.json"))

def basket_series(fits_key):
    f=FITS[fits_key]; px={b:load(b) for b in f["basket"]}
    ds=sorted(set.intersection(*[set(v) for v in px.values()]))
    out={}
    for i in range(1,len(ds)):
        r=sum(w*(px[b][ds[i]]/px[b][ds[i-1]]-1) for b,w in zip(f["basket"],f["w"]) if w>0)
        out[ds[i]]=r
    return out

def series_ret(sym):
    px=load(sym); ds=sorted(px)
    return {ds[i]: px[ds[i]]/px[ds[i-1]]-1 for i in range(1,len(ds))}

def core_ret(start,end):
    m=C.run(vol_target=.30,win=32,cap=2.0,gate="sma10vol",band=4.0,start=start,end=end)
    idx=[i for i,d in enumerate(C.DATES) if start<=d<=end]
    ds=[C.DATES[i] for i in idx if i!=0]          # one date per appended equity point
    e=m["eq"]
    assert len(ds)==len(e)-1, (len(ds),len(e))
    return {ds[i-1]: e[i]/e[i-1]-1 for i in range(1,len(e))}, m

def metrics(r):
    e=[1.0]
    for x in r: e.append(e[-1]*(1+x))
    n=len(r); yrs=n/252; cagr=e[-1]**(1/yrs)-1
    mu=sum(r)/n; sd=math.sqrt(sum((x-mu)**2 for x in r)/(n-1)); vol=sd*math.sqrt(252)
    pk=e[0]; mdd=0
    for v in e: pk=max(pk,v); mdd=min(mdd,v/pk-1)
    return cagr,vol,(cagr/vol if vol else 0),mdd,(cagr/abs(mdd) if mdd else 0)

def build(start,end,use_proxy=True):
    cr,_=core_ret(start,end)
    brk=series_ret("BRK_B"); cash=series_ret("BIL")
    if use_proxy:
        ais=basket_series("AIS"); aipo=basket_series("AIPO")
    else:
        ais=series_ret("AIS"); aipo=series_ret("AIPO")
    ds=sorted(set(cr)&set(brk)&set(cash)&set(ais)&set(aipo))
    ds=[d for d in ds if start<=d<=end]
    sleeve={d:0.5*ais[d]+0.5*aipo[d] for d in ds}
    return ds, {"CORE":cr,"BRK":brk,"SLEEVE":sleeve,"CASH":cash}
