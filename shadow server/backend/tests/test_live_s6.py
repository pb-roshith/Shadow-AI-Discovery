import json
import unittest
from engine.pipeline import run
from engine.db import list_payloads
from tests.test_live_s1 import LiveScenarioOne


class LiveScenarioSix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LiveScenarioOne.setUpClass()
        cls.root = LiveScenarioOne.root

    @classmethod
    def tearDownClass(cls):
        LiveScenarioOne.tearDownClass()

    def test_sdk_calls_are_live_deduplicated_and_scoped_to_chatbot(self):
        run('hybrid')
        before = [c for c in list_payloads('candidates') if c['entity'] == 'customer-assistant']
        self.assertEqual({c['provider'] for c in before}, {'Google', 'Mistral', 'OpenAI'})
        self.assertTrue(all(c['channels'] == ['Code'] for c in before))
        event = {'ts': '2026-10-27T12:00:00+00:00', 'app': 'customer-assistant', 'provider': 'Google',
                 'model': 'test-model', 'request_id': 's6-request', 'status': 'success', 'origin': 'live_sdk'}
        (self.root / 'logs/sdk_calls.jsonl').write_text((json.dumps(event) + '\n') * 2)
        run('hybrid')
        candidate = next(c for c in list_payloads('candidates') if c['entity'] == 'customer-assistant' and c['provider'] == 'Google')
        self.assertEqual(candidate['channels'], ['Code', 'Network'])
        signal = next(s for s in candidate['signals'] if s['channel'] == 'Network')
        self.assertEqual(signal['event_count'], 1)
        self.assertEqual(signal['attributes']['evidence_origin'], 'live_sdk')
        self.assertFalse(signal['attributes']['via_gateway'])
        self.assertEqual(signal['attributes']['outcomes'], {'success': 1, 'failed': 0})
        self.assertTrue(all(s['entity'] == 'customer-assistant' for s in candidate['signals']))
