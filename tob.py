#!/usr/bin/env python3
"""
tob.py — Tactical Opportunity Book (Playbook v3 §10, approved 2026-11-02).

Short-term bets that sit BESIDE the v3 buckets, never inside them. Every bet is one
ticket in state/tactical.json and walks this lifecycle:

  DRAFT         an advisor session drafts the exact entry and exit   (tob.py draft)
  APPROVED      Shawn approves it at a real terminal                 (tob.py approve)
  ENTRY_PLACED  the entry limit is resting at the broker
  OPEN          the entry filled (fully, or partly and the rest expired)
  EXIT_PLACED   the exit is resting: a trailing stop, or a time-exit sell
  CLOSED        the exit filled             CANCELLED  never filled / withdrawn / expired

An exit cannot be placed until the entry fills, so the DAILY RUN is the monitor:
`tob.py sync` reconciles every active bet against the broker first, then v3_execute
adds the bet's next order (protective stop, or time exit) to the plan the model reviews.
A bet stops being monitored once it is CLOSED or CANCELLED.

Why the plumbing matters: the engine sizes each ticker across all accounts, so on
2026-11-01 any dip-buy — in QLD, or in a non-playbook ticker counted as legacy — would
have been trimmed or offset by the very next run. The engine therefore subtracts OPEN
tactical shares from bucket drift, and the executor leaves tactical orders out of its
pending-order netting.

    ./tob.py list                       # every bet, newest first
    ./tob.py show T-20261102-QLD        # full ticket
    ./tob.py draft --setup A --thesis "..." --invalidation "..."
    ./tob.py approve T-20261102-QLD [--place-now]   # HUMAN ONLY: needs a terminal
    ./tob.py cancel T-20261102-QLD
    ./tob.py sync                       # reconcile with the broker (the daily run does this)

Exit: 0 ok · 2 refused by a rail · 3 IBKR failure · 4 kill switch · 5 not a terminal
"""
import argparse, contextlib, datetime as dt, fcntl, hashlib, json, math, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state")
LEDGER = os.path.join(STATE, "tactical.json")
LEDGER_LOCK = os.path.join(STATE, "tactical.lock")
PRICES = os.path.join(STATE, "prices")

# ---- book rules (Playbook v3 §10) ------------------------------------------
GROSS_CAP_PCT = 0.05        # all open tactical bets together, of investable NAV
SGOV_FLOOR_PCT = 0.10       # cash + SGOV may not fall below this after an entry
MAX_ACTIVE = 2              # open bets at once, and at most one per setup
COOLDOWN_SESSIONS = 21      # after a stop-out, no new bet of that setup for this long
ENTRY_COLLAR = 0.01         # entry limit = last close +1%: marketable at the open
ENTRY_VALID_SESSIONS = 2    # GTD: the broker cancels an unfilled entry after this
APPROVAL_VALID_SESSIONS = 3 # an approved ticket not placed by then is withdrawn
EXIT_COLLAR = 0.005         # time-exit / breached-stop sell limit = last close -0.5%
SYNC_MAX_AGE_SEC = 3*3600   # the executor refuses to plan on an older reconciliation

SETUPS = {
    # A — uptrend pullback. Tested: ai-infra-bt/tactical/p2,p3 (2026-11-01).
    "A": dict(symbol="QLD", signal="QQQ", dip_min=0.075, lookback=63,
              trail_pct=0.20, max_sessions=63, risk_pct=0.01),
    # B — conviction ticket. UNTESTED by design: half the risk, own scorecard.
    "B": dict(symbol=None, risk_pct=0.005, max_sessions_cap=126),
}
ACTIVE = ("APPROVED", "ENTRY_PLACED", "OPEN", "EXIT_PLACED")
HOLDING = ("ENTRY_PLACED", "OPEN", "EXIT_PLACED")   # states that can hold filled shares


# ---- ledger ------------------------------------------------------------------
def load(path=None):
    path = path or LEDGER
    if not os.path.exists(path): return {"bets": []}
    with open(path) as f: return json.load(f)


def save(ledger, path=None):
    path = path or LEDGER
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(ledger, f, indent=1)
    os.replace(tmp, path)        # atomic: a crash never leaves half a ledger


@contextlib.contextmanager
def locked(path=None):
    """Read-modify-write the ledger under an exclusive lock; yields the ledger."""
    os.makedirs(STATE, exist_ok=True)
    with open(LEDGER_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        led = load(path)
        yield led
        save(led, path)


def now_iso(): return dt.datetime.now().isoformat(timespec="seconds")


def event(bet, msg):
    bet.setdefault("events", []).append({"ts": now_iso(), "msg": msg})


def find(ledger, bet_id):
    for b in ledger.get("bets", []):
        if b["id"] == bet_id: return b
    return None


def active(ledger): return [b for b in ledger.get("bets", []) if b["status"] in ACTIVE]


def open_qty(bet):
    """Shares this bet currently owns at the broker."""
    if bet["status"] not in HOLDING: return 0
    return int(round((bet.get("filled_qty") or 0) - (bet.get("exit_filled_qty") or 0)))


def holdings(ledger):
    """{account: {symbol: shares}} owned by tactical bets — excluded from bucket drift."""
    out = {}
    for b in ledger.get("bets", []):
        q = open_qty(b)
        if q > 0:
            out.setdefault(b["account"], {}).setdefault(b["symbol"], 0)
            out[b["account"]][b["symbol"]] += q
    return out


def holdings_by_symbol(ledger):
    out = {}
    for d in holdings(ledger).values():
        for s, q in d.items(): out[s] = out.get(s, 0) + q
    return out


def order_perm_ids(ledger):
    """perm ids of every tactical order that may still be live at the broker."""
    ids = set()
    for b in active(ledger):
        for k in ("entry_perm_id", "exit_perm_id"):
            if b.get(k): ids.add(int(b[k]))
    return ids


def is_fresh(ledger, max_age=SYNC_MAX_AGE_SEC):
    ts = ledger.get("synced_at")
    if not ts: return False
    return (dt.datetime.now() - dt.datetime.fromisoformat(ts)).total_seconds() <= max_age


def ticket_fields(bet):
    """What Shawn approves. Any change after approval invalidates the approval."""
    return {k: bet.get(k) for k in ("id", "setup", "symbol", "account", "entry", "exit")}


def ticket_hash(bet):
    raw = json.dumps(ticket_fields(bet), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def fingerprint(ledger):
    """The part of the ledger a reviewed plan depends on (replay guard)."""
    return {b["id"]: [b["status"], b.get("entry_perm_id"), b.get("exit_perm_id"), open_qty(b)]
            for b in active(ledger)}


# ---- calendar ------------------------------------------------------------------
# Weekdays, not exchange sessions: a holiday shifts a 63-session hold by a day or two,
# which is far inside the noise of the rule it implements.
def add_weekdays(d, n):
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5: n -= 1
    return d


def weekdays_between(a, b):
    """Weekdays strictly after a, up to and including b."""
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        if d.weekday() < 5: n += 1
    return n


def _date(s): return dt.date.fromisoformat(str(s)[:10])


# ---- signals ---------------------------------------------------------------------
def read_closes(symbol):
    path = os.path.join(PRICES, symbol.replace(" ", "_") + ".json")
    if not os.path.exists(path): return {}
    return json.load(open(path)).get("closes", {})


def setup_a_check(closes, lookback=63, dip_min=0.075):
    """Setup A trigger on the signal series (QQQ). Same month logic as v3_engine.regime_on:
    the trend leg reads the last COMPLETED month present in the data (mc[-2])."""
    import v3_engine as E
    ds = sorted(closes); c = [closes[d] for d in ds]
    if len(c) < lookback + 1: return dict(ok=False, why=f"only {len(c)} closes")
    hi = max(c[-(lookback+1):]); last = c[-1]; dip = 1 - last/hi
    mc, months = E.monthly_closes(ds, c)
    if len(mc) < E.GATE_MONTHS + 1: return dict(ok=False, why="trend leg not armed")
    sma = sum(mc[-(E.GATE_MONTHS+1):-1]) / E.GATE_MONTHS
    trend_on = mc[-2] >= sma
    ok = trend_on and dip >= dip_min
    why = (f"{ds[-1]} close {last:.2f} is {dip:.1%} below its {lookback}-session high {hi:.2f} "
           f"(need ≥{dip_min:.1%}); {months[-2]} close {mc[-2]:.2f} vs 10-mo avg {sma:.2f} → "
           f"trend leg {'ON' if trend_on else 'OFF'}")
    return dict(ok=ok, asof=ds[-1], last=last, high=hi, dip=round(dip, 4),
                trend_on=trend_on, month_close=mc[-2], sma=round(sma, 2), why=why)


# ---- rails -----------------------------------------------------------------------
def _cash_and_sgov(t):
    cash = sum(max(0.0, float(v)) for v in (t.get("cash_by_account") or {}).values())
    sg = sum(float(d.get("SGOV", 0)) for d in (t.get("positions_by_account") or {}).values())
    return cash + sg*float(t.get("sgov_price") or 0)


def committed_by_account(resting):
    """Cash already promised to resting BUYs (IBKR's cash figure does not subtract them)."""
    out = {}
    for r in (resting or {}).values():
        for od in r.get("orders", []):
            if od.get("action") == "BUY" and od.get("account"):
                out[od["account"]] = out.get(od["account"], 0.0) + float(od["qty"])*float(od.get("limit") or 0)
    return out


def spendable(t, account, resting=None):
    cash = float((t.get("cash_by_account") or {}).get(account, 0.0))
    avail = float((t.get("available_by_account") or {}).get(account, cash))
    return max(0.0, min(cash, avail) - committed_by_account(resting).get(account, 0.0))


def exposure(bet, prices):
    """Dollars a bet ties up: shares owned at market, plus any unfilled entry at its limit."""
    e = bet.get("entry") or {}
    unfilled = 0
    if bet["status"] in ("APPROVED", "DRAFT"): unfilled = e.get("qty", 0)
    elif bet["status"] == "ENTRY_PLACED": unfilled = e.get("qty", 0) - (bet.get("filled_qty") or 0)
    px = float(prices.get(bet["symbol"]) or e.get("limit") or 0)
    return open_qty(bet)*px + max(0, unfilled)*float(e.get("limit") or 0)


def validate(bet, t, ledger, resting=None, stage="draft", signal=None, today=None):
    """Every rule a ticket must pass. Returns a list of reasons; empty means it may proceed.
    stage: draft | approve | place. All are HARD refusals — a tactical bet is optional, so
    there is no clamp-and-continue the way bucket rebalances have."""
    import v3_execute as X
    errs = []
    today = today or dt.date.today()
    inav = float(t.get("investable_nav") or t["nav"])
    prices = dict(t.get("prices") or {})
    sym, setup = bet["symbol"], bet["setup"]
    e, x = bet["entry"], bet["exit"]
    if setup not in SETUPS: errs.append(f"unknown setup {setup}")
    if sym not in X.WHITELIST or sym == "SGOV": errs.append(f"{sym} is not a tradable playbook symbol")
    if e.get("action") != "BUY": errs.append("only long entries are allowed")
    if (e.get("qty") or 0) <= 0: errs.append("entry qty must be positive")
    if bet["account"] not in X.DEFAULT_ACCOUNT_TYPES: errs.append(f"unknown account {bet['account']}")
    if stage in ("approve", "place") and bet.get("approved_hash") not in (None, ticket_hash(bet)):
        errs.append("ticket changed after approval")
    if errs: return errs

    # the bet's own size: dollars at risk if the stop is hit, and gross exposure
    notional = e["qty"]*e["limit"]
    risk = notional*x["stop_pct"]
    cap_risk = SETUPS[setup]["risk_pct"]*inav
    if risk > cap_risk*1.02:
        errs.append(f"risk ${risk:,.0f} ({risk/inav:.2%} NAV) exceeds the setup-{setup} unit "
                    f"${cap_risk:,.0f} ({SETUPS[setup]['risk_pct']:.1%})")
    others = [b for b in active(ledger) if b["id"] != bet["id"]]
    gross = sum(exposure(b, prices) for b in others) + notional
    if gross > GROSS_CAP_PCT*inav*1.02:
        errs.append(f"tactical gross ${gross:,.0f} would exceed {GROSS_CAP_PCT:.0%} of investable "
                    f"NAV (${GROSS_CAP_PCT*inav:,.0f})")
    if len(others) >= MAX_ACTIVE: errs.append(f"already {len(others)} active bets (max {MAX_ACTIVE})")
    if any(b["setup"] == setup for b in others): errs.append(f"a setup-{setup} bet is already active")
    # cooldown after a stop-out of the same setup
    for b in ledger.get("bets", []):
        if (b["setup"] == setup and b["status"] == "CLOSED" and b.get("exit_kind") == "STOP"
                and b.get("closed_at")
                and weekdays_between(_date(b["closed_at"]), today) < COOLDOWN_SESSIONS):
            errs.append(f"setup {setup} stopped out on {b['closed_at'][:10]}; "
                        f"cooldown {COOLDOWN_SESSIONS} sessions")
    # cash: never margin, never below the SGOV floor
    if stage != "approve":
        room = spendable(t, bet["account"], resting)
        if notional*1.01 > room:
            errs.append(f"{bet['account']} has ${room:,.0f} spendable, entry needs "
                        f"${notional*1.01:,.0f} (no margin, no same-night SGOV funding)")
    if _cash_and_sgov(t) - notional < SGOV_FLOOR_PCT*inav:
        errs.append(f"cash+SGOV would fall below the {SGOV_FLOOR_PCT:.0%} floor")

    # the setup's own trigger, re-checked at every stage: a pre-registered rule, not a mood
    if setup == "A":
        core = (t.get("buckets") or {}).get("core") or {}
        if not core.get("gate_on", False): errs.append("core gate is DEFENSIVE — setup A needs it ON")
        sg = signal or setup_a_check(read_closes(SETUPS["A"]["signal"]))
        if not sg.get("ok"): errs.append("setup A trigger not met: " + sg.get("why", "?"))
    elif setup == "B":
        if not (bet.get("thesis") and bet.get("invalidation")):
            errs.append("setup B needs a written thesis and invalidation")
        if x.get("max_sessions", 0) > SETUPS["B"]["max_sessions_cap"]:
            errs.append(f"setup B hold is capped at {SETUPS['B']['max_sessions_cap']} sessions")

    if stage == "place":
        last = prices.get(sym)
        if last and abs(last - bet["ref_price"])/bet["ref_price"] > 0.03:
            errs.append(f"{sym} moved {abs(last-bet['ref_price'])/bet['ref_price']:.1%} since the "
                        f"ticket was drafted (${bet['ref_price']:.2f} -> ${last:.2f}); redraft")
        if os.path.exists(X.KILL): errs.append("kill switch is set")
    return errs


# ---- drafting ---------------------------------------------------------------------
def size(setup, inav, limit, stop_pct):
    """Shares such that a stop-out loses at most the setup's risk unit, and the bet stays
    inside the gross cap. For setup A: 1% / 20% = 5% of NAV."""
    by_risk = SETUPS[setup]["risk_pct"]*inav / (limit*stop_pct)
    by_gross = GROSS_CAP_PCT*inav / limit
    return int(math.floor(min(by_risk, by_gross)))


def pick_account(t, symbol, cost, resting=None):
    import v3_execute as X
    for a in X.ACCOUNT_PREFERENCE.get(symbol, []):
        if spendable(t, a, resting) >= cost*1.01: return a
    return None


def draft(t, ledger, setup, today=None, symbol=None, qty=None, stop_pct=None,
          max_sessions=None, thesis="", invalidation="", account=None, signal=None):
    today = today or dt.date.today()
    S = SETUPS[setup]
    symbol = symbol or S["symbol"]
    if not symbol: raise ValueError("setup B needs --symbol")
    stop_pct = stop_pct if stop_pct is not None else S.get("trail_pct")
    max_sessions = max_sessions or S.get("max_sessions")
    if not stop_pct or not max_sessions: raise ValueError("setup B needs --stop-pct and --hold")
    ref = float(t["prices"][symbol])
    limit = round(ref*(1+ENTRY_COLLAR), 2)
    inav = float(t.get("investable_nav") or t["nav"])
    q = size(setup, inav, limit, stop_pct)
    if qty: q = min(q, int(qty))
    account = account or pick_account(t, symbol, q*limit) or \
        __import__("v3_execute").ACCOUNT_PREFERENCE[symbol][0]
    bid = f"T-{today:%Y%m%d}-{symbol.replace(' ', '')}"
    n = sum(1 for b in ledger.get("bets", []) if b["id"].startswith(bid))
    if n: bid += f"-{n+1}"
    sg = signal if signal is not None else (setup_a_check(read_closes(S["signal"])) if setup == "A" else None)
    bet = dict(
        id=bid, setup=setup, symbol=symbol, account=account, status="DRAFT",
        thesis=thesis, invalidation=invalidation,
        entry=dict(action="BUY", qty=q, limit=limit, tif="GTD", outside_rth=True,
                   good_till=add_weekdays(today, ENTRY_VALID_SESSIONS).isoformat()),
        exit=dict(kind="TRAIL", stop_pct=stop_pct, max_sessions=max_sessions),
        ref_price=ref, asof=t.get("asof"), nav=t["nav"], investable_nav=inav,
        risk_usd=round(q*limit*stop_pct, 2), notional=round(q*limit, 2),
        signal=sg, drafted_at=now_iso())
    bet["ticket_hash"] = ticket_hash(bet)
    event(bet, f"drafted: BUY {q} {symbol} @ {limit} [{account}]")
    return bet


# ---- broker reconciliation ----------------------------------------------------------
def _fill_from(snapshot, perm, bet_key, bet):
    """Merge a broker order's state + executions into the bet. Returns (filled, status, avg)."""
    o = (snapshot.get("orders") or {}).get(perm) or {}
    execs = (snapshot.get("execs") or {}).get(perm) or []
    store = bet.setdefault(bet_key, {})
    for ex in execs: store[ex["exec_id"]] = dict(shares=ex["shares"], price=ex["price"], ts=ex["ts"])
    sh = sum(v["shares"] for v in store.values())
    avg = (sum(v["shares"]*v["price"] for v in store.values())/sh) if sh else None
    filled = max(sh, float(o.get("filled") or 0))
    return filled, o.get("status"), avg


DEAD = ("Cancelled", "ApiCancelled", "Inactive")


def apply_broker(bet, snapshot, today=None):
    """Advance one bet's state from a broker snapshot. Pure — returns a list of alerts.

    snapshot = {"orders": {perm_id: {status, filled, total}},   # open AND completed
                "execs":  {perm_id: [{exec_id, shares, price, ts}]},
                "positions": {account: {symbol: qty}}}"""
    today = today or dt.date.today()
    alerts = []
    st = bet["status"]

    if st == "APPROVED" and not bet.get("entry_perm_id"):
        if weekdays_between(_date(bet["approved_at"]), today) > APPROVAL_VALID_SESSIONS:
            bet["status"] = "CANCELLED"; bet["closed_at"] = now_iso()
            event(bet, f"approval expired unplaced after {APPROVAL_VALID_SESSIONS} sessions")
        return alerts

    if st == "ENTRY_PLACED":
        perm = int(bet["entry_perm_id"])
        filled, status, avg = _fill_from(snapshot, perm, "entry_execs", bet)
        known = perm in (snapshot.get("orders") or {})
        bet["filled_qty"] = int(round(filled))
        if avg: bet["fill_price"] = round(avg, 4)
        total = bet["entry"]["qty"]
        done = status == "Filled" or filled >= total
        dead = status in DEAD or (not known and _date(bet["entry"]["good_till"]) < today)
        if done or (dead and filled > 0):
            bet["status"] = "OPEN"; bet["fill_date"] = today.isoformat()
            if not bet.get("fill_price"):
                bet["fill_price"] = bet["entry"]["limit"]; bet["fill_price_estimated"] = True
                alerts.append(f"{bet['id']}: entry filled but no execution rows visible — "
                              f"fill price recorded as the limit {bet['entry']['limit']}")
            bet["expiry_date"] = add_weekdays(today, bet["exit"]["max_sessions"]).isoformat()
            event(bet, f"entry filled {bet['filled_qty']}/{total} @ {bet['fill_price']}; "
                       f"time exit {bet['expiry_date']}")
            alerts.append(f"{bet['id']}: entry FILLED {bet['filled_qty']} {bet['symbol']} "
                          f"@ {bet['fill_price']} — the next run places the stop")
        elif dead:
            bet["status"] = "CANCELLED"; bet["closed_at"] = now_iso()
            event(bet, f"entry ended unfilled ({status or 'not found at broker'})")
            alerts.append(f"{bet['id']}: entry ended UNFILLED ({status or 'expired'})")
        elif not known:
            alerts.append(f"{bet['id']}: entry perm {perm} not visible at the broker yet")

    elif st == "EXIT_PLACED":
        perm = int(bet["exit_perm_id"])
        filled, status, avg = _fill_from(snapshot, perm, "exit_execs", bet)
        known = perm in (snapshot.get("orders") or {})
        bet["exit_filled_qty"] = int(round(filled))
        if avg: bet["exit_price"] = round(avg, 4)
        held = (bet.get("filled_qty") or 0)
        if status == "Filled" or filled >= held:
            bet["status"] = "CLOSED"; bet["closed_at"] = now_iso()
            if not bet.get("exit_price"):
                bet["exit_price"] = bet.get("exit_limit") or bet.get("fill_price")
                bet["exit_price_estimated"] = True
            ep, xp = bet["fill_price"], bet["exit_price"]
            bet["pnl_usd"] = round((xp - ep)*held, 2)
            bet["r_multiple"] = round((xp - ep)/(ep*bet["exit"]["stop_pct"]), 2)
            event(bet, f"closed by {bet['exit_kind']} @ {xp}: P&L ${bet['pnl_usd']:,.0f}, "
                       f"{bet['r_multiple']:+.2f}R")
            alerts.append(f"{bet['id']}: CLOSED by {bet['exit_kind']} @ {xp} "
                          f"({bet['r_multiple']:+.2f}R, ${bet['pnl_usd']:,.0f})")
        elif status in DEAD or not known:
            # nobody in this system cancels a stop except the time exit, which records
            # its own replacement — so a vanished exit means the bet is unprotected again
            bet["status"] = "OPEN"; bet.pop("exit_perm_id", None)
            event(bet, f"exit order {perm} is gone ({status or 'not found'}) — back to OPEN")
            alerts.append(f"{bet['id']}: exit order {perm} disappeared ({status or 'not found'}); "
                          "the next run re-places it")

    # the account must still hold what the ledger says it does
    q = open_qty(bet)
    if q > 0:
        have = float(((snapshot.get("positions") or {}).get(bet["account"]) or {}).get(bet["symbol"], 0))
        if have + 0.5 < q:
            bet["mismatch"] = f"ledger {q} {bet['symbol']} but {bet['account']} holds {have:.0f}"
            alerts.append(f"{bet['id']}: MISMATCH — {bet['mismatch']}")
        else:
            bet.pop("mismatch", None)
    return alerts


def broker_snapshot(perm_ids, host="127.0.0.1", port=4001, cid=63):
    from ib_async import IB, ExecutionFilter
    ib = IB(); ib.connect(host, port, clientId=cid, timeout=30)
    try:
        orders = {}
        ib.reqAllOpenOrders(); ib.sleep(2)
        for tr in ib.openTrades():
            orders[tr.order.permId] = dict(status=tr.orderStatus.status,
                                           filled=float(tr.orderStatus.filled or 0),
                                           total=float(tr.order.totalQuantity))
        for tr in ib.reqCompletedOrders(False):
            p = tr.order.permId
            if p in perm_ids and p not in orders:
                orders[p] = dict(status=tr.orderStatus.status,
                                 filled=float(getattr(tr.order, "filledQuantity", 0) or 0),
                                 total=float(tr.order.totalQuantity))
        execs = {}
        for fl in ib.reqExecutions(ExecutionFilter()):
            e = fl.execution
            if e.permId in perm_ids:
                execs.setdefault(e.permId, []).append(dict(
                    exec_id=e.execId, shares=float(e.shares), price=float(e.price), ts=str(e.time)))
        positions = {}
        for p in ib.positions():
            positions.setdefault(p.account, {})[p.contract.symbol] = float(p.position)
        return dict(orders={k: v for k, v in orders.items() if k in perm_ids}, execs=execs,
                    positions=positions)
    finally:
        try: ib.disconnect()
        except Exception: pass


def sync(host="127.0.0.1", port=4001, cid=63, today=None, snapshot_fn=None):
    """Reconcile every active bet with the broker. Raises on an IBKR failure."""
    with locked() as led:
        act = active(led)
        if not act:
            led["synced_at"] = now_iso(); return []
        perms = order_perm_ids(led)
        snap = (snapshot_fn or broker_snapshot)(perms, host, port, cid)
        alerts = []
        for b in act: alerts += apply_broker(b, snap, today)
        led["synced_at"] = now_iso()
        return alerts


# ---- the daily monitor: next lifecycle order for each bet -------------------------------
def plan_actions(ledger, t, resting=None, today=None):
    """Orders the daily run should add for tactical bets. Returns (orders, notes, blocks).
    Every order carries tob_id/tob_step so placement can be recorded back on the ticket."""
    today = today or dt.date.today()
    prices = dict(t.get("prices") or {})
    orders, notes, blocks = [], [], []
    acts = active(ledger)
    if acts and not is_fresh(ledger):
        blocks.append(f"tactical ledger last reconciled {ledger.get('synced_at') or 'never'} — "
                      "stale; refusing to plan around unknown tactical fills")
        return orders, notes, blocks
    for b in acts:
        if b.get("mismatch"):
            blocks.append(f"{b['id']}: {b['mismatch']} — fix the ledger before trading {b['symbol']}")
            continue
        sym, last = b["symbol"], prices.get(b["symbol"])
        tag = f"TOB {b['id']} setup {b['setup']}"
        if b["status"] == "APPROVED" and not b.get("entry_perm_id"):
            errs = validate(b, t, ledger, resting, stage="place", today=today)
            if errs:
                notes.append(f"{b['id']}: approved entry NOT placed — " + "; ".join(errs))
                continue
            e = b["entry"]
            orders.append(dict(symbol=sym, action="BUY", qty=e["qty"], price=e["limit"],
                               limit=e["limit"], notional=e["qty"]*e["limit"], account=b["account"],
                               pending=0, tactical=True, tob_id=b["id"], tob_step="entry",
                               tif=e["tif"], good_till=e["good_till"], outside_rth=e["outside_rth"],
                               reason=f"{tag}: approved entry"))
        elif b["status"] == "OPEN":
            q = open_qty(b)
            if q <= 0 or not last: continue
            closes = read_closes(sym)
            since = [v for d, v in closes.items() if d >= b["fill_date"]]
            peak = max([b["fill_price"], last] + since)
            stop = round(peak*(1 - b["exit"]["stop_pct"]), 2)
            expired = _date(b["expiry_date"]) <= today
            if expired or last <= stop:
                why = "time exit reached" if expired else f"last {last} already through stop {stop}"
                orders.append(dict(symbol=sym, action="SELL", qty=q, price=last,
                                   limit=round(last*(1-EXIT_COLLAR), 2), notional=q*last,
                                   account=b["account"], pending=0, tactical=True, tob_id=b["id"],
                                   tob_step="time_exit" if expired else "stop_breached",
                                   reason=f"{tag}: {why}"))
            else:
                orders.append(dict(symbol=sym, action="SELL", qty=q, price=last, notional=q*last,
                                   account=b["account"], pending=0, tactical=True, tob_id=b["id"],
                                   tob_step="stop", order_type="TRAIL",
                                   trail_pct=b["exit"]["stop_pct"]*100, trail_stop=stop,
                                   reason=f"{tag}: protective {b['exit']['stop_pct']:.0%} trailing "
                                          f"stop from peak {peak:.2f} → stop {stop}"))
        elif b["status"] == "EXIT_PLACED" and b.get("exit_kind") == "STOP":
            if _date(b["expiry_date"]) <= today and last:
                q = open_qty(b)
                orders.append(dict(symbol=sym, action="SELL", qty=q, price=last,
                                   limit=round(last*(1-EXIT_COLLAR), 2), notional=q*last,
                                   account=b["account"], pending=0, tactical=True, tob_id=b["id"],
                                   tob_step="time_exit", cancel_perm=b["exit_perm_id"],
                                   reason=f"{tag}: {b['exit']['max_sessions']}-session time exit "
                                          f"(cancels stop {b['exit_perm_id']})"))
    return orders, notes, blocks


def record_placements(placed, ledger_path=None):
    """Write broker ids from v3_execute.place() back onto the tickets."""
    tac = [p for p in placed if p.get("tob_id")]
    if not tac: return
    with locked(ledger_path) as led:
        for p in tac:
            b = find(led, p["tob_id"])
            if not b: continue
            if p.get("status") != "PLACED":
                event(b, f"{p['tob_step']} {p['status']}: {p.get('note','')}"); continue
            if p["tob_step"] == "entry":
                b["status"] = "ENTRY_PLACED"; b["entry_perm_id"] = p["perm_id"]
                b["entry_order_id"] = p.get("order_id"); b["entry_placed_at"] = now_iso()
            else:
                b["status"] = "EXIT_PLACED"; b["exit_perm_id"] = p["perm_id"]
                b["exit_order_id"] = p.get("order_id"); b["exit_placed_at"] = now_iso()
                # a stop already breached at planning time is still a stop-out (cooldown applies)
                b["exit_kind"] = "TIME" if p["tob_step"] == "time_exit" else "STOP"
                if p.get("limit"): b["exit_limit"] = p["limit"]
            event(b, f"{p['tob_step']} PLACED perm {p['perm_id']}: {p['action']} {p['qty']} "
                     f"{p['symbol']} " + (f"trail {p.get('trail_pct')}% stop {p.get('trail_stop')}"
                                         if p.get("order_type") == "TRAIL" else f"@ {p.get('limit')}"))


# ---- rendering ----------------------------------------------------------------------
def render(b, full=False):
    e, x = b["entry"], b["exit"]
    lines = [f"{b['id']}  [{b['status']}]  setup {b['setup']}  {b['symbol']}  account {b['account']}",
             f"  ENTRY  BUY {e['qty']} {b['symbol']} LMT {e['limit']}  ({e['tif']} until "
             f"{e['good_till']}, extended hours {'yes' if e['outside_rth'] else 'no'})"
             f"  = ${e['qty']*e['limit']:,.0f}",
             f"  EXIT   {x['stop_pct']:.0%} trailing stop (broker-side, placed once filled) "
             f"OR time exit after {x['max_sessions']} sessions, whichever first",
             f"  RISK   ${b.get('risk_usd', 0):,.0f} if stopped = "
             f"{b.get('risk_usd', 0)/b['investable_nav']:.2%} of investable NAV ${b['investable_nav']:,.0f}"]
    if b.get("signal"): lines.append(f"  SIGNAL {b['signal'].get('why')}")
    if b.get("thesis"): lines.append(f"  THESIS {b['thesis']}")
    if b.get("invalidation"): lines.append(f"  INVALID IF {b['invalidation']}")
    if b.get("filled_qty"): lines.append(f"  FILLED {b['filled_qty']} @ {b.get('fill_price')} on "
                                         f"{b.get('fill_date', '?')}; time exit {b.get('expiry_date', '?')}")
    if b.get("exit_perm_id"): lines.append(f"  EXIT ORDER perm {b['exit_perm_id']} ({b.get('exit_kind')})")
    if b.get("r_multiple") is not None: lines.append(f"  RESULT {b['r_multiple']:+.2f}R, ${b['pnl_usd']:,.0f}")
    if b.get("mismatch"): lines.append(f"  ⚠ {b['mismatch']}")
    lines.append(f"  ticket {b['ticket_hash']}" + (f" · approved {b['approved_at']} by {b['approved_by']}"
                                                   if b.get("approved_at") else ""))
    if full:
        for ev in b.get("events", []): lines.append(f"    {ev['ts']}  {ev['msg']}")
    return "\n".join(lines)


# ---- CLI ------------------------------------------------------------------------------
def _targets():
    import v3_execute as X
    try:
        return X.get_targets(False)
    except Exception as e:
        print(f"IBKR read failed — nothing drafted or approved: {e}", file=sys.stderr); sys.exit(3)


def _notify(title, body, prio="high"):
    try: subprocess.run([os.path.join(HERE, "notify.sh"), title, body, prio],
                        check=False, capture_output=True, timeout=20)
    except Exception: pass


def cmd_draft(a):
    t = _targets()
    led = load()
    bet = draft(t, led, a.setup, symbol=a.symbol, qty=a.qty, stop_pct=a.stop_pct,
                max_sessions=a.hold, thesis=a.thesis, invalidation=a.invalidation, account=a.account)
    errs = validate(bet, t, led, stage="draft")
    print(render(bet))
    if errs:
        print("\nREFUSED — not saved:"); [print(f"  - {e}") for e in errs]; sys.exit(2)
    with locked() as led2: led2.setdefault("bets", []).append(bet)
    print(f"\nsaved as DRAFT. Shawn approves at a terminal:\n  ./tob.py approve {bet['id']} --place-now")


def _human_terminal():
    return sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("CLAUDECODE")


def cmd_approve(a):
    # The approval is the human circuit breaker for the entry. An agent shell has no TTY
    # and carries CLAUDECODE=1, so a model cannot approve its own draft.
    if not _human_terminal():
        print("approve needs Shawn at a real terminal (no TTY, or running inside an agent).",
              file=sys.stderr); sys.exit(5)
    led = load(); b = find(led, a.id)
    if not b or b["status"] != "DRAFT":
        print(f"{a.id}: no DRAFT with that id", file=sys.stderr); sys.exit(2)
    if b["ticket_hash"] != ticket_hash(b):
        print(f"{a.id}: ticket was edited after drafting — redraft it", file=sys.stderr); sys.exit(2)
    t = _targets()
    errs = validate(b, t, led, stage="approve")
    print(render(b) + "\n")
    if errs:
        print("REFUSED:"); [print(f"  - {e}") for e in errs]; sys.exit(2)
    ans = input(f"Type the ticket id to approve {'AND PLACE NOW ' if a.place_now else ''}"
                f"[{b['id']}]: ").strip()
    if ans != b["id"]:
        print("not approved."); sys.exit(2)
    with locked() as led2:
        b2 = find(led2, a.id)
        b2.update(status="APPROVED", approved_at=now_iso(),
                  approved_by=os.environ.get("USER", "?"), approved_hash=ticket_hash(b2))
        event(b2, "approved at a terminal")
    print(f"{a.id} APPROVED.")
    if a.place_now: place_now(a.id)
    else: print("The next daily run places the entry (after the model review).")


def place_now(bet_id):
    """Place an approved entry immediately, under the executor's lock and rails. The
    human approval just given is the review; the model step is skipped for this one order."""
    import v3_execute as X
    got, why = X.acquire_lock()
    if not got: print(f"LOCKED: {why}"); sys.exit(2)
    try:
        try:
            alerts = sync()
            for al in alerts: print("  " + al)
            t = X.get_targets(False)
            resting = X.get_resting("127.0.0.1", 4001, 82)
        except Exception as e:
            print(f"IBKR read failed: {e}"); sys.exit(3)
        led = load(); b = find(led, bet_id)
        orders, notes, blocks = plan_actions(led, t, resting)
        mine = [o for o in orders if o.get("tob_id") == bet_id and o["tob_step"] == "entry"]
        for n in notes + blocks: print("  " + n)
        if blocks or not mine:
            print("entry NOT placed — it stays APPROVED; the daily run retries if it still qualifies")
            sys.exit(2)
        placed = X.place(mine, "127.0.0.1", 4001)
        X.log_audit(dict(mode="LIVE-TACTICAL", approved_by=b.get("approved_by"), placed=placed))
        record_placements(placed)
        for p in placed:
            print(f"  {p['status']}: {p['action']} {p['qty']} {p['symbol']} @ {p.get('limit')} "
                  f"[{p['account']}] perm {p.get('perm_id')} {p.get('note','')}")
        ok = [p for p in placed if p["status"] == "PLACED"]
        _notify("🎯 Tactical entry placed" if ok else "🚨 Tactical entry FAILED",
                "; ".join(f"{p['action']} {p['qty']} {p['symbol']} @ {p.get('limit')} {p['status']}"
                          for p in placed)[:300], "high" if ok else "urgent")
        if not ok: sys.exit(3)
    finally:
        X.release_lock()


def cmd_cancel(a):
    led = load(); b = find(led, a.id)
    if not b or b["status"] not in ("DRAFT", "APPROVED", "ENTRY_PLACED"):
        print(f"{a.id}: only a DRAFT, APPROVED or resting entry can be cancelled here", file=sys.stderr)
        sys.exit(2)
    if b["status"] == "ENTRY_PLACED":
        from ib_async import IB
        ib = IB(); ib.connect("127.0.0.1", 4001, clientId=1, timeout=30)
        try:
            ib.reqAllOpenOrders(); ib.sleep(2)
            tr = next((tr for tr in ib.openTrades() if tr.order.permId == b["entry_perm_id"]), None)
            if tr: ib.cancelOrder(tr.order); ib.sleep(2)
        finally: ib.disconnect()
        print("cancel sent; the next sync records any partial fill before closing the ticket")
        return
    with locked() as led2:
        b2 = find(led2, a.id); b2["status"] = "CANCELLED"; b2["closed_at"] = now_iso()
        event(b2, "cancelled before placement")
    print(f"{a.id} CANCELLED")


def cmd_sync(a):
    if not active(load()):
        with locked() as led: led["synced_at"] = now_iso()
        return
    try:
        alerts = sync(a.host, a.port)
    except Exception as e:
        print(f"tactical sync failed: {e}", file=sys.stderr); sys.exit(3)
    for al in alerts: print(al)
    if alerts: _notify("🎯 Tactical book", " · ".join(alerts)[:300])


def cmd_list(a):
    led = load()
    bets = [b for b in led.get("bets", []) if (not a.active or b["status"] in ACTIVE)]
    if not bets: print("tactical book: no bets" + (" active" if a.active else "")); return
    print(f"tactical book (last reconciled {led.get('synced_at') or 'never'}):")
    for b in reversed(bets): print(render(b)); print()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft"); d.add_argument("--setup", required=True, choices=sorted(SETUPS))
    d.add_argument("--symbol"); d.add_argument("--qty", type=int)
    d.add_argument("--stop-pct", type=float); d.add_argument("--hold", type=int)
    d.add_argument("--thesis", default=""); d.add_argument("--invalidation", default="")
    d.add_argument("--account")
    p = sub.add_parser("approve"); p.add_argument("id"); p.add_argument("--place-now", action="store_true")
    c = sub.add_parser("cancel"); c.add_argument("id")
    s = sub.add_parser("sync"); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=4001)
    l = sub.add_parser("list"); l.add_argument("--active", action="store_true")
    sh = sub.add_parser("show"); sh.add_argument("id")
    a = ap.parse_args()
    if a.cmd == "show":
        b = find(load(), a.id)
        print(render(b, full=True) if b else f"{a.id}: not found"); return
    {"draft": cmd_draft, "approve": cmd_approve, "cancel": cmd_cancel,
     "sync": cmd_sync, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    main()
