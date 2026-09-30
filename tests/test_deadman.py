#!/usr/bin/env python3
"""Scenario suite for deadman.py — runs the real script in throwaway repo dirs."""
import io, os, shutil, subprocess, sys, tempfile, time
from datetime import datetime

SRC = "/Users/shawn/workspace/portfolio-watcher/deadman.py"
PY = "/usr/bin/python3"
OFF = "+0800"

def row(ts, kind, sid, outcome):
    return "%s %s\t%s\t%s\t%s\t%s" % (ts, OFF, kind, sid, "%s-%s" % (kind, ts[:10]), outcome)

class Repo:
    def __init__(self, rows=None, killswitch_age_days=None, ref_now=None):
        self.d = tempfile.mkdtemp(prefix="dm-")
        os.makedirs(os.path.join(self.d, "state"))
        shutil.copy(SRC, os.path.join(self.d, "deadman.py"))
        if rows is not None:
            io.open(os.path.join(self.d, "state", "sessions.tsv"), "w").write(
                "\n".join(rows) + ("\n" if rows else ""))
        if killswitch_age_days is not None:
            p = os.path.join(self.d, "state", "AUTOEXEC_OFF")
            io.open(p, "w").write("")
            base = (datetime.strptime(ref_now, "%Y-%m-%d %H:%M").timestamp()
                    if ref_now else time.time())
            t = base - killswitch_age_days * 86400
            os.utime(p, (t, t))
    def run(self, now):
        r = subprocess.run([PY, os.path.join(self.d, "deadman.py"), "--now", now],
                           capture_output=True, text=True)
        return r.returncode, r.stdout.strip()
    def add(self, r):
        io.open(os.path.join(self.d, "state", "sessions.tsv"), "a").write(r + "\n")

# A normal week: Tue 09-29 .. Sat 10-03 (2026-10-03 is a Saturday).
WEEK = [
    row("2026-09-29 09:00:03", "daily",  "AAA1", "CLEAN"),
    row("2026-09-30 09:00:03", "daily",  "AAA2", "EXECUTED"),
    row("2026-10-01 09:00:03", "daily",  "AAA3", "CLEAN"),
    row("2026-10-02 09:00:03", "daily",  "AAA4", "CLEAN"),
    row("2026-10-03 09:00:03", "daily",  "AAA5", "CLEAN"),
    row("2026-10-03 09:30:03", "weekly", "AAA6", "CLEAN"),
]

FAILS = 0
def check(name, got, want, detail=""):
    global FAILS
    ok = got == want
    if not ok: FAILS += 1
    print("  %s  %-34s got=%s want=%s %s" % ("PASS" if ok else "FAIL", name, got, want, detail))

print("== schedule awareness (the Sun/Mon gap a fixed threshold gets wrong) ==")
check("Sun 12:00 after Sat run",   Repo(WEEK).run("2026-10-04 12:00")[0], 0)
check("Mon 20:00 after Sat run",   Repo(WEEK).run("2026-10-05 20:00")[0], 0)
check("Tue 11:00 (inside grace)",  Repo(WEEK).run("2026-10-06 11:00")[0], 0)
rc, out = Repo(WEEK).run("2026-10-06 11:31")
check("Tue 11:31 (grace expired)", rc, 10, "| %s" % out.splitlines()[0].split("\t")[1])
rc, out = Repo(WEEK + [row("2026-10-06 09:00:03", "daily", "AAA7", "CLEAN")]).run("2026-10-06 12:00")
check("Tue 12:00 after Tue run",   rc, 0)

print("\n== silence ==")
rc, out = Repo(WEEK).run("2026-10-13 12:00")   # a full week later
n = out.splitlines()[0].split("\t")[1]
check("laptop off one week",       rc, 10, "| %s" % n)
check("  counted 6 missed slots",  "6 scheduled" in n, True)
rc, out = Repo([]).run("2026-10-06 12:00")
check("empty ledger",              rc, 10, "| %s" % out.splitlines()[0].split("\t")[1])

print("\n== stuck ==")
check("RUNNING 1h old",            Repo(WEEK + [row("2026-10-06 09:00:03","daily","B1","RUNNING")]).run("2026-10-06 10:00")[0], 0)
rc, out = Repo(WEEK + [row("2026-10-06 09:00:03","daily","B1","RUNNING")]).run("2026-10-06 14:00")
check("RUNNING 5h old",            rc, 10, "| %s" % out.splitlines()[0].split("\t")[1])

print("\n== failing (the 2026-09-27 case: rows healthy, system not) ==")
one = WEEK + [row("2026-10-06 09:00:03","daily","C1","FAILED-engine")]
check("1 failure",                 Repo(one).run("2026-10-06 12:00")[0], 0)
two = one + [row("2026-10-07 09:00:03","daily","C2","FAILED-engine")]
rc, out = Repo(two).run("2026-10-07 12:00")
check("2 consecutive failures",    rc, 10, "| %s" % out.splitlines()[0].split("\t")[1])

print("\n== halting / killswitch ==")
h = WEEK + [row("2026-10-06 09:00:03","daily","D%d"%i,"HALTED") for i in range(4)]
rc, out = Repo(h).run("2026-10-06 12:00")
check("4 consecutive HALTs",       rc, 10, "| %s" % out.splitlines()[0].split("\t")[1])
check("killswitch 3 days",         Repo(WEEK + [row("2026-10-06 09:00:03","daily","E1","HALTED-killswitch")], killswitch_age_days=3, ref_now="2026-10-06 12:00").run("2026-10-06 12:00")[0], 0)
rc, out = Repo(WEEK + [row("2026-10-06 09:00:03","daily","E1","HALTED-killswitch")], killswitch_age_days=9, ref_now="2026-10-06 12:00").run("2026-10-06 12:00")
check("killswitch 9 days",         rc, 10, "| %s" % out.splitlines()[0].split("\t")[1])

print("\n== dedup / re-nag / recovery ==")
r = Repo(two)
check("first alert",               r.run("2026-10-07 12:00")[0], 10)
check("same problem 6h later",     r.run("2026-10-07 18:00")[0], 9)
check("same problem 13h later",    r.run("2026-10-08 01:00")[0], 10)
r2 = Repo(two)
r2.run("2026-10-07 12:00")
r2.add(row("2026-10-08 09:00:03", "daily", "C3", "EXECUTED"))
rc, out = r2.run("2026-10-08 12:00")
check("recovery after clean run",  rc, 11, "| %s" % out.splitlines()[0].split("\t")[1])
check("quiet once recovered",      r2.run("2026-10-08 13:00")[0], 0)

print("\n%s (%d failure(s))" % ("ALL PASS" if not FAILS else "FAILURES", FAILS))
sys.exit(1 if FAILS else 0)
