"""Return-stacking test: lever each blend to a CONSTANT risk budget, then compare return."""
import bench2 as B, bench3, math
X=['SPY','QQQ','IWM','MDY','EFA','EEM','EWJ','EWZ','TLT','IEF','SHY','LQD','HYG','TIP','AGG',
   'GLD','SLV','DBC','DBA','FXE','FXY','IYR','SMH','ITB','IBB','KRE','OIH']
def rets(r):
    e=r["equity"]; return [e[i]/e[i-1]-1 for i in range(1,len(e))]
def mets(r):
    e=[1.0]
    for x in r: e.append(e[-1]*(1+x))
    yrs=len(r)/252; cagr=e[-1]**(1/yrs)-1; mu=sum(r)/len(r)
    sd=math.sqrt(sum((x-mu)**2 for x in r)/(len(r)-1)); vol=sd*math.sqrt(252)
    pk=e[0]; mdd=0
    for v in e: pk=max(pk,v); mdd=min(mdd,v/pk-1)
    return cagr,vol,(cagr/vol if vol else 0),mdd

for a,b,lab in [("2011-01-01","2026-08-24","2011-2026"),("2020-01-01","2026-08-24","2020-2026")]:
    qqq=rets(B.simulate_portfolio(['QQQ'],a,b,lambda bb,**k:[1.0]*len(bb),max_leverage=1.0))
    tr =rets(B.simulate_portfolio(X,a,b,B.sig_ensemble,max_leverage=3.0,long_only=False))
    n=min(len(qqq),len(tr)); core=[1.85*x for x in qqq[-n:]]; tr=tr[-n:]
    _,_,_,base_dd=mets(core)
    print(f"\n### {lab} — each blend levered to match the 100%-QLD drawdown of {base_dd*100:.1f}%")
    print(f"  {'blend':<24}{'lev':>6}{'CAGR':>9}{'vol':>7}{'Sharpe':>8}{'maxDD':>8}   vs 100% QLD")
    base_cagr=None
    for w in (0.0,0.1,0.2,0.3,0.4,0.5):
        mix=[(1-w)*core[i]+w*tr[i] for i in range(n)]
        lo,hi=0.5,4.0
        for _ in range(40):                       # solve leverage that matches base_dd
            m=(lo+hi)/2
            _,_,_,dd=mets([m*x for x in mix])
            if dd < base_dd: hi=m
            else: lo=m
        L=(lo+hi)/2
        c,v,s,dd=mets([L*x for x in mix])
        if base_cagr is None: base_cagr=c
        print(f"  {f'{int((1-w)*100)}% QLD / {int(w*100)}% trend':<24}{L:>6.2f}{c*100:>8.1f}%{v*100:>6.1f}%{s:>8.2f}{dd*100:>7.1f}%   {(c-base_cagr)*100:>+6.1f}pp")
