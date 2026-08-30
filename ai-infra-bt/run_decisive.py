"""The decisive tests: long history, sub-periods, and trend-as-diversifier."""
import bench2 as B, bench3, math
X=['SPY','QQQ','IWM','MDY','EFA','EEM','EWJ','EWZ','TLT','IEF','SHY','LQD','HYG','TIP','AGG',
   'GLD','SLV','DBC','DBA','FXE','FXY','IYR','SMH','ITB','IBB','KRE','OIH']
def avail(a,b):
    out=[]
    for s in X:
        try:
            bb=[x for x in bench3.bars(s) if a<=x['d']<=b]
            if len(bb)>400: out.append(s)
        except Exception: pass
    return out

PER=[("2007-01-01","2026-08-24","full (incl. 2008)"),
     ("2007-01-01","2010-12-31","2007-2010 GFC"),
     ("2011-01-01","2019-12-31","2011-2019 QE bull"),
     ("2020-01-01","2026-08-24","2020-2026 covid+inflation")]
print("=== DIVERSIFIED CROSS-ASSET TREND vs SPY, BY REGIME ===\n")
for a,b,lab in PER:
    U=avail(a,b)
    print(f"--- {lab}  [{a} -> {b}]  n={len(U)} instruments")
    print("  "+B.PHDR)
    print("  "+B.pfmt(B.perf(B.simulate_portfolio(['SPY'],a,b,lambda bb,**k:[1.0]*len(bb),max_leverage=1.0)),"SPY buy&hold"))
    for lab2,fn,lo,lev in [("Ensemble Donch LO x3",B.sig_ensemble,True,3.0),
                           ("TSMOM L/S x3",B.sig_tsmom,False,3.0),
                           ("Ensemble Donch L/S x3",B.sig_ensemble,False,3.0)]:
        print("  "+B.pfmt(B.perf(B.simulate_portfolio(U,a,b,fn,max_leverage=lev,long_only=lo)),lab2))
    print()

print("\n=== TREND AS A DIVERSIFIER: blend with an SPY core (2007-2026) ===\n")
a,b="2007-01-01","2026-08-24"; U=avail(a,b)
spy=B.simulate_portfolio(['SPY'],a,b,lambda bb,**k:[1.0]*len(bb),max_leverage=1.0)
tr =B.simulate_portfolio(U,a,b,B.sig_ensemble,max_leverage=3.0,long_only=False)
def rets(r): 
    e=r["equity"]; return [e[i]/e[i-1]-1 for i in range(1,len(e))]
rs,rt=rets(spy),rets(tr); n=min(len(rs),len(rt)); rs,rt=rs[-n:],rt[-n:]
ms,mt=sum(rs)/n,sum(rt)/n
cov=sum((rs[i]-ms)*(rt[i]-mt) for i in range(n))/(n-1)
sd_s=math.sqrt(sum((x-ms)**2 for x in rs)/(n-1)); sd_t=math.sqrt(sum((x-mt)**2 for x in rt)/(n-1))
print(f"  correlation(SPY, trend) = {cov/(sd_s*sd_t):+.3f}   <- the whole case for holding it\n")
print("  "+f"{'blend':<22}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>8}{'MAR':>7}")
for w in (0.0,0.1,0.2,0.3,0.4,0.5,1.0):
    e=[1.0]
    for i in range(n): e.append(e[-1]*(1+(1-w)*rs[i]+w*rt[i]))
    r=[e[i]/e[i-1]-1 for i in range(1,len(e))]
    yrs=len(r)/252; cagr=e[-1]**(1/yrs)-1; mu=sum(r)/len(r)
    sd=math.sqrt(sum((x-mu)**2 for x in r)/(len(r)-1)); vol=sd*math.sqrt(252)
    pk=e[0]; mdd=0
    for v in e: pk=max(pk,v); mdd=min(mdd,v/pk-1)
    print("  "+f"{f'{int((1-w)*100)}% SPY / {int(w*100)}% trend':<22}{cagr*100:>7.1f}%{vol*100:>6.1f}%{cagr/vol:>8.2f}{mdd*100:>7.1f}%{cagr/abs(mdd):>7.2f}")
