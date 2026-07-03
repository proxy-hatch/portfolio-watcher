#!/Users/shawn/workspace/portfolio-watcher/.venv/bin/python
"""Read-only market metrics for the Portfolio Watcher unattended runs.

Fetches daily bars from IB Gateway (READ clientId 50/51/52) and emits computed
indicators as JSON so the scheduled watcher's trigger math is DETERMINISTIC
rather than done by hand by the model.

THIS FILE CONTAINS NO ORDER CODE. It only reads historical bars and computes
indicators. (The watcher's read-only safety relies in part on this.)

Usage:
  metrics.py SYM [SYM ...] [--ref QQQ] [--duration "1 Y"] [--held]

  --held  ALSO price every currently-held stock (auto-discovered read-only via
          reqPositions), so NAV / sleeve math never falls back to estimating a
          legacy holding (e.g. BRK B / CEG / AGQ) from account GPV residuals.
          Held names get real `position` + `position_value` fields. The symbol
          list can go stale; positions can't — so prefer --held for the watcher.

Output (stdout): one JSON object:
  {"asof": <utc iso>, "ref": "QQQ", "duration": "1 Y",
   "symbols": {"QLD": {<metrics>, "position": .., "position_value": ..}|{"error": "..."}, ...}}
"""
import sys
import json
import math
import argparse
from datetime import datetime, timezone

import pandas as pd
import numpy as np
from ib_async import IB, Stock

# Listing exchange per symbol so SMART qualification is unambiguous.
# (Only used as a fallback when a symbol is passed explicitly and NOT auto-
# discovered via --held; held names carry their own qualified contract.)
PRIMARY = {
    "QLD": "ARCA", "QQQ": "NASDAQ", "SGOV": "ARCA", "TQQQ": "NASDAQ",
    "CAT": "NYSE", "MSFT": "NASDAQ", "NBIS": "NASDAQ", "BE": "NYSE",
    "CORZ": "NASDAQ", "SNDK": "NASDAQ",
    "BRK B": "NYSE", "CEG": "NASDAQ", "AGQ": "ARCA", "BRK.B": "NYSE",
}


def rnd(x, p=4):
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(xf) or math.isinf(xf):
        return None
    return round(xf, p)


def bars_to_df(bars):
    df = pd.DataFrame([
        {"date": b.date, "open": b.open, "high": b.high,
         "low": b.low, "close": b.close, "volume": b.volume}
        for b in bars
    ])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def wilder_atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    adx_s = dx.ewm(alpha=1 / n, adjust=False).mean()
    return adx_s, plus_di, minus_di


def metrics_for(df):
    c = df["close"]
    last = float(c.iloc[-1])

    def sma(n):
        return float(c.tail(n).mean()) if len(c) >= n else None

    high20 = float(df["high"].tail(20).max())
    high63 = float(df["high"].tail(63).max())
    high252 = float(df["high"].tail(252).max())
    sma50 = sma(50)

    hh = None
    if len(df) >= 20:
        hh = bool(df["high"].tail(10).max() > df["high"].iloc[-20:-10].max())

    atr_s = wilder_atr(df)
    adx_s, pdi, mdi = adx(df)

    logret = np.log(c / c.shift(1))
    rv20 = (float(logret.tail(20).std(ddof=1) * math.sqrt(252))
            if len(c) > 21 else None)

    # 10-month SMA on month-end closes (for the §1.2c vol-target gate)
    m = c.copy()
    m.index = df["date"]
    mclose = m.resample("ME").last().dropna()
    sma10mo = float(mclose.tail(10).mean()) if len(mclose) >= 10 else None
    monthly_close = float(mclose.iloc[-1]) if len(mclose) >= 1 else None

    return {
        "last_close": rnd(last),
        "last_date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "n_bars": int(len(df)),
        "sma20": rnd(sma(20)), "sma50": rnd(sma50), "sma200": rnd(sma(200)),
        "high_20d": rnd(high20), "high_3mo": rnd(high63), "high_1y": rnd(high252),
        "drawdown_from_3mo_high_pct": rnd((last / high63 - 1) * 100, 2),
        "drawdown_from_1y_high_pct": rnd((last / high252 - 1) * 100, 2),
        "pct_above_sma50": rnd((last / sma50 - 1) * 100, 2) if sma50 else None,
        "pct_below_20d_high": rnd((last / high20 - 1) * 100, 2),
        "higher_highs": hh,
        "atr14": rnd(float(atr_s.iloc[-1])),
        "adx14": rnd(float(adx_s.iloc[-1]), 2),
        "plus_di14": rnd(float(pdi.iloc[-1]), 2),
        "minus_di14": rnd(float(mdi.iloc[-1]), 2),
        "realized_vol_20d_annual_pct": rnd(rv20 * 100, 2) if rv20 is not None else None,
        "sma_10month": rnd(sma10mo),
        "latest_monthly_close": rnd(monthly_close),
    }


def beta_vs_ref(df_sym, df_ref, lookback=252):
    a = df_sym[["date", "close"]].rename(columns={"close": "s"})
    b = df_ref[["date", "close"]].rename(columns={"close": "r"})
    m = pd.merge(a, b, on="date", how="inner").tail(lookback + 1)
    if len(m) < 30:
        return None
    sr = np.log(m["s"] / m["s"].shift(1)).dropna()
    rr = np.log(m["r"] / m["r"].shift(1)).dropna()
    var = rr.var(ddof=1)
    if var == 0 or math.isnan(var):
        return None
    return rnd(float(np.cov(sr, rr, ddof=1)[0, 1] / var), 3)


def held_stock_positions(ib):
    """Read-only: aggregate held STK positions across all accounts.

    Returns ({symbol: qualified Contract}, {symbol: net qty}). No order code —
    reqPositions is a pure read, preserving this module's read-only guarantee.
    """
    contracts, qty = {}, {}
    for p in ib.reqPositions():
        c = p.contract
        if c.secType != "STK" or not p.position:
            continue
        qty[c.symbol] = qty.get(c.symbol, 0.0) + float(p.position)
        contracts.setdefault(c.symbol, c)
    return contracts, {s: q for s, q in qty.items() if q}


def fetch(ib, sym, duration, contract=None):
    if contract is None:
        primary = PRIMARY.get(sym)
        contract = (Stock(sym, "SMART", "USD", primaryExchange=primary)
                    if primary else Stock(sym, "SMART", "USD"))
    elif not contract.exchange:
        contract.exchange = "SMART"   # held contract carries conId + primaryExchange
    ib.qualifyContracts(contract)
    bars = ib.reqHistoricalData(
        contract, endDateTime="", durationStr=duration,
        barSizeSetting="1 day", whatToShow="TRADES",
        useRTH=True, formatDate=1,
    )
    return bars_to_df(bars)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--ref", default="QQQ")
    ap.add_argument("--duration", default="1 Y")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4001)
    ap.add_argument("--held", action="store_true",
                    help="also price every held stock (read-only reqPositions)")
    args = ap.parse_args()

    ib = IB()
    connected = False
    last_err = None
    for cid in (50, 51, 52):
        try:
            ib.connect(args.host, args.port, clientId=cid, timeout=20)
            connected = True
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
    if not connected:
        print(json.dumps({"error": f"connect failed: {last_err}"}))
        sys.exit(2)

    out = {
        "asof": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ref": args.ref,
        "duration": args.duration,
        "symbols": {},
    }
    held_contracts, held_qty = ({}, {})
    if args.held:
        try:
            held_contracts, held_qty = held_stock_positions(ib)
            out["held_symbols"] = sorted(held_qty)
        except Exception as e:  # noqa: BLE001
            out["held_error"] = str(e)

    wanted = list(dict.fromkeys(list(held_qty) + args.symbols + [args.ref]))
    dfs = {}
    try:
        for sym in wanted:
            try:
                df = fetch(ib, sym, args.duration, contract=held_contracts.get(sym))
                if df.empty:
                    out["symbols"][sym] = {"error": "no bars returned"}
                    continue
                dfs[sym] = df
                m = metrics_for(df)
                if sym in held_qty:
                    m["position"] = rnd(held_qty[sym], 2)
                    m["position_value"] = rnd(held_qty[sym] * m["last_close"], 2)
                out["symbols"][sym] = m
            except Exception as e:  # noqa: BLE001
                out["symbols"][sym] = {"error": str(e)}
        ref_df = dfs.get(args.ref)
        if ref_df is not None:
            for sym, df in dfs.items():
                if sym == args.ref:
                    out["symbols"][sym]["beta_vs_ref"] = 1.0
                else:
                    out["symbols"][sym]["beta_vs_ref"] = beta_vs_ref(df, ref_df)
    finally:
        ib.disconnect()

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
