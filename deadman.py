#!/usr/bin/env python3
"""
deadman.py — dead-man's switch for the Portfolio Watcher.

WHY THIS EXISTS
    2026-09-27..30. IB Gateway lost its session to an unanswered 2FA prompt. The daily
    runs kept firing and kept failing (FAILED-engine). Every failure dutifully fired an
    ntfy push — into an app iOS had offloaded for space, so every one was dropped in
    silence. Four days passed with an autonomous trading system doing nothing, and no
    one knew.

    The lesson is not "fix ntfy". It is that a system reporting through a single push
    channel cannot report that the channel itself is broken. Absence of alarm is not
    evidence of health. So this script is built to survive the failure it reports on:

      * it runs from its OWN launchd agent, so it still runs when run.sh is the broken part
      * it uses system python3, never the repo venv, for the same reason
      * it escalates over several channels, one of which (ntfy -> email) is PULL-durable:
        an unread email survives an offloaded app
      * it always writes state/deadman-status.txt, which `wf-sessions` prints — a channel
        that requires no delivery at all, only that the user looks

WHAT IT CHECKS
    state/sessions.tsv is the heartbeat ledger: run.sh appends a row when a run starts
    and stamps the outcome at every exit path.

      SILENT      no run row since the last scheduled slot  -> launchd, laptop, or run.sh
      STUCK       newest row still says RUNNING, hours old  -> began, never came back
      FAILING     the last N completed runs all failed      -> the 2026-09-27 case
      HALTING     the last N completed runs all HALTed      -> fail-closed is working, but
                                                               nothing converges and nobody said
      KILLSWITCH  state/AUTOEXEC_OFF set and forgotten      -> trading silently off

    A healthy heartbeat row is NOT the same as a healthy system — that distinction is the
    whole point of FAILING and HALTING. Sep 29 and 30 both wrote perfectly good rows.

OUTPUT
    stdout, when there is something to say:
        line 1:  <severity>\t<title>
        line 2+: body
    exit 0 healthy · 9 unhealthy but already reported · 10 alert · 11 recovered
"""

import io
import json
import os
import sys
from datetime import datetime, timedelta, time as dtime

DIR = os.path.dirname(os.path.abspath(__file__))
TSV = os.path.join(DIR, "state", "sessions.tsv")
STATE = os.path.join(DIR, "state", "deadman-state.json")
STATUS = os.path.join(DIR, "state", "deadman-status.txt")
KILLSWITCH = os.path.join(DIR, "state", "AUTOEXEC_OFF")

# run.sh's schedule, mirrored here. Python weekday(): Mon=0 ... Sun=6, so Tue-Sat is 1..5.
# Both this and launchd work in LOCAL time, so the two stay in step if the laptop travels.
RUN_DAYS = {1, 2, 3, 4, 5}
RUN_AT = dtime(9, 0)

GRACE_H = 2.5   # a run can legitimately take ~25 min; leave margin before calling it missed
STUCK_H = 3.0   # a row still marked RUNNING after this never reached a stamp
FAIL_N = 2      # consecutive hard failures before shouting
HALT_N = 4      # consecutive model HALTs before mentioning it
KILL_DAYS = 7   # kill switch left on this long is probably forgotten, not deliberate
RENAG_H = 12    # while unhealthy, say it again this often

FAIL_PREFIX = ("FAILED", "BLOCKED", "EXECUTION")
DONE_EXCLUDE = ("RUNNING", "-", "")


# ---------- helpers -------------------------------------------------------------------

def human_age(delta):
    """'3d 4h' / '5h 12m' / '43m' — short enough for a notification title."""
    s = int(delta.total_seconds())
    if s < 0:
        s = 0
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return "%dd %dh" % (d, h)
    if h:
        return "%dh %dm" % (h, m)
    return "%dm" % m


def load_rows():
    """Parse the heartbeat ledger into naive-local rows, oldest first."""
    out = []
    try:
        raw = io.open(TSV, encoding="utf-8").read().splitlines()
    except (IOError, OSError):
        return out
    for line in raw:
        f = line.split("\t")
        if len(f) < 3:
            continue
        try:
            at = datetime.strptime(f[0], "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            continue
        # Normalise to naive local: the same frame launchd schedules in.
        out.append({
            "at": at.astimezone().replace(tzinfo=None),
            "kind": f[1],
            "sid": f[2],
            "label": f[3] if len(f) > 3 and f[3] else f[1],
            "outcome": (f[4] if len(f) > 4 else "-").strip() or "-",
        })
    out.sort(key=lambda r: r["at"])
    return out


def missed_slots(since, now):
    """Scheduled run slots strictly after `since` and already past their grace period."""
    cutoff = now - timedelta(hours=GRACE_H)
    out = []
    d = cutoff.date()
    for _ in range(120):                      # bounded walk back; ~4 months is plenty
        if d.weekday() in RUN_DAYS:
            cand = datetime.combine(d, RUN_AT)
            if cand <= since:
                break                         # walking backwards: everything older is known
            if cand <= cutoff:
                out.append(cand)
        d -= timedelta(days=1)
    return sorted(out)


def is_fail(outcome):
    return outcome.startswith(FAIL_PREFIX)


def is_halt(outcome):
    # HALTED-killswitch is deliberate — the user set it. It gets its own, slower check.
    return outcome.startswith("HALTED") and "killswitch" not in outcome


def completed(rows):
    return [r for r in rows if r["outcome"] not in DONE_EXCLUDE]


# ---------- the checks ----------------------------------------------------------------

def evaluate(now, rows):
    """Return a list of (severity, signature, title, detail), worst first."""
    problems = []

    if not rows:
        return [(
            "critical", "no-history",
            "Watcher has no run history",
            "state/sessions.tsv is empty or unreadable. The scheduler has never recorded "
            "a run, or the state directory was lost.",
        )]

    last = rows[-1]
    age = now - last["at"]

    # --- SILENT: the scheduler or the machine, not the strategy ---
    missed = missed_slots(last["at"], now)
    if missed:
        span = "%s .. %s" % (missed[0].strftime("%a %m-%d %H:%M"),
                             missed[-1].strftime("%a %m-%d %H:%M")) \
            if len(missed) > 1 else missed[0].strftime("%a %m-%d %H:%M")
        problems.append((
            "critical", "silent:%d" % len(missed),
            "Watcher SILENT — %d scheduled run(s) missed" % len(missed),
            "Last run %s at %s (%s ago, outcome %s).\n"
            "Missed slots: %s.\n"
            "The run never started: launchd did not fire, the laptop was off or asleep, "
            "or run.sh died before writing its row." % (
                last["label"], last["at"].strftime("%Y-%m-%d %H:%M"), human_age(age),
                last["outcome"], span),
        ))

    # --- STUCK: it started and never came back ---
    if last["outcome"] == "RUNNING" and age > timedelta(hours=STUCK_H):
        problems.append((
            "critical", "stuck:%s" % last["sid"][:8],
            "Watcher STUCK — %s never finished" % last["label"],
            "Started %s (%s ago) and is still stamped RUNNING. The run began but never "
            "reached any exit path — killed mid-flight by the watchdog, a sleep, or a "
            "crash. Check logs/%s.log and whether orders were left half-placed." % (
                last["at"].strftime("%Y-%m-%d %H:%M"), human_age(age), last["kind"]),
        ))

    # --- FAILING: rows look healthy, the system is not. This is the 2026-09-27 case. ---
    done = completed(rows)
    if len(done) >= FAIL_N:
        streak = []
        for r in reversed(done):
            if is_fail(r["outcome"]):
                streak.append(r)
            else:
                break
        if len(streak) >= FAIL_N:
            streak.reverse()
            lines = "\n".join("  %s  %s" % (r["label"], r["outcome"]) for r in streak)
            good = next((r for r in reversed(done) if not is_fail(r["outcome"])), None)
            since = ("Last clean run: %s (%s, %s ago)." % (
                good["label"], good["at"].strftime("%Y-%m-%d %H:%M"),
                human_age(now - good["at"]))) if good else "No clean run on record."
            problems.append((
                "critical", "failing:%d:%s" % (len(streak), streak[-1]["outcome"]),
                "Watcher FAILING — %d consecutive failed runs" % len(streak),
                "%s\n%s\nThe schedule is firing but nothing is being placed." % (lines, since),
            ))

    # --- HALTING: fail-closed is working as designed, but nothing is converging ---
    if len(done) >= HALT_N:
        hstreak = []
        for r in reversed(done):
            if is_halt(r["outcome"]):
                hstreak.append(r)
            else:
                break
        if len(hstreak) >= HALT_N:
            problems.append((
                "notice", "halting:%d" % len(hstreak),
                "Watcher has HALTed %d runs in a row" % len(hstreak),
                "Every recent run ended HALT. Fail-closed is behaving correctly, but the "
                "portfolio has stopped converging toward target and no one has looked at "
                "why. Read the run logs for the stated reason.",
            ))

    # --- KILLSWITCH: trading is off and possibly forgotten ---
    if os.path.exists(KILLSWITCH):
        try:
            set_at = datetime.fromtimestamp(os.path.getmtime(KILLSWITCH))
            days = (now - set_at).days
        except OSError:
            set_at, days = None, 0
        if days >= KILL_DAYS:
            problems.append((
                "warn", "killswitch:%d" % (days // KILL_DAYS),
                "Auto-exec still OFF after %d days" % days,
                "state/AUTOEXEC_OFF has been set since %s. Every run halts before placing "
                "anything. Remove the file to resume autonomous execution." % (
                    set_at.strftime("%Y-%m-%d") if set_at else "an unknown date"),
            ))

    order = {"critical": 0, "warn": 1, "notice": 2}
    problems.sort(key=lambda p: order.get(p[0], 9))
    return problems


# ---------- status file, dedup state ---------------------------------------------------

def write_status(now, rows, problems):
    """The pull-durable channel: no delivery required, only that someone looks."""
    lines = ["Portfolio Watcher — dead-man's switch",
             "checked : %s" % now.strftime("%Y-%m-%d %H:%M:%S (%a, local)")]
    if rows:
        last = rows[-1]
        lines.append("last run: %-24s %s  %s  (%s ago)" % (
            last["label"], last["at"].strftime("%Y-%m-%d %H:%M"), last["outcome"],
            human_age(now - last["at"])))
    else:
        lines.append("last run: none on record")
    lines.append("verdict : %s" % (
        "OK" if not problems else "UNHEALTHY — %d problem(s)" % len(problems)))
    for sev, _sig, title, detail in problems:
        lines.append("")
        lines.append("  [%s] %s" % (sev, title))
        for d in detail.splitlines():
            lines.append("      %s" % d)
    lines.append("")
    try:
        io.open(STATUS, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    except (IOError, OSError):
        pass


def load_state():
    try:
        return json.loads(io.open(STATE, encoding="utf-8").read())
    except Exception:
        return {}


def save_state(d):
    try:
        io.open(STATE, "w", encoding="utf-8").write(json.dumps(d, indent=2) + "\n")
    except (IOError, OSError):
        pass


# ---------- main -----------------------------------------------------------------------

def arg_now():
    """--now 'YYYY-MM-DD HH:MM' overrides the clock.

    Not test scaffolding: an alarm you cannot fire on demand is an alarm you cannot
    trust. This makes every branch reproducible ("what would it have said on Sep 30?")
    without waiting days for the real condition.
    """
    if "--now" in sys.argv:
        raw = sys.argv[sys.argv.index("--now") + 1]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        raise SystemExit("--now: expected 'YYYY-MM-DD HH:MM'")
    return datetime.now().replace(microsecond=0)


def main():
    now = arg_now()
    # --force ignores the re-nag window; --no-save makes the run wholly side-effect free, so
    # a dry run can never consume the dedup slot a real alert is about to need.
    force = "--force" in sys.argv
    save = "--no-save" not in sys.argv

    rows = load_rows()
    problems = evaluate(now, rows)
    if save:
        write_status(now, rows, problems)
    prev = load_state()

    if not problems:
        if prev.get("signature"):
            if save:
                save_state({})
            body = "Health checks are clean again."
            if rows:
                body += " Last run %s at %s (%s)." % (
                    rows[-1]["label"], rows[-1]["at"].strftime("%Y-%m-%d %H:%M"),
                    rows[-1]["outcome"])
            sys.stdout.write("notice\t\u2705 Watcher recovered\n")
            sys.stdout.write(body + "\n")
            return 11
        return 0

    sig = "|".join(p[1] for p in problems)
    last_alert = prev.get("last_alert")
    if not force and prev.get("signature") == sig and last_alert:
        try:
            since = now - datetime.strptime(last_alert, "%Y-%m-%d %H:%M:%S")
            if since < timedelta(hours=RENAG_H):
                # Still unhealthy, just already announced. Distinct from healthy on purpose:
                # a log line reading "ok" through a live outage is the same false comfort
                # that let 2026-09-27..30 run for four days.
                return 9
        except ValueError:
            pass

    if save:
        first_seen = prev.get("first_seen") if prev.get("signature") == sig else None
        save_state({
            "signature": sig,
            "first_seen": first_seen or now.strftime("%Y-%m-%d %H:%M:%S"),
            "last_alert": now.strftime("%Y-%m-%d %H:%M:%S"),
            "count": (prev.get("count", 0) + 1) if prev.get("signature") == sig else 1,
        })

    sev, _sig, title, detail = problems[0]
    body = [detail]
    for s2, _g, t, _d in problems[1:]:
        body.append("")
        body.append("Also [%s]: %s" % (s2, t))
    sys.stdout.write("%s\t%s\n" % (sev, title))
    sys.stdout.write("\n".join(body) + "\n")
    return 10


if __name__ == "__main__":
    sys.exit(main())
