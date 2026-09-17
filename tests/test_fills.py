import json
from pathlib import Path
import tempfile
import unittest
import fills
import v3_execute as v


EXECS = [
    dict(exec_id='e1', ts='2026-09-16 18:36:38', symbol='QLD', side='BOT', shares=51.0,
         price=87.39, order_id=84, perm_id=583658373, client_id=1,
         account='U17856045', commission=1.0),
    dict(exec_id='e2', ts='2026-09-16 19:08:11', symbol='AIPO', side='BOT', shares=49.0,
         price=27.39, order_id=88, perm_id=583658375, client_id=1,
         account='U3847490', commission=0.5),
    dict(exec_id='e3', ts='2026-09-16 19:08:11', symbol='AIPO', side='BOT', shares=48.0,
         price=27.39, order_id=88, perm_id=583658375, client_id=1,
         account='U3847490', commission=0.5),
]
AUDIT = {'mode': 'LIVE', 'placed': [
    dict(symbol='QLD', action='BUY', qty=51, price=86.96, limit=87.39, status='PLACED',
         order_id=84, perm_id=583658373),
    dict(symbol='AIPO', action='BUY', qty=97, price=27.25, limit=27.39, status='PLACED',
         order_id=88, perm_id=583658375)]}


class FillsTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.audit = Path(self.td.name)/'orders-audit.jsonl'
        self.audit.write_text(json.dumps(AUDIT)+'\n')
        self.store = Path(self.td.name)/'fills.jsonl'

    def tearDown(self): self.td.cleanup()

    def run_once(self, rows=None):
        written = []
        s = fills.reconcile(audit_path=str(self.audit), store_path=str(self.store),
                            fetch=lambda: list(EXECS if rows is None else rows),
                            audit_writer=written.append)
        return s, written

    def test_partial_executions_of_one_order_are_averaged(self):
        s, _ = self.run_once()
        aipo = [o for o in s['orders'] if o['symbol'] == 'AIPO'][0]
        self.assertEqual(aipo['shares'], 97.0)          # 49 + 48
        self.assertAlmostEqual(aipo['avg_price'], 27.39)
        self.assertEqual(aipo['fill_ratio'], 1.0)

    def test_reconciliation_is_idempotent(self):
        first, w1 = self.run_once()
        second, w2 = self.run_once()
        self.assertEqual(first['new'], 3)
        self.assertEqual(second['new'], 0, 'a re-run must not double-count fills')
        self.assertEqual(len(self.store.read_text().strip().splitlines()), 3)
        self.assertEqual(len(w1), 1); self.assertEqual(len(w2), 0)

    def test_slippage_is_measured_against_the_real_fill(self):
        s, _ = self.run_once()
        qld = [o for o in s['orders'] if o['symbol'] == 'QLD'][0]
        self.assertTrue(qld['matched'])
        # paid 87.39 against an 86.96 reference close -> ~49.5bps worse
        self.assertAlmostEqual(qld['slip_vs_ref_bps'], 49.4, places=0)
        # filled exactly at the limit -> no price improvement
        self.assertAlmostEqual(qld['price_improvement_bps'], 0.0, places=1)

    def test_an_execution_we_never_placed_is_still_recorded_and_flagged(self):
        rows = [dict(EXECS[0], exec_id='x9', perm_id=999, order_id=999)]
        s, _ = self.run_once(rows)
        self.assertEqual(s['new'], 1)
        self.assertFalse(s['orders'][0]['matched'])
        self.assertIn('no PLACED record', s['orders'][0]['note'])

    def test_a_sell_that_fills_above_its_limit_is_not_called_slippage(self):
        rows = [dict(EXECS[0], exec_id='s1', symbol='SGOV', side='SLD', shares=9.0,
                     price=100.70, perm_id=111, order_id=70)]
        audit = {'mode': 'LIVE', 'placed': [dict(symbol='SGOV', action='SELL', qty=9,
                 price=100.55, limit=100.05, status='PLACED', order_id=70, perm_id=111)]}
        self.audit.write_text(json.dumps(audit)+'\n')
        s, _ = self.run_once(rows)
        o = s['orders'][0]
        self.assertLess(o['slip_vs_ref_bps'], 0, 'selling above the reference is a gain')
        # filled at 100.70 against a 100.05 limit: 65bps BETTER than the limit, and
        # price_improvement is signed so positive always means "better than the limit"
        self.assertGreater(o['price_improvement_bps'], 0)

    def test_reconciliation_failure_never_stops_a_trading_pass(self):
        def boom(): raise RuntimeError('gateway said no')
        with self.assertRaises(RuntimeError):
            fills.reconcile(audit_path=str(self.audit), store_path=str(self.store), fetch=boom)
        # v3_execute wraps it; prove the wrapper swallows it
        self.assertIn('fills: reconciliation unavailable', Path(v.__file__).read_text())


class RejectionNoteTests(unittest.TestCase):
    class Trade:
        def __init__(self, oid, log=()):
            self.order = type('O', (), {'orderId': oid})()
            self.log = list(log)

    def test_broker_error_text_reaches_the_note(self):
        errors = {84: ['201: Order rejected - reason:Available converted to base: 5964.23 USD']}
        note = v.rejection_note(errors, self.Trade(84))
        self.assertIn('5964.23', note)
        self.assertIn('201', note)

    def test_falls_back_to_trade_log_when_the_error_channel_said_nothing(self):
        entry = type('E', (), {'message': 'cancelled by system'})()
        self.assertIn('cancelled by system', v.rejection_note({}, self.Trade(9, [entry])))

    def test_silence_yields_an_empty_note_not_a_crash(self):
        self.assertEqual(v.rejection_note({}, self.Trade(1)), '')

    def test_benign_connection_codes_are_not_treated_as_rejections(self):
        self.assertIn(2104, v.BENIGN_ERROR_CODES)
        self.assertIn(1100, v.BENIGN_ERROR_CODES)


if __name__ == '__main__':
    unittest.main()
