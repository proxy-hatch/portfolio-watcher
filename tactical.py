# tactical.py — v2 tactical-trend signals (validated 2026-06-26). Pure functions.
def entry_gate(close, sma50, sma200, higher_highs):
    return bool(close > sma50 and close > sma200 and higher_highs)

def extension_pct(close, sma50):
    return close / sma50 - 1.0

def dampened_fraction(ext, lo=0.12, hi=0.52, floor=0.10):
    if ext <= lo:
        return 1.0
    if ext >= hi:
        return floor
    return 1.0 - (1.0 - floor) * (ext - lo) / (hi - lo)

def risk_budget_shares(nav, atr14, price, R=0.0085, atr_mult=3.0, pos_cap_frac=0.06):
    stop_dist = atr_mult * atr14
    if stop_dist <= 0 or price <= 0:
        return 0
    shares = (R * nav) / stop_dist
    cap_shares = (pos_cap_frac * nav) / price            # per-name notional cap
    return int(min(shares, cap_shares))

def b1_trail_level(highest_close_since_entry, atr14, atr_mult=3.0):
    return highest_close_since_entry - atr_mult * atr14

def b3_regime_break(close, sma50):
    return bool(close < sma50)

def b2_catastrophe_level(recent_close, atr14, atr_mult=3.0, floor_mult=1.5):
    return recent_close - floor_mult * atr_mult * atr14

def cooldown_ok(close, prior_peak, bars_since_exit, sma50_now, sma50_prev, n=5):
    if close > prior_peak:
        return True
    return bool(bars_since_exit >= n and sma50_now > sma50_prev)


def _atr14(highs, lows, closes):
    import numpy as np
    h, l, c = np.array(highs, float), np.array(lows, float), np.array(closes, float)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = tr[0]
    for x in tr[1:]:
        atr = atr + (x - atr) / 14.0     # Wilder
    return float(atr)

def levels_from_bars(closes, highs, lows, entry_date_idx, atr_mult=3.0):
    peak = max(closes[entry_date_idx:])
    atr = _atr14(highs, lows, closes)
    return {
        "highest_close_since_entry": peak,
        "atr14": atr,
        "b1_trail": b1_trail_level(peak, atr, atr_mult),
        "b2_floor": b2_catastrophe_level(closes[-1], atr, atr_mult),
        "regime_break_today": None,   # filled by caller with sma50
    }
