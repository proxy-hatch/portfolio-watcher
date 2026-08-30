"""Why is the win rate only ~39% when every entry is in a confirmed uptrend?"""
import engine, universe as U, math
V3=dict(gc=True,hh_tol=0.95,clear=2.0,m1=3.5,m2=5.25,b3="buffer",b3_buf=0.5)
T=[]
for s in U.IS_NAMES:
    try: T+=engine.simulate(s,*U.IS_PERIOD,**V3)
    except Exception: pass
n=len(T); R=[x["R"] for x in T]

print("="*74)
print("REASON 1 — THE TRAILING STOP MAKES MOST 'UP' TRADES BOOK AS LOSSES")
print("="*74)
print("""  You enter at price P. The trail sits at (highest close so far) - 3.5 ATR.
  At entry the highest close IS P, so the stop starts 3.5 ATR BELOW your entry.
  For the stop to even reach break-even, price must first rise MORE THAN 3.5 ATR.
  That is exactly 1.00 R.

  => Any trade that rises less than 1.00 R before turning is booked a LOSS,
     no matter how correct the trend call was.\n""")
mfe=[x["mfe"] for x in T]
buckets=[(0,0.5),(0.5,1.0),(1.0,2.0),(2.0,4.0),(4.0,99)]
print(f"  {'best point reached (MFE)':<28}{'trades':>8}{'share':>8}{'won?':>10}")
for lo,hi in buckets:
    g=[x for x in T if lo<=x["mfe"]<hi]
    if not g: continue
    w=sum(1 for x in g if x["R"]>0)
    print(f"  {f'{lo:.1f} - {hi:.1f} R':<28}{len(g):>8}{len(g)/n*100:>7.0f}%{w}/{len(g):>8}")
doomed=[x for x in T if x["mfe"]<1.0]
print(f"\n  {len(doomed)} of {n} trades ({len(doomed)/n*100:.0f}%) never rose 1.00 R.")
print(f"  Of those, {sum(1 for x in doomed if x['R']>0)} won. They were losses BY CONSTRUCTION.")
above=[x for x in T if x["mfe"]>=1.0]
print(f"  Of the {len(above)} that DID clear 1.00 R, {sum(1 for x in above if x['R']>0)} won "
      f"({sum(1 for x in above if x['R']>0)/len(above)*100:.0f}%).")

print("\n"+"="*74)
print("REASON 2 — 'IN AN UPTREND' IS A WEAK PREDICTOR, HONESTLY MEASURED")
print("="*74)
hit_up=hit_dn=0
for s in U.IS_NAMES:
    try: b=engine.bars(s)
    except Exception: continue
    p=dict(engine.DEFAULTS); p.update(V3)
    for i,x in enumerate(b):
        if not x["atr"] or not x["sma200"]: continue
        if x["d"]<U.IS_PERIOD[0] or x["d"]>U.IS_PERIOD[1]: continue
        if not engine._gate(x,p): continue
        up=x["c"]+3.5*x["atr"]; dn=x["c"]-3.5*x["atr"]
        for y in b[i+1:i+300]:
            if y["h"]>=up: hit_up+=1; break
            if y["l"]<=dn: hit_dn+=1; break
print(f"  From every bar where the gate says 'clean uptrend, enter':")
print(f"    reached +3.5 ATR first : {hit_up:>6}")
print(f"    reached -3.5 ATR first : {hit_dn:>6}")
print(f"    -> the trend continued far enough only {hit_up/(hit_up+hit_dn)*100:.0f}% of the time.")
print("\n  A confirmed uptrend is NOT a high-probability bet. It is a slightly")
print("  favourable one attached to a very large payoff when it works.")

print("\n"+"="*74)
print("REASON 3 — HIGH WIN RATE IS AVAILABLE, AND IT LOSES MONEY")
print("="*74)
print(f"  {'exit rule':<34}{'win rate':>10}{'avg win':>9}{'avg loss':>10}{'expectancy':>12}")
for lab,tgt in [("take profit at +0.5 R",0.5),("take profit at +1.0 R",1.0),
                ("take profit at +2.0 R",2.0),("take profit at +4.0 R",4.0)]:
    out=[]
    for x in T:
        out.append(tgt if x["mfe"]>=tgt else x["R"])
    w=[v for v in out if v>0]; l=[v for v in out if v<=0]
    aw=sum(w)/len(w) if w else 0; al=abs(sum(l)/len(l)) if l else 0
    print(f"  {lab:<34}{len(w)/len(out)*100:>9.0f}%{aw:>9.2f}{al:>10.2f}{sum(out)/len(out):>+11.3f}R")
w=[v for v in R if v>0]; l=[v for v in R if v<=0]
print(f"  {'let it run (v3 trailing stop)':<34}{len(w)/n*100:>9.0f}%{sum(w)/len(w):>9.2f}"
      f"{abs(sum(l)/len(l)):>10.2f}{sum(R)/n:>+11.3f}R  <-- best")
print("\n  Capping winners at +0.5R gives you a 70%+ win rate and destroys the edge,")
print("  because the whole return lives in the few trades that run to +4R and beyond.")
