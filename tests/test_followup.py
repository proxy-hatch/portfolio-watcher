import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import watcher_followup as f


class FollowupTests(unittest.TestCase):
    def setup_run(self, td):
        root=Path(td); (root/'state/runs').mkdir(parents=True)
        rid='aaaaaaaa-1111-2222-3333-444444444444'
        (root/'state/last-daily-session').write_text(rid)
        meta={'run_id':rid,'kind':'daily','provider':'codex','outcome':'EXECUTED','artifact_prefix':str(root/'logs/run')}
        (root/'state/runs'/f'{rid}.json').write_text(json.dumps(meta))
        return root,rid

    def test_legacy_ids_resume_claude_without_codex_bootstrap(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'state').mkdir()
            (root/'state/last-daily-session').write_text('old-claude-id')
            command=f.prepare(root,{'vault':td},'daily',None,False,[])
            self.assertEqual(command[:3],['/opt/homebrew/bin/claude','-r','old-claude-id'])
            self.assertIn('--dangerously-skip-permissions',command)

    def test_bootstrap_persists_id_and_safe_default_use_separate_conversations(self):
        with tempfile.TemporaryDirectory() as td:
            root,rid=self.setup_run(td)
            c={'vault':td,'codex_bin':'/codex','model':'gpt-6-astra','followup_effort':'high'}
            with patch.object(f,'bootstrap',return_value='codex-default') as boot:
                first=f.prepare(root,c,'daily',None,False,[])
                again=f.prepare(root,c,'daily',None,False,[])
                self.assertEqual(boot.call_count,1)
            self.assertEqual(first,again)
            self.assertEqual(first[:3],['/codex','resume','codex-default'])
            self.assertIn('--dangerously-bypass-approvals-and-sandbox',first)
            with patch.object(f,'bootstrap',return_value='codex-safe'):
                safe=f.prepare(root,c,'daily',rid,True,[])
            self.assertEqual(safe[:3],['/codex','resume','codex-safe'])
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',safe)
            self.assertIn('on-request',safe)
            stored=json.loads((root/'state/runs'/f'{rid}.json').read_text())
            self.assertEqual(stored['followup_session_id'],'codex-default')
            self.assertEqual(stored['safe_followup_session_id'],'codex-safe')

    def test_new_context_contains_actual_outcome_and_cannot_replay_unasked(self):
        with tempfile.TemporaryDirectory() as td:
            root,rid=self.setup_run(td)
            text=f.context(root,json.loads((root/'state/runs'/f'{rid}.json').read_text()))
            self.assertIn('EXECUTED',text)
            self.assertIn('not a new trade authorization',text)

    def test_corrupt_metadata_does_not_fall_back_to_claude(self):
        with tempfile.TemporaryDirectory() as td:
            root,rid=self.setup_run(td)
            (root/'state/runs'/f'{rid}.json').write_text('broken')
            with self.assertRaises(ValueError): f.prepare(root,{'vault':td},'daily',None,False,[])
