"""
§1.2c QLD strategic-core optimiser.
Uses REAL QLD total-return bars (so real 2x decay + fees are in the data),
REAL BIL for the cash leg, QQQ for signals. 2006-2026 incl. 2008 and 2022.

Sleeve model: within the core sleeve, hold w = L/2 in QLD, remainder in BIL.
  L_t = min(cap, vol_target / realised_vol(QQQ, win))    [vol targeting]
  regime gate: if OFF -> L = 0 (fully defensive)
  rebalance only when |w_target - w_held| > band/2  (band is in pp of NAV)
"""
import json, math, os
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_adj")
ANN = 252

def load(sym):
    raw = open(os.path.join(D, f"{sym}.json")).read()
    j = json.loads(raw[raw.index("{"):])
    return {str(x["date"])[:10]: x["close"] for x in j["rows"] if x["close"]}

QQQ, QLD, BIL = load("QQQ"), load("QLD"), load("BIL")
DEF = {"BIL": BIL, "GLD": load("GLD"), "TLT": load("TLT"), "IEF": load("IEF")}
DATES = sorted(set(QQQ) & set(QLD))
DATES = [d for d in DATES if d >= "2006-09-01"]

def _pre():
    q = [QQQ[d] for d in DATES]
    r = [0.0] + [math.log(q[i]/q[i-1]) for i in range(1, len(q))]
    vol = {}
    for w in (10, 20, 26, 32, 40, 60, 120):
        v = [None]*len(q)
        for i in range(w, len(q)):
            s = r[i-w+1:i+1]; mu = sum(s)/w
            v[i] = math.sqrt(sum((x-mu)**2 for x in s)/(w-1))*math.sqrt(ANN)
        vol[w] = v
    # monthly-close SMAs on QQQ (regime gate), evaluated daily off month-end closes
    me = {}
    for i, d in enumerate(DATES):
        me[d[:7]] = (i, q[i])
    months = sorted(me)
    sma = {}
    for n in (6, 8, 10, 12):
        for k in range(len(months)):
            if k+1 >= n:
                vals = [me[months[j]][1] for j in range(k+1-n, k+1)]
                sma[(n, months[k])] = sum(vals)/n
    d200 = [None]*len(q)
    for i in range(200, len(q)): d200[i] = sum(q[i-199:i+1])/200
    mclose = {m: me[m][1] for m in months}
    return q, vol, months, sma, d200, mclose
Q, VOL, MONTHS, SMA, D200, MCLOSE = _pre()
MIDX = {m: i for i, m in enumerate(MONTHS)}

def gate_on(i, mode, vol_now):
    """Risk-on? Uses only the LAST COMPLETED month's close vs its SMA -> no look-ahead."""
    if mode == "none": return True
    if mode == "sma200":
        return D200[i] is not None and Q[i] > D200[i]
    k = MIDX[DATES[i][:7]]
    if k == 0: return True
    prev = MONTHS[k-1]
    n = {"sma10": 10, "sma10vol": 10, "sma6": 6, "sma8": 8, "sma12": 12}[mode]
    s = SMA.get((n, prev))
    if s is None: return True
    below = MCLOSE[prev] < s
    if mode == "sma10vol":
        return not (below and (vol_now or 0) > 0.20)
    return not below

SLEEVE_NAV = 0.40   # the core sleeve is 40% of NAV at 1x-equivalent; band is quoted in pp of NAV
def run(vol_target=0.30, win=20, cap=3.0, gate="sma10vol", band=4.0, cost_bps=5.0, defensive="BIL",
        start="2006-09-01", end="2026-08-24"):
    idx = [i for i, d in enumerate(DATES) if start <= d <= end]
    if not idx: return None
    eq = [1.0]; w_held = 0.0; turn_total = 0.0; nreb = 0; expo = []
    prev_bil = None
    for i in idx:
        if i == 0: continue
        if isinstance(win, str):
            if win == "max20_60":   a,b_ = VOL[20][i-1], VOL[60][i-1]; v = max(a,b_) if a and b_ else None
            elif win == "avg20_60": a,b_ = VOL[20][i-1], VOL[60][i-1]; v = (a+b_)/2 if a and b_ else None
            elif win == "max20_32": a,b_ = VOL[20][i-1], VOL[32][i-1]; v = max(a,b_) if a and b_ else None
            else: v = None
        else:
            v = VOL[win][i-1]
        if v is None or v <= 0:
            w_t = w_held
        else:
            L = min(cap, vol_target / v)
            if "+" in gate:
                g1, g2 = gate.split("+")
                ok = gate_on(i-1, g1, v) and gate_on(i-1, g2, v)
            elif "|" in gate:
                g1, g2 = gate.split("|")
                ok = gate_on(i-1, g1, v) or gate_on(i-1, g2, v)
            else:
                ok = gate_on(i-1, gate, v)
            if not ok: L = 0.0
            w_t = L / 2.0                      # QLD is 2x
        # band is pp of NAV; w is a fraction of the sleeve, sleeve = SLEEVE_NAV of NAV
        if abs(w_t - w_held) * SLEEVE_NAV * 100 > band:
            turn_total += abs(w_t - w_held); nreb += 1
            cost = abs(w_t - w_held) * cost_bps / 10000.0
            w_held = w_t
        else:
            cost = 0.0
        d0, d1 = DATES[i-1], DATES[i]
        rq = QLD[d1]/QLD[d0] - 1
        DA = DEF[defensive]
        rb = (DA[d1]/DA[d0] - 1) if (d0 in DA and d1 in DA) else (
             (BIL[d1]/BIL[d0] - 1) if (d0 in BIL and d1 in BIL) else 0.00008)
        ret = w_held*rq + max(0.0, 1.0-w_held)*rb - cost
        eq.append(eq[-1]*(1+ret)); expo.append(w_held)
    r = [eq[i]/eq[i-1]-1 for i in range(1, len(eq))]
    n = len(r); yrs = n/ANN
    cagr = eq[-1]**(1/yrs)-1
    mu = sum(r)/n; sd = math.sqrt(sum((x-mu)**2 for x in r)/(n-1)); vol = sd*math.sqrt(ANN)
    pk = eq[0]; mdd = 0
    for x in eq: pk = max(pk, x); mdd = min(mdd, x/pk-1)
    dn = [x for x in r if x < 0]
    dsd = math.sqrt(sum(x*x for x in dn)/len(dn))*math.sqrt(ANN) if dn else 0
    return dict(cagr=cagr, vol=vol, sharpe=cagr/vol if vol else 0, sortino=cagr/dsd if dsd else 0,
                mdd=mdd, mar=cagr/abs(mdd) if mdd else 0, eq=eq, expo=sum(expo)/len(expo),
                reb=nreb, turn=turn_total, yrs=yrs)

def rolling(eq, years):
    w = int(years*ANN)
    if len(eq) <= w: return None
    out = [(eq[i+w]/eq[i])**(1/years)-1 for i in range(0, len(eq)-w, 21)]
    return min(out), sorted(out)[len(out)//2], max(out), sum(1 for x in out if x < 0)/len(out)

HDR = f"{'config':<34}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>8}{'MAR':>7}{'expo':>7}{'reb/yr':>8}"
def fmt(m, lab):
    if not m: return f"{lab:<34} n/a"
    return (f"{lab:<34}{m['cagr']*100:>7.1f}%{m['vol']*100:>6.1f}%{m['sharpe']:>8.2f}"
            f"{m['mdd']*100:>7.1f}%{m['mar']:>7.2f}{m['expo']*100:>6.0f}%{m['reb']/m['yrs']:>8.1f}")
