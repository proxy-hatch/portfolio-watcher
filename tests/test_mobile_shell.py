import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class MobileShellTests(unittest.TestCase):
    def setup_scripts(self,td):
        root=Path(td)
        for name in ('wf.sh','sessions.sh'): shutil.copy(ROOT/name,root/name)
        (root/'state').mkdir()
        (root/'state/last-daily-session').write_text('aaaaaaaa-1111-2222-3333-444444444444')
        (root/'state/sessions.tsv').write_text('now\tdaily\taaaaaaaa-1111-2222-3333-444444444444\tdaily-label\tEXECUTED\nnow\tdaily\taaaaaaaa-5555-2222-3333-444444444444\tolder\tCLEAN\n')
        fake=root/'tmux'
        fake.write_text('#!/bin/sh\ncase "$*" in *ls*) exit 0;; esac\nprintf "%s\\n" "$@"\n')
        fake.chmod(0o700)
        return root,dict(os.environ,WATCHER_TMUX_BIN=str(fake))

    def test_explicit_run_id_keys_tmux_and_inner_command(self):
        with tempfile.TemporaryDirectory() as td:
            root,env=self.setup_scripts(td)
            p=subprocess.run(['zsh',str(root/'wf.sh'),'daily','--safe','--sid','bbbbbbbb-1111-2222-3333-444444444444'],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn('wf-daily-safe-bbbbbbbb',p.stdout)
            self.assertIn('--sid bbbbbbbb-1111-2222-3333-444444444444',p.stdout)

    def test_shadow_run_is_forwarded_and_gets_distinct_tmux(self):
        with tempfile.TemporaryDirectory() as td:
            root,env=self.setup_scripts(td)
            p=subprocess.run(['zsh',str(root/'wf.sh'),'run','daily','--shadow'],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn('wf-run-daily-shadow',p.stdout)
            self.assertIn('run.sh daily --shadow',p.stdout)

    def test_ambiguous_history_prefix_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root,env=self.setup_scripts(td)
            p=subprocess.run(['zsh',str(root/'sessions.sh'),'resume','aaaaaaaa'],env=env,capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('ambiguous',p.stderr.lower())
