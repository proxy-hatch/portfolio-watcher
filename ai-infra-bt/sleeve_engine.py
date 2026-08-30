"""
Apply the §1.2c ruleset (vol-target sizing + vol-conditioned 10-month regime gate)
to an arbitrary holding, so the AI-infra sleeve is managed like the QLD core.
Signal and holding are the same asset here (unlevered), so cap defaults to 1.0.
"""
import json, os, math
D="data_adj"; ANN=252
def load(s):
    j=json.loads(open(f"{D}/{s}.json").read()[open(f"{D}/{s}.json").read().index("{"):])
    return {str(x["date"])[:10]: x["close"] for x in j["rows"] if x["close"]}

def from_returns(rets):
    """Build a price series {date: level} from a {date: return} dict."""
    ds=sorted(rets); px={}; lvl=1.0
    for d in ds: lvl*= (1+rets[d]); px[d]=lvl
    return px

def run(px, vol_target=0.25, win=32, cap=1.0, gate="sma10vol", band=4.0,
        cost_bps=5.0, cash=None, start=None, end=None):
    ds=sorted(px)
    if start: ds=[d for d in ds if d>=start]
    if end:   ds=[d for d in ds if d<=end]
    c=[px[d] for d in ds]
    r=[0.0]+[math.log(c[i]/c[i-1]) for i in range(1,len(c))]
    vol=[None]*len(c)
    for i in range(win,len(c)):
        s=r[i-win+1:i+1]; mu=sum(s)/win
        vol[i]=math.sqrt(sum((x-mu)**2 for x in s)/(win-1))*math.sqrt(ANN)
    # month-end closes -> 10-month SMA gate (uses last COMPLETED month, no look-ahead)
    me={}
    for i,d in enumerate(ds): me[d[:7]]=(i,c[i])
    months=sorted(me); midx={m:i for i,m in enumerate(months)}
    sma={}
    for k in range(len(months)):
        if k+1>=10: sma[months[k]]=sum(me[months[j]][1] for j in range(k-9,k+1))/10
    eq=[1.0]; w=0.0; nreb=0; expo=[]
    for i in range(1,len(ds)):
        v=vol[i-1]
        if v is None or v<=0: wt=w
        else:
            L=min(cap, vol_target/v)
            k=midx[ds[i-1][:7]]
            on=True
            if k>0:
                prev=months[k-1]; s=sma.get(prev)
                if s is not None:
                    below = me[prev][1] < s
                    on = not (below and v>0.20) if gate=="sma10vol" else not below
            if not on: L=0.0
            wt=L
        cost=0.0
        if abs(wt-w)*100 > band:
            cost=abs(wt-w)*cost_bps/10000.0; nreb+=1; w=wt
        rr=c[i]/c[i-1]-1
        cr=0.00008
        if cash and ds[i] in cash and ds[i-1] in cash: cr=cash[ds[i]]/cash[ds[i-1]]-1
        eq.append(eq[-1]*(1+w*rr+max(0.0,1-w)*cr-cost)); expo.append(w)
    return dict(dates=ds, eq=eq, expo=sum(expo)/len(expo) if expo else 0, reb=nreb,
                yrs=len(eq)/ANN)

def metrics(eq):
    r=[eq[i]/eq[i-1]-1 for i in range(1,len(eq))]
    n=len(r); yrs=n/ANN; cagr=eq[-1]**(1/yrs)-1
    mu=sum(r)/n; sd=math.sqrt(sum((x-mu)**2 for x in r)/(n-1)); vol=sd*math.sqrt(ANN)
    pk=eq[0]; mdd=0
    for v in eq: pk=max(pk,v); mdd=min(mdd,v/pk-1)
    return cagr,vol,(cagr/vol if vol else 0),mdd,(cagr/abs(mdd) if mdd else 0)
