import json
import unittest
from unittest.mock import MagicMock, patch

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine import s3_demo
from tests.proxy_harness import ProxyHarness


class S3Demo(unittest.TestCase):
    def setUp(self):
        recorder = patch.object(s3_demo, 'write_request')
        self.metrics = recorder.start()
        self.addCleanup(recorder.stop)
        app = FastAPI()
        app.include_router(s3_demo.router)
        self.client = TestClient(app)

    def test_real_proxy_upload_returns_only_verified_metadata(self):
        with ProxyHarness(offline=True) as proxy, patch.object(s3_demo, 'PROXY', f'http://priya:demo@127.0.0.1:{proxy.port}'), \
                patch.object(s3_demo, 'CA', proxy.ca), patch.object(s3_demo, 'status', return_value={'ready': True}), \
                patch.object(s3_demo, 'telemetry_path', side_effect=lambda name: proxy.root / 'logs' / name):
            response = self.client.post('/demos/s3/run')
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertTrue(body['verified'])
            self.assertTrue(body['blocked'])
            self.assertEqual(body['http_status'], 403)
            self.assertEqual(body['evidence']['dlp'][0]['match_count'], 14)
            self.assertEqual(body['evidence']['network']['proxy_user'], 'priya')
            self.assertEqual(proxy.server.connections_received, 0)
            self.assertEqual(self.metrics.call_args.args[0], 'priya-chatgpt')
            self.assertEqual(self.metrics.call_args.args[2], 'blocked')
            self.assertGreaterEqual(self.metrics.call_args.args[3]['duration_ms'], 0)
            self.assertNotIn('ACC-', response.text)
            self.assertNotIn('demo@', response.text)
            self.assertNotIn('/backend-api', response.text)

    def test_unready_does_not_upload(self):
        with patch.object(s3_demo, 'status', return_value={'ready': False}), patch.object(s3_demo.requests, 'Session') as session:
            self.assertEqual(self.client.post('/demos/s3/run').status_code, 503)
            session.assert_not_called()

    def test_concurrent_upload_rejected(self):
        with s3_demo.UPLOAD_LOCK:
            self.assertEqual(self.client.post('/demos/s3/run').status_code, 409)

    def test_block_without_audit_is_not_verified(self):
        session = MagicMock()
        session.post.return_value.status_code = 403
        session.post.return_value.headers = {'X-ShadowAI-DLP': 'blocked'}
        with patch.object(s3_demo, 'status', return_value={'ready': True}), patch.object(s3_demo, 'records', return_value=[]), \
                patch.object(s3_demo.requests, 'Session', return_value=session), patch.object(s3_demo.time, 'sleep'):
            result = self.client.post('/demos/s3/run').json()
        self.assertTrue(result['blocked'])
        self.assertFalse(result['verified'])
        self.assertIsNone(result['evidence'])

    def test_proxy_error_does_not_expose_credentials(self):
        session = MagicMock()
        session.post.side_effect = requests.exceptions.ProxyError('407 priya:demo@localhost password')
        with patch.object(s3_demo, 'status', return_value={'ready': True}), patch.object(s3_demo, 'records', return_value=[]), \
                patch.object(s3_demo.requests, 'Session', return_value=session):
            response = self.client.post('/demos/s3/run')
        self.assertEqual(response.status_code, 502)
        self.assertIn('407', response.text)
        self.assertNotIn('demo@', response.text)
        self.assertNotIn('password', response.text)

    def test_discovery_returns_only_real_s3_joined_findings(self):
        candidate = dict(id='s3', name='priya → chatgpt.com', user_id='priya',
                         signals=[{'host':'chatgpt.com', 'channel':'DLP', 'ts_first':'2026-10-28T12:00:00+05:30', 'ts_last':'2026-10-28T12:00:00+05:30'}],
                         channels=['DLP', 'Network'], confidence=85, risk=85, decision='Raise issue',
                         join_rules_fired=['J4'], private_field='excluded')
        with patch('engine.pipeline.run', return_value={'id': 'actual-run'}) as run, \
                patch('engine.db.list_payloads', return_value=[candidate, dict(candidate, user_id='ahmed')]):
            response = self.client.post('/demos/s3/discover')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['run_id'], 'actual-run')
        self.assertEqual(len(response.json()['candidates']), 1)
        self.assertNotIn('private_field', response.text)
        self.assertEqual(run.call_args.args, ('live',))

    def test_discovery_selects_the_current_upload(self):
        target = dict(flow_id='current', ts='2026-10-28T12:00:00+05:30')
        def candidate(id, timestamp):
            return dict(id=id, user_id='priya', join_rules_fired=['J4'], signals=[
                dict(host='chatgpt.com', channel='DLP', ts_first=timestamp, ts_last=timestamp)])
        rows = [candidate('current-candidate', target['ts']), candidate('old', '2026-10-28T10:00:00+05:30')]
        with patch.object(s3_demo, 'records', return_value=[target]), \
                patch('engine.pipeline.run', return_value={'id':'actual'}), patch('engine.db.list_payloads', return_value=rows):
            response = self.client.post('/demos/s3/discover', json={'flow_id':'current'})
        self.assertEqual([c['id'] for c in response.json()['candidates']], ['current-candidate'])
