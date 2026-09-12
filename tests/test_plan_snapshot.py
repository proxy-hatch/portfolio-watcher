import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import v3_execute as v


class SnapshotTests(unittest.TestCase):
    def test_frozen_plan_embeds_its_own_full_engine_snapshot(self):
        targets = {'asof':'2026-09-09','nav':10000,'investable_nav':9500,
                   'buckets':{'core':{'target':4500}},'positions_by_account':{}}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'plan.json'
            v.save_plan(p, [], targets, {})
            saved = json.loads(p.read_text())
            self.assertEqual(saved.get('targets'), targets)
            self.assertEqual(saved['plan'], [])

    def test_empty_run_still_writes_reviewable_snapshot(self):
        targets = {'asof':'2026-09-09','nav':10000,'buckets':{}}
        with tempfile.TemporaryDirectory() as td:
            a = SimpleNamespace(establish=False,nav=None,host='localhost',port=1,client_id=52,
                                live=False,plan=None,save_plan=str(Path(td)/'plan.json'),
                                save_targets=str(Path(td)/'targets.json'))
            with patch.object(v,'KILL',str(Path(td)/'kill')), patch.object(v,'get_targets',return_value=targets), patch.object(v,'get_resting',return_value={}), patch.object(v,'nav_sanity',return_value=None), patch.object(v,'build_plan',return_value=([],10000)), patch.object(v,'clear_fail'):
                v._main(a)
            self.assertTrue(Path(a.save_plan).exists(), 'clean runs need a snapshot too')
            self.assertEqual(json.loads(Path(a.save_targets).read_text()), targets)

    def test_shadow_cannot_be_combined_with_live(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,str(Path(v.__file__)),'--shadow','--live'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('cannot combine',result.stderr)

    def test_shadow_state_and_notifications_are_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'state').mkdir()
            (root/'state/nav-history.jsonl').write_text('{"nav":100}\n')
            with patch.multiple(v,HERE=td,STATE=str(root/'state'),KILL=str(root/'state/AUTOEXEC_OFF'),
                                SHADOW=False,FAILS='',AUDIT='',LOCK='',NAVH=''):
                v.configure_shadow()
                self.assertNotEqual(v.STATE,str(root/'state'))
                self.assertEqual(Path(v.NAVH).read_text(),'{"nav":100}\n')
                with patch.object(v.subprocess,'run') as process:
                    v.notify('title','body'); process.assert_not_called()
                self.assertEqual((root/'state/nav-history.jsonl').read_text(),'{"nav":100}\n')

    def test_shadow_engine_uses_separate_reader_client_id(self):
        from types import SimpleNamespace
        with patch.object(v,'SHADOW',True), patch.object(v.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{}')) as p:
            v.get_targets(False)
            args=p.call_args[0][0]
            self.assertIn('--client-id',args)
            self.assertNotEqual(args[args.index('--client-id')+1],'51')
