import alloc, math, itertools
ds,S=alloc.build('2018-01-01','2026-08-24',use_proxy=True)
R={k:[S[k][d] for d in ds] for k in ['CORE','BRK','SLEEVE','CASH']}
def port(w):
    return [sum(w[k]*R[k][i] for k in R) for i in range(len(ds))]
def m(w): return alloc.metrics(port(w))

STEP=0.05
grid=[]
vals=[round(x*STEP,2) for x in range(int(1/STEP)+1)]
for c in vals:
    for b in vals:
        for s in vals:
            if c+b+s>1.0+1e-9: continue
            w=dict(CORE=c,BRK=b,SLEEVE=s,CASH=round(1-c-b-s,2))
            cagr,vol,sh,mdd,mar=m(w)
            grid.append((w,cagr,vol,sh,mdd,mar))

def show(title, rows):
    print(f"\n{title}")
    print(f"  {'CORE':>6}{'BRK':>6}{'SLEEVE':>8}{'CASH':>7}{'CAGR':>9}{'vol':>8}{'Sharpe':>8}{'maxDD':>9}{'MAR':>7}")
    for w,cagr,vol,sh,mdd,mar in rows:
        print(f"  {w['CORE']*100:>5.0f}%{w['BRK']*100:>5.0f}%{w['SLEEVE']*100:>7.0f}%{w['CASH']*100:>6.0f}%"
              f"{cagr*100:>8.1f}%{vol*100:>7.1f}%{sh:>8.2f}{mdd*100:>8.1f}%{mar:>7.2f}")

show("MAX SHARPE (unconstrained — note it just chases the best backtest return)",
     sorted(grid,key=lambda x:-x[3])[:3])
show("MAX MAR (return per unit of drawdown)", sorted(grid,key=lambda x:-x[5])[:3])

for cap in (0.20,0.25,0.30):
    band=[g for g in grid if abs(g[4])<=cap and g[0]['SLEEVE']<=0.25]
    if band:
        show(f"BEST CAGR with maxDD <= {cap*100:.0f}% and sleeve <= 25%",
             sorted(band,key=lambda x:-x[1])[:3])

print("\n\nEQUAL-RISK-CONTRIBUTION (no return forecast needed)")
import statistics
vols={k:alloc.metrics(R[k])[1] for k in R}
inv={k:(1/vols[k] if vols[k]>0 else 0) for k in ['CORE','BRK','SLEEVE']}
tot=sum(inv.values())
for target_cash in (0.0,0.2,0.3,0.4):
    w={k:(1-target_cash)*inv[k]/tot for k in inv}; w['CASH']=target_cash
    cagr,vol,sh,mdd,mar=m(w)
    print(f"  cash {target_cash*100:>3.0f}%  ->  CORE {w['CORE']*100:>4.1f}%  BRK {w['BRK']*100:>4.1f}%  SLEEVE {w['SLEEVE']*100:>4.1f}%"
          f"   CAGR {cagr*100:>5.1f}%  vol {vol*100:>4.1f}%  maxDD {mdd*100:>6.1f}%  MAR {mar:.2f}")
