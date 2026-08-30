"""
Testbench v3 — cross-sectional (relative) momentum + dual momentum.
Adds the family engine.py/bench2.py cannot express: strategies that RANK a
universe and hold only the leaders, which is where the documented long-only
equity edge lives (Jegadeesh-Titman; Antonacci dual momentum).
"""
import math, os, json, engine, bench2 as B

USE_ADJ = True
def _load(sym):
    d = "data_adj" if USE_ADJ and os.path.exists(
        os.path.join(os.path.dirname(engine.DATA), "data_adj", f"{sym}.json")) else "data"
    p = os.path.join(os.path.dirname(engine.DATA), d, f"{sym}.json")
    raw = open(p).read(); j = json.loads(raw[raw.index("{"):])
    return [dict(d=str(x["date"])[:10], o=x["open"], h=x["high"], l=x["low"], c=x["close"])
            for x in j["rows"] if x["close"] and x["close"] > 0], d

_C = {}
def bars(sym):
    if sym not in _C:
        b, src = _load(sym)
        cut = 0
        for i in range(1, len(b)):
            if abs(b[i]["o"]/b[i-1]["c"] - 1) > engine.JUMP_TOL: cut = i
        vs = engine.VALID_START.get(sym)
        if vs: cut = max(cut, next((i for i, x in enumerate(b) if x["d"] >= vs), 0))
        _C[sym] = (b[cut:], src)
    return _C[sym][0]

def source(sym):
    bars(sym); return _C[sym][1]

def xsmom(syms, start, end, lookback=252, skip=21, top_k=5, abs_filter=True,
          vol_target=0.15, max_leverage=1.0, cash_yield=0.02, cost_bps=10.0,
          rebal=21, vol_win=60):
    """
    Cross-sectional momentum:
      * rank by trailing `lookback` return, skipping the most recent `skip` days
        (the standard 12-1 construction; skipping avoids short-term reversal)
      * hold the top `top_k`, inverse-vol weighted
      * `abs_filter`: additionally require the name's own momentum > 0 (dual momentum)
      * rebalance every `rebal` sessions (21 = monthly)
    """
    data = {}
    for s in syms:
        b = bars(s)
        b = [x for x in b if start <= x["d"] <= end]
        if len(b) < lookback + 60: continue
        c = [x["c"] for x in b]
        data[s] = dict(dates=[x["d"] for x in b], c=c, vol=B.realised_vol(c, vol_win))
    if not data: return None
    idx = {s: {d: i for i, d in enumerate(v["dates"])} for s, v in data.items()}
    alld = sorted({d for v in data.values() for d in v["dates"]})

    # --- pass 1: unscaled unit-risk book (causal) ---
    base_w, base_r = [], []
    w = {}
    for k in range(1, len(alld)):
        d0, d1 = alld[k-1], alld[k]
        if (k-1) % rebal == 0:
            sc = []
            for s, v in data.items():
                i0 = idx[s].get(d0)
                if i0 is None or i0 < lookback + skip: continue
                m = v["c"][i0-skip] / v["c"][i0-skip-lookback] - 1
                if v["vol"][i0] and v["vol"][i0] > 0: sc.append((m, s))
            sc.sort(reverse=True)
            picks = [s for m, s in sc[:top_k] if (m > 0 or not abs_filter)]
            w = {s: 1.0 / data[s]["vol"][idx[s][d0]] for s in picks}
            risk = sum(abs(x) * data[s]["vol"][idx[s][d0]] for s, x in w.items())
            if risk > 0: w = {s: x / risk for s, x in w.items()}
        r = 0.0
        for s, x in w.items():
            i0, i1 = idx[s].get(d0), idx[s].get(d1)
            if i0 is None or i1 is None: continue
            r += x * (data[s]["c"][i1] / data[s]["c"][i0] - 1)
        base_w.append(dict(w)); base_r.append(r)

    # --- pass 2: vol-target the book (may hold cash), cap leverage ---
    equity = [1.0]; wprev = {}; gross = []; nheld = []; pv_win = 60
    for k in range(1, len(alld)):
        j = k - 1
        if j >= pv_win:
            hist = base_r[j-pv_win:j]
            mu = sum(hist)/len(hist)
            sd = math.sqrt(sum((x-mu)**2 for x in hist)/(len(hist)-1))
            pv = sd * math.sqrt(B.ANN)
            lev = (vol_target / pv) if pv > 1e-9 else 0.0
        else:
            lev = 0.0
        wl = {s: x * lev for s, x in base_w[j].items()}
        g = sum(abs(x) for x in wl.values())
        if g > max_leverage and g > 0: wl = {s: x * max_leverage / g for s, x in wl.items()}
        ret = base_r[j] * min(lev, (max_leverage / g * lev) if g > max_leverage else lev)
        d0, d1 = alld[k-1], alld[k]
        ret = 0.0
        for s, x in wl.items():
            i0, i1 = idx[s].get(d0), idx[s].get(d1)
            if i0 is None or i1 is None: continue
            ret += x * (data[s]["c"][i1] / data[s]["c"][i0] - 1)
        cw = max(0.0, 1.0 - sum(abs(x) for x in wl.values()))
        ret += cw * cash_yield / B.ANN
        turn = sum(abs(wl.get(s, 0) - wprev.get(s, 0)) for s in set(wl) | set(wprev))
        ret -= turn * cost_bps / 10000.0
        equity.append(equity[-1] * (1 + ret)); wprev = dict(wl)
        gross.append(sum(abs(x) for x in wl.values())); nheld.append(len(wl))
    return dict(dates=alld, equity=equity, gross=gross, want_lev=0,
                avg_held=sum(nheld)/len(nheld) if nheld else 0)

def buyhold(syms, start, end, **kw):
    return xsmom(syms, start, end, top_k=len(syms), abs_filter=False, **kw)


_IND = {}
def bars_ind(sym):
    """Adjusted bars WITH engine indicators attached (ATR/SMA/slopes)."""
    if sym not in _IND:
        _IND[sym] = engine.indicators([dict(x) for x in bars(sym)])
    return _IND[sym]
