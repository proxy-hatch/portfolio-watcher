import core_opt as C
CAND = {
 "A  current spec":                    dict(vol_target=.30,win=20,cap=3.0,gate="sma10vol",band=4.0),
 "B  win32":                           dict(vol_target=.30,win=32,cap=3.0,gate="sma10vol",band=4.0),
 "C  win32 + cap2":                    dict(vol_target=.30,win=32,cap=2.0,gate="sma10vol",band=4.0),
 "D  win32 + cap2 + band8":            dict(vol_target=.30,win=32,cap=2.0,gate="sma10vol",band=8.0),
 "E  win32 + cap2 + band12":           dict(vol_target=.30,win=32,cap=2.0,gate="sma10vol",band=12.0),
 "F  E but cap2.5":                    dict(vol_target=.30,win=32,cap=2.5,gate="sma10vol",band=12.0),
 "G  E at vol-target 0.25":            dict(vol_target=.25,win=32,cap=2.0,gate="sma10vol",band=12.0),
 "H  E at vol-target 0.35":            dict(vol_target=.35,win=32,cap=2.0,gate="sma10vol",band=12.0),
}
print("=== COMBINATIONS, full period 2006-2026 ===\n"); print(C.HDR)
for k,v in CAND.items(): print(C.fmt(C.run(**v), k))

print("\n\n=== SUB-PERIOD STABILITY (MAR = CAGR / maxDD) ===\n")
SUB=[("2006-09-01","2013-12-31","2006-2013 (GFC)"),
     ("2014-01-01","2019-12-31","2014-2019"),
     ("2020-01-01","2026-08-24","2020-2026")]
print(f"{'config':<28}"+"".join(f"{l:>26}" for _,_,l in SUB))
for k,v in CAND.items():
    row=f"{k:<28}"
    for a,b,_ in SUB:
        m=C.run(start=a,end=b,**v)
        row+=f"{m['cagr']*100:>9.1f}%{m['mdd']*100:>8.1f}%{m['mar']:>8.2f}"
    print(row)

print("\n\n=== ROLLING N-YEAR CAGR (the 5/10/15-year question) ===\n")
print(f"{'config':<28}{'5y worst':>10}{'5y med':>9}{'10y worst':>11}{'10y med':>9}{'15y worst':>11}{'15y med':>9}")
for k,v in CAND.items():
    m=C.run(**v); row=f"{k:<28}"
    for y in (5,10,15):
        r=C.rolling(m['eq'],y)
        row += f"{r[0]*100:>9.1f}%{r[1]*100:>8.1f}%" if r else f"{'n/a':>10}{'':>9}"
    print(row)
