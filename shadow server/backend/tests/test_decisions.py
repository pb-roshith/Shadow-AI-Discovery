import unittest
import copy
import os
import shutil
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
from engine.api import app
from engine.decide import decide
from engine.score import score
from engine.config import reference_file


class RiskDecisions(unittest.TestCase):
    def test_existing_registry_migrates_rules_without_changing_thresholds(self):
        from engine import bootstrap, config, db
        with TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            shutil.copytree(config.ROOT / 'reference', root / 'reference')
            shutil.copytree(config.ROOT / 'scenarios', root / 'scenarios', ignore=shutil.ignore_patterns('__pycache__'))
            stack.enter_context(patch.dict(os.environ, {'SHADOWAI_DB_BACKEND': 'sqlite'}))
            for module in (bootstrap, config, db):
                stack.enter_context(patch.object(module, 'ROOT', root))
            legacy = copy.deepcopy(reference_file('rules.yaml'))
            legacy['decision_rules'] = [row for row in legacy['decision_rules'] if row['id'] not in ('R4', 'R5')]
            legacy['decision_rules'].append({'id': 'R4', 'condition': 'otherwise', 'decision': 'MONITOR'})
            legacy['join_rules'][0]['description'] = 'Custom join description'
            legacy['issue_due'] = '3 working days'
            scoring = reference_file('scoring.yaml')
            scoring['thresholds']['issue_risk'] = 91
            db.put_document('reference_documents', 'rules.yaml', legacy)
            db.put_document('reference_documents', 'scoring.yaml', scoring)
            bootstrap.seed_documents()
            bootstrap.seed_documents()
            migrated = db.document('reference_documents', 'rules.yaml')
            self.assertEqual(migrated['decision_rules'], reference_file('rules.yaml')['decision_rules'])
            self.assertEqual(migrated['join_rules'][0]['description'], 'Custom join description')
            self.assertEqual(migrated['issue_due'], '3 working days')
            self.assertEqual(db.document('reference_documents', 'scoring.yaml'), scoring)

    def test_decision_boundaries_and_precedence(self):
        cases = [
            ('Approved', 90, 90, 'R4', 'Raise issue'),
            ('Approved', 40, 70, 'R4', 'Raise issue'),
            ('Approved', 70, 69, 'R2', 'Genuine'),
            ('Approved', 69, 69, 'R5', 'Monitor'),
            ('Approved', 39, 90, 'R1', 'False positive'),
            ('Unknown', 40, 70, 'R3', 'Raise issue'),
            ('Restricted', 90, 70, 'R3', 'Raise issue'),
            ('Revoked', 90, 69, 'R5', 'Monitor'),
            ('Unknown', 39, 90, 'R1', 'False positive'),
        ]
        with patch('engine.decide.reference', side_effect=reference_file):
            for status, confidence, risk, rule, decision in cases:
                with self.subTest(status=status, confidence=confidence, risk=risk):
                    result = decide({'inventory': {'status': status, 'reason': ''},
                                     'confidence': confidence, 'risk': risk, 'signals': []})
                    self.assertEqual((result['rule'], result['decision']), (rule, decision))
                    self.assertEqual(sum(row['fired'] for row in result['decision_trace']), 1)
                    self.assertEqual([row['rule'] for row in result['decision_trace']],
                                     [row['id'] for row in reference_file('rules.yaml')['decision_rules']])

    def candidate(self, kind, channel='MCP', tools=None):
        return {'signals': [{'signal_id': 'test', 'signal_type': kind, 'channel': channel,
                            'event_count': 10, 'attributes': {'identity_source': 'direct', 'tools': tools or []}}],
                'inventory': {'status': 'Approved', 'owner': 'Database owner', 'reason': ''},
                'user_id': 'service', 'user': {'type': 'service'}, 'repo_register': None,
                'cmdb': {'criticality': 'High', 'data_classification': 'Confidential', 'holds_customer_data': 'yes'}}

    def test_approved_mcp_write_access_increases_risk_and_raises_issue(self):
        with patch('engine.score.reference', side_effect=reference_file), patch('engine.decide.reference', side_effect=reference_file):
            read = score(self.candidate('mcp_server_running', tools=[{'name': 'query_loans', 'write': False}]))
            write = decide(score(self.candidate('mcp_server_running', tools=[{'name': 'execute_sql', 'write': True}])))
        self.assertGreater(write['risk'], read['risk'])
        self.assertGreaterEqual(write['risk'], 70)
        self.assertEqual((write['rule'], write['decision']), ('R4', 'Raise issue'))
        control = next(row for row in write['risk_factors'] if row['name'] == 'Control weakness')
        self.assertEqual(control['points'], 5)
        self.assertIn('write/destructive MCP', control['reason'])
        self.assertEqual(write['risk'], sum(row['points'] for row in write['risk_factors']))

    def test_approved_exposed_credential_increases_risk_and_keeps_override(self):
        with patch('engine.score.reference', side_effect=reference_file), patch('engine.decide.reference', side_effect=reference_file):
            clean = score(self.candidate('sdk_import', 'Code'))
            exposed = decide(score(self.candidate('credential_in_file', 'Secret')))
        self.assertGreater(exposed['risk'], clean['risk'])
        self.assertEqual((exposed['rule'], exposed['decision']), ('R0', 'Raise issue'))


class CredentialDecisions(unittest.TestCase):
    def test_exposed_credentials_override_approval_and_confidence(self):
        for kind in ('credential_in_file', 'credential_in_history'):
            for confidence in (10, 75, 100):
                with self.subTest(kind=kind, confidence=confidence):
                    candidate = {'confidence': confidence, 'risk': 25,
                                 'inventory': {'status': 'Approved', 'reason': 'All tools globally approved'},
                                 'signals': [{'signal_type': kind}]}
                    result = decide(candidate)
                    self.assertEqual(result['decision'], 'Raise issue')
                    self.assertEqual(result['rule'], 'R0')
                    self.assertEqual(sum(trace['fired'] for trace in result['decision_trace']), 1)

    def test_approved_use_without_credentials_keeps_genuine_decision(self):
        candidate = {'confidence': 90, 'risk': 25, 'inventory': {'status': 'Approved', 'reason': ''},
                     'signals': [{'signal_type': 'sdk_import'}]}
        self.assertEqual(decide(candidate)['decision'], 'Genuine')

    def test_scenario_six_summary_prefers_credential_issue(self):
        candidates = [
            {'id': 'gemini', 'entity': 'customer-assistant', 'provider': 'Google', 'decision': 'Genuine',
             'confidence': 90, 'risk': 35, 'signals': [{'ts_last': '2026-10-27T12:00:00Z', 'attributes': {'live_scenario': 'S6'}}]},
            {'id': 'openai-secret', 'entity': 'customer-assistant', 'provider': 'OpenAI', 'decision': 'Raise issue',
             'confidence': 75, 'risk': 25, 'signals': [{'ts_last': '2026-10-26T12:00:00Z', 'attributes': {}}]},
        ]
        def records(table):
            return candidates if table == 'candidates' else [{'id': 'S6', 'entity': 'customer-assistant'}]
        with patch('engine.api.list_payloads', side_effect=records):
            result = TestClient(app).get('/scenarios').json()[0]
        self.assertEqual(result['result']['id'], 'openai-secret')
        self.assertEqual(result['result']['decision'], 'Raise issue')
