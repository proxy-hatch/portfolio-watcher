import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch

import tob
import v3_execute as v

TFSA, RRSP, MRGN = "U17856045", "U17884372", "U3847490"
TYPES = {TFSA: "registered", RRSP: "registered", MRGN: "margin"}
MON = dt.date(2026, 11, 2)
SIG_OK = dict(ok=True, why="QQQ 9.1% below high; trend leg ON")
SIG_NO = dict(ok=False, why="QQQ 3.0% below high (need ≥7.5%)")


def targets(cash=None, sgov=None, qld=None, core_on=True, sleeve_on=True, tac=None):
    cash = cash or {TFSA: 8128.33, RRSP: 16626.75, MRGN: 280.55}
    pos = {a: {"SGOV": n} for a, n in (sgov or {RRSP: 238, MRGN: 463}).items()}
    for a, n in (qld or {TFSA: 950}).items(): pos.setdefault(a, {})["QLD"] = n
    return {"asof": "2026-10-30", "nav": 232881.0, "investable_nav": 225352.0,
            "cash_by_account": cash, "available_by_account": dict(cash), "account_types": TYPES,
            "positions_by_account": pos, "sgov_price": 100.7,
            "prices": {"QLD": 82.59, "AIS": 59.58, "AIPO": 24.66, "SGOV": 100.7, "QQQ": 690.49},
            "tactical": tac or {},
            "buckets": {"core": {"symbol": "QLD", "gate_on": core_on},
                        "sleeve": {"symbols": ["AIS", "AIPO"], "gate_on": sleeve_on}}}


def a_bet(led=None, t=None, **kw):
    b = tob.draft(t or targets(), led or {"bets": []}, "A", today=MON, signal=SIG_OK, **kw)
    return b


def fresh(bets):
    return {"bets": bets, "synced_at": tob.now_iso()}


class Drafting(unittest.TestCase):
    def test_setup_a_sizes_to_the_risk_unit_and_skips_the_empty_tfsa(self):
        b = a_bet()
        # 1% NAV / 20% stop = 5% NAV = $11,268 at the +1% limit 83.42 -> 135 sh
        self.assertEqual(b["entry"]["limit"], 83.42)
        self.assertEqual(b["entry"]["qty"], 135)
        self.assertEqual(b["account"], RRSP)        # TFSA has $8.1k, RRSP $16.6k
        self.assertEqual(b["entry"]["tif"], "GTD")
        self.assertTrue(b["entry"]["outside_rth"])
        self.assertEqual(b["entry"]["good_till"], "2026-11-04")
        self.assertLessEqual(b["risk_usd"], 0.01*225352)
        self.assertEqual(tob.validate(b, targets(), {"bets": []}, signal=SIG_OK, today=MON), [])

    def test_trigger_not_met_is_refused(self):
        b = a_bet()
        errs = tob.validate(b, targets(), {"bets": []}, signal=SIG_NO, today=MON)
        self.assertTrue(any("trigger not met" in e for e in errs))

    def test_core_defensive_is_refused(self):
        b = a_bet()
        errs = tob.validate(b, targets(core_on=False), {"bets": []}, signal=SIG_OK, today=MON)
        self.assertTrue(any("DEFENSIVE" in e for e in errs))

    def test_no_account_can_pay_is_refused_never_margin(self):
        t = targets(cash={TFSA: 100, RRSP: 100, MRGN: -500})
        b = a_bet(t=t)
        errs = tob.validate(b, t, {"bets": []}, signal=SIG_OK, today=MON)
        self.assertTrue(any("spendable" in e for e in errs))

    def test_oversized_ticket_is_refused(self):
        b = a_bet(); b["entry"]["qty"] = 400
        errs = tob.validate(b, targets(), {"bets": []}, signal=SIG_OK, today=MON)
        self.assertTrue(any("risk" in e for e in errs))
        self.assertTrue(any("gross" in e for e in errs))

    def test_cooldown_after_stop_out(self):
        old = a_bet(); old.update(status="CLOSED", exit_kind="STOP", closed_at="2026-10-20T10:00:00")
        b = a_bet()
        errs = tob.validate(b, targets(), {"bets": [old]}, signal=SIG_OK, today=MON)
        self.assertTrue(any("cooldown" in e for e in errs))

    def test_edit_after_approval_is_caught(self):
        b = a_bet(); b["approved_hash"] = tob.ticket_hash(b); b["entry"]["qty"] = 100
        errs = tob.validate(b, targets(), {"bets": []}, stage="place", signal=SIG_OK, today=MON)
        self.assertIn("ticket changed after approval", errs)


class Lifecycle(unittest.TestCase):
    def placed(self):
        b = a_bet(); b.update(status="ENTRY_PLACED", entry_perm_id=111, approved_at="2026-11-02T10:00:00",
                             baseline_qty=0.0)
        return b

    def test_the_real_2026_11_03_fill_is_found_from_positions(self):
        # this gateway returns no completed orders and no executions: the filled entry just
        # vanishes from the book. The RRSP position is the only evidence, and it is enough.
        b = self.placed()
        snap = {"orders": {}, "execs": {}, "positions": {RRSP: {"QLD": 135.0}},
                "avg_cost": {RRSP: {"QLD": 83.42741037037037}}}
        tob.apply_broker(b, snap, dt.date(2026, 11, 4))
        self.assertEqual((b["status"], b["filled_qty"]), ("OPEN", 135))
        self.assertAlmostEqual(b["fill_price"], 83.4274, places=4)
        self.assertEqual(b["fill_price_source"], "avg_cost")
        self.assertEqual(tob.holdings(fresh([b])), {RRSP: {"QLD": 135}})

    def test_off_the_book_with_no_shares_before_expiry_blocks_the_run(self):
        b = self.placed()
        tob.apply_broker(b, {"orders": {}, "execs": {}, "positions": {RRSP: {}}}, MON)
        self.assertIn("unreconciled", b)
        _, _, blocks = tob.plan_actions(fresh([b]), targets())
        self.assertTrue(blocks)

    def test_unknown_baseline_blocks_instead_of_guessing(self):
        b = self.placed(); b.pop("baseline_qty")
        tob.apply_broker(b, {"orders": {}, "execs": {}, "positions": {RRSP: {"QLD": 135}}}, MON)
        self.assertEqual(b["status"], "ENTRY_PLACED")
        self.assertIn("unreconciled", b)

    def test_entry_fill_opens_the_bet_with_execution_price(self):
        b = self.placed()
        snap = {"orders": {111: {"status": "Filled", "filled": 135, "total": 135}},
                "execs": {111: [{"exec_id": "e1", "shares": 100, "price": 82.0, "ts": "x"},
                                {"exec_id": "e2", "shares": 35, "price": 82.4, "ts": "x"}]},
                "positions": {RRSP: {"QLD": 135}}}
        tob.apply_broker(b, snap, MON)
        self.assertEqual(b["status"], "OPEN")
        self.assertEqual(b["filled_qty"], 135)
        self.assertAlmostEqual(b["fill_price"], (100*82.0+35*82.4)/135, places=3)
        self.assertEqual(tob.open_qty(b), 135)
        self.assertEqual(b["expiry_date"], tob.add_weekdays(MON, 63).isoformat())

    def test_partial_fill_then_gtd_expiry_keeps_the_partial(self):
        b = self.placed()
        snap = {"orders": {111: {"status": "Cancelled", "filled": 60, "total": 135}},
                "execs": {}, "positions": {RRSP: {"QLD": 60}}}
        tob.apply_broker(b, snap, MON)
        self.assertEqual((b["status"], b["filled_qty"]), ("OPEN", 60))
        self.assertTrue(b["fill_price_estimated"])

    def test_unfilled_entry_expires_to_cancelled(self):
        b = self.placed()
        tob.apply_broker(b, {"orders": {}, "execs": {}, "positions": {}}, dt.date(2026, 11, 5))
        self.assertEqual(b["status"], "CANCELLED")

    def test_resting_partial_counts_as_owned_shares(self):
        b = self.placed()
        snap = {"orders": {111: {"status": "Submitted", "filled": 50, "total": 135}},
                "execs": {}, "positions": {RRSP: {"QLD": 50}}}
        tob.apply_broker(b, snap, MON)
        self.assertEqual((b["status"], tob.open_qty(b)), ("ENTRY_PLACED", 50))

    def test_stop_fill_closes_with_r_multiple(self):
        b = self.placed(); b.update(status="EXIT_PLACED", filled_qty=135, fill_price=82.0,
                                    exit_perm_id=222, exit_kind="STOP", expiry_date="2027-01-29")
        snap = {"orders": {222: {"status": "Filled", "filled": 135, "total": 135}},
                "execs": {222: [{"exec_id": "x1", "shares": 135, "price": 65.6, "ts": "t"}]},
                "positions": {RRSP: {}}}
        tob.apply_broker(b, snap, MON)
        self.assertEqual(b["status"], "CLOSED")
        self.assertEqual(b["r_multiple"], -1.0)
        self.assertEqual(tob.open_qty(b), 0)

    def test_stop_that_vanished_with_the_shares_is_a_close(self):
        b = self.placed(); b.update(status="EXIT_PLACED", filled_qty=135, fill_price=82.0, stop_level=65.6,
                                    exit_perm_id=222, exit_kind="STOP", expiry_date="2027-01-29")
        tob.apply_broker(b, {"orders": {}, "execs": {}, "positions": {RRSP: {"QLD": 0}}}, MON)
        self.assertEqual((b["status"], b["exit_price"], b["r_multiple"]), ("CLOSED", 65.6, -1.0))
        self.assertTrue(b["exit_price_estimated"])

    def test_stop_that_vanished_with_shares_still_held_is_re_placed(self):
        b = self.placed(); b.update(status="EXIT_PLACED", filled_qty=135, fill_price=82.0,
                                    exit_perm_id=222, exit_kind="STOP", expiry_date="2027-01-29")
        tob.apply_broker(b, {"orders": {}, "execs": {}, "positions": {RRSP: {"QLD": 135}}}, MON)
        self.assertEqual(b["status"], "OPEN")

    def test_shares_missing_from_an_open_bet_blocks(self):
        b = self.placed(); b.update(status="OPEN", filled_qty=135, fill_price=82.0, fill_date="2026-11-02",
                                    expiry_date="2027-01-29")
        tob.apply_broker(b, {"orders": {}, "execs": {}, "positions": {RRSP: {"QLD": 20}}}, MON)
        self.assertIn("mismatch", b)
        _, _, blocks = tob.plan_actions(fresh([b]), targets())
        self.assertTrue(blocks)                     # never re-place a stop on missing shares


class Monitor(unittest.TestCase):
    def test_approved_entry_becomes_a_gtd_extended_hours_order(self):
        b = a_bet(); b.update(status="APPROVED", approved_at="2026-11-02T10:00:00")
        b["approved_hash"] = tob.ticket_hash(b)
        with patch.object(tob, "setup_a_check", return_value=SIG_OK):
            orders, notes, blocks = tob.plan_actions(fresh([b]), targets(), today=MON)
        self.assertEqual((notes, blocks), ([], []))
        o, = orders
        self.assertEqual((o["action"], o["qty"], o["account"], o["tob_step"]), ("BUY", 135, RRSP, "entry"))
        self.assertEqual(o["baseline_qty"], 0.0)
        order, lmt = v.build_order(o)
        self.assertEqual((order.orderType, order.tif, order.outsideRth, lmt), ("LMT", "GTD", True, 83.42))
        self.assertEqual(order.goodTillDate, "20261104 20:00:00 US/Eastern")

    def test_approved_entry_that_no_longer_qualifies_is_not_placed(self):
        b = a_bet(); b.update(status="APPROVED", approved_at="2026-11-02T10:00:00")
        with patch.object(tob, "setup_a_check", return_value=SIG_NO):
            orders, notes, _ = tob.plan_actions(fresh([b]), targets(), today=MON)
        self.assertEqual(orders, []); self.assertTrue(notes)

    def test_open_bet_gets_a_broker_side_trailing_stop(self):
        b = a_bet(); b.update(status="OPEN", filled_qty=135, fill_price=82.0, fill_date="2026-11-02",
                             expiry_date="2027-01-29")
        with patch.object(tob, "read_closes", return_value={"2026-11-02": 84.0}):
            orders, _, _ = tob.plan_actions(fresh([b]), targets(qld={TFSA: 950, RRSP: 135}), today=MON)
        o, = orders
        self.assertEqual((o["tob_step"], o["order_type"], o["qty"]), ("stop", "TRAIL", 135))
        self.assertEqual(o["trail_stop"], round(84.0*0.8, 2))   # trails from the peak since entry
        order, lmt = v.build_order(o)
        self.assertEqual((order.orderType, order.trailingPercent, order.tif, lmt), ("TRAIL", 20.0, "GTC", None))

    def test_time_exit_cancels_the_stop_then_sells(self):
        b = a_bet(); b.update(status="EXIT_PLACED", filled_qty=135, fill_price=82.0, exit_perm_id=222,
                             exit_kind="STOP", fill_date="2026-08-01", expiry_date="2026-11-02")
        orders, _, _ = tob.plan_actions(fresh([b]), targets(qld={TFSA: 950, RRSP: 135}), today=MON)
        o, = orders
        self.assertEqual((o["tob_step"], o["cancel_perm"], o["action"], o["qty"]), ("time_exit", 222, "SELL", 135))

    def test_stale_ledger_blocks_planning(self):
        b = a_bet(); b.update(status="OPEN", filled_qty=135, fill_price=82.0, fill_date="2026-11-02",
                             expiry_date="2027-01-29")
        _, _, blocks = tob.plan_actions({"bets": [b], "synced_at": "2026-10-01T00:00:00"}, targets())
        self.assertTrue(blocks)

    def test_record_placements_writes_perm_ids_back(self):
        b = a_bet(); b["status"] = "APPROVED"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tactical.json")
            tob.save({"bets": [b]}, path)
            tob.record_placements([dict(tob_id=b["id"], tob_step="entry", status="PLACED", perm_id=111,
                                        order_id=5, action="BUY", qty=135, symbol="QLD", limit=83.42)], path)
            b2 = tob.load(path)["bets"][0]
        self.assertEqual((b2["status"], b2["entry_perm_id"]), ("ENTRY_PLACED", 111))


class ExecutorInteraction(unittest.TestCase):
    def test_core_trim_never_sells_tactical_shares(self):
        # RRSP holds only the tactical 135; the core's 950 are in the TFSA
        t = targets(qld={TFSA: 950, RRSP: 135},
                    tac={"holdings_by_account": {RRSP: {"QLD": 135}}})
        sell = dict(symbol="QLD", action="SELL", qty=200, price=82.59, notional=200*82.59,
                    reason="t", account=TFSA, pending=0)
        out, errs, notes = v.add_funding([sell], t, {})
        legs = {(o["symbol"], o["account"]): o["qty"] for o in out if o["symbol"] == "QLD"}
        self.assertEqual(legs, {("QLD", TFSA): 200})

    def test_the_real_2026_11_03_core_trim_stays_out_of_the_tactical_account(self):
        # the 11-03 plan routed SELL 119 QLD to the RRSP, which held only the tactical lot
        t = targets(qld={TFSA: 950, RRSP: 135},
                    tac={"holdings_by_account": {}, "ringfenced": [[RRSP, "QLD"]]})
        sell = dict(symbol="QLD", action="SELL", qty=119, price=80.30, notional=119*80.30,
                    reason="t", account=TFSA, pending=0)
        out, _, _ = v.add_funding([sell], t, {})
        self.assertEqual({(o["symbol"], o["account"]): o["qty"] for o in out if o["symbol"] == "QLD"},
                         {("QLD", TFSA): 119})
        buy = dict(symbol="QLD", action="BUY", qty=20, price=80.30, notional=20*80.30,
                   reason="t", account=TFSA, pending=0)
        t2 = targets(cash={TFSA: 0, RRSP: 16000, MRGN: 0}, sgov={RRSP: 0, MRGN: 0},
                     tac={"ringfenced": [[RRSP, "QLD"]]})
        out, _, _ = v.add_funding([buy], t2, {})
        self.assertFalse(any(o["symbol"] == "QLD" and o["account"] == RRSP for o in out))

    def test_one_bet_per_account_and_symbol(self):
        a = a_bet(); a.update(id="T-20261101-QLD", status="OPEN", setup="B")
        b = a_bet()
        errs = tob.validate(b, targets(), {"bets": [a]}, signal=SIG_OK, today=MON)
        self.assertTrue(any("already holds an active QLD bet" in e for e in errs))

    def test_reserved_tactical_cash_is_not_spent_twice(self):
        t = targets(cash={TFSA: 0, RRSP: 16626.75, MRGN: 0}, sgov={RRSP: 0, MRGN: 0})
        buy = dict(symbol="BRK B", action="BUY", qty=12, price=542.0, notional=12*542.0,
                   reason="t", account=RRSP, pending=0)
        out, _, notes = v.add_funding([buy], t, {}, reserved={RRSP: 135*83.42})
        brk = sum(o["qty"] for o in out if o["symbol"] == "BRK B")
        self.assertLessEqual(brk*542.0*1.01, 16626.75 - 135*83.42)

    def test_defensive_sleeve_no_longer_blocks_a_core_buy(self):
        t = targets(sleeve_on=False)
        t["buckets"]["core"].update(current_shares=900, target_shares=950)
        t["buckets"]["ballast"] = {}
        qld = dict(symbol="QLD", action="BUY", qty=50, price=82.59, notional=50*82.59, account=TFSA)
        errs, _ = v.check_rails([qld], 225352.0, t)
        self.assertEqual(errs, [])
        ais = dict(symbol="AIS", action="BUY", qty=10, price=59.58, notional=595.8, account=MRGN)
        errs, _ = v.check_rails([ais], 225352.0, t)
        self.assertTrue(any("sleeve gate is DEFENSIVE" in e for e in errs))

    def test_bucket_orders_keep_their_old_shape(self):
        o = dict(symbol="QLD", action="SELL", qty=10, price=86.26, account=TFSA)
        order, lmt = v.build_order(o)
        self.assertEqual((order.orderType, order.tif, order.outsideRth, lmt), ("LMT", "GTC", False, 85.83))


if __name__ == "__main__":
    unittest.main()
