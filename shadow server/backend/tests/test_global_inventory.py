import json
import unittest
from fastapi.testclient import TestClient
from engine.api import app
from engine.db import list_payloads
from engine.inventory import global_entries
from engine.pipeline import run
from tests.test_live_s1 import LiveScenarioOne


class GlobalInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LiveScenarioOne.setUpClass()
        cls.root = LiveScenarioOne.root
        cls.client = TestClient(app)
        path = cls.root / 'repos/credit-dossier/requirements.txt'
        path.write_text(path.read_text() + '\ngoogle-genai\n')

    @classmethod
    def tearDownClass(cls):
        LiveScenarioOne.tearDownClass()

    def change(self, provider, status):
        current = self.client.get('/inventory').json()
        matches = [row for row in current['entries'] if row['provider'] == provider]
        if matches:
            for row in matches:
                row['status'] = status
        else:
            current['entries'].append({'inv_id': 'AI-GLOBAL-' + provider, 'asset': 'Gemini', 'tool_name': 'Gemini',
                'provider': provider, 'match_type': 'tool', 'match_value': 'Gemini', 'required_route': 'any',
                'status': status, 'owner': 'Global test'})
        response = self.client.put('/inventory', json={'entries': current['entries'],
            'expected_revision': current['revision'], 'reason': 'Change global approval for ' + provider})
        self.assertEqual(response.status_code, 200, response.text)

    def test_all_tools_required_and_approvals_apply_to_every_repo(self):
        run('hybrid')
        credit = next(c for c in list_payloads('candidates') if c['entity'] == 'credit-dossier')
        self.assertEqual(credit['inventory']['status'], 'Unknown')
        self.change('Google', 'Approved')
        candidates = list_payloads('candidates')
        google = [c for c in candidates if c['provider'] == 'Google']
        self.assertEqual({c['entity'] for c in google}, {'credit-dossier', 'customer-assistant'})
        self.assertTrue(all(c['inventory']['tool_status'] == 'Approved' for c in google))
        chatbot = [c for c in candidates if c['entity'] == 'customer-assistant']
        self.assertTrue(all(c['inventory']['status'] == 'Restricted' for c in chatbot))
        self.change('OpenAI', 'Approved')
        chatbot = [c for c in list_payloads('candidates') if c['entity'] == 'customer-assistant']
        self.assertTrue(all(c['inventory']['status'] == 'Approved' for c in chatbot))
        self.assertTrue(all(len(c['inventory']['tools']) == 3 for c in chatbot))
        self.change('Mistral', 'Restricted')
        candidates = list_payloads('candidates')
        self.assertTrue(all(c['inventory']['status'] == 'Restricted' for c in candidates
                            if c['entity'] in ('credit-dossier', 'customer-assistant')))
        # Approval also covers a repository created after the user approved Google.
        new_repo = self.root / 'repos/new-chat-app'
        new_repo.mkdir()
        (new_repo / 'requirements.txt').write_text('google-genai\n')
        run('hybrid')
        new_candidate = next(c for c in list_payloads('candidates') if c['entity'] == 'new-chat-app')
        self.assertEqual(new_candidate['inventory']['status'], 'Approved')

    def test_dummy_readme_key_is_detected_without_storing_the_value(self):
        fake = 'sk-proj-DEMO_CUSTOMER_ASSISTANT_NOT_A_REAL_KEY_0123456789abcdef'
        readme = self.root / 'repos/customer-assistant/README.md'
        readme.write_text('Dummy credential; never used by the app.\nOPENAI_API_KEY=' + fake + '\n')
        current = self.client.get('/inventory').json()
        for row in current['entries']:
            row['status'] = 'Approved'
        if not any(row['provider'] == 'Google' for row in current['entries']):
            current['entries'].append({'inv_id': 'AI-README-GOOGLE', 'asset': 'Gemini', 'tool_name': 'Gemini',
                'provider': 'Google', 'match_type': 'tool', 'match_value': 'Gemini', 'required_route': 'any',
                'status': 'Approved', 'owner': 'Test owner'})
        self.client.put('/inventory', json={'entries': current['entries'],
            'expected_revision': current['revision'], 'reason': 'Approve tools before testing exposed credentials'})
        run('hybrid')
        signals = [s for s in list_payloads('signals') if s['entity'] == 'customer-assistant' and s['channel'] == 'Secret']
        self.assertTrue(any(s['source_ref'].endswith('README.md') for s in signals))
        self.assertNotIn(fake, json.dumps(signals))
        candidate = next(c for c in list_payloads('candidates') if c['entity'] == 'customer-assistant' and c['provider'] == 'OpenAI')
        self.assertEqual(candidate['inventory']['status'], 'Approved')
        self.assertEqual(candidate['decision'], 'Raise issue')
        self.assertEqual(candidate['rule'], 'R0')
        self.assertTrue(any(issue['candidate_id'] == candidate['id'] for issue in list_payloads('issues')))


class LegacyGlobalMigration(unittest.TestCase):
    def test_duplicate_scopes_become_one_global_entry(self):
        common = {'asset': 'Gemini', 'provider': 'Google', 'owner': 'Owner', 'match_type': 'app', 'required_route': 'gateway'}
        rows = global_entries([{**common, 'inv_id': 'one', 'match_value': 'old-app', 'status': 'Approved'},
                               {**common, 'inv_id': 'two', 'match_value': 'other-app', 'status': 'Restricted'}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['match_type'], 'tool')
        self.assertEqual(rows[0]['match_value'], 'Gemini')
        self.assertEqual(rows[0]['required_route'], 'any')
        self.assertEqual(rows[0]['status'], 'Restricted')
