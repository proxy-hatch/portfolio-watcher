"""Matrix: universe x (long-only vs long/short) x leverage. Same rules throughout."""
import bench2 as B
U = {
 "U1 AI sleeve (4)":     (["BE","NBIS","CORZ","SNDK"],"2025-01-01","2026-08-24"),
 "U3 Mega-cap (7)":      (["GOOG","MSFT","META","AAPL","NVDA","MU","COST"],"2011-01-01","2026-08-24"),
 "U4 Sector ETF (14)":   (["XLK","XLE","XLF","XLV","XLI","XLY","XLP","XLU","XLB","SMH","XBI","ITB","KRE","XRT"],"2011-01-01","2026-08-24"),
 "U6 Cross-asset (32)":  (["SPY","QQQ","IWM","MDY","EFA","EEM","VGK","EWJ","EWZ","TLT","IEF","LQD","HYG","TIP","AGG",
                           "GLD","SLV","DBC","USO","UNG","DBA","FXE","FXY","VNQ","XLK","XLE","XLF","XLV","XLI","XLY","XLP","XLU"],
                          "2011-01-01","2026-08-24"),
}
SIG = {"EWMAC 16/64": B.sig_ewmac, "Donchian 100/50": B.sig_donchian,
       "Ensemble Donchian": B.sig_ensemble, "TSMOM 12m": B.sig_tsmom}
print(f"{'universe':<22}{'signal':<20}{'mode':<12}{'lev':>4}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>8}{'MAR':>7}")
print("-"*96)
for un,(syms,a,b) in U.items():
    first=True
    for sn,fn in SIG.items():
        for mode,lo in (("long-only",True),("long/short",False)):
            for lev in (1.0,2.0):
                try:
                    m=B.perf(B.simulate_portfolio(syms,a,b,fn,max_leverage=lev,long_only=lo))
                except Exception: m=None
                if not m: continue
                print(f"{(un if first else ''):<22}{sn:<20}{mode:<12}{lev:>4.0f}"
                      f"{m['cagr']*100:>7.1f}%{m['vol']*100:>6.1f}%{m['sharpe']:>8.2f}{m['mdd']*100:>7.1f}%{m['mar']:>7.2f}")
                first=False
    print()
