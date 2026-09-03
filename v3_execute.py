#!/usr/bin/env python3
"""
v3_execute.py — deterministic order placement for Portfolio Playbook v3.

The model NEVER decides an order. v3_engine.py computes targets; this script
diffs them against live positions and places the difference. Every guard below
maps to a failure that actually happened to this book.

    ./v3_execute.py                    # dry run (default) — prints the plan
    ./v3_execute.py --live             # place orders
    ./v3_execute.py --establish --live # initial build-out (ignores drift bands)

Exit: 0 ok/nothing to do · 2 blocked by a guard · 3 IBKR failure · 4 kill switch
"""
import argparse, json, os, subprocess, sys, datetime as dt, math

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state")
KILL = os.path.join(STATE, "AUTOEXEC_OFF")
FAILS = os.path.join(STATE, "autoexec-consecutive-failures")
AUDIT = os.path.join(STATE, "orders-audit.jsonl")
LOCK  = os.path.join(STATE, "v3_execute.lock")
NAVH  = os.path.join(STATE, "nav-history.jsonl")

# ---- rails ---------------------------------------------------------------
WHITELIST   = {"QLD", "AIS", "AIPO", "BRK B", "SGOV"}
ACCOUNTS    = {"QLD": "U17856045",      # TFSA — §1.2c core
               "AIS": "U3847490",       # Margin — sleeve
               "AIPO": "U3847490",      # Margin — sleeve
               "BRK B": "U17884372",    # RRSP — ballast
               "SGOV": None}            # parked per-account, not traded here
MAX_RUN_NOTIONAL_PCT = 0.10   # ≤10% of NAV traded in any single run
MAX_ORDER_NOTIONAL_PCT = 0.08 # ≤8% of NAV in any single order
COLLAR = 0.005                # marketable limit = last ±0.5%; never a market order
MIN_ORDER_USD = 500           # don't churn on dust
MAX_CONSEC_FAILS = 2          # auto-trip the kill switch after this many
REPLAY_MAX_AGE_SEC = 3600     # an approved plan older than this is not executed
REPLAY_MAX_DRIFT = 0.015      # abort if any plan symbol moved >1.5% since review
MAX_NAV_MOVE = 0.20           # >20% NAV change vs last run = something is wrong
MAX_DELTA_RATIO = 5.0         # target/current beyond this smells of a corporate action
LOCK_STALE_SEC = 3600         # a lock older than this is assumed orphaned
CASH_BUFFER = 1.01            # fund 1% over the order value for slippage/fees

# HOUSE CONVENTION: every order in this book is placed with clientId 1.
# IBKR only lets the originating clientId (or 0) cancel/modify an order, so keeping
# ALL order placement on a single id is what makes orders traceable and cancellable
# later — from a followup session, a script, or by hand. Do not change this.
ORDER_CLIENT_ID = 1

def acquire_lock():
    """One execution at a time — a manual run and the scheduled run must not overlap."""
    os.makedirs(STATE, exist_ok=True)
    if os.path.exists(LOCK):
        age = dt.datetime.now().timestamp() - os.path.getmtime(LOCK)
        owner = open(LOCK).read().strip()
        if age < LOCK_STALE_SEC:
            return False, f"another run holds the lock ({owner}, {age:.0f}s ago)"
        os.remove(LOCK)
    open(LOCK, "w").write(f"pid={os.getpid()} {dt.datetime.now().isoformat(timespec='seconds')}")
    return True, None

def release_lock():
    try: os.remove(LOCK)
    except Exception: pass

def nav_sanity(nav):
    """Compare NAV to the previous run. A wild move means bad data, not a real move."""
    prev = None
    if os.path.exists(NAVH):
        try:
            lines = [l for l in open(NAVH).read().splitlines() if l.strip()]
            if lines: prev = json.loads(lines[-1]).get("nav")
        except Exception: pass
    with open(NAVH, "a") as f:
        f.write(json.dumps({"ts": dt.datetime.now().isoformat(timespec="seconds"),
                            "nav": nav})+"\n")
    if prev and prev > 0:
        move = abs(nav-prev)/prev
        if move > MAX_NAV_MOVE:
            return f"NAV moved {move:.1%} since last run (${prev:,.0f} -> ${nav:,.0f})"
    return None

def log_audit(rec):
    os.makedirs(STATE, exist_ok=True)
    rec["ts"] = dt.datetime.now().isoformat(timespec="seconds")
    with open(AUDIT, "a") as f: f.write(json.dumps(rec)+"\n")

def emit(msg):
    """
    Print to BOTH streams. run.sh pastes the plan's stdout into the review prompt;
    anything written only to stderr is invisible to the reviewer. On 2026-08-29 the
    BLOCKED line and the funding leg were stderr-only, so the model was asked to
    approve a three-leg plan when the engine had actually produced four legs and an
    error. A refusal must never be the part that gets truncated.
    """
    print(msg)
    print(msg, file=sys.stderr)

def notify(title, body, prio="default"):
    try: subprocess.run([os.path.join(HERE, "notify.sh"), title, body, prio],
                        check=False, capture_output=True, timeout=20)
    except Exception: pass

# --- failure accounting ------------------------------------------------------
# Two different things used to share one counter, which is why a CORRECT refusal
# disabled the whole system on 2026-08-29:
#
#   MALFUNCTION — the machinery broke (engine crash, IBKR unreachable, placement
#                 exception, broker rejected an order). Repeats mean something is
#                 genuinely wrong and trading must stop. Trips the kill switch.
#   REFUSAL     — a rail did its job and declined to trade (funding short, symbol
#                 not whitelisted, gate contradiction, replay drift). The system is
#                 working as designed. Never trips the kill switch; it only reports.
#
# Both are deduplicated by (session, key). The Saturday daily 09:00 and weekly 09:30
# runs see identical state, so one condition used to count twice and reach
# MAX_CONSEC_FAILS=2 within 30 minutes — the threshold was effectively 1.

def _load_fails():
    try:
        d = json.load(open(FAILS))
        return d if isinstance(d, dict) else {"n": 0, "seen": {}}
    except Exception:
        return {"n": 0, "seen": {}}

def _save_fails(d):
    os.makedirs(STATE, exist_ok=True)
    with open(FAILS, "w") as f: json.dump(d, f)

def bump_fail(reason, key=None, session=None):
    """Count a MALFUNCTION. Same condition in the same session counts once."""
    d = _load_fails()
    tag = f"{session or 'na'}|{key or reason[:60]}"
    if tag in d.get("seen", {}):
        return d.get("n", 0)          # already counted this session — not a new failure
    d.setdefault("seen", {})[tag] = reason[:200]
    d["n"] = d.get("n", 0) + 1
    _save_fails(d)
    if d["n"] >= MAX_CONSEC_FAILS:
        open(KILL, "w").write(
            f"auto-tripped {dt.datetime.now().isoformat()}: "
            f"{d['n']} distinct MALFUNCTIONS. Last: {reason}\n")
        notify("🚨 v3 auto-exec DISABLED",
               f"{d['n']} malfunctions. Last: {reason}", "urgent")
    return d["n"]

def note_refusal(reason, key=None, session=None):
    """
    Record a rail doing its job. Reported, never punished — a refusal is the system
    working. Notifies once per session per condition so a persistent block (e.g. a
    funding shortfall that recurs every run) does not spam, but also never silently
    disables trading the way the shared counter used to.
    """
    d = _load_fails()
    tag = f"{session or 'na'}|refusal|{key or reason[:60]}"
    first = tag not in d.get("seen", {})
    if first:
        d.setdefault("seen", {})[tag] = reason[:200]
        _save_fails(d)
    streak = sum(1 for k in d.get("seen", {}) if "|refusal|" in k)
    if first:
        notify("v3 auto-exec BLOCKED (rail held)",
               f"{reason[:220]}  [no orders; automation stays ARMED]",
               "high" if streak < 3 else "urgent")
    return streak

def clear_fail():
    if os.path.exists(FAILS): os.remove(FAILS)

STALE_LIMIT_PCT = 0.02   # a resting limit >2% away from market is unlikely to fill

def get_resting(host, port, cid):
    """All resting orders, netted per symbol. Pending BUYs count toward the target."""
    from ib_async import IB
    ib = IB(); ib.connect(host, port, clientId=cid, timeout=30)
    try:
        ib.reqAllOpenOrders(); ib.sleep(2)
        out = {}
        for tr in ib.openTrades():
            o, c = tr.order, tr.contract
            rec = out.setdefault(c.symbol, dict(net=0.0, orders=[]))
            signed = o.totalQuantity if o.action == "BUY" else -o.totalQuantity
            rec["net"] += signed
            # orderId comes back as 0 for any order this client did not place
            # (the three legacy TFSA sells report id=0, clientId=0). permId is the
            # only stable handle, and it is what a cancel/modify must key off.
            rec["orders"].append(dict(action=o.action, qty=o.totalQuantity,
                                      type=o.orderType, limit=o.lmtPrice or None,
                                      tif=o.tif, account=o.account,
                                      order_id=o.orderId, perm_id=o.permId,
                                      client_id=o.clientId,
                                      ours=(o.clientId == ORDER_CLIENT_ID and o.orderId),
                                      status=tr.orderStatus.status))
        return out
    finally:
        try: ib.disconnect()
        except Exception: pass

def get_targets(establish, nav=None):
    cmd = [sys.executable, os.path.join(HERE, "v3_engine.py"), "--json"]
    if establish: cmd.append("--establish")
    if nav: cmd += ["--nav", str(nav)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(f"v3_engine failed rc={p.returncode}: {p.stderr.strip()[:300]}")
    return json.loads(p.stdout)

def build_plan(t, resting):
    """
    Target vs (current position + PENDING resting orders) -> orders.
    Netting matters: a resting BUY already moves you toward the target, so ordering
    the full gap on top of it would double up. Pure arithmetic, no judgement.
    """
    # investable_nav excludes legacy holdings the strategy cannot spend; the notional
    # caps must use the same base the targets were sized from.
    nav = t.get("investable_nav") or t["nav"]; plan = []
    b = t["buckets"]
    def add(sym, tgt_sh, cur_sh, price, why):
        pend = resting.get(sym, {}).get("net", 0.0)
        d = int(round(tgt_sh - cur_sh - pend))
        if d == 0: return
        if abs(d*price) < MIN_ORDER_USD: return
        note = f" (net of {pend:+.0f} pending)" if pend else ""
        plan.append(dict(symbol=sym, action="BUY" if d > 0 else "SELL", qty=abs(d),
                         price=price, notional=abs(d)*price, reason=why+note,
                         pending=pend, account=ACCOUNTS.get(sym)))
    c = b["core"]
    if c["action"] == "REBALANCE":
        add(c["symbol"], c["target_shares"], c["current_shares"], c["price"],
            f"core L={c['leverage']} drift {c['drift_pp']}pp")
    s = b["sleeve"]
    if s["action"] == "REBALANCE":
        for sym, leg in s["legs"].items():
            add(sym, leg["target_shares"], leg["current_shares"], leg["price"],
                f"sleeve L={s['leverage']} drift {s['drift_pp']}pp")
    x = b["ballast"]
    if x["action"] == "REBALANCE":
        add(x["symbol"], x["target_shares"], x["current_shares"], x["price"],
            f"ballast drift {x['drift_pp']}pp")

    return plan, nav

def add_funding(plan, t, resting):
    """
    Make every BUY payable from what its OWN account can actually spend right now,
    and queue SGOV sells to top the account up for later runs.

    The hard constraint learned on 2026-09-01: a funding SELL placed in the same run
    CANNOT pay for that run's BUY. Runs fire at 09:00 Taipei = ~21:00 ET, five hours
    after the close, so the sell is a GTC limit that cannot fill for another ~12
    hours — while IBKR checks buying power the instant the buy is submitted:

        Error 201: Order rejected - reason:Available converted to base: 5964.23 USD
                   Cash needed for this order and other pending orders: 9199.59 USD

    Sorting SELLs ahead of BUYs and sleeping 2.5s between them never addressed this;
    it only controls submission order, not settlement. So the buy is CLAMPED to what
    the account can pay today and the shortfall is funded for next time — the same
    "clamp, never block" rule already used for size caps. The remainder converges over
    runs instead of stalling (09-02 and 09-03 both re-planned the identical rejected
    order and had to be vetoed by the reviewer).

    Two different cash numbers, deliberately:
      spendable — AvailableFunds, what IBKR checks an order against NOW. Caps buys.
      committed — spendable + proceeds of SGOV sells already resting. Decides whether
                  to sell MORE, so a pending sell is never duplicated.

    Returns (plan_with_funding, blocking_errors, notes).
    """
    avail = t.get("available_by_account") or t.get("cash_by_account", {}) or {}
    posacct = t.get("positions_by_account", {})
    sgov_px = t.get("sgov_price")
    if not sgov_px:
        return plan, [], []

    transit_sh = {}
    for od in (resting.get("SGOV") or {}).get("orders", []):
        if od["action"] == "SELL" and od.get("account"):
            transit_sh[od["account"]] = transit_sh.get(od["account"], 0.0) + od["qty"]

    need, notes, errs = {}, [], []
    for o in plan:
        if o["action"] == "BUY" and o["account"]:
            need[o["account"]] = need.get(o["account"], 0.0) + o["notional"]

    fund, drop = [], []
    for acct, req in sorted(need.items()):
        spendable = avail.get(acct, 0.0)
        pend_sh = transit_sh.get(acct, 0.0)
        transit = pend_sh*sgov_px
        if pend_sh:
            notes.append(f"{acct}: {pend_sh:.0f} SGOV (${transit:,.0f}) already resting from "
                         f"an earlier run — counted toward funding, not re-sold")

        # 1. clamp this account's BUYs to what it can pay for TODAY
        budget = spendable/CASH_BUFFER
        if req > budget:
            legs = [o for o in plan if o["action"] == "BUY" and o["account"] == acct]
            legs.sort(key=lambda o: o["notional"], reverse=True)
            room = budget
            for o in legs:
                if o["notional"] <= room:
                    room -= o["notional"]; continue
                newq = int(room // o["price"]) if o["price"] else 0
                if newq*o["price"] < MIN_ORDER_USD:
                    drop.append(o)
                    notes.append(f"{o['symbol']} {acct}: deferred entirely — "
                                 f"${spendable:,.0f} spendable cannot cover a "
                                 f"${MIN_ORDER_USD:,.0f} minimum order")
                else:
                    notes.append(f"{o['symbol']} {acct}: {o['qty']} -> {newq} sh — capped at "
                                 f"${spendable:,.0f} spendable (a funding sell placed now "
                                 f"cannot fill until the next open); remainder next run")
                    o["qty"] = newq
                    o["notional"] = newq*o["price"]
                    o["reason"] += " [cash-capped]"
                    room -= o["notional"]

        # 2. queue SGOV so the REMAINDER is affordable on a later run
        short = req*CASH_BUFFER - spendable - transit
        if short <= 0:
            continue
        held = posacct.get(acct, {}).get("SGOV", 0.0) - pend_sh
        sell = math.ceil(short/sgov_px)
        if sell > held:
            sell = int(held)
            if sell > 0:
                notes.append(f"{acct}: only {held:.0f} SGOV free — funding what it can; "
                             f"the target closes over several runs")
            else:
                notes.append(f"{acct}: no SGOV left to fund with; the remainder waits for "
                             f"cash from elsewhere")
        if sell > 0:
            fund.append(dict(symbol="SGOV", action="SELL", qty=int(sell), price=sgov_px,
                             notional=sell*sgov_px, account=acct, funding=True, pending=0,
                             reason=f"top up {acct} for the NEXT run: ${spendable:,.0f} "
                                    f"spendable vs ${req:,.0f} wanted"))

    plan = [o for o in plan if o not in drop]
    return fund + plan, errs, notes

def check_rails(plan, nav, t):
    """
    Two kinds of rail:
      HARD BLOCK — a safety violation; abort the whole run.
      CLAMP      — the order is merely too big; scale it down and let the
                   remainder complete on the next run. Blocking on size would
                   deadlock any gap wider than the cap (a 12pp core gap could
                   never close), so size is always clamped, never blocked.
    Returns (blocking_errors, clamp_notes) and MUTATES plan with clamped sizes.
    """
    errs, notes = [], []
    for o in plan:
        if o["symbol"] not in WHITELIST:
            errs.append(f"{o['symbol']} not in whitelist")
        if o["account"] is None:
            errs.append(f"{o['symbol']} has no account mapping")
    # corporate action / bad data: a target wildly out of scale with the holding
    for k in ("core", "ballast"):
        bk = t["buckets"].get(k) or {}
        cur, tgt = bk.get("current_shares") or 0, bk.get("target_shares") or 0
        if cur and tgt and (tgt/cur > MAX_DELTA_RATIO or cur/tgt > MAX_DELTA_RATIO):
            errs.append(f"{k}: target {tgt} vs held {cur} differs by >{MAX_DELTA_RATIO}x "
                        f"— possible split/corporate action")
    for k in ("core", "sleeve"):
        if not t["buckets"][k].get("gate_on", True) and any(
                o["action"] == "BUY" for o in plan):
            errs.append(f"{k} gate is DEFENSIVE but plan contains BUYs")
    if errs:
        return errs, notes

    # clamp per-order (funding SELLs are exempt — clamping them would underfund the buys)
    for o in plan:
        if o.get("funding"): continue
        cap = nav*MAX_ORDER_NOTIONAL_PCT
        if o["notional"] > cap:
            newq = max(1, int(cap // o["price"]))
            notes.append(f"{o['symbol']} clamped {o['qty']}->{newq} sh "
                         f"(per-order {MAX_ORDER_NOTIONAL_PCT:.0%} NAV cap); remainder next run")
            o["qty"] = newq; o["notional"] = newq*o["price"]

    # clamp the run as a whole, largest-first, preserving order priority
    cap = nav*MAX_RUN_NOTIONAL_PCT
    tot = sum(o["notional"] for o in plan if not o.get("funding"))
    if tot > cap:
        scale = cap/tot
        for o in plan:
            if o.get("funding"): continue
            newq = max(0, int(o["qty"]*scale))
            if newq != o["qty"]:
                notes.append(f"{o['symbol']} clamped {o['qty']}->{newq} sh "
                             f"(run {MAX_RUN_NOTIONAL_PCT:.0%} NAV cap); remainder next run")
            o["qty"] = newq; o["notional"] = newq*o["price"]
        plan[:] = [o for o in plan if o["qty"] > 0
                   and (o.get("funding") or o["notional"] >= MIN_ORDER_USD)]
    return errs, notes

def place(plan, host, port, cid=None):
    from ib_async import IB, Stock, LimitOrder
    # Always the same client id so v3 can cancel/modify what it placed.
    ib = IB(); ib.connect(host, port, clientId=ORDER_CLIENT_ID, timeout=30)
    # SELLs first — but ONLY so a same-symbol reduce-then-add can never cross, NOT
    # because it funds anything. Runs fire ~5h after the close, so a funding SELL is a
    # GTC limit that cannot fill for ~12 hours while IBKR checks buying power on
    # submission. add_funding() is what keeps every BUY inside its account's spendable
    # cash; ordering here does not and never did.
    plan = sorted(plan, key=lambda o: 0 if o["action"] == "SELL" else 1)
    placed = []
    try:
        # Quantities are already NET of resting orders (build_plan). The only
        # duplicate guard still needed is an exact same-side same-qty repeat,
        # which would indicate this run already executed.
        dupes = {}
        ib.reqAllOpenOrders(); ib.sleep(2)
        for tr in ib.openTrades():
            dupes[(tr.contract.symbol, tr.order.action, tr.order.totalQuantity)] = tr.order.orderId
        for o in plan:
            dk = (o["symbol"], o["action"], float(o["qty"]))
            if dk in dupes:
                placed.append(dict(o, status="SKIPPED_DUPLICATE",
                                   note=f"identical order #{dupes[dk]} already resting")); continue
            c = Stock(o["symbol"], "SMART", "USD")
            q = ib.qualifyContracts(c)
            if not q:
                placed.append(dict(o, status="FAILED", note="cannot qualify")); continue
            lmt = round(o["price"]*(1+COLLAR) if o["action"] == "BUY"
                        else o["price"]*(1-COLLAR), 2)
            # GTC, not DAY: a DAY order that doesn't fill vanishes silently at the close and
            # the system only notices a run later. A GTC order stays visible on the book,
            # is netted against the target by the next run, and shows the stale ⚠ flag if
            # it drifts far from market. Surviving the session is the safer failure mode.
            order = LimitOrder(o["action"], o["qty"], lmt, tif="GTC")
            order.account = o["account"]
            order.outsideRth = False
            tr = ib.placeOrder(q[0], order)
            ib.sleep(2.5)
            st = tr.orderStatus.status
            # An order IBKR refuses comes back Inactive/ApiCancelled — that is a
            # FAILURE, not a placement. Silently counting it as PLACED is exactly
            # how a "we exited" belief diverges from reality.
            bad = st in ("Inactive", "ApiCancelled", "Cancelled")
            why = ""
            if bad:
                logs = getattr(tr, "log", []) or []
                why = "; ".join(str(getattr(e, "message", "")) for e in logs[-2:])[:160]
            placed.append(dict(o, status=("REJECTED" if bad else "PLACED"), limit=lmt,
                               order_id=tr.order.orderId, order_status=st, note=why))
    finally:
        try: ib.disconnect()
        except Exception: pass
    return placed

def _plan_scope(plan):
    """Symbols this plan actually depends on. Legacy holdings are deliberately out of
    scope: an unrelated AGQ fill between review and execution says nothing about
    whether these orders are still correct, and aborting on it would throw away a
    valid plan (and, before the refusal/malfunction split, count toward the kill
    switch)."""
    return {o["symbol"] for o in plan} | {"SGOV"}

def _scoped_positions(posacct, syms):
    return {a: {s: q for s, q in d.items() if s in syms}
            for a, d in (posacct or {}).items()}

def save_plan(path, plan, t, resting):
    """Freeze the reviewed plan plus the state it assumed, so --live can verify it."""
    syms = _plan_scope(plan)
    snap = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
            "asof": t["asof"], "nav": t["nav"],
            "investable_nav": t.get("investable_nav"), "plan": plan,
            "scope": sorted(syms),
            "positions": _scoped_positions(t.get("positions_by_account"), syms),
            "resting": {k: v.get("net", 0) for k, v in (resting or {}).items()
                        if k in syms}}
    with open(path, "w") as f: json.dump(snap, f, indent=1)

def load_and_verify_plan(path, t, resting):
    """
    Replay guard. The model approved a specific plan against a specific world state;
    execute that plan only if the world still matches. Otherwise abort and let the
    next run rebuild — approving plan A and placing plan B makes the review worthless.
    """
    snap = json.load(open(path))
    errs = []
    age = (dt.datetime.now() - dt.datetime.fromisoformat(snap["ts"])).total_seconds()
    if age > REPLAY_MAX_AGE_SEC:
        errs.append(f"approved plan is {age/60:.0f} min old (max {REPLAY_MAX_AGE_SEC/60:.0f})")
    if snap.get("asof") != t.get("asof"):
        errs.append(f"asof changed {snap.get('asof')} -> {t.get('asof')}")
    syms = set(snap.get("scope") or _plan_scope(snap["plan"]))
    now_pos = _scoped_positions(t.get("positions_by_account"), syms)
    if now_pos != snap.get("positions"):
        errs.append("positions changed since review (plan symbols)")
    now_rest = {k: v.get("net", 0) for k, v in (resting or {}).items() if k in syms}
    if now_rest != snap.get("resting"):
        errs.append("resting orders changed since review (plan symbols)")
    # prices: an after-hours move can put every limit far from market
    live = {}
    for bk in t["buckets"].values():
        if bk.get("symbol"): live[bk["symbol"]] = bk.get("price")
        for lk, lv in (bk.get("legs") or {}).items(): live[lk] = lv.get("price")
    live["SGOV"] = t.get("sgov_price")
    for o in snap["plan"]:
        p_then, p_now = o.get("price"), live.get(o["symbol"])
        if p_then and p_now:
            d = abs(p_now - p_then)/p_then
            if d > REPLAY_MAX_DRIFT:
                errs.append(f"{o['symbol']} moved {d:.1%} since review "
                            f"(${p_then:.2f} -> ${p_now:.2f})")
    return snap["plan"], errs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="actually place orders")
    ap.add_argument("--establish", action="store_true")
    ap.add_argument("--save-plan", metavar="FILE",
                    help="dry run: write the plan + a freshness fingerprint for later replay")
    ap.add_argument("--plan", metavar="FILE",
                    help="--live: replay EXACTLY this approved plan instead of recomputing")
    ap.add_argument("--nav", type=float, default=None)
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=4001)
    ap.add_argument("--client-id", type=int, default=52)
    a = ap.parse_args()

    got, why = acquire_lock()
    if not got:
        print(f"LOCKED: {why}", file=sys.stderr); sys.exit(2)
    try:
        _main(a)
    finally:
        release_lock()

def _main(a):
    if os.path.exists(KILL):
        print(f"KILL SWITCH ACTIVE ({KILL}):\n{open(KILL).read()}", file=sys.stderr)
        notify("v3 auto-exec halted", "Kill switch is set; no orders placed.", "high")
        sys.exit(4)

    try:
        t = get_targets(a.establish, a.nav)
    except Exception as e:
        n = bump_fail(f"engine: {e}", key="engine")
        emit(f"engine failed ({n} malfunction(s)): {e}"); sys.exit(3)

    try:
        resting = get_resting(a.host, a.port, a.client_id + 30)
    except Exception as e:
        n = bump_fail(f"resting-orders: {e}", key="resting")
        emit(f"could not read resting orders ({n} malfunction(s)): {e}")
        sys.exit(3)

    sess = t.get("asof")
    naverr = nav_sanity(t["nav"])
    if naverr:
        # a NAV jump this large is bad data, not a market move -> malfunction
        emit(f"  BLOCKED: {naverr}")
        notify("v3 auto-exec BLOCKED", naverr[:250], "urgent")
        bump_fail(naverr, key="nav-sanity", session=sess); sys.exit(2)

    if a.live and a.plan:
        plan, verrs = load_and_verify_plan(a.plan, t, resting)
        nav = t["nav"]
        print(f"v3_execute [REPLAY of approved plan]  {a.plan}")
        if verrs:
            for e in verrs: emit(f"  ABORTED: {e}")
            log_audit(dict(mode="REPLAY-ABORT", reasons=verrs, plan=plan))
            # the guard working as designed is a refusal, not a malfunction
            note_refusal("replay: " + verrs[0], key="replay", session=sess)
            sys.exit(2)
        for o in plan:
            print(f"  {o['action']:<4} {o['qty']:>5} {o['symbol']:<6} @~${o['price']:>8.2f}  [{o['account']}]")
        placed = place(plan, a.host, a.port, a.client_id)
        log_audit(dict(mode="LIVE", replayed_from=a.plan, placed=placed))
        ok = [p for p in placed if p["status"] == "PLACED"]
        # A broker rejection is a MALFUNCTION and must not clear the counter. This is
        # the path run.sh --live actually takes; the identical check further down only
        # ever ran in the non-replay path, so 2026-09-01's Error 201 on QLD was audited
        # and then immediately cleared instead of counted.
        rej = [p for p in placed if p["status"] in ("REJECTED", "FAILED")]
        if rej:
            detail = "; ".join(f"{r['action']} {r['qty']} {r['symbol']} {r.get('note','')}"
                               for r in rej)[:200]
            bump_fail("rejected: " + detail, key="rejected", session=sess)
            for r in rej: emit(f"  REJECTED: {r['symbol']} {r.get('note','') or '(no reason returned)'}")
        else:
            clear_fail()
        print("\n  " + "\n  ".join(f"{p['status']}: {p['symbol']} {p.get('note','')}" for p in placed))
        notify(("⚠ v3 executed %d, REJECTED %d" % (len(ok), len(rej))) if rej
               else f"v3 executed {len(ok)} order(s)",
               "; ".join(f"{p['action']} {p['qty']} {p['symbol']} @ {p.get('limit')}" for p in ok)[:300] or "none",
               "urgent" if rej else "high")
        return

    plan, nav = build_plan(t, resting)
    # Advisory: the schedule always runs ~5h after the close, so orders normally rest
    # until the next open. A manual run during RTH fills within seconds instead.
    try:
        from zoneinfo import ZoneInfo
        et = dt.datetime.now(ZoneInfo("America/New_York"))
        rth = et.weekday() < 5 and (9, 30) <= (et.hour, et.minute) < (16, 0)
    except Exception:
        rth = False
    mode = "LIVE" if a.live else "DRY RUN"
    print(f"v3_execute [{mode}]  asof {t['asof']}  NAV ${nav:,.0f}"
          + ("   ⚠ US market OPEN — orders will fill immediately, not rest to the open" if rth else ""))
    if not plan:
        print("  nothing to do — all buckets within band"); clear_fail(); return

    if resting:
        # Prices come from the engine's `prices` map, which now covers EVERY held
        # symbol. It used to read only t["buckets"], so legacy symbols resolved to
        # mkt=None and the stale-limit warning silently never fired for exactly the
        # orders most likely to be stale (AGQ sat at a $129.89 limit vs $82.67).
        prices = dict(t.get("prices") or {})
        for bk in t["buckets"].values():
            if bk.get("symbol"): prices.setdefault(bk["symbol"], bk.get("price"))
            for lk, lv in (bk.get("legs") or {}).items():
                prices.setdefault(lk, lv.get("price"))
        print("  resting orders on the book:")
        for sym, r in sorted(resting.items()):
            for od in r["orders"]:
                mkt = prices.get(sym)
                far = ""
                if mkt and od["limit"]:
                    off = abs(od["limit"]-mkt)/mkt
                    if off > STALE_LIMIT_PCT:
                        far = f"  ⚠ {off:.1%} from market ${mkt:.2f} — unlikely to fill"
                elif od["limit"]:
                    far = "  ⚠ no market price — cannot judge fillability"
                # orderId is 0 for anything this system did not place; permId is the
                # only stable handle and cid!=1 orders are NOT ours to cancel/modify.
                ref = f"#{od['order_id']}" if od.get("ours") else f"perm:{od.get('perm_id')}"
                own = "" if od.get("ours") else f" [cid={od.get('client_id')} not ours]"
                print(f"    {ref:<14} {od['action']:<4} {od['qty']:>5.0f} {sym:<6} "
                      f"{od['type']} {od['limit'] or ''} {od['tif']} [{od['account']}]{own}{far}")
        print()
    for o in plan:
        print(f"  {o['action']:<4} {o['qty']:>5} {o['symbol']:<6} @~${o['price']:>8.2f} "
              f"= ${o['notional']:>10,.0f}  [{o['account']}]  {o['reason']}")
    print(f"  total notional ${sum(o['notional'] for o in plan):,.0f} "
          f"({sum(o['notional'] for o in plan)/nav:.1%} NAV)")

    errs, notes = check_rails(plan, nav, t)
    if errs:
        for e in errs: emit(f"  BLOCKED: {e}")
        log_audit(dict(mode=mode, blocked=errs, plan=plan))
        note_refusal("rails: " + errs[0], key="rails:" + errs[0][:40], session=sess)
        sys.exit(2)
    if notes:
        print()
        for n in notes: print(f"  CLAMPED: {n}")
        print(f"  -> revised total ${sum(o['notional'] for o in plan):,.0f} "
              f"({sum(o['notional'] for o in plan)/nav:.1%} NAV)")
        for o in plan:
            print(f"     {o['action']:<4} {o['qty']:>5} {o['symbol']:<6} = ${o['notional']:>10,.0f}")
    if not plan:
        print("  nothing left after clamping"); clear_fail(); return

    plan, fund_errs, fund_notes = add_funding(plan, t, resting)
    # Print the funding picture BEFORE any exit: on a shortfall this used to die at
    # sys.exit(2) before the funding legs were shown, so the reviewer saw a plan with
    # the funding half missing and no indication anything had gone wrong.
    if fund_notes or fund_errs or any(o.get("funding") for o in plan):
        print("\n  funding (buys are capped at TODAY's spendable cash; these SELLs "
              "top the account up for the NEXT run):")
        for n_ in fund_notes:
            print(f"     - {n_}")
        for o in plan:
            if o.get("funding"):
                print(f"     SELL {o['qty']:>5} SGOV = ${o['notional']:>9,.0f}  [{o['account']}]  {o['reason']}")
    if fund_errs:
        for e in fund_errs: emit(f"  BLOCKED: {e}")
        log_audit(dict(mode=mode, blocked=fund_errs, plan=plan))
        note_refusal("funding: " + fund_errs[0],
                     key="funding:" + fund_errs[0][:40], session=sess)
        sys.exit(2)

    if not a.live:
        if a.save_plan:
            save_plan(a.save_plan, plan, t, resting)
            print(f"\n  approved-plan artifact written: {a.save_plan}")
        print("  dry run — no orders sent. run.sh replays this exact plan on APPROVE.")
        log_audit(dict(mode="DRY", plan=plan)); return

    try:
        placed = place(plan, a.host, a.port, a.client_id)
    except Exception as e:
        n = bump_fail(f"place: {e}", key="place", session=sess)
        emit(f"placement failed ({n} malfunction(s)): {e}")
        notify("🚨 v3 order placement FAILED", str(e)[:300], "urgent"); sys.exit(3)

    log_audit(dict(mode="LIVE", placed=placed, engine=t["buckets"]))
    ok = [p for p in placed if p["status"] == "PLACED"]
    rej = [p for p in placed if p["status"] in ("REJECTED", "FAILED")]
    if rej:
        # the broker refusing an order we constructed is our bug, not a rail working
        bump_fail("rejected: " + "; ".join(f"{r['symbol']} {r.get('note','')}"
                                           for r in rej)[:180],
                  key="rejected", session=sess)
    else:
        clear_fail()
    lines = [f"{p['action']} {p['qty']} {p['symbol']} @ {p.get('limit')}" for p in ok]
    print("\n  " + "\n  ".join(f"{p['status']}: {p['symbol']} {p.get('note','')}" for p in placed))
    notify(f"v3 executed {len(ok)} order(s)", "; ".join(lines)[:300] or "none", "high")

if __name__ == "__main__":
    main()
