import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import codex_agent as a


class AgentTests(unittest.TestCase):
    def test_catalog_removes_execution_tools_without_changing_model_instructions(self):
        original={"slug":"gpt-6-astra","tool_mode":"code_mode_only", "apply_patch_tool_type":"freeform","experimental_supported_tools":["clock"], "model_messages":{"base_instructions":"original"}}
        restricted=a.restricted_catalog(original)
        self.assertEqual(restricted["tool_mode"],"standard")
        self.assertIsNone(restricted["apply_patch_tool_type"])
        self.assertEqual(restricted["experimental_supported_tools"],[])
        self.assertEqual(restricted["model_messages"], original["model_messages"])
        self.assertEqual(original["tool_mode"],"code_mode_only")

    def test_cli_requires_chatgpt_even_if_saved_auth_is_api(self):
        args=a.command({'codex_bin':'/codex','model':'gpt-6-astra'},Path('/tmp'),None,Path('/tmp/output.json'),'medium',False)
        self.assertIn('forced_login_method="chatgpt"',args)

    def test_only_completed_exact_approval_is_accepted(self):
        good = {'verdict': 'APPROVE', 'reason': 'consistent', 'plan_sha256': 'a'*64}
        self.assertEqual(a.validate_verdict(good, 'a'*64)['verdict'], 'APPROVE')
        for bad in [dict(good, verdict='APPROVE maybe'), dict(good, plan_sha256='b'*64),
                    dict(good, reason=''), dict(good, orders=[]), [], None]:
            with self.subTest(bad=bad), self.assertRaises(a.AgentError):
                a.validate_verdict(bad, 'a'*64)

    def test_completed_text_does_not_override_failure_or_tool_execution(self):
        events = [{'type': 'thread.started', 'thread_id': 'sid'},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 3}}]
        self.assertEqual(a.check_events(events, False), 'sid')
        for bad in [events[:-1], events + [{'type':'turn.failed','error':{'message':'oops'}}],
                    events + [{'type':'item.completed','item':{'type':'command_execution'}}]]:
            with self.assertRaises(a.AgentError): a.check_events(bad, False)
        with self.assertRaises(a.AgentError):
            a.check_events(events + [{'type':'item.completed','item':{'type':'web_search'}}], False)
        self.assertEqual(a.check_events(events + [{'type':'item.completed','item':{'type':'web_search'}}], True), 'sid')

    def test_auth_and_quota_not_retried_but_timeout_is(self):
        for category, calls in [('auth', 1), ('quota', 1), ('invalid', 1), ('timeout', 2), ('api', 2)]:
            with self.subTest(category=category), tempfile.TemporaryDirectory() as td:
                with patch.object(a, 'attempt', side_effect=a.AgentError(category, 'failed')) as p:
                    with self.assertRaises(a.AgentError):
                        a.run_agent('prompt', Path(td)/'review', {}, {}, retries=1)
                    self.assertEqual(p.call_count, calls)

    def test_timeout_kills_descendant_even_if_parent_exits(self):
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td)/'escaped'
            code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',\"import time,pathlib; time.sleep(0.8); pathlib.Path(sys.argv[1]).touch()\".replace('import time,pathlib','import time,pathlib,sys'),sys.argv[1]]); time.sleep(10)"
            with self.assertRaises(a.AgentError) as cm:
                a.run_process([sys.executable, '-c', code, str(flag)], '', Path(td)/'proc', 0.15)
            self.assertEqual(cm.exception.category, 'timeout')
            import time
            time.sleep(1)
            self.assertFalse(flag.exists())

    def test_subprocess_environment_cannot_switch_to_api_billing(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'secret','CODEX_API_KEY':'secret','CODEX_HOME':'/untrusted'}):
            env = a.agent_env()
            self.assertNotIn('OPENAI_API_KEY', env)
            self.assertNotIn('CODEX_API_KEY', env)
            self.assertNotIn('CODEX_HOME', env)

    def test_attempt_reads_real_jsonl_and_last_message(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td)/'codex'
            fake.write_text('#!'+sys.executable+'\nimport sys,json,pathlib\na=sys.argv\npathlib.Path(a[a.index("-o")+1]).write_text(json.dumps({"verdict":"HALT","reason":"uncertain","plan_sha256":"a"*64}))\nprint(json.dumps({"type":"thread.started","thread_id":"abc"}))\nprint(json.dumps({"type":"turn.completed"}))\n')
            fake.chmod(0o700)
            with patch.object(a, 'write_catalog'):
                result = a.attempt('hello', Path(td)/'review', a.VERDICT_SCHEMA,
                               {'codex_bin':str(fake),'model':'gpt-6-astra'}, timeout=3)
            self.assertEqual(result['session_id'], 'abc')
            self.assertEqual(result['output']['verdict'], 'HALT')
