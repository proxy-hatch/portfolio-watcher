"""Dip-buy events on QQQ (total return, 1999-2026). Does buying after an X% pullback beat a
random entry over the same horizon? IS 1999-2012 picks, OOS 2013-2026 judges. No look-ahead:
signal on close t, enter close t, measure close t+H."""
import sys; sys.path.insert(0, sys.argv[1]); from common import *
q=load("QQQ"); ds=sorted(q); c=[q[d] for d in ds]; n=len(c)
# filters
sma200=[None]*n
for i in range(199,n): sma200[i]=sum(c[i-199:i+1])/200
me={}; 
for i,d in enumerate(ds): me[d[:7]]=c[i]
months=sorted(me)
def gate_on(i):  # last COMPLETED month above its 10-mo SMA (trend leg of the v3 gate only)
    m=ds[i][:7]; k=months.index(m)
    if k<11: return None
    prev=months[k-1]; sma=sum(me[months[j]] for j in range(k-10,k))/10
    return me[prev]>=sma
mcache={}
G=[gate_on(i) for i in range(n)]
def events(X,lb,filt,H):
    ev=[]; last=-10**9
    for i in range(lb,n-H):
        hi=max(c[i-lb:i+1]); dd=c[i]/hi-1
        if dd>-X: continue
        if i-last<H: continue          # one event per holding period
        if filt=="gate" and G[i] is not True: continue
        if filt=="sma200" and (sma200[i] is None or c[i]<sma200[i]): continue
        if filt=="gateoff" and G[i] is not False: continue
        ev.append(i); last=i
    return ev
def stats(idx,H,lo,hi):
    idx=[i for i in idx if lo<=ds[i]<=hi]
    if not idx: return None
    f=[c[i+H]/c[i]-1 for i in idx]
    mae=[min(c[i:i+H+1])/c[i]-1 for i in idx]
    base=[c[i+H]/c[i]-1 for i in range(n-H) if lo<=ds[i]<=hi]
    mb=sum(base)/len(base)
    return len(f), sum(f)/len(f), mb, sum(1 for x in f if x>0)/len(f), min(f), sum(mae)/len(mae)
P={"IS":("1999-03-10","2012-12-31"),"OOS":("2013-01-01","2026-08-24")}
print(f"{'X':>5} {'filt':>7} {'H':>3} | {'per':>3} {'n':>3} {'fwd':>7} {'base':>7} {'edge':>7} {'hit':>5} {'worst':>7} {'avgMAE':>7}")
for filt in ["none","gate","sma200","gateoff"]:
  for X in [0.05,0.075,0.10,0.15]:
    for H in [21,63]:
      ev=events(X,63,filt,H)
      for p,(lo,hi) in P.items():
        s=stats(ev,H,lo,hi)
        if not s: print(f"{X:>5.3f} {filt:>7} {H:>3} | {p:>3}   0"); continue
        k,f,b,h,w,m=s
        print(f"{X:>5.3f} {filt:>7} {H:>3} | {p:>3} {k:>3} {f:>7.1%} {b:>7.1%} {f-b:>+7.1%} {h:>5.0%} {w:>7.1%} {m:>7.1%}")
# where are we now (state/prices has QQQ to 10-30, price-only but fine for drawdown)
import json
live=json.load(open("/Users/shawn/workspace/portfolio-watcher/state/prices/QQQ.json"))["closes"]
lv=list(live.values()) if isinstance(live,dict) else [x[1] for x in live]
print(f"\nNOW: QQQ {lv[-1]:.2f}, 63d high {max(lv[-64:]):.2f}, drawdown {lv[-1]/max(lv[-64:])-1:.1%}")
