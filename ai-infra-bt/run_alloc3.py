"""Final allocation: managed core x BRK.B x MANAGED AI-infra sleeve x cash."""
import alloc, sleeve_engine as SE, math
ds,S=alloc.build('2011-01-01','2026-08-24',use_proxy=True)
bil=SE.load('BIL')
# managed sleeve
spx=SE.from_returns(S['SLEEVE'])
sr=SE.run(spx,vol_target=.20,win=32,cap=1.0,gate='sma10vol',band=8.0,cash=bil)
sleeve={sr['dates'][i]: sr['eq'][i]/sr['eq'][i-1]-1 for i in range(1,len(sr['eq']))}
keys=sorted(set(S['CORE'])&set(S['BRK'])&set(S['CASH'])&set(sleeve))
R={'CORE':[S['CORE'][d] for d in keys],'BRK':[S['BRK'][d] for d in keys],
   'SLEEVE':[sleeve[d] for d in keys],'CASH':[S['CASH'][d] for d in keys]}
print(f"window {keys[0]} -> {keys[-1]}  ({len(keys)/252:.1f} yrs)\n")
print("COMPONENTS (all managed as they will actually be run)")
print(f"  {'':<28}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>9}{'MAR':>7}")
for k in R:
    e=[1.0]
    for x in R[k]: e.append(e[-1]*(1+x))
    c,v,s,m,mar=SE.metrics(e)
    print(f"  {k:<28}{c*100:>7.1f}%{v*100:>6.1f}%{s:>8.2f}{m*100:>8.1f}%{mar:>7.2f}")
print("\nCORRELATIONS")
ks=list(R)
print('  '+' '*10+''.join(f'{k:>9}' for k in ks))
for a in ks:
    row=f'  {a:<10}'
    for b in ks:
        x,y=R[a],R[b]; n=len(x); mx,my=sum(x)/n,sum(y)/n
        cov=sum((x[i]-mx)*(y[i]-my) for i in range(n))/(n-1)
        vx=sum((t-mx)**2 for t in x)/(n-1); vy=sum((t-my)**2 for t in y)/(n-1)
        row+=f'{cov/math.sqrt(vx*vy):>9.2f}'
    print(row)
def M(w,sub=None):
    idx=range(len(keys)) if sub is None else [i for i,d in enumerate(keys) if sub[0]<=d<=sub[1]]
    e=[1.0]
    for i in idx: e.append(e[-1]*(1+sum(w[k]*R[k][i] for k in R)))
    return SE.metrics(e)
CAND={
 "1  core-anchored (rec.)": dict(CORE=.45,BRK=.15,SLEEVE=.20,CASH=.20),
 "2  balanced":             dict(CORE=.40,BRK=.20,SLEEVE=.20,CASH=.20),
 "3  growth":               dict(CORE=.50,BRK=.10,SLEEVE=.25,CASH=.15),
 "4  conservative":         dict(CORE=.35,BRK=.20,SLEEVE=.15,CASH=.30),
 "5  no sleeve (baseline)": dict(CORE=.50,BRK=.20,SLEEVE=.00,CASH=.30),
}
print("\nCANDIDATE ALLOCATIONS — full window")
print(f"  {'':<26}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>9}{'MAR':>7}")
for k,w in CAND.items():
    c,v,s,m,mar=M(w)
    print(f"  {k:<26}{c*100:>7.1f}%{v*100:>6.1f}%{s:>8.2f}{m*100:>8.1f}%{mar:>7.2f}")
print("\nSTRESS (CAGR / maxDD)")
SUB=[("2020-02-01","2020-04-30","covid"),("2022-01-01","2022-12-31","2022 bear"),
     ("2018-10-01","2018-12-31","Q4-18"),("2026-06-01","2026-08-24","this summer")]
print(f"  {'':<26}"+"".join(f"{l:>21}" for _,_,l in SUB))
for k,w in CAND.items():
    row=f"  {k:<26}"
    for a,b,_ in SUB:
        c,v,s,m,mar=M(w,(a,b)); row+=f"{c*100:>10.1f}%{m*100:>10.1f}%"
    print(row)
