#!/usr/bin/env python3
"""
v3_engine.py — Portfolio Playbook v3 target calculator.

Single source of truth for every number the daily/weekly watcher needs.
NOTHING here is computed by the model at run time: indicators, leverage,
targets and drift are all produced by this script and consumed as data.

Spec: 03-strategies/trend-following/Portfolio Playbook v3 (2026-08-25).md

    ./v3_engine.py                 # human table
    ./v3_engine.py --json          # machine readable
    ./v3_engine.py --nav 250000    # override NAV (default: live from IBKR)

Exit codes: 0 ok · 2 stale/missing data · 3 IBKR connection failure
"""
import argparse, json, math, sys, datetime as dt
from zoneinfo import ZoneInfo
from collections import defaultdict

ANN = 252

# ---- v3 locked parameters -------------------------------------------------
CORE = dict(symbol="QLD", signal="QQQ", vol_target=0.30, win=32, cap=2.0,
            band_pp=4.0, alloc=0.45)
SLEEVE = dict(symbols=["AIS", "AIPO"], vol_target=0.20, win=32, cap=1.0,
              band_pp=8.0, alloc=0.20)
BALLAST = dict(symbol="BRK B", alloc=0.15, band_pp=5.0)
CASH = dict(symbol="SGOV", alloc=0.20)
GATE_VOL_FLOOR = 0.20      # gate only bites when realised vol also exceeds this
GATE_MONTHS = 10

# Everything the playbook actually manages. Anything else held in the accounts is
# LEGACY: it is real money and belongs in NAV for reporting, but the strategy can
# neither size into it nor spend it, so it must NOT inflate the base that targets
# are computed from. Counting it for sizing while refusing it for funding is what
# deadlocked every run from 2026-08-29 (TFSA short $6,038 against $36k of frozen
# AGQ/CEG). Targets are computed on INVESTABLE nav = nav - legacy.
PLAYBOOK_SYMS = {"QLD", "AIS", "AIPO", "BRK B", "BRKB", "SGOV"}

def last_completed_session(now=None):
    """
    Most recent weekday whose 16:00 ET close has passed.

    IBKR returns a PARTIAL bar for a session in progress. Using it silently poisons
    every downstream number — realised vol, leverage, target shares — because half a
    day of range is treated as a full day. Observed 2026-08-26: an in-progress bar
    moved L 1.378 -> 1.421 and the QLD target 866 -> 896 shares. Holidays are not
    enumerated; a missing bar just means the newest real bar is older, which the
    staleness guard already covers.
    """
    et = now or dt.datetime.now(ZoneInfo("America/New_York"))
    d = et.date()
    if et.weekday() >= 5 or et.hour < 16 or (et.hour == 16 and et.minute < 15):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d

def drop_incomplete(px, cutoff):
    """Remove bars dated after the last completed session."""
    dropped = {}
    for sym, series in px.items():
        bad = [d for d in series if dt.date.fromisoformat(d) > cutoff]
        for d in bad:
            dropped.setdefault(sym, []).append(d); del series[d]
    return dropped

def wilder_vol(closes, win):
    """Annualised realised vol of log returns over the trailing `win` sessions."""
    if len(closes) < win + 1: return None
    r = [math.log(closes[i]/closes[i-1]) for i in range(len(closes)-win, len(closes))]
    mu = sum(r)/len(r)
    sd = math.sqrt(sum((x-mu)**2 for x in r)/(len(r)-1))
    return sd*math.sqrt(ANN)

def monthly_closes(dates, closes):
    last = {}
    for d, c in zip(dates, closes): last[d[:7]] = c
    return [last[m] for m in sorted(last)], sorted(last)

def regime_on(dates, closes, vol_now):
    """v3 gate: defensive only if LAST COMPLETED month closed below its 10-mo SMA
    AND realised vol > floor. Returns (on, detail) — no look-ahead."""
    mc, months = monthly_closes(dates, closes)
    if len(mc) < GATE_MONTHS + 1:
        return True, f"warm-up: {len(mc)}/{GATE_MONTHS+1} monthly closes — gate not armed"
    prev_close = mc[-2]                       # last COMPLETED month
    sma = sum(mc[-(GATE_MONTHS+1):-1])/GATE_MONTHS
    below = prev_close < sma
    hot = (vol_now or 0) > GATE_VOL_FLOOR
    on = not (below and hot)
    return on, (f"{months[-2]} close {prev_close:.2f} vs 10mo SMA {sma:.2f} "
                f"({'below' if below else 'above'}), vol {(vol_now or 0)*100:.1f}% "
                f"{'>' if hot else '<='} {GATE_VOL_FLOOR*100:.0f}% -> {'RISK-ON' if on else 'DEFENSIVE'}")

def blend_series(series_map, syms, weights=None):
    """Equal-weight (or given weight) daily-rebalanced blend -> synthetic level series."""
    weights = weights or [1/len(syms)]*len(syms)
    common = sorted(set.intersection(*[set(series_map[s]) for s in syms]))
    lvl, out, dates = 1.0, [], []
    for i in range(1, len(common)):
        r = sum(w*(series_map[s][common[i]]/series_map[s][common[i-1]] - 1)
                for s, w in zip(syms, weights))
        lvl *= (1+r); out.append(lvl); dates.append(common[i])
    return dates, out

def fetch(ib, symbols, duration="3 Y"):
    from ib_async import Stock
    out = {}
    for s in symbols:
        c = Stock(s, "SMART", "USD")
        q = ib.qualifyContracts(c)
        if not q: raise RuntimeError(f"cannot qualify {s}")
        bars = ib.reqHistoricalData(q[0], "", duration, "1 day", "ADJUSTED_LAST", True, 1)
        if not bars: raise RuntimeError(f"no bars for {s}")
        out[s] = {b.date.isoformat()[:10]: b.close for b in bars if b.close}
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--nav", type=float, default=None)
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=4001)
    ap.add_argument("--client-id", type=int, default=51)
    ap.add_argument("--max-stale-days", type=int, default=5)
    ap.add_argument("--establish", action="store_true",
                    help="initial build-out: ignore rebalance bands, action every gap")
    a = ap.parse_args()

    try:
        from ib_async import IB
        ib = IB(); ib.connect(a.host, a.port, clientId=a.client_id, timeout=30)
    except Exception as e:
        print(f"IBKR connect failed: {e}", file=sys.stderr); sys.exit(3)

    try:
        syms = ([CORE["signal"], CORE["symbol"]] + SLEEVE["symbols"]
                + [BALLAST["symbol"], CASH["symbol"]])
        px = fetch(ib, syms)

        # --- in-progress session guard (runs BEFORE staleness) --------------
        cutoff = last_completed_session()
        dropped = drop_incomplete(px, cutoff)
        for sym, series in px.items():
            if not series:
                print(f"no completed bars for {sym} on/before {cutoff}", file=sys.stderr)
                sys.exit(2)

        # --- staleness guard ------------------------------------------------
        today = dt.date.today(); stale = {}
        for s, d in px.items():
            last = max(d); age = (today - dt.date.fromisoformat(last)).days
            if age > a.max_stale_days: stale[s] = f"{last} ({age}d old)"
        if stale:
            print(f"STALE DATA: {stale}", file=sys.stderr); sys.exit(2)

        # --- NAV + positions ------------------------------------------------
        nav = a.nav
        pos = defaultdict(float)
        per_acct = defaultdict(lambda: defaultdict(float))
        for p in ib.positions():
            pos[p.contract.symbol] += p.position
            per_acct[p.account][p.contract.symbol] += p.position
        cash, avail = {}, {}
        if nav is None or True:
            tot = 0.0
            for acct in ib.managedAccounts():
                # F… is the FA master (aggregates children -> would double-count);
                # U27464927 is a pending application that reports nothing.
                if acct.startswith("F"): continue
                for v in ib.accountValues(acct):
                    if v.currency != "USD": continue
                    if v.tag == "NetLiquidation": tot += float(v.value)
                    elif v.tag == "TotalCashValue": cash[acct] = float(v.value)
                    # AvailableFunds is what IBKR actually checks an order against.
                    # In the Margin account it is $51,095 while TotalCashValue reads
                    # $210 — funding off cash there sold SGOV to buy things the
                    # account could already afford. In a registered account the two
                    # are equal, so this is strictly more accurate everywhere.
                    elif v.tag == "AvailableFunds": avail[acct] = float(v.value)
            if nav is None: nav = tot
        if not nav or nav <= 0:
            print("could not determine NAV", file=sys.stderr); sys.exit(2)

        # --- legacy (non-playbook) holdings -> investable NAV ----------------
        # Priced here rather than assumed: an unpriced legacy holding would silently
        # collapse investable NAV back onto total NAV and re-create the sizing bug,
        # so a pricing failure is fatal. Fail closed, never mis-size.
        legacy_syms = sorted({s for s in pos if s not in PLAYBOOK_SYMS and abs(pos[s]) > 0})
        if legacy_syms:
            try:
                lpx = fetch(ib, legacy_syms, duration="10 D")
            except Exception as e:
                print(f"cannot price legacy holding(s) {legacy_syms}: {e} — "
                      f"investable NAV unknown, refusing to size", file=sys.stderr)
                sys.exit(2)
            px.update(lpx)
        legacy, legacy_val = {}, 0.0
        for s in legacy_syms:
            p_ = px[s][max(px[s])]
            v_ = pos[s]*p_
            legacy_val += v_
            legacy[s] = dict(qty=pos[s], price=p_, value=round(v_, 2),
                             accounts=[a for a, d in per_acct.items() if d.get(s)])
        inav = nav - legacy_val
        if inav <= 0:
            print(f"investable NAV <= 0 (nav ${nav:,.0f} - legacy ${legacy_val:,.0f})",
                  file=sys.stderr); sys.exit(2)

        out = {"asof": max(px[CORE["signal"]]),
               "last_completed_session": cutoff.isoformat(),
               "dropped_incomplete": dropped,
               "nav": round(nav, 2),
               "investable_nav": round(inav, 2),
               "legacy_value": round(legacy_val, 2),
               "legacy": legacy,
               "cash_by_account": {k: round(v, 2) for k, v in cash.items()},
               # what an order can actually be placed against, per account
               "available_by_account": {k: round(avail.get(k, cash.get(k, 0.0)), 2)
                                        for k in set(cash) | set(avail)},
               "positions_by_account": {a: dict(d) for a, d in per_acct.items()},
               # last close for EVERY held/traded symbol, legacy included — lets the
               # executor flag resting limits that sit far from market (it previously
               # had no price for legacy symbols, so the stale-limit warning was dead
               # code for exactly the orders most likely to be stale).
               "prices": {s: px[s][max(px[s])] for s in px},
               "sgov_price": px[CASH["symbol"]][max(px[CASH["symbol"]])],
               "buckets": {}}

        # --- CORE -----------------------------------------------------------
        sig = px[CORE["signal"]]; sd = sorted(sig); sc = [sig[d] for d in sd]
        v = wilder_vol(sc, CORE["win"])
        on, detail = regime_on(sd, sc, v)
        L = 0.0 if not on else min(CORE["cap"], CORE["vol_target"]/v)
        tgt_pct = (L/2)*CORE["alloc"]
        last_qld = px[CORE["symbol"]][max(px[CORE["symbol"]])]
        tgt_val = inav*tgt_pct; tgt_sh = int(round(tgt_val/last_qld))
        cur_sh = pos.get(CORE["symbol"], 0.0); cur_val = cur_sh*last_qld
        drift = (cur_val-tgt_val)/inav*100
        out["buckets"]["core"] = dict(
            symbol=CORE["symbol"], vol=round(v,4), leverage=round(L,3), gate_on=on,
            gate_detail=detail, target_pct_nav=round(tgt_pct*100,2),
            target_value=round(tgt_val,2), target_shares=tgt_sh, price=last_qld,
            current_shares=cur_sh, current_value=round(cur_val,2),
            drift_pp=round(drift,2), band_pp=CORE["band_pp"],
            drift_basis="pp of NAV",
            action="REBALANCE" if (a.establish or abs(drift) > CORE["band_pp"]) else "hold")

        # --- SLEEVE (gate per-fund during warm-up) --------------------------
        bd, bl = blend_series(px, SLEEVE["symbols"])
        sv = wilder_vol(bl, SLEEVE["win"])
        gates = {}
        for s in SLEEVE["symbols"]:
            ds = sorted(px[s]); cs = [px[s][d] for d in ds]
            gates[s] = regime_on(ds, cs, wilder_vol(cs, SLEEVE["win"]))
        sleeve_on = all(g[0] for g in gates.values())
        sL = 0.0 if not sleeve_on else min(SLEEVE["cap"], SLEEVE["vol_target"]/sv)
        s_alloc = inav*SLEEVE["alloc"]; s_inv = s_alloc*sL
        legs = {}
        for s in SLEEVE["symbols"]:
            p = px[s][max(px[s])]; tv = s_inv/len(SLEEVE["symbols"])
            cs_ = pos.get(s, 0.0)
            legs[s] = dict(price=p, target_value=round(tv,2), target_shares=int(round(tv/p)),
                           current_shares=cs_, current_value=round(cs_*p,2))
        cur_s_val = sum(l["current_value"] for l in legs.values())
        # band is expressed in pp of the SLEEVE allocation (matches the backtest),
        # so drift must be measured against s_alloc — not against NAV.
        s_drift = ((cur_s_val-s_inv)/s_alloc*100) if s_alloc else 0.0
        out["buckets"]["sleeve"] = dict(
            symbols=SLEEVE["symbols"], blend_vol=round(sv,4), leverage=round(sL,3),
            gate_on=sleeve_on, gate_detail={k: v2[1] for k, v2 in gates.items()},
            allocation=round(s_alloc,2), target_invested=round(s_inv,2),
            target_cash=round(s_alloc-s_inv,2), legs=legs,
            current_value=round(cur_s_val,2), drift_pp=round(s_drift,2),
            band_pp=SLEEVE["band_pp"],
            drift_basis="pp of sleeve allocation",
            action="REBALANCE" if (a.establish or abs(s_drift) > SLEEVE["band_pp"]) else "hold")

        # --- BALLAST --------------------------------------------------------
        bsym = BALLAST["symbol"]; bp = px[bsym][max(px[bsym])]
        btv = inav*BALLAST["alloc"]; bcs = pos.get(bsym.replace(" ", ""), pos.get(bsym, 0.0))
        bdrift = (bcs*bp-btv)/inav*100
        out["buckets"]["ballast"] = dict(
            symbol=bsym, price=bp, target_pct_nav=BALLAST["alloc"]*100,
            target_value=round(btv,2), target_shares=int(round(btv/bp)),
            current_shares=bcs, current_value=round(bcs*bp,2), drift_pp=round(bdrift,2),
            band_pp=BALLAST["band_pp"],
            drift_basis="pp of NAV",
            action="REBALANCE" if (a.establish or abs(bdrift) > BALLAST["band_pp"]) else "hold")

        out["buckets"]["cash"] = dict(
            symbol=CASH["symbol"], target_pct_nav=CASH["alloc"]*100,
            target_value=round(inav*CASH["alloc"],2),
            plus_engine_cash=round(inav*CORE["alloc"]-tgt_val + s_alloc-s_inv, 2))
    finally:
        try: ib.disconnect()
        except Exception: pass

    if a.json:
        print(json.dumps(out, indent=2)); return
    b = out["buckets"]
    if out.get("dropped_incomplete"):
        n = sum(len(v) for v in out["dropped_incomplete"].values())
        print(f"  [dropped {n} in-progress bar(s) after {out['last_completed_session']}]")
    if out.get("legacy"):
        print(f"  LEGACY (not managed, excluded from the sizing base): "
              f"${out['legacy_value']:,.0f} = "
              + ", ".join(f"{k} {v['qty']:.0f}@${v['price']:.2f}"
                          for k, v in out["legacy"].items()))
    print(f"PORTFOLIO PLAYBOOK v3 — targets as of {out['asof']}   "
          f"investable ${out['investable_nav']:,.0f} of NAV ${out['nav']:,.0f}"
          + ("   [--establish: bands ignored]" if a.establish else "") + "\n")
    c = b["core"]
    print(f"CORE   {c['symbol']}  vol32 {c['vol']*100:.2f}%  L={c['leverage']:.3f}  gate {'ON' if c['gate_on'] else 'DEFENSIVE'}")
    print(f"       {c['gate_detail']}")
    print(f"       target {c['target_pct_nav']:.2f}% NAV = ${c['target_value']:,.0f} = {c['target_shares']} sh @ ${c['price']:.2f}")
    print(f"       holding {c['current_shares']:.0f} sh = ${c['current_value']:,.0f}   drift {c['drift_pp']:+.2f}pp (band ±{c['band_pp']:.0f}) -> {c['action']}\n")
    s = b["sleeve"]
    print(f"SLEEVE {'+'.join(s['symbols'])}  blend vol32 {s['blend_vol']*100:.2f}%  L={s['leverage']:.3f}  gate {'ON' if s['gate_on'] else 'DEFENSIVE'}")
    for k, v2 in s["gate_detail"].items(): print(f"       {k}: {v2}")
    print(f"       allocation ${s['allocation']:,.0f} -> invest ${s['target_invested']:,.0f}, SGOV ${s['target_cash']:,.0f}")
    for k, l in s["legs"].items():
        print(f"         {k:<5} target ${l['target_value']:,.0f} = {l['target_shares']} sh @ ${l['price']:.2f}   holding {l['current_shares']:.0f} sh")
    print(f"       drift {s['drift_pp']:+.2f}pp of sleeve (band ±{s['band_pp']:.0f}) -> {s['action']}\n")
    x = b["ballast"]
    print(f"BALLAST {x['symbol']}  target {x['target_pct_nav']:.0f}% = ${x['target_value']:,.0f} = {x['target_shares']} sh @ ${x['price']:.2f}")
    print(f"       holding {x['current_shares']:.0f} sh = ${x['current_value']:,.0f}   drift {x['drift_pp']:+.2f}pp (band ±{x['band_pp']:.0f}) -> {x['action']}\n")
    z = b["cash"]
    print(f"CASH   {z['symbol']}  explicit {z['target_pct_nav']:.0f}% = ${z['target_value']:,.0f}   + engine-held ${z['plus_engine_cash']:,.0f}")

if __name__ == "__main__":
    main()
