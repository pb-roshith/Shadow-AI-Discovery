import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine.collectors.hybrid import HybridCollector
from engine.collectors.local import Collector
from engine.score import score
from scenarios.demo import write_log


class LiveApplicationPolicy(unittest.TestCase):
    def test_live_mode_does_not_read_seeded_streams_or_demo_endpoint_configs(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, {'SHADOWAI_DB_BACKEND': 'sqlite'}), patch('engine.collectors.hybrid.ROOT', Path(temp)):
            logs = Path(temp) / 'logs'
            logs.mkdir()
            event = dict(ts='2026-10-27T12:00:00+00:00', proxy_user='priya', host='chatgpt.com', origin='seeded_demo')
            for name in ('proxy.jsonl','gateway.jsonl','dlp.jsonl','endpoint.jsonl','mcp_runtime.jsonl','mcp_audit.jsonl'):
                (logs/name).write_text(json.dumps(event))
            collector = HybridCollector('test','live')
            with patch.object(Collector,'read_events') as read, patch.object(Collector,'collect_endpoint') as endpoint, patch.object(Collector,'collect_mcp') as mcp:
                for name in ('proxy.jsonl','gateway.jsonl','dlp.jsonl','endpoint.jsonl','mcp_runtime.jsonl','mcp_audit.jsonl'):
                    self.assertEqual(collector.read_events(name),[])
                collector.collect_endpoint()
                collector.collect_mcp()
                read.assert_not_called()
                endpoint.assert_not_called()
                mcp.assert_not_called()

    def test_policy_intelligence_uses_real_deduplicated_sdk_attempts(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, {'SHADOWAI_DB_BACKEND': 'sqlite'}), patch('engine.collectors.hybrid.ROOT', Path(temp)):
            logs = Path(temp) / 'logs'
            logs.mkdir()
            event = dict(ts='2026-10-27T12:00:00+00:00', app='policy-intelligence', provider='OpenAI', model='test', request_id='policy-one', status='success', origin='live_sdk')
            (logs / 'sdk_calls.jsonl').write_text('\n'.join(json.dumps(e) for e in (event, event, dict(event, request_id='fake', origin='replay'))))
            collector = HybridCollector('test', 'database')
            with patch.object(Collector, 'collect_logs'):
                collector.collect_logs()
            self.assertEqual(len(collector.matches), 1)
            signal = collector.matches[0]
            self.assertEqual(signal['entity'], 'policy-intelligence')
            self.assertEqual(signal['attributes']['live_scenario'], 'S2')
            self.assertEqual(signal['event_count'], 1)
            self.assertEqual(signal['user_id'], 'dev-svc')
            self.assertEqual(signal['attributes']['outcomes'], {'success': 1, 'failed': 0})

    def test_policy_scoring_counts_sdk_attempts_without_counting_source_files(self):
        with patch.dict(os.environ, {'SHADOWAI_DB_BACKEND': 'sqlite'}):
            for provider in ('OpenAI', 'Mistral', 'Google'):
                with self.subTest(provider=provider):
                    attributes = {'live_scenario': 'S2', 'evidence_origin': 'live_sdk', 'request_ids': ['policy-one']}
                    runtime = dict(signal_id='sdk', channel='Network', signal_type='ai_network_call', provider=provider,
                                   event_count=1, attributes=attributes)
                    code = dict(runtime, signal_id='code', channel='Code', signal_type='sdk_import', event_count=20)
                    code['attributes'] = {'live_scenario': 'S2', 'evidence_origin': 'live'}
                    candidate = dict(signals=[runtime, code], user_id='dev-svc', cmdb={}, repo_register={}, user={}, inventory={'status':'Unknown'})
                    recurrence = next(f for f in score(candidate)['confidence_factors'] if f['name']=='Recurrence')
                    self.assertEqual(recurrence['points'], 0)
                    self.assertIn('1 recorded runtime', recurrence['reason'])
                    candidate['signals'] = [code]
                    recurrence = next(f for f in score(candidate)['confidence_factors'] if f['name']=='Recurrence')
                    self.assertIn('0 recorded runtime', recurrence['reason'])

    def test_installed_policy_scenario_retires_fake_openai_traffic(self):
        self.assertTrue(HybridCollector.retired_demo('old', dict(origin='seeded_demo', proxy_user='dev-svc', host='api.openai.com')))
        self.assertFalse(HybridCollector.retired_demo('actual', dict(origin='live', proxy_user='dev-svc', host='api.openai.com')))

    def test_no_fixture_fallback_in_any_mode(self):
        fixtures = [(1, {'app': 'credit-dossier', 'origin': 'seeded_demo'}),
                    (2, {'app': 'customer-assistant', 'origin': 'replay'}),
                    (3, {'app': 'loan-ops-helper', 'origin': 'seeded_demo'})]
        with TemporaryDirectory() as temp, patch.dict(os.environ, {'SHADOWAI_DB_BACKEND': 'sqlite'}), patch('engine.collectors.hybrid.ROOT', Path(temp)):
            for mode in ('database', 'replay', 'observed'):
                collector = HybridCollector('test', mode)
                with patch.object(Collector, 'read_events', return_value=fixtures):
                    self.assertEqual(collector.read_events('gateway.jsonl'), fixtures[2:])

    def test_sdk_attempts_are_live_deduplicated_and_code_does_not_inflate_recurrence(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, {'SHADOWAI_DB_BACKEND': 'sqlite'}), patch('engine.collectors.hybrid.ROOT', Path(temp)):
            logs = Path(temp) / 'logs'
            logs.mkdir()
            event = dict(ts='2026-10-27T12:00:00+00:00', app='customer-assistant', provider='Google', request_id='one', status='failed', origin='live_sdk')
            fake = dict(event, request_id='fake', origin='seeded_demo')
            (logs / 'sdk_calls.jsonl').write_text('\n'.join(json.dumps(e) for e in (event, event, fake)))
            collector = HybridCollector('test', 'database')
            with patch.object(Collector, 'collect_logs'):
                collector.collect_logs()
            self.assertEqual(len(collector.matches), 1)
            signal = collector.matches[0]
            self.assertEqual(signal['event_count'], 1)
            self.assertEqual(signal['attributes']['outcomes'], {'success': 0, 'failed': 1})
            self.assertEqual(signal['source_ref'], 'live:logs/sdk_calls.jsonl')
            self.assertEqual(signal['attributes']['identity_source'], 'register')
            signal['signal_id'] = 'runtime'
            code = dict(signal, signal_id='code', channel='Code', signal_type='sdk_import', event_count=20)
            c = dict(signals=[signal, code], user_id='customer-assistant-svc', cmdb={}, repo_register={}, user={}, inventory={'status': 'Unknown'})
            result = score(c)
            recurrence = next(f for f in result['confidence_factors'] if f['name'] == 'Recurrence')
            self.assertEqual(recurrence['points'], 0)
            self.assertIn('1 recorded runtime', recurrence['reason'])

    def test_demo_log_setup_preserves_actual_invocations(self):
        with TemporaryDirectory() as temp, patch('scenarios.demo.ROOT', Path(temp)):
            logs = Path(temp) / 'logs'
            logs.mkdir()
            live = {'origin': 'live', 'request_id': 'actual'}
            (logs / 'gateway.jsonl').write_text(json.dumps(live) + '\n')
            write_log('gateway', [])
            self.assertEqual(json.loads((logs / 'gateway.jsonl').read_text()), live)
