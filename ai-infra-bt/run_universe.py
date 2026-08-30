"""THE DECISIVE EXPERIMENT — hold the rules constant, vary the universe."""
import bench2 as B

U = {
 "U1 AI sleeve (4 names)":      (["BE","NBIS","CORZ","SNDK"], "2025-01-01","2026-08-24"),
 "U2 Leopold longs (17)":       (["NBIS","CRWV","BE","SEI","TE","PSIX","BW","PUMP","IREN","CORZ",
                                  "APLD","RIOT","CLSK","BTDR","HIVE","SNDK","WYFI"],"2025-01-01","2026-08-24"),
 "U3 Mega-cap tech (7)":        (["GOOG","MSFT","META","AAPL","NVDA","MU","COST"],"2011-01-01","2026-08-24"),
 "U4 Sector ETFs (14)":         (["XLK","XLE","XLF","XLV","XLI","XLY","XLP","XLU","XLB","SMH",
                                  "XBI","ITB","KRE","XRT"],"2011-01-01","2026-08-24"),
 "U5 Cross-asset ETFs (18)":    (["SPY","QQQ","IWM","MDY","EFA","EEM","VGK","EWJ","EWZ","TLT","IEF",
                                  "LQD","HYG","TIP","GLD","SLV","DBC","USO"],"2011-01-01","2026-08-24"),
 "U6 Everything ETF (32)":      (["SPY","QQQ","IWM","MDY","EFA","EEM","VGK","EWJ","EWZ","TLT","IEF","LQD",
                                  "HYG","TIP","AGG","GLD","SLV","DBC","USO","UNG","DBA","FXE","FXY","VNQ",
                                  "XLK","XLE","XLF","XLV","XLI","XLY","XLP","XLU"],"2011-01-01","2026-08-24"),
}
print("Long-only, inverse-vol sizing, 15% target vol, 1.0x leverage cap, 10bps turnover cost, 2% cash yield\n")
for un,(syms,a,b) in U.items():
    print(f"### {un}   [{a} -> {b}]")
    print("  "+B.PHDR)
    for sn, fn in B.SIGNALS.items():
        try: m = B.perf(B.simulate_portfolio(syms,a,b,fn))
        except Exception as e: m=None
        print("  "+B.pfmt(m,sn))
    # buy&hold equal-weight benchmark
    try:
        m=B.perf(B.simulate_portfolio(syms,a,b,lambda bb,**k:[1.0]*len(bb)))
        print("  "+B.pfmt(m,"— equal-wt buy&hold"))
    except Exception: pass
    print()
