"""
AI-Infra Tactical Trend — backtest engine (v3 development)
==========================================================
Deterministic, dependency-free (stdlib only) trade-level simulator.

Contract:
  * Daily OHLC bars, IBKR TRADES, split-adjusted, NOT dividend-adjusted.
  * All signals evaluated on EVERY daily close (never on "run days").
  * Signal on close t  ->  fill at open of t+1  (except B2, a resting intraday stop).
  * Trade-level study (v2 Part D method): each trade is one unit of RISK, not one
    unit of capital, so results are comparable across names of different volatility.

Primary metric is the R-multiple:  R = (exit - entry) / (m1 * ATR14_at_entry)
i.e. profit expressed in units of the initial trail distance. Expectancy in R and
payoff in R are the "risk-reward ratio" the sleeve is judged on.
"""
import json, os, datetime as dt

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# --- Listing-integrity overrides -------------------------------------------------
# Mechanical rule: a >45% overnight jump (open vs prior close) marks a split /
# merger / ticker-reuse discontinuity; the usable window starts AFTER the last one.
# Explicit overrides encode known corporate events the jump-screen cannot see.
VALID_START = {
    "NBIS": "2024-10-21",   # Nebius relisting; pre-date bars are stitched Yandex (YNDX)
    "BTDR": "2023-04-17",   # Bitdeer SPAC completion
    "WULF": "2021-06-28",   # TeraWulf merger
    "TE":   "2025-01-06",   # T1 Energy, ex-FREYR ticker change
    "APLD": "2021-02-01",   # Applied Blockchain -> Applied Digital
}
EXCLUDE = {"SHAZ"}          # +3145% artifact 2025-01-29; series unusable
JUMP_TOL = 0.80   # >80% overnight = corporate action; real high-vol gaps (NBIS +51.7% on the
                  # 2025-09-08 Microsoft deal, BE +57.8% on the 2024-11-15 AEP deal) must survive

# --- Data ------------------------------------------------------------------------
def load(sym):
    raw = open(os.path.join(DATA, f"{sym}.json")).read()
    d = json.loads(raw[raw.index("{"):])
    b = [dict(d=str(x["date"])[:10], o=x["open"], h=x["high"], l=x["low"], c=x["close"])
         for x in d["rows"]]
    b = [x for x in b if all(x[k] and x[k] > 0 for k in ("o", "h", "l", "c"))]
    # auto-trim after last discontinuity
    cut = 0
    for i in range(1, len(b)):
        if abs(b[i]["o"] / b[i-1]["c"] - 1) > JUMP_TOL:
            cut = i
    vs = VALID_START.get(sym)
    if vs:
        cut = max(cut, next((i for i, x in enumerate(b) if x["d"] >= vs), 0))
    return b[cut:]

def indicators(b):
    """Wilder ATR14; SMA20/50/200; rolling closing-high. Mutates and returns b."""
    for i, x in enumerate(b):
        tr = (x["h"] - x["l"]) if i == 0 else max(
            x["h"] - x["l"], abs(x["h"] - b[i-1]["c"]), abs(x["l"] - b[i-1]["c"]))
        x["tr"] = tr
    atr = None
    for i, x in enumerate(b):
        if i == 13:   atr = sum(y["tr"] for y in b[:14]) / 14.0
        elif i > 13:  atr = (atr * 13 + x["tr"]) / 14.0
        x["atr"] = atr if i >= 13 else None
        for w in (20, 50, 200):
            x[f"sma{w}"] = (sum(y["c"] for y in b[i-w+1:i+1]) / w) if i >= w-1 else None
        x["hh60"] = max(y["c"] for y in b[max(0, i-59):i+1])
        x["mom60"] = (x["c"]/b[i-60]["c"] - 1) if i >= 60 else None
    for i, x in enumerate(b):
        x["sma50_up"]  = (x["sma50"]  > b[i-5]["sma50"])   if i >= 5  and x["sma50"]  and b[i-5]["sma50"]   else None
        x["sma200_up"] = (x["sma200"] > b[i-10]["sma200"]) if i >= 10 and x["sma200"] and b[i-10]["sma200"] else None
    return b

_CACHE = {}
def bars(sym):
    if sym not in _CACHE:
        _CACHE[sym] = indicators(load(sym))
    return _CACHE[sym]

# --- Strategy --------------------------------------------------------------------
DEFAULTS = dict(
    m1=3.0,          # B1 close-trail: CTH - m1*ATR
    m2=4.5,          # B2 resting catastrophe stop: CTH - m2*ATR
    b3="strict",     # off | strict | confirm2 | buffer | slope
    b3_buf=0.5,      # buffer mode: close < SMA50 - b3_buf*ATR
    shock=0.0,       # B4: exit if 1-day decline >= shock*ATR (0 = off)
    shock2=0.0,      # B4b: exit if 2-day decline >= shock2*ATR (0 = off)
    clear=0.0,       # C1+ entry clearance: (close-SMA50)/ATR >= clear
    ext_max=99.0,    # C2 hard extension ceiling in ATR (99 = off)
    reentry="v2",    # v2 | reclaim50
    n_cool=5,        # minimum closes in cooldown
    cost=0.0015,     # round-trip cost: commission + slippage on marketable open fills
    hh_tol=0.90,     # C1 higher-high structure: close >= hh_tol * 60d closing high
    gc=False,        # C1 require golden-cross regime (SMA50 > SMA200)
    mom=0.0,         # C1 require 60-day momentum >= mom (e.g. 0.10 = +10%)
)

def _gate(x, p):
    """C1 eligibility: clean uptrend + v3 entry-clearance guard."""
    if not (x["atr"] and x["sma50"] and x["sma200"] and x["sma50_up"] is not None):
        return False
    if not (x["c"] > x["sma50"] and x["sma50_up"]):        return False
    if not (x["c"] > x["sma200"] and x["sma200_up"]):      return False
    if not (x["c"] >= p["hh_tol"] * x["hh60"]):             return False   # higher-high structure
    if p["gc"] and not (x["sma50"] > x["sma200"]):          return False
    if p["mom"] and (x.get("mom60") is None or x["mom60"] < p["mom"]): return False
    ext = (x["c"] - x["sma50"]) / x["atr"]
    return p["clear"] <= ext <= p["ext_max"]

def simulate(sym, start, end, **kw):
    """Run the state machine. Returns list of closed trades."""
    p = dict(DEFAULTS); p.update(kw)
    b = bars(sym)
    idx = [i for i, x in enumerate(b) if start <= x["d"] <= end]
    if not idx: return []
    lo, hi = idx[0], idx[-1]

    trades, state, pos = [], "FLAT", None
    cool_until_high, cool_from = None, None
    for i in range(lo, hi + 1):
        x = b[i]
        if not x["atr"] or not x["sma200"]: continue

        if state == "LONG":
            pos["cth"] = max(pos["cth"], x["c"])
            pos["mfe"] = max(pos["mfe"], (x["h"] - pos["entry"]) / pos["D"])
            pos["mae"] = min(pos["mae"], (x["l"] - pos["entry"]) / pos["D"])
            b1 = pos["cth"] - p["m1"] * x["atr"]
            b2 = pos["cth"] - p["m2"] * x["atr"]
            if x["l"] <= b2:                      # resting stop, intraday
                trades.append(_close(pos, x["d"], b2, "B2", i, p["cost"])); state, cool_from = "COOL", i
                cool_until_high = pos["cth"]; pos = None; continue
            fire = []
            if x["c"] < b1: fire.append("B1")
            # B3 regime
            if p["b3"] != "off" and x["sma50"]:
                if   p["b3"] == "strict"   and x["c"] < x["sma50"]: fire.append("B3")
                elif p["b3"] == "buffer"   and x["c"] < x["sma50"] - p["b3_buf"] * x["atr"]: fire.append("B3")
                elif p["b3"] == "confirm2" and x["c"] < x["sma50"] and b[i-1]["c"] < (b[i-1]["sma50"] or 9e9): fire.append("B3")
                elif p["b3"] == "slope"    and x["sma50_up"] is False: fire.append("B3")
            # B4 shock (velocity, not level)
            if p["shock"] and (b[i-1]["c"] - x["c"]) >= p["shock"] * x["atr"]: fire.append("B4")
            if p["shock2"] and i >= 2 and (b[i-2]["c"] - x["c"]) >= p["shock2"] * x["atr"]: fire.append("B4b")
            if fire and i + 1 <= hi:
                trades.append(_close(pos, b[i+1]["d"], b[i+1]["o"], "+".join(fire), i+1, p["cost"]))
                state, cool_from, cool_until_high = "COOL", i, pos["cth"]; pos = None
                continue

        elif state in ("FLAT", "COOL"):
            ok = True
            if state == "COOL":
                nc = i - cool_from
                if p["reentry"] == "v2":
                    ok = (x["c"] > cool_until_high) or (nc >= p["n_cool"] and x["sma50_up"])
                else:  # reclaim50
                    ok = nc >= p["n_cool"] and x["c"] > x["sma50"] and x["sma200_up"]
            if ok and _gate(x, p) and i + 1 <= hi:
                e = b[i+1]["o"]
                pos = dict(sym=sym, sd=x["d"], ed=b[i+1]["d"], entry=e, i0=i+1,
                           D=p["m1"] * x["atr"], atr0=x["atr"], cth=e, mfe=0.0, mae=0.0,
                           ext0=(x["c"] - x["sma50"]) / x["atr"])
                state = "LONG"

    if state == "LONG" and pos:                    # mark open trade to window end
        trades.append(_close(pos, b[hi]["d"], b[hi]["c"], "OPEN", hi, p["cost"]))
    return trades

def _close(pos, d, px, rule, i, cost=0.0015):
    px = px * (1 - cost)          # charge full round-trip at the exit
    return dict(sym=pos["sym"], entry_d=pos["ed"], exit_d=d, entry=pos["entry"], exit=px,
                rule=rule, D=pos["D"], atr0=pos["atr0"], ext0=pos["ext0"],
                R=(px - pos["entry"]) / pos["D"], ret=(px / pos["entry"] - 1),
                bars=i - pos["i0"], mfe=pos["mfe"], mae=pos["mae"],
                giveback=(pos["cth"] - px) / pos["D"])

# --- Metrics ---------------------------------------------------------------------
def metrics(trades):
    t = [x for x in trades if x["rule"] != "OPEN"] or trades
    if not t: return None
    R = [x["R"] for x in t]
    w = [r for r in R if r > 0]; l = [r for r in R if r <= 0]
    aw = sum(w)/len(w) if w else 0.0
    al = abs(sum(l)/len(l)) if l else 0.0
    return dict(
        n=len(t), win=len(w)/len(t),
        avg_win_R=aw, avg_loss_R=al,
        payoff=(aw/al if al else float("inf")),
        exp_R=sum(R)/len(t), total_R=sum(R),
        pf=(sum(w)/abs(sum(l)) if l and sum(l) else float("inf")),
        avg_ret=sum(x["ret"] for x in t)/len(t),
        med_hold=sorted(x["bars"] for x in t)[len(t)//2],
        whipsaw=sum(1 for x in t if x["R"] < 0 and x["bars"] <= 10)/len(t),
        giveback=sorted(x["giveback"] for x in t)[len(t)//2],
    )

def fmt(m, label=""):
    if not m: return f"{label:<34} (no trades)"
    return (f"{label:<34}{m['n']:>4}{m['win']*100:>7.0f}%{m['avg_win_R']:>8.2f}"
            f"{m['avg_loss_R']:>8.2f}{m['payoff']:>8.2f}{m['exp_R']:>8.2f}"
            f"{m['total_R']:>9.1f}{m['pf']:>7.2f}{m['whipsaw']*100:>7.0f}%{m['med_hold']:>6}")

HDR = f"{'':<34}{'n':>4}{'win':>8}{'avgW_R':>7}{'avgL_R':>8}{'payoff':>8}{'expR':>8}{'totR':>9}{'PF':>7}{'whip':>8}{'hold':>6}"
