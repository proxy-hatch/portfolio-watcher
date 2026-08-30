"""
Testbench v2 — PORTFOLIO-level simulator.
=========================================
Testbench v1 (engine.py) is trade-level: it answers "is this trade rule good?".
It cannot answer "is this a business?" because it ignores correlation, capital
allocation, portfolio vol, and drawdown. This does.

Design
------
* Signal functions return a TARGET WEIGHT per symbol per day in [-1, 1]
  (long-only variants clamp at 0). Continuous signals are supported, so
  strategies that scale position with conviction are first-class.
* Position sizing: inverse-vol (risk parity) -> each name targets the same
  risk contribution -> portfolio scaled to a target annualised volatility.
* Portfolio vol targeting uses a trailing covariance-free estimate
  (portfolio vol from the realised series of the target portfolio), capped
  by a leverage limit, which is what a cash equity account can actually do.
* Costs charged on turnover.
"""
import json, os, math
import engine

DATA = engine.DATA
ANN = 252

# ---------- price panel ----------
def panel(syms, start, end):
    """Aligned close panel: {date: {sym: close}} plus sorted date list."""
    px = {}
    for s in syms:
        try: b = engine.bars(s)
        except Exception: continue
        for x in b:
            if start <= x["d"] <= end:
                px.setdefault(x["d"], {})[s] = x["c"]
    dates = sorted(px)
    return dates, px

def series(sym, start, end):
    try:
        import bench3
        b = bench3.bars_ind(sym)
    except Exception:
        try: b = engine.bars(sym)
        except Exception: return [], []
    b = [x for x in b if start <= x["d"] <= end]
    return [x["d"] for x in b], b

# ---------- indicator helpers on a close series ----------
def ewma(vals, span):
    a = 2.0 / (span + 1.0); out = []; m = None
    for v in vals:
        m = v if m is None else a * v + (1 - a) * m
        out.append(m)
    return out

def realised_vol(closes, win=32):
    """Annualised vol of daily log returns, trailing `win`."""
    out = [None] * len(closes)
    r = [0.0] + [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
    for i in range(len(closes)):
        if i < win: continue
        w = r[i-win+1:i+1]
        mu = sum(w) / win
        sd = math.sqrt(sum((x-mu)**2 for x in w) / (win-1))
        out[i] = sd * math.sqrt(ANN)
    return out

# ---------- SIGNALS: each returns list of target weights aligned to bars ----------
def sig_tsmom(b, lookback=252, **kw):
    """Moskowitz/Ooi/Pedersen: sign of trailing excess return. Binary, no stops."""
    c = [x["c"] for x in b]
    lo = kw.get("long_only", True)
    return [None if i < lookback else (1.0 if c[i] > c[i-lookback] else (0.0 if lo else -1.0))
            for i in range(len(c))]

def sig_ewmac(b, fast=16, slow=64, cap=2.0, **kw):
    """Carver EWMAC: continuous, vol-normalised crossover forecast, scaled to [0,1]."""
    c = [x["c"] for x in b]
    f, s = ewma(c, fast), ewma(c, slow)
    vol = realised_vol(c, 32)
    out = []
    for i in range(len(c)):
        if vol[i] is None or not vol[i]:
            out.append(None); continue
        daily_px_vol = c[i] * vol[i] / math.sqrt(ANN)
        raw = (f[i] - s[i]) / daily_px_vol if daily_px_vol else 0.0
        fc = raw / 4.0
        fc = max(-cap, min(cap, fc))
        if kw.get("long_only", True): fc = max(0.0, fc)
        out.append(fc / cap)
    return out

def sig_donchian(b, entry=100, exit_=50, **kw):
    """Turtle-style breakout: long on N-day closing high, flat on M-day closing low."""
    c = [x["c"] for x in b]; out = []; pos = 0.0
    for i in range(len(c)):
        if i < entry: out.append(None); continue
        lo = kw.get("long_only", True)
        if c[i] >= max(c[i-entry+1:i+1]): pos = 1.0
        elif c[i] <= min(c[i-entry+1:i+1]) and not lo: pos = -1.0
        elif i >= exit_ and pos > 0 and c[i] <= min(c[i-exit_+1:i+1]): pos = 0.0
        elif i >= exit_ and pos < 0 and c[i] >= max(c[i-exit_+1:i+1]): pos = 0.0
        out.append(pos)
    return out

def sig_ma(b, fast=50, slow=200, **kw):
    """Classic dual-MA regime filter, binary."""
    c = [x["c"] for x in b]; out = []
    for i in range(len(c)):
        if i < slow: out.append(None); continue
        f = sum(c[i-fast+1:i+1])/fast; s = sum(c[i-slow+1:i+1])/slow
        lo = kw.get("long_only", True)
        out.append(1.0 if (c[i] > s and f > s) else (0.0 if lo else -1.0))
    return out

def sig_ensemble(b, **kw):
    """Average of three speeds — the standard CTA answer to speed uncertainty."""
    lo = kw.get("long_only", True)
    a = sig_donchian(b, 50, 25, long_only=lo); c_ = sig_donchian(b, 100, 50, long_only=lo); d = sig_donchian(b, 200, 100, long_only=lo)
    out = []
    for i in range(len(b)):
        v = [x for x in (a[i], c_[i], d[i]) if x is not None]
        out.append(sum(v)/3.0 if len(v) == 3 else None)
    return out

def sig_v3(b, **kw):
    """Current v3 spec as a weight series (binary in/out), for apples-to-apples."""
    p = dict(engine.DEFAULTS); p.update(dict(gc=True, hh_tol=0.95, clear=2.0,
                                             m1=3.5, m2=5.25, b3="buffer", b3_buf=0.5))
    out = [None]*len(b); state = 0; cth = None; cool_from = -999; cool_hi = None
    for i, x in enumerate(b):
        if not x["atr"] or not x["sma200"]: out[i] = None; continue
        if state:
            cth = max(cth, x["c"])
            if x["l"] <= cth - p["m2"]*x["atr"]: state = 0; cool_from = i; cool_hi = cth
            elif x["c"] < cth - p["m1"]*x["atr"] or x["c"] < x["sma50"] - p["b3_buf"]*x["atr"]:
                state = 0; cool_from = i; cool_hi = cth
        else:
            ok = True
            if cool_hi is not None:
                nc = i - cool_from
                ok = (x["c"] > cool_hi) or (nc >= p["n_cool"] and x["sma50_up"])
            if ok and engine._gate(x, p): state = 1; cth = x["c"]
        out[i] = float(state)
    return out

SIGNALS = {"v3 (current spec)": sig_v3, "TSMOM 12m": sig_tsmom, "EWMAC 16/64": sig_ewmac,
           "Donchian 100/50": sig_donchian, "MA 50/200": sig_ma, "Ensemble Donchian": sig_ensemble}

# ---------- portfolio simulation ----------
def simulate_portfolio(syms, start, end, signal, target_vol=0.15, max_leverage=1.0,
                       vol_win=32, cost_bps=10.0, cash_yield=0.02, allow_short=None,
                       pv_win=60, rebal=5, buffer=0.10, **kw):
    """
    Correct CTA-style construction:
      1. risk-parity base weights  w_i = sig_i / vol_i   (equal risk contribution)
      2. normalise to unit gross risk: sum_i |w_i| * vol_i = 1
      3. scale the WHOLE book so trailing realised portfolio vol == target_vol
         (this is where diversification turns into return: a well-diversified
          unit-risk book has low realised vol, so it gets levered UP)
      4. apply a hard leverage cap (cash account = 1.0, margin = 2.0+)
    Uninvested capital earns `cash_yield`. Costs charged on turnover.
    """
    if allow_short is None: allow_short = not kw.get("long_only", True)
    data = {}
    for s_ in syms:
        _, b = series(s_, start, end)
        if len(b) < 260: continue
        c = [x["c"] for x in b]
        data[s_] = dict(dates=[x["d"] for x in b], c=c,
                        sig=signal(b, **kw), vol=realised_vol(c, vol_win))
    if not data: return None
    alldates = sorted({d for v in data.values() for d in v["dates"]})
    idx = {s_: {d: i for i, d in enumerate(v["dates"])} for s_, v in data.items()}

    # --- pass 1: unscaled unit-risk portfolio return series (causal) ---
    base_w, base_r = [], []
    for k in range(1, len(alldates)):
        d0, d1 = alldates[k-1], alldates[k]
        w = {}
        for s_, v in data.items():
            i0 = idx[s_].get(d0)
            if i0 is None: continue
            sg, vl = v["sig"][i0], v["vol"][i0]
            if sg is None or not vl or vl <= 0: continue
            if sg > 0 or (allow_short and sg < 0): w[s_] = sg / vl
        risk = sum(abs(x) * data[s2]["vol"][idx[s2][d0]] for s2, x in w.items())
        if risk > 0: w = {s2: x / risk for s2, x in w.items()}
        r = 0.0
        for s2, x in w.items():
            i0, i1 = idx[s2].get(d0), idx[s2].get(d1)
            if i0 is None or i1 is None: continue
            r += x * (data[s2]["c"][i1] / data[s2]["c"][i0] - 1)
        base_w.append(w); base_r.append(r)

    # --- pass 2: vol-target, cap leverage, periodic rebalance with no-trade buffer ---
    equity = [1.0]; wprev = {}; dates_out = [alldates[0]]; gross = []; wants = []
    wlive = {}
    for k in range(1, len(alldates)):
        j = k - 1
        if j >= pv_win:
            hist = base_r[j-pv_win:j]
            mu = sum(hist)/len(hist)
            sd = math.sqrt(sum((x-mu)**2 for x in hist)/(len(hist)-1))
            pv = sd * math.sqrt(ANN)
            lev = (target_vol / pv) if pv > 1e-9 else 0.0
        else:
            lev = 0.0
        w_t = {s2: x * lev for s2, x in base_w[j].items()}
        want = sum(abs(x) for x in w_t.values())
        wants.append(want)
        if want > max_leverage and want > 0:
            w_t = {s2: x * max_leverage / want for s2, x in w_t.items()}
        # rebalance only every `rebal` sessions, and only names outside the buffer
        if j % rebal == 0 or not wlive:
            newlive = dict(wlive)
            for s2 in set(w_t) | set(wlive):
                tgt = w_t.get(s2, 0.0); cur = wlive.get(s2, 0.0)
                if abs(tgt - cur) > buffer * max(abs(tgt), 0.02):
                    if abs(tgt) < 1e-9: newlive.pop(s2, None)
                    else: newlive[s2] = tgt
            wlive = newlive
        ret = 0.0
        d0, d1 = alldates[k-1], alldates[k]
        for s2, x in wlive.items():
            i0, i1 = idx[s2].get(d0), idx[s2].get(d1)
            if i0 is None or i1 is None: continue
            ret += x * (data[s2]["c"][i1] / data[s2]["c"][i0] - 1)
        cash_w = max(0.0, 1.0 - sum(abs(x) for x in wlive.values()))
        ret += cash_w * cash_yield / ANN
        turn = sum(abs(wlive.get(s2, 0) - wprev.get(s2, 0)) for s2 in set(wlive) | set(wprev))
        ret -= turn * cost_bps / 10000.0
        equity.append(equity[-1] * (1 + ret)); wprev = dict(wlive)
        dates_out.append(d1); gross.append(sum(abs(x) for x in wlive.values()))
    return dict(dates=dates_out, equity=equity, gross=gross,
                want_lev=sum(wants)/len(wants) if wants else 0)


# ---------- metrics ----------
def perf(res):
    if not res or len(res["equity"]) < 60: return None
    e = res["equity"]
    r = [e[i]/e[i-1]-1 for i in range(1, len(e))]
    n = len(r); yrs = n / ANN
    cagr = e[-1]**(1/yrs) - 1 if yrs > 0 and e[-1] > 0 else -1
    mu = sum(r)/n
    sd = math.sqrt(sum((x-mu)**2 for x in r)/(n-1)) if n > 1 else 0
    vol = sd*math.sqrt(ANN)
    dn = [x for x in r if x < 0]
    dsd = math.sqrt(sum(x*x for x in dn)/len(dn))*math.sqrt(ANN) if dn else 0
    peak = e[0]; mdd = 0
    for v in e:
        peak = max(peak, v); mdd = min(mdd, v/peak - 1)
    return dict(cagr=cagr, vol=vol, sharpe=(cagr/vol if vol else 0),
                sortino=(cagr/dsd if dsd else 0), mdd=mdd,
                mar=(cagr/abs(mdd) if mdd else 0), yrs=yrs,
                gross=sum(res["gross"])/len(res["gross"]) if res["gross"] else 0,
                want=res.get("want_lev",0), final=e[-1])

PHDR = f"{'strategy':<22}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'Sortino':>8}{'maxDD':>8}{'MAR':>7}{'exposure':>9}{'wants':>7}"
def pfmt(m, label):
    if not m: return f"{label:<22}  (insufficient data)"
    return (f"{label:<22}{m['cagr']*100:>7.1f}%{m['vol']*100:>6.1f}%{m['sharpe']:>8.2f}"
            f"{m['sortino']:>8.2f}{m['mdd']*100:>7.1f}%{m['mar']:>7.2f}{m['gross']*100:>8.0f}%{m['want']:>7.1f}")
