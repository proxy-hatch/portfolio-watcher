import json
from pathlib import Path
import tempfile
import unittest
import price_store as ps


class PriceStoreTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.root = self.td.name
    def tearDown(self): self.td.cleanup()

    def series(self, n, step=0.01, base=100.0):
        return {f'2026-{1+i//28:02d}-{1+i%28:02d}': base*(1+step)**i for i in range(n)}

    def test_symbols_with_spaces_round_trip(self):
        ps.save({'BRK B': self.series(5)}, self.root)
        self.assertTrue((Path(self.root)/'state/prices/BRK_B.json').exists())
        self.assertEqual(len(ps.load(self.root, 'BRK B')), 5)

    def test_saving_merges_rather_than_replaces(self):
        ps.save({'QLD': {'2026-01-01': 1.0, '2026-01-02': 2.0}}, self.root)
        ps.save({'QLD': {'2026-01-02': 2.0, '2026-01-03': 3.0}}, self.root)
        stored = ps.load(self.root, 'QLD')
        self.assertEqual(sorted(stored), ['2026-01-01', '2026-01-02', '2026-01-03'],
                         'a later run must not discard earlier history')

    def test_manifest_reports_coverage(self):
        man = ps.save({'QLD': self.series(4), 'AIS': self.series(4)}, self.root)
        self.assertEqual(man['QLD']['bars'], 4)
        self.assertEqual(json.load(open(Path(self.root)/'state/prices/_manifest.json'))['AIS']['bars'], 4)

    def test_correlations_refuse_to_report_on_too_few_observations(self):
        ps.save({'QLD': self.series(5), 'AIS': self.series(5)}, self.root)
        out = ps.correlations(self.root, ['QLD', 'AIS'])
        self.assertIn('error', out)
        self.assertIn('too few', out['error'])

    def test_correlations_report_n_alongside_the_matrix(self):
        import random
        random.seed(7)
        a = {f'2026-{1+i//28:02d}-{1+i%28:02d}': 100*(1+random.gauss(0, .01))**i for i in range(60)}
        b = {d: v*1.5 for d, v in a.items()}
        ps.save({'QLD': a, 'AIS': b}, self.root)
        out = ps.correlations(self.root, ['QLD', 'AIS'])
        self.assertNotIn('error', out)
        self.assertGreaterEqual(out['n'], 20)
        self.assertAlmostEqual(out['matrix']['QLD']['AIS'], 1.0, places=6)
        self.assertAlmostEqual(out['matrix']['QLD']['QLD'], 1.0, places=6)

    def test_missing_series_is_empty_not_an_exception(self):
        self.assertEqual(ps.load(self.root, 'NOPE'), {})
        self.assertIn('error', ps.correlations(self.root, ['NOPE', 'ALSONOPE']))


if __name__ == '__main__':
    unittest.main()
