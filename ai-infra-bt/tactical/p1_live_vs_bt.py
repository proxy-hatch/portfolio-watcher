import sys; sys.path.insert(0, sys.argv[1]); from common import *
import alloc, sleeve_engine as SE
ds,S=alloc.build('2011-01-01','2026-08-24',use_proxy=True)
bil=SE.load('BIL'); spx=SE.from_returns(S['SLEEVE'])
sr=SE.run(spx,vol_target=.20,win=32,cap=1.0,gate='sma10vol',band=8.0,cash=bil)
sl={sr['dates'][i]: sr['eq'][i]/sr['eq'][i-1]-1 for i in range(1,len(sr['eq']))}
keys=sorted(set(S['CORE'])&set(S['BRK'])&set(S['CASH'])&set(sl))
w=dict(CORE=.45,BRK=.15,SLEEVE=.20,CASH=.20)
eq=[1.0]
for d in keys: eq.append(eq[-1]*(1+w['CORE']*S['CORE'][d]+w['BRK']*S['BRK'][d]+w['SLEEVE']*sl[d]+w['CASH']*S['CASH'][d]))
dd=dd_stats(eq)
print(f"v3 backtest {keys[0]}..{keys[-1]}  maxDD {min(dd):.1%}")
print(f"  share of days in drawdown <= -10%: {sum(1 for x in dd if x<=-0.10)/len(dd):.1%}")
# distinct drawdown episodes deeper than 10%
ep=0; inn=False
for x in dd:
    if x<=-0.10 and not inn: ep+=1; inn=True
    if x>-0.02: inn=False
print(f"  distinct episodes reaching -10%: {ep} in {len(keys)/252:.1f} yrs  (~1 every {len(keys)/252/ep:.1f} yrs)")
r46=[eq[i+46]/eq[i]-1 for i in range(len(eq)-46)]
r46s=sorted(r46); pct=sum(1 for x in r46 if x<=-0.061)/len(r46)
print(f"  46-session return <= -6.1% (live since 08-26): {pct:.1%} of windows; 5th pct {r46s[int(.05*len(r46s))]:.1%}")
# deepest drawdown episodes
pk=eq[0];pd=keys[0];worst=[]
