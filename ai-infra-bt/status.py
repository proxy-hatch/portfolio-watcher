"""v3 live gate screen + risk-budgeted sizing. Reusable by the daily watcher."""
import sys, engine

V3 = dict(gc=True, hh_tol=0.95, clear=2.0, m1=3.5, m2=5.25, b3="buffer", b3_buf=0.5)
NAV = 247274.0        # override with argv[1]
R_PCT = 0.0085        # equal-risk budget per name (v2 Part A worked example)

def status(sym, nav=NAV):
    b = engine.bars(sym); x = b[-1]
    if not (x["atr"] and x["sma50"] and x["sma200"]): return None
    ext = (x["c"] - x["sma50"]) / x["atr"]
    chk = [("close>SMA50",      x["c"] > x["sma50"]),
           ("SMA50 rising",     bool(x["sma50_up"])),
           ("close>SMA200",     x["c"] > x["sma200"]),
           ("SMA200 rising",    bool(x["sma200_up"])),
           ("SMA50>SMA200",     x["sma50"] > x["sma200"]),
           (f"close>=95% 60d-hi", x["c"] >= V3["hh_tol"] * x["hh60"]),
           (f"clearance>=2.0ATR", ext >= V3["clear"])]
    fails = [n for n, ok in chk if not ok]
    D = V3["m1"] * x["atr"]
    return dict(sym=sym, d=x["d"], c=x["c"], atr=x["atr"], ext=ext, sma50=x["sma50"],
                sma200=x["sma200"], hh60=x["hh60"], fails=fails, D=D,
                shares=int(R_PCT * nav / D), notional=int(R_PCT*nav/D)*x["c"],
                b1=x["c"] - D, b2=x["c"] - V3["m2"] * x["atr"])

if __name__ == "__main__":
    nav = float(sys.argv[1]) if len(sys.argv) > 1 else NAV
    names = ["BE","NBIS","CORZ","SNDK","CRWV","IREN","APLD","RIOT","CLSK","BTDR",
             "HIVE","SEI","TE","PSIX","BW","PUMP","WYFI"]
    print(f"v3 GATE SCREEN — NAV ${nav:,.0f}, R={R_PCT*100:.2f}%/name, D=3.5xATR14\n")
    print(f"{'sym':<6}{'close':>9}{'ATR':>8}{'ext(ATR)':>9}{'sh':>6}{'notional':>10}{'B1':>10}{'B2':>10}  status")
    ok = []
    for s in names:
        r = status(s, nav)
        if not r: continue
        if r["fails"]:
            print(f"{s:<6}{r['c']:>9.2f}{r['atr']:>8.2f}{r['ext']:>9.2f}{'':>6}{'':>10}{'':>10}{'':>10}  FAIL: {', '.join(r['fails'])}")
        else:
            ok.append(r)
            print(f"{s:<6}{r['c']:>9.2f}{r['atr']:>8.2f}{r['ext']:>9.2f}{r['shares']:>6}{r['notional']:>10,.0f}{r['b1']:>10.2f}{r['b2']:>10.2f}  ELIGIBLE")
    tot = sum(r["notional"] for r in ok)
    print(f"\n  eligible: {len(ok)}  |  notional ${tot:,.0f} = {tot/nav*100:.1f}% NAV (cap 15%)"
          f"  |  risk-at-stops ${len(ok)*R_PCT*nav:,.0f} = {len(ok)*R_PCT*100:.1f}% NAV (cap 10%)")
