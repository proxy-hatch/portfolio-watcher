#!/usr/bin/env python3
"""
Persist the daily engine's adjusted-close series to disk.

Why: the weekly review's correlation refresh has been deferred three times because the
only cached series live in `ai-infra-bt/data_adj/`, frozen at 2026-08-25 — the playbook
approval date. Recomputing core/sleeve (0.81) and BRK.B (0.31) correlations from that
data would reproduce the approval figures and present them as an update, which is worse
than reporting nothing. A fresh pull does not fit inside the weekly's time bounds.

The daily engine already fetches every series it needs. Writing them out costs nothing,
needs no extra IBKR request, and accumulates real history from this point forward.

Symbols with spaces ("BRK B") are stored under a sanitised filename; the manifest keeps
the mapping so nothing has to guess.
"""
import json
import os

SUBDIR = "prices"


def _safe(symbol): return symbol.replace(" ", "_").replace("/", "_")


def _dir(root): return os.path.join(root, "state", SUBDIR)


def save(px, root):
    """Merge today's bars into whatever is already stored. Returns the manifest."""
    d = _dir(root)
    os.makedirs(d, exist_ok=True)
    manifest = {}
    for symbol, series in (px or {}).items():
        if not series: continue
        path = os.path.join(d, _safe(symbol)+".json")
        merged = {}
        if os.path.exists(path):
            try: merged = json.load(open(path)).get("closes", {})
            except Exception: merged = {}
        merged.update({str(k): float(v) for k, v in series.items()})
        tmp = path+".tmp"
        with open(tmp, "w") as f:
            json.dump(dict(symbol=symbol, closes=merged), f)
        os.replace(tmp, path)
        manifest[symbol] = dict(file=os.path.basename(path), bars=len(merged),
                                first=min(merged), last=max(merged))
    tmp = os.path.join(d, "_manifest.json.tmp")
    with open(tmp, "w") as f: json.dump(manifest, f, indent=1)
    os.replace(tmp, os.path.join(d, "_manifest.json"))
    return manifest


def load(root, symbol):
    path = os.path.join(_dir(root), _safe(symbol)+".json")
    if not os.path.exists(path): return {}
    try: return json.load(open(path)).get("closes", {})
    except Exception: return {}


def returns(closes):
    ds = sorted(closes)
    return {ds[i]: closes[ds[i]]/closes[ds[i-1]] - 1
            for i in range(1, len(ds)) if closes[ds[i-1]]}


def correlations(root, symbols, window=250):
    """Pairwise correlation of daily returns over the trailing `window` sessions.

    Returns the matrix plus `n`, because a correlation from 12 observations is not a
    finding and the reader must be able to see that.
    """
    series = {s: returns(load(root, s)) for s in symbols}
    series = {s: r for s, r in series.items() if r}
    if len(series) < 2:
        return dict(error="need at least two stored series", have=sorted(series))
    common = sorted(set.intersection(*[set(r) for r in series.values()]))[-window:]
    n = len(common)
    if n < 20:
        return dict(error=f"only {n} overlapping sessions stored; too few to report",
                    n=n, symbols=sorted(series))
    out = {}
    for a in series:
        for b in series:
            x = [series[a][d] for d in common]; y = [series[b][d] for d in common]
            mx, my = sum(x)/n, sum(y)/n
            cov = sum((x[i]-mx)*(y[i]-my) for i in range(n))/(n-1)
            vx = sum((v-mx)**2 for v in x)/(n-1); vy = sum((v-my)**2 for v in y)/(n-1)
            out.setdefault(a, {})[b] = round(cov/((vx*vy)**0.5), 3) if vx > 0 and vy > 0 else None
    return dict(n=n, window=window, start=common[0], end=common[-1], matrix=out)


if __name__ == "__main__":
    import argparse
    HERE = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=HERE)
    ap.add_argument("--window", type=int, default=250)
    ap.add_argument("--symbols", nargs="*", default=["QLD", "AIS", "AIPO", "BRK B", "SGOV", "QQQ"])
    a = ap.parse_args()
    man_path = os.path.join(_dir(a.root), "_manifest.json")
    if os.path.exists(man_path):
        print("stored series:")
        for s, m in sorted(json.load(open(man_path)).items()):
            print(f"  {s:<6} {m['bars']:>5} bars  {m['first']} .. {m['last']}")
    c = correlations(a.root, a.symbols, a.window)
    print()
    if c.get("error"): print("correlations:", c["error"])
    else:
        print(f"correlations — {c['n']} sessions, {c['start']} .. {c['end']}")
        syms = sorted(c["matrix"])
        print("       " + "".join(f"{s:>8}" for s in syms))
        for s in syms:
            print(f"  {s:<5}" + "".join(f"{c['matrix'][s].get(t, float('nan')):>8.2f}" for t in syms))
