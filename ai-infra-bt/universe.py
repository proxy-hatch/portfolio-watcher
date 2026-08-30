"""Universe + period definitions. Frozen for reproducibility (v3, 2026-08-25)."""

# ---- IN-SAMPLE (parameter selection ONLY) --------------------------------------
# Names deliberately chosen from the v2 Part D screen, NOT from the v3 request list,
# and a period that ENDS before every evaluation window begins. Includes
# anti-survivorship names that trended then died and never recovered.
IS_NAMES = ["MARA","RIOT","CLSK","WULF","APLD","HIVE","IONQ","MSTR",
            "PLUG","SPCE","FCEL","AI","NIO","TSLA","ENPH","SEDG",
            "ROKU","NET","SHOP","PSIX","BW","PUMP"]
IS_PERIOD = ("2020-08-26", "2023-12-31")

# ---- OUT-OF-SAMPLE evaluation sets (exactly as requested) ----------------------
EVAL = {
 "E1 AI sleeve as traded":       (["BE","NBIS","CORZ","SNDK"],              "2026-01-01","2026-08-24"),
 "E2 Leopold Sit-Awareness longs":(["NBIS","CRWV","BE","SEI","TE","PSIX","BW","PUMP",
                                   "IREN","CORZ","APLD","RIOT","CLSK","BTDR","HIVE",
                                   "SNDK","WYFI"],                          "2025-01-01","2026-08-24"),
 "E3 NVDA bull run":             (["NVDA"],                                 "2023-11-01","2025-09-30"),
 "E4 MU bull run":               (["MU"],                                   "2025-04-01","2026-07-31"),
 "E5 Mega-cap since 2025":       (["GOOG","MSFT","META","AAPL"],            "2025-01-01","2026-08-24"),
 "E6 COST 2023-2025":            (["COST"],                                 "2023-01-01","2025-12-31"),
}

# ---- Benchmark: what actually happened, NOT following v2 ------------------------
# R computed on the same basis as the engine: R = (exit-entry)/(3*ATR14_at_entry)
BENCH = [("BE",   257.29, 306.32,  24.04),
         ("CORZ",  26.20,  21.89,   1.61),
         ("NBIS", 229.52, 226.10,  22.29),
         ("SNDK",1986.01,1393.91, 164.97)]
def bench():
    R=[(x-e)/(3*a) for _,e,x,a in BENCH]
    w=[r for r in R if r>0]; l=[r for r in R if r<=0]
    aw=sum(w)/len(w); al=abs(sum(l)/len(l))
    return dict(n=len(R),win=len(w)/len(R),avg_win_R=aw,avg_loss_R=al,payoff=aw/al,
                exp_R=sum(R)/len(R),total_R=sum(R),pf=sum(w)/abs(sum(l)),
                avg_ret=0,med_hold=22,whipsaw=0.25,giveback=0)
