import json
import unittest
from unittest.mock import patch
from engine.pipeline import run
from engine.db import list_payloads
from engine.governance import signal_bundle
import scenarios.demo as demo
from tests.test_live_s1 import LiveScenarioOne


class LiveScenarioSeven(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LiveScenarioOne.setUpClass()
        cls.root = LiveScenarioOne.root
        demo.repository('loan-risk-classifier', {'app.py': 'import ollama\n', 'requirements.txt': 'ollama\n'})

    @classmethod
    def tearDownClass(cls):
        LiveScenarioOne.tearDownClass()

    def test_code_then_real_local_attempts_are_scoped_deduplicated_and_auditable(self):
        run('hybrid')
        before = next(c for c in list_payloads('candidates') if c['entity'] == 'loan-risk-classifier')
        self.assertEqual(before['channels'], ['Code'])
        event = dict(ts='2026-10-27T12:00:00+00:00',app='loan-risk-classifier',provider='Ollama',model='local-model',request_id='one',status='success',origin='live_local',host='127.0.0.1:11434')
        events = [event,event,dict(event,request_id='two',status='failed'),dict(event,request_id='fake',origin='seeded_demo'),dict(event,request_id='old',app='ai-risk-classifier')]
        (self.root / 'logs/ollama_calls.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
        run('hybrid')
        after = next(c for c in list_payloads('candidates') if c['entity'] == 'loan-risk-classifier')
        self.assertEqual(after['channels'], ['Code','Endpoint'])
        runtime = next(s for s in after['signals'] if s['signal_type'] == 'local_model_call')
        self.assertEqual(runtime['event_count'], 2)
        self.assertEqual(runtime['attributes']['outcomes'], {'success':1,'failed':1})
        self.assertEqual(runtime['attributes']['evidence_origin'], 'live_local')
        self.assertTrue(runtime['attributes']['local_only'])
        self.assertIn('J1', after['join_rules_fired'])
        self.assertGreater(after['confidence'], before['confidence'])
        self.assertEqual(next(f['points'] for f in after['risk_factors'] if f['name']=='External exposure'), 0)
        self.assertTrue(signal_bundle(runtime)['verified'])
        self.assertFalse(any(s['attributes'].get('evidence_origin')=='static_fixture' for s in after['signals']))
        self.assertFalse(any(c['entity']=='ahmed-scratch' for c in list_payloads('candidates')))
        run('replay')
        again = next(c for c in list_payloads('candidates') if c['entity']=='loan-risk-classifier')
        self.assertEqual(next(s['event_count'] for s in again['signals'] if s['signal_type']=='local_model_call'), 2)


class ScenarioAssociations(unittest.TestCase):
    def test_local_classifier_is_s7_and_does_not_steal_s4(self):
        from engine import api
        app = dict(id='app',entity='loan-risk-classifier',provider='Ollama',user_id='ahmed',
                   decision='Monitor',risk=10,confidence=75,signals=[{'signal_type':'local_model_call'}])
        ambient = dict(id='ambient',entity='',provider='Ollama',user_id='ahmed',
                       decision='Monitor',risk=10,confidence=75,signals=[{'signal_type':'ai_process'}])
        scenarios = [dict(id='S4',provider='Ollama',user_id='ahmed'),dict(id='S7',provider='Anthropic',entity='ahmed-scratch')]
        with patch.object(api,'list_payloads',side_effect=lambda table:[app,ambient] if table=='candidates' else scenarios):
            records = api.scenarios()
        self.assertEqual(records[0]['result']['id'], 'ambient')
        self.assertEqual(records[0]['source'], 'demo')
        self.assertEqual(records[1]['result']['id'], 'app')
        self.assertEqual(records[1]['source'], 'live')
        self.assertEqual(records[1]['entity'], 'loan-risk-classifier')
