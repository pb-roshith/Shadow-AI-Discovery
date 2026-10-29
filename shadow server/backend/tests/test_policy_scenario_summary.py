import unittest
from unittest.mock import patch
from engine.api import scenarios


class PolicyScenarioSummary(unittest.TestCase):
    def test_credential_issue_takes_priority_over_approved_live_provider(self):
        openai = dict(id='openai', entity='policy-intelligence', provider='OpenAI', decision='Raise issue',
                      confidence=65, risk=35, signals=[dict(ts_last='2026-10-26T12:00:00Z', attributes={'live_scenario':'S2'})])
        gemini = dict(id='gemini', entity='policy-intelligence', provider='Google', decision='Genuine',
                      confidence=80, risk=45, signals=[dict(ts_last='2026-10-27T12:00:00Z', attributes={'live_scenario':'S2','evidence_origin':'live_sdk'})])
        for candidates in ([openai,gemini], [gemini,openai]):
            with self.subTest(order=[c['id'] for c in candidates]), patch('engine.api.list_payloads', side_effect=lambda table: candidates if table=='candidates' else [{'id':'S2'}]):
                result = scenarios()[0]
                self.assertEqual(result['result']['decision'], 'Raise issue')
                self.assertEqual(result['result']['id'], 'openai')
                self.assertEqual(result['provider'], 'OpenAI')
                self.assertEqual(set(result['candidate_ids']), {'openai','gemini'})

    def test_live_provider_is_shown_when_no_issue_exists(self):
        gemini = dict(id='gemini', entity='policy-intelligence', provider='Google', decision='Genuine',
                      confidence=80, risk=45, signals=[dict(ts_last='2026-10-27T12:00:00Z', attributes={'live_scenario':'S2','evidence_origin':'live_sdk'})])
        with patch('engine.api.list_payloads', side_effect=lambda table: [gemini] if table=='candidates' else [{'id':'S2'}]):
            result=scenarios()[0]
            self.assertEqual(result['result']['decision'], 'Genuine')
            self.assertEqual(result['provider'], 'Google')
