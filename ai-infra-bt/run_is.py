"""Step 1 — IN-SAMPLE ablation. Selection happens here and ONLY here."""
import engine, universe as U

def run(names, a, b, **kw):
    t = []
    for s in names:
        try: t += engine.simulate(s, a, b, **kw)
        except Exception: pass
    return t

def show(label, **kw):
    t = run(U.IS_NAMES, *U.IS_PERIOD, **kw)
    m = engine.metrics(t)
    # robustness: how many names improve expectancy vs baseline
    return m, t

BASE = dict()
print("IN-SAMPLE ABLATION —", len(U.IS_NAMES), "names,", U.IS_PERIOD[0], "->", U.IS_PERIOD[1])
print("(selection set: anti-survivorship + 2021 top + 2022 bear; none of the v3 request names in this period)\n")
print(engine.HDR)
mb, tb = show("base")
print(engine.fmt(mb, "A0  v2 as specified"))
per_name_base = {}
for s in U.IS_NAMES:
    m = engine.metrics(engine.simulate(s, *U.IS_PERIOD))
    per_name_base[s] = m["exp_R"] if m else None

TESTS = [
 ("A1  + entry clearance 1.0 ATR",      dict(clear=1.0)),
 ("A1  + entry clearance 1.5 ATR",      dict(clear=1.5)),
 ("A1  + entry clearance 2.0 ATR",      dict(clear=2.0)),
 ("A2  B3 off (B1 only)",               dict(b3="off")),
 ("A2  B3 confirm-2-closes",            dict(b3="confirm2")),
 ("A2  B3 buffer 0.5 ATR",              dict(b3="buffer")),
 ("A2  B3 = SMA50 slope down",          dict(b3="slope")),
 ("A3  + shock exit 2.0 ATR/1d",        dict(shock=2.0)),
 ("A3  + shock exit 2.5 ATR/1d",        dict(shock=2.5)),
 ("A3  + shock exit 3.0 ATR/1d",        dict(shock=3.0)),
 ("A3  + shock exit 3.0 ATR/2d",        dict(shock2=3.0)),
 ("A3  + shock exit 3.5 ATR/2d",        dict(shock2=3.5)),
 ("A4  re-entry reclaim50 n=3",         dict(reentry="reclaim50", n_cool=3)),
 ("A4  re-entry reclaim50 n=5",         dict(reentry="reclaim50", n_cool=5)),
 ("A5  B1 multiple 2.5",                dict(m1=2.5)),
 ("A5  B1 multiple 3.5",                dict(m1=3.5)),
 ("A5  B1 multiple 4.0",                dict(m1=4.0)),
]
res = {}
for lab, kw in TESTS:
    m, t = show(lab, **kw)
    imp = 0
    for s in U.IS_NAMES:
        mm = engine.metrics(engine.simulate(s, *U.IS_PERIOD, **kw))
        if mm and per_name_base[s] is not None and mm["exp_R"] > per_name_base[s]: imp += 1
    res[lab] = (m, imp)
    print(engine.fmt(m, lab), f"  [{imp}/{len(U.IS_NAMES)} names improved]")
