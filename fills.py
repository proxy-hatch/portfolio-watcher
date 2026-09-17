#!/usr/bin/env python3
"""
Reconcile BROKER EXECUTIONS into the order audit.

Why this exists: `orders-audit.jsonl` recorded placements only — limit, order_id,
`PreSubmitted` — and no fill price was ever written back. Full execution was inferred
from position deltas, so the 0.5% collar was an assumption rather than a measurement,
and the weekly execution-quality check could not run (blocked W36, W37).

Two hard constraints discovered on 2026-09-17 by probing the live gateway:

  1. The execution window is SHORT and NOT controllable. `ExecutionFilter.time` is
     ignored — asking for 1, 7 or 30 days back returns the identical set. Of three
     known 2026-09-16 fills the API returned two; the SGOV sell that demonstrably
     filled (the cash arrived) was already gone. So reconciliation MUST run every
     day and PERSIST what it sees. A skipped day loses that day's fills permanently.
  2. `avgFillPrice` on a completed order comes back 0.0, so price must be taken from
     the execution rows, and multiple partial executions per order must be averaged.

Idempotent: every execution is keyed by its broker execId in state/fills.jsonl, so
re-running a day adds nothing. Never fatal — a reconciliation failure must not stop
the trading pass.
"""
import datetime as dt
import json
import os

# Connection-status codes IBKR pushes through the same error channel.
BENIGN_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2119, 2158, 2100}


def fetch_executions(host="127.0.0.1", port=4001, cid=92):
    """Pull today's visible executions. Import is local so tests need no ib_async."""
    from ib_async import IB
    try:
        from ib_async import ExecutionFilter
    except ImportError:
        from ib_async.objects import ExecutionFilter
    ib = IB(); ib.connect(host, port, clientId=cid, timeout=30)
    try:
        rows = []
        for fl in ib.reqExecutions(ExecutionFilter()):
            e, c = fl.execution, fl.contract
            comm = getattr(getattr(fl, "commissionReport", None), "commission", None)
            rows.append(dict(exec_id=e.execId, ts=str(e.time), symbol=c.symbol,
                             side=e.side, shares=float(e.shares), price=float(e.price),
                             order_id=e.orderId, perm_id=e.permId,
                             client_id=e.clientId, account=e.acctNumber,
                             commission=(float(comm) if comm is not None else None)))
        return rows
    finally:
        try: ib.disconnect()
        except Exception: pass


def _read_jsonl(path):
    if not path or not os.path.exists(path): return []
    out = []
    for line in open(path):
        line = line.strip()
        if not line: continue
        try: out.append(json.loads(line))
        except ValueError: continue
    return out


def placements(audit_path):
    """Every order this system reports having PLACED, keyed by its stable handles."""
    by = {}
    for rec in _read_jsonl(audit_path):
        if rec.get("mode") != "LIVE": continue
        for p in rec.get("placed") or []:
            if p.get("status") != "PLACED": continue
            for key in (("perm", p.get("perm_id")), ("ord", p.get("order_id"))):
                if key[1]: by[key] = p
    return by


def group_by_order(rows):
    """Average the partial executions of one order — IBKR splits a fill into several."""
    grouped = {}
    for r in rows:
        k = r.get("perm_id") or ("ord", r.get("order_id"))
        g = grouped.setdefault(k, dict(symbol=r["symbol"], side=r["side"], shares=0.0,
                                       notional=0.0, order_id=r.get("order_id"),
                                       perm_id=r.get("perm_id"), account=r.get("account"),
                                       commission=0.0, n=0, ts=r.get("ts")))
        g["shares"] += r["shares"]; g["notional"] += r["shares"]*r["price"]; g["n"] += 1
        if r.get("commission"): g["commission"] += r["commission"]
        g["ts"] = max(g["ts"] or "", r.get("ts") or "")
    for g in grouped.values():
        g["avg_price"] = round(g["notional"]/g["shares"], 4) if g["shares"] else None
    return grouped


def match(grouped, placed_by):
    """Attach each filled order to its placement and measure what the collar cost."""
    out = []
    for key, g in grouped.items():
        p = placed_by.get(("perm", g.get("perm_id"))) or placed_by.get(("ord", g.get("order_id")))
        row = dict(g)
        if p:
            ref, lmt = p.get("price"), p.get("limit")
            row.update(matched=True, plan_price=ref, limit=lmt,
                       plan_qty=p.get("qty"), action=p.get("action"))
            if ref and g["avg_price"]:
                # signed so positive ALWAYS means "worse than the reference close"
                sign = 1 if g["side"].upper().startswith("B") else -1
                row["slip_vs_ref_bps"] = round(sign*(g["avg_price"]/ref - 1)*10000, 1)
            if lmt and g["avg_price"]:
                sign = 1 if g["side"].upper().startswith("B") else -1
                row["price_improvement_bps"] = round(sign*(lmt/g["avg_price"] - 1)*10000, 1)
            if p.get("qty") and g["shares"]:
                row["fill_ratio"] = round(g["shares"]/float(p["qty"]), 4)
        else:
            row.update(matched=False,
                       note="no PLACED record — placed before reconciliation existed, "
                            "by hand, or outside this system")
        out.append(row)
    return out


def reconcile(host="127.0.0.1", port=4001, cid=92, audit_path=None, store_path=None,
              fetch=None, audit_writer=None):
    """Persist any execution not seen before and report it. Returns a summary dict."""
    fetch = fetch or (lambda: fetch_executions(host, port, cid))
    rows = fetch()
    seen = {r.get("exec_id") for r in _read_jsonl(store_path)}
    fresh = [r for r in rows if r.get("exec_id") and r["exec_id"] not in seen]
    if fresh and store_path:
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        stamped = dt.datetime.now().isoformat(timespec="seconds")
        with open(store_path, "a") as f:
            for r in fresh:
                f.write(json.dumps(dict(r, reconciled_at=stamped))+"\n")
    filled = match(group_by_order(fresh), placements(audit_path))
    summary = dict(mode="FILLS", visible=len(rows), new=len(fresh), orders=filled)
    if fresh and audit_writer:
        audit_writer(dict(summary))
    return summary


def render(summary):
    if not summary.get("new"):
        return (f"  fills: nothing new ({summary.get('visible', 0)} visible to the broker API)")
    lines = [f"  fills reconciled: {summary['new']} new execution(s)"]
    for o in summary["orders"]:
        # never begin with BUY/SELL: run.sh treats such lines as plan ORDERS
        head = (f"     filled {o.get('action') or o['side']} {o['shares']:.0f} {o['symbol']} "
                f"@ {o['avg_price']}")
        if o.get("matched"):
            bits = []
            if o.get("limit") is not None: bits.append(f"limit {o['limit']}")
            if o.get("price_improvement_bps") is not None:
                bits.append(f"{o['price_improvement_bps']:+.1f}bps vs limit")
            if o.get("slip_vs_ref_bps") is not None:
                # vs the PRIOR close: mostly the overnight move, not a trading cost
                bits.append(f"{o['slip_vs_ref_bps']:+.1f}bps vs prior close incl. overnight move")
            if o.get("fill_ratio") is not None and o["fill_ratio"] < 1:
                bits.append(f"PARTIAL {o['fill_ratio']:.0%}")
            lines.append(head + ("  (" + ", ".join(bits) + ")" if bits else ""))
        else:
            lines.append(head + "  (unmatched — " + o.get("note", "")[:60] + ")")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse, sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=4001)
    ap.add_argument("--client-id", type=int, default=92)
    ap.add_argument("--state", default=os.path.join(HERE, "state"))
    a = ap.parse_args()
    s = reconcile(a.host, a.port, a.client_id,
                  audit_path=os.path.join(a.state, "orders-audit.jsonl"),
                  store_path=os.path.join(a.state, "fills.jsonl"))
    print(render(s))
    sys.exit(0)
