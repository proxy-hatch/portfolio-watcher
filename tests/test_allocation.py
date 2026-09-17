import unittest
from unittest.mock import patch
import v3_execute as v

TFSA, RRSP, MRGN = "U17856045", "U17884372", "U3847490"
TYPES = {TFSA: "registered", RRSP: "registered", MRGN: "margin"}


def state(cash, sgov, avail=None, extra=None, px=100.55):
    pos = {a: {"SGOV": n} for a, n in sgov.items()}
    for a, d in (extra or {}).items(): pos.setdefault(a, {}).update(d)
    return {"sgov_price": px, "cash_by_account": cash, "account_types": TYPES,
            "available_by_account": avail or dict(cash), "positions_by_account": pos}


def buy(sym, qty, price):
    return dict(symbol=sym, action="BUY", qty=qty, price=price, notional=qty*price,
                reason="t", account=v.ACCOUNTS.get(sym), pending=0)


def legs(out):
    return {(o["symbol"], o["action"], o["account"]): o["qty"] for o in out}


class AllocationTests(unittest.TestCase):
    def test_the_real_2026_09_17_book_routes_the_core_past_an_empty_tfsa(self):
        t = state({TFSA: 966.40, RRSP: 5334.62, MRGN: -2286.04},
                  {TFSA: 0, RRSP: 357, MRGN: 550}, avail={TFSA: 966.40, RRSP: 5334.62, MRGN: 50505.43})
        out, errs, notes = v.add_funding([buy("QLD", 157, 86.96)], t, {})
        L = legs(out)
        self.assertEqual(L[("QLD", "BUY", TFSA)], 11, "preferred account first")
        self.assertEqual(L[("QLD", "BUY", RRSP)], 60, "then the RRSP's own cash")
        self.assertEqual(L[("SGOV", "SELL", RRSP)], 76, "RRSP sells SGOV tonight for the other 86")
        self.assertNotIn(("QLD", "BUY", MRGN), L, "margin is last and was not needed")
        self.assertEqual(L[("SGOV", "SELL", MRGN)], 23, "the $2,286 margin loan is cleared")
        self.assertTrue(any("NEXT run" in n for n in notes))

    def test_margin_pays_with_same_night_sgov_and_never_borrowing_power(self):
        t = state({MRGN: 0.0}, {MRGN: 550}, avail={MRGN: 50000.0})
        out, _, _ = v.add_funding([buy("AIPO", 100, 27.61)], t, {})
        L = legs(out)
        self.assertEqual(L[("AIPO", "BUY", MRGN)], 100)
        sold = L[("SGOV", "SELL", MRGN)]*100.55
        self.assertGreaterEqual(sold, 100*27.61*v.CASH_BUFFER, "every dollar is real, none borrowed")

    def test_a_registered_account_never_spends_tonights_sale_tonight(self):
        # the exact 2026-09-01 state that produced Error 201
        t = state({TFSA: 5962.29}, {TFSA: 92}, px=100.69)
        with patch.dict(v.ACCOUNT_PREFERENCE, {"QLD": [TFSA]}):
            out, _, notes = v.add_funding([buy("QLD", 101, 90.24)], t, {})
        L = legs(out)
        self.assertEqual(L[("QLD", "BUY", TFSA)], 65)
        self.assertLessEqual(65*90.24*v.CASH_BUFFER, 5962.29)
        self.assertEqual(L[("SGOV", "SELL", TFSA)], 33)

    def test_an_accounts_native_holding_is_not_crowded_out_by_overflow(self):
        t = state({TFSA: 966.40, RRSP: 5334.62, MRGN: 0.0}, {TFSA: 0, RRSP: 357, MRGN: 550})
        out, _, _ = v.add_funding([buy("QLD", 157, 86.96), buy("BRK B", 13, 519.80)], t, {})
        L = legs(out)
        self.assertEqual(L[("BRK B", "BUY", RRSP)], 10, "BRK.B gets RRSP cash before QLD overflow")
        self.assertNotIn(("QLD", "BUY", RRSP), L)

    def test_sells_come_from_the_least_preferred_account_first(self):
        t = state({TFSA: 0, RRSP: 0}, {}, extra={TFSA: {"QLD": 900}, RRSP: {"QLD": 60}})
        o = dict(buy("QLD", 100, 86.96), action="SELL")
        L = legs(v.add_funding([o], t, {})[0])
        self.assertEqual(L[("QLD", "SELL", RRSP)], 60)
        self.assertEqual(L[("QLD", "SELL", TFSA)], 40)

    def test_sgov_already_queued_is_not_sold_twice(self):
        t = state({TFSA: 0.0, RRSP: 0.0}, {RRSP: 357})
        resting = {"SGOV": {"net": -76, "orders": [dict(action="SELL", qty=76, account=RRSP, limit=100.0)]}}
        out, _, notes = v.add_funding([buy("QLD", 86, 86.96)], t, resting)
        self.assertNotIn(("SGOV", "SELL", RRSP), legs(out))
        self.assertTrue(any("already on its way" in n for n in notes))

    def test_cash_already_promised_to_resting_buys_is_not_spent_again(self):
        # 2026-09-17: TFSA shows $966 but $961 is tied up in an unfilled 11-share QLD buy,
        # and Margin's unfilled AIS buy would add $2,601 to a margin loan when it fills.
        t = state({TFSA: 966.39, RRSP: 0.0, MRGN: -2286.05}, {TFSA: 0, RRSP: 0, MRGN: 550},
                  avail={TFSA: 966.39, RRSP: 0.0, MRGN: 50680.06})
        resting = {"QLD": {"orders": [dict(action="BUY", qty=11, account=TFSA, limit=87.39)]},
                   "AIS": {"orders": [dict(action="BUY", qty=39, account=MRGN, limit=66.69)]}}
        with patch.dict(v.ACCOUNT_PREFERENCE, {"QLD": [TFSA]}):
            out, _, notes = v.add_funding([buy("QLD", 20, 86.96)], t, resting)
        L = legs(out)
        self.assertNotIn(("QLD", "BUY", TFSA), L, "would double-spend and be rejected")
        self.assertEqual(L[("SGOV", "SELL", MRGN)], 50, "loan + pending AIS buy both covered")


if __name__ == "__main__":
    unittest.main()
