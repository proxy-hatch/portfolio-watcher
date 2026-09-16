from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest
import risk_evidence as r

BASE='<rss xmlns:ndaq="http://www.nasdaqtrader.com/"><channel><pubDate>Sat, 12 Sep 2026 00:51:10 GMT</pubDate><ndaq:numItems>{count}</ndaq:numItems>{items}</channel></rss>'
class RiskEvidenceTests(unittest.TestCase):
    def test_fresh_complete_feed_distinguishes_absence_and_active_halt(self):
        t=datetime(2026,9,12,0,52,tzinfo=timezone.utc)
        item='<item><ndaq:IssueSymbol>QLD</ndaq:IssueSymbol><ndaq:HaltDate>09/11/2026</ndaq:HaltDate><ndaq:ReasonCode>T1</ndaq:ReasonCode></item>'
        result=r.parse_halts(BASE.format(count=1,items=item),['QLD','AIS'],t)
        self.assertEqual(result['active_symbols'],['QLD'])
        self.assertEqual(result['not_listed'],['AIS'])
        self.assertEqual(result['status'],'halt')

    def test_stale_or_truncated_feed_is_unknown(self):
        t=datetime(2026,9,13,tzinfo=timezone.utc)
        self.assertEqual(r.parse_halts(BASE.format(count=0,items=''),['QLD'],t)['status'],'unknown')
        with self.assertRaises(ValueError):r.parse_halts(BASE.format(count=2,items=''),['QLD'],datetime(2026,9,12,0,52,tzinfo=timezone.utc))

    def test_resumed_halt_does_not_become_active(self):
        item='<item><ndaq:IssueSymbol>QLD</ndaq:IssueSymbol><ndaq:ResumptionDate>09/11/2026</ndaq:ResumptionDate><ndaq:ResumptionTradeTime>15:00:00.000</ndaq:ResumptionTradeTime></item>'
        out=r.parse_halts(BASE.format(count=1,items=item),['QLD'],datetime(2026,9,12,0,52,tzinfo=timezone.utc))
        self.assertEqual(out['active_symbols'],[])
        self.assertEqual(out['status'],'checked')

    def test_identified_halt_survives_other_coverage_failures(self):
        for overall,row in [('halt','clear'),('clear','halt')]:
            evidence={'status':overall,'summary':'issuer suspension','symbols':[{'symbol':'QLD','status':row,'finding':'suspension','sources':[]}]}
            out=r.assess_evidence(evidence,['QLD'],{'error':'calendar unavailable'},{'status':'unknown'})
            self.assertEqual(out['status'],'halt')
            self.assertIn('suspension',out['summary'])

    def test_fetch_has_total_deadline_even_while_bytes_keep_arriving(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length','100');self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b'x');self.wfile.flush();time.sleep(.05)
                except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*_):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                started=time.monotonic()
                result=r.fetch_halts([],Path(td)/'feed.xml',total_timeout=.15,socket_timeout=.1,
                                     url=f'http://127.0.0.1:{server.server_port}/')
                elapsed=time.monotonic()-started
            self.assertEqual(result['status'],'unknown')
            self.assertIn('deadline',result['error'])
            self.assertLess(elapsed,1.0)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=1)
