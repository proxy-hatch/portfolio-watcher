import json
from pathlib import Path
import tempfile
import unittest
import watcher as w
from codex_agent import AgentError


class FakeServices:
    def __init__(self, verdict='APPROVE', plan_rc=0, empty=False, failure=None, exec_rc=0):
        self.verdict, self.plan_rc, self.empty = verdict, plan_rc, empty
        self.failure, self.exec_rc = failure, exec_rc
        self.executions, self.reports, self.notifications = [], [], []
    def build(self, run):
        if self.failure == 'engine': raise AgentError('engine', 'engine failed')
        p = run.artifact('plan.json')
        p.write_text(json.dumps({'targets':{'asof':'2026-09-09'},'plan':[] if self.empty else [{'symbol':'QLD','qty':1}]}))
        return self.plan_rc, p
    def evidence(self, run, plan): return {'status':'clear'}
    def review(self, run, packet, digest):
        if self.failure == 'timeout': raise AgentError('timeout', 'timed out')
        if self.failure == 'changed': run.artifact('plan.json').write_text('{}')
        return {'session_id':'review-id','output':{'verdict':self.verdict,'reason':'test','plan_sha256':digest}}
    def execute(self, run, plan):
        self.executions.append(plan.read_bytes())
        return self.exec_rc, 'PLACED: QLD' if not self.exec_rc else 'REJECTED: QLD'
    def report(self, run):
        self.reports.append(run.data['outcome'])
        if self.failure == 'report': raise AgentError('timeout','report timed out')
        return {'session_id':'report-id','output':{'report':'Weekly factual report','summary':'Week summary'}}
    def notify(self, title, body, priority): self.notifications.append((title,body,priority))


class PipelineTests(unittest.TestCase):
    def invoke(self, td, svc, kind='daily', shadow=False):
        return w.run_pipeline(Path(td), {'vault':str(Path(td)/'vault')}, kind, shadow, svc)

    def test_only_approved_unchanged_nonempty_successful_plan_can_execute(self):
        for verdict,rc,empty,failure,want,count in [
            ('APPROVE',0,False,None,'EXECUTED',1),
            ('HALT',0,False,None,'HALTED',0),
            ('APPROVE maybe',0,False,None,'FAILED-invalid',0),
            ('APPROVE',2,False,None,'BLOCKED',0),
            ('APPROVE',4,False,None,'HALTED-killswitch',0),
            ('APPROVE',0,True,None,'CLEAN',0),
            ('APPROVE',0,False,'timeout','FAILED-timeout',0),
            ('APPROVE',0,False,'changed','FAILED-invalid',0)]:
            with self.subTest(want=want), tempfile.TemporaryDirectory() as td:
                svc=FakeServices(verdict,rc,empty,failure)
                result=self.invoke(td,svc)
                self.assertEqual(result['outcome'],want)
                self.assertEqual(len(svc.executions),count)
                stored=json.loads((Path(td)/'state/runs'/f"{result['run_id']}.json").read_text())
                self.assertEqual(stored['outcome'],want)
                self.assertIn(want,svc.notifications[0][0])

    def test_shadow_never_executes_notifies_or_updates_live_latest(self):
        with tempfile.TemporaryDirectory() as td:
            svc=FakeServices()
            result=self.invoke(td,svc,shadow=True)
            self.assertEqual(result['outcome'],'SHADOW-APPROVED')
            self.assertEqual(svc.executions,[])
            self.assertEqual(svc.notifications,[])
            self.assertFalse((Path(td)/'state/last-daily-session').exists())
            self.assertFalse((Path(td)/'vault').exists())

    def test_weekly_report_runs_after_failed_trading_but_never_for_daily(self):
        for kind,expected in [('daily',[]),('weekly',['FAILED-engine'])]:
            with tempfile.TemporaryDirectory() as td:
                svc=FakeServices(failure='engine'); result=self.invoke(td,svc,kind)
                self.assertEqual(svc.reports,expected)
                self.assertEqual(result['outcome'],'FAILED-engine')
                if kind=='weekly': self.assertEqual(result['report_status'],'COMPLETE')

    def test_report_failure_cannot_overwrite_execution_status(self):
        with tempfile.TemporaryDirectory() as td:
            svc=FakeServices(failure='report'); result=self.invoke(td,svc,'weekly')
            self.assertEqual(result['outcome'],'EXECUTED')
            self.assertEqual(result['report_status'],'FAILED-timeout')
            self.assertEqual(len(svc.notifications),2)

    def test_broker_rejections_not_reported_as_execution_success(self):
        with tempfile.TemporaryDirectory() as td:
            svc=FakeServices(exec_rc=3); result=self.invoke(td,svc)
            self.assertEqual(result['outcome'],'FAILED-exec')
            self.assertIn('REJECTED',result['execution_output'])

    def test_duplicate_only_execution_is_clean_not_executed(self):
        class DuplicateServices(FakeServices):
            def execute(self,run,plan): return 0,'SKIPPED_DUPLICATE: QLD identical order already resting'
        with tempfile.TemporaryDirectory() as td:
            result=self.invoke(td,DuplicateServices())
            self.assertEqual(result['outcome'],'CLEAN')
            self.assertEqual(result['submitted_orders'],0)

    def test_interrupted_weekly_report_has_terminal_status(self):
        class InterruptServices(FakeServices):
            def report(self,run): raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as td:
            result=self.invoke(td,InterruptServices(),'weekly')
            self.assertEqual(result['report_status'],'FAILED-interrupted')
            self.assertEqual(result['outcome'],'EXECUTED')

    def test_shadow_does_not_take_live_trading_lock(self):
        from watcher_state import locked
        with tempfile.TemporaryDirectory() as td:
            with locked(Path(td)/'state/trading.lock',blocking=False):
                result=self.invoke(td,FakeServices(),shadow=True)
            self.assertEqual(result['outcome'],'SHADOW-APPROVED')

    def test_execution_timeout_never_claims_nothing_was_attempted(self):
        class TimeoutServices(FakeServices):
            def execute(self,run,plan): raise AgentError('timeout','broker process timed out')
        with tempfile.TemporaryDirectory() as td:
            result=self.invoke(td,TimeoutServices())
            self.assertEqual(result['outcome'],'FAILED-exec')
            text=Path(result['artifact_prefix']+'.outcome.md').read_text()
            self.assertNotIn('No execution was attempted.',text)
            self.assertIn('completion is unknown',text)

    def test_reviewer_assesses_materiality_of_visible_coverage_gaps(self):
        class CoverageServices(FakeServices):
            def evidence(self,run,plan):return {'status':'unknown','summary':'Some coverage is incomplete; no identified halt.'}
        with tempfile.TemporaryDirectory() as td:
            result=self.invoke(td,CoverageServices(),shadow=True)
            self.assertEqual(result['outcome'],'SHADOW-APPROVED')
        with tempfile.TemporaryDirectory() as td:
            result=self.invoke(td,CoverageServices(verdict='HALT'),shadow=True)
            self.assertEqual(result['outcome'],'HALTED')

    def test_identified_halt_cannot_be_overridden_by_approval(self):
        class HaltServices(FakeServices):
            def evidence(self,run,plan):return {'status':'halt','summary':'Active exchange halt.'}
        with tempfile.TemporaryDirectory() as td:
            svc=HaltServices();result=self.invoke(td,svc)
            self.assertEqual(result['outcome'],'HALTED')
            self.assertEqual(svc.executions,[])
