#!/usr/bin/env python3
"""stamp_session.py <sessions.tsv> <sid> <status> — set the outcome on a run's row."""
import sys, io
tsv, sid, status = sys.argv[1], sys.argv[2], sys.argv[3]
try: rows = io.open(tsv, encoding="utf-8").read().splitlines()
except FileNotFoundError: sys.exit(0)
out = []
for r in rows:
    f = r.split("\t")
    if len(f) >= 5 and f[2] == sid:
        f[4] = status; r = "\t".join(f)
    out.append(r)
io.open(tsv, "w", encoding="utf-8").write("\n".join(out) + "\n")
