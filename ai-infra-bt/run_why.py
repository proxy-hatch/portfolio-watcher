"""Why few-asset trend following fails: the arithmetic, from measured trades."""
import engine, universe as U, bench3, math, random
V3 = dict(gc=True, hh_tol=0.95, clear=2.0, m1=3.5, m2=5.25, b3="buffer", b3_buf=0.5)

# unbiased sample: anti-survivorship names, 2020-2023
T=[]
for s in U.IS_NAMES:
    try: T+=engine.simulate(s,*U.IS_PERIOD,**V3)
    except Exception: pass
R=[x["R"] for x in T]
n=len(R); mu=sum(R)/n
sd=math.sqrt(sum((x-mu)**2 for x in R)/(n-1))
print("="*72); print("1. THE PER-TRADE EDGE IS REAL BUT TINY"); print("="*72)
print(f"  trades                    {n}")
print(f"  average result            {mu:+.3f} R   (R = one unit of planned risk)")
print(f"  spread (std dev)          {sd:.3f} R")
print(f"  signal-to-noise per trade {mu/sd:.3f}")
need=(2*sd/mu)**2 if mu>0 else float('inf')
print(f"\n  Trades needed before the edge is even 95% distinguishable from luck: {need:,.0f}")
print(f"    at ~6 trades/yr (4-name sleeve):        {need/6:,.0f} years")
print(f"    at ~40 trades/yr (30-name book):        {need/40:,.0f} years")
print(f"    at ~150 trades/yr (CTA, 100+ markets):  {need/150:,.0f} years")

print("\n"+"="*72); print("2. NEARLY ALL THE PROFIT COMES FROM A FEW TRADES"); print("="*72)
S=sorted(R,reverse=True); gross=sum(x for x in S if x>0)
for k in (1,3,5,10):
    cut=max(1,int(n*k/100))
    print(f"  top {k:>2}% of trades ({cut:>2} of {n}) = {sum(S[:cut])/gross*100:>5.1f}% of all gross profit")
wins=[x for x in R if x>0]
print(f"\n  Win rate {len(wins)/n*100:.0f}%. Biggest winner {max(R):+.2f}R, biggest loser {min(R):+.2f}R.")
print(f"  You cannot rule-engineer a big winner into existence — you can only be")
print(f"  holding enough different things that one of them happens to you.")

print("\n"+"="*72); print("3. THE 4-NAME SLEEVE IS ROUGHLY ONE BET, NOT FOUR"); print("="*72)
def rets(s,a,b):
    x=[y for y in bench3.bars(s) if a<=y["d"]<=b]
    return {x[i]["d"]: x[i]["c"]/x[i-1]["c"]-1 for i in range(1,len(x))}
def corr(u,v):
    k=sorted(set(u)&set(v))
    if len(k)<60: return None
    a=[u[d] for d in k]; b=[v[d] for d in k]; m=len(a)
    ma,mb=sum(a)/m,sum(b)/m
    ca=math.sqrt(sum((x-ma)**2 for x in a)); cb=math.sqrt(sum((x-mb)**2 for x in b))
    return sum((a[i]-ma)*(b[i]-mb) for i in range(m))/(ca*cb) if ca and cb else None
for lab,names,a,b in [("AI sleeve",["BE","NBIS","CORZ","SNDK"],"2025-06-01","2026-08-24"),
                      ("Cross-asset 8",["SPY","TLT","GLD","DBC","EEM","FXY","HYG","IEF"],"2011-01-01","2026-08-24")]:
    rr={s:rets(s,a,b) for s in names}
    cs=[c for i,x in enumerate(names) for y in names[i+1:] if (c:=corr(rr[x],rr[y])) is not None]
    if not cs: continue
    avg=sum(cs)/len(cs); N=len(names)
    eff=N/(1+(N-1)*max(avg,0))
    print(f"  {lab:<15} {N} assets, average pairwise correlation {avg:+.2f}  ->  ~{eff:.1f} genuinely independent bets")

print("\n"+"="*72); print("4. WHAT A BETTER EXIT CAN AND CANNOT DO"); print("="*72)
mfe=[x["mfe"] for x in T]
cap=[(x["R"]/x["mfe"]) for x in T if x["mfe"]>0.05]
print(f"  Average best-point-in-trade (MFE)     {sum(mfe)/len(mfe):+.2f} R")
print(f"  Average actual result                 {mu:+.2f} R")
print(f"  So exits already capture roughly      {sum(cap)/len(cap)*100:.0f}% of the best available point")
loss=[x for x in R if x<=0]
print(f"\n  Perfect-hindsight test — turn EVERY loss into a break-even (impossible):")
print(f"    expectancy would go {mu:+.3f}R -> {sum(x for x in R if x>0)/n:+.3f}R")
print(f"    trades still needed to prove it: {((2*sd/(sum(x for x in R if x>0)/n))**2):,.0f}")
print(f"  Even a flawless exit leaves you needing hundreds of trades to harvest it.")

print("\n"+"="*72); print("5. HOW OFTEN YOU'D BE LOSING AFTER N TRADES (bootstrap, 20k runs)"); print("="*72)
random.seed(7)
print(f"  {'after':<10}{'chance you are DOWN':>22}{'chance you are down >5R':>26}")
for N in (4,10,20,50,100,400):
    dn=sum(1 for _ in range(20000) if sum(random.choice(R) for _ in range(N))<0)
    bad=sum(1 for _ in range(20000) if sum(random.choice(R) for _ in range(N))<-5)
    print(f"  {N:<10}{dn/20000*100:>21.0f}%{bad/20000*100:>25.0f}%")
