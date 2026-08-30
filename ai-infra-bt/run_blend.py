"""Does the diversifier result hold against the user's ACTUAL core (QLD 2x Nasdaq)?"""
import bench2 as B, bench3, math
X=['SPY','QQQ','IWM','MDY','EFA','EEM','EWJ','EWZ','TLT','IEF','SHY','LQD','HYG','TIP','AGG',
   'GLD','SLV','DBC','DBA','FXE','FXY','IYR','SMH','ITB','IBB','KRE','OIH']
def rets(r):
    e=r["equity"]; return [e[i]/e[i-1]-1 for i in range(1,len(e))]
def stats(r,lab):
    e=[1.0]
    for x in r: e.append(e[-1]*(1+x))
    yrs=len(r)/252; cagr=e[-1]**(1/yrs)-1; mu=sum(r)/len(r)
    sd=math.sqrt(sum((x-mu)**2 for x in r)/(len(r)-1)); vol=sd*math.sqrt(252)
    pk=e[0]; mdd=0
    for v in e: pk=max(pk,v); mdd=min(mdd,v/pk-1)
    return f"{lab:<26}{cagr*100:>7.1f}%{vol*100:>6.1f}%{cagr/vol:>8.2f}{mdd*100:>7.1f}%{cagr/abs(mdd):>7.2f}"
HDR=f"{'blend':<26}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>8}{'MAR':>7}"

for a,b,lab in [("2011-01-01","2026-08-24","2011-2026"),
                ("2011-01-01","2019-12-31","2011-2019"),
                ("2020-01-01","2026-08-24","2020-2026")]:
    qqq=rets(B.simulate_portfolio(['QQQ'],a,b,lambda bb,**k:[1.0]*len(bb),max_leverage=1.0))
    tr =rets(B.simulate_portfolio(X,a,b,B.sig_ensemble,max_leverage=3.0,long_only=False))
    n=min(len(qqq),len(tr)); qqq,tr=qqq[-n:],tr[-n:]
    core=[1.85*x for x in qqq]     # ~QLD-equivalent: 2x QQQ net of decay/financing (~0.15 drag)
    mq,mt=sum(core)/n,sum(tr)/n
    cov=sum((core[i]-mq)*(tr[i]-mt) for i in range(n))/(n-1)
    sq=math.sqrt(sum((x-mq)**2 for x in core)/(n-1)); st=math.sqrt(sum((x-mt)**2 for x in tr)/(n-1))
    print(f"\n### {lab}   corr(QLD-core, trend) = {cov/(sq*st):+.3f}")
    print("  "+HDR)
    for w in (0.0,0.1,0.15,0.2,0.3,0.4):
        print("  "+stats([(1-w)*core[i]+w*tr[i] for i in range(n)],
                          f"{int((1-w)*100)}% QLD / {int(w*100)}% trend"))
