import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
NAMES = ['credit-dossier', 'policy-intelligence', 'loan-risk-classifier', 'customer-assistant']


def load(name):
    folder = ROOT / 'repo server' / name
    sys.path.insert(0, str(folder))
    try:
        spec = importlib.util.spec_from_file_location(name.replace('-', '_') + '_app', folder / 'app.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(folder))


class Apps(unittest.TestCase):
    def test_each_app_has_its_own_identity_and_api(self):
        for name in NAMES:
            with self.subTest(repo=name):
                client = TestClient(load(name).app)
                self.assertEqual(client.get('/api/health').json(), {'status': 'ok', 'repo': 'loan-risk-classifier' if name == 'loan-risk-classifier' else name})
                self.assertEqual(client.get('/docs').status_code, 200)
                self.assertEqual(client.post('/api/run', json={'text': '  '}).status_code, 422)
                self.assertEqual(client.post('/api/repos/another/run', json={'text': 'x'}).status_code, 404)

    def test_credit_provider_selection(self):
        module = load('credit-dossier')
        client = TestClient(module.app)
        for provider in ('gemini', 'mistral'):
            with patch.dict(os.environ, {'GEMINI_API_KEY': 'test', 'MISTRAL_API_KEY': 'test'}), patch.object(module, 'summarise', return_value='Summary') as call:
                response = client.post('/api/run', json={'text': 'What is the risk?', 'memo': '[Paragraph 1]\nBorrower risk is high.', 'provider': provider})
            self.assertEqual(response.json()['text'], 'Summary')
            self.assertEqual(response.json()['provider'], provider)
            self.assertEqual(response.headers['x-request-id'], response.json()['request_id'])
            self.assertIn('Borrower risk is high.', call.call_args.args[0])
            self.assertIn('What is the risk?', call.call_args.args[0])
            self.assertEqual(call.call_args.kwargs, {'provider': provider, 'request_id': response.json()['request_id']})
        self.assertEqual(client.post('/api/run', json={'text': 'x', 'provider': 'unknown'}).status_code, 422)

    def test_missing_key_and_redacted_provider_failure(self):
        module = load('credit-dossier')
        client = TestClient(module.app)
        with patch.dict(os.environ, {'DOSSIER_ROUTE': 'sdk'}, clear=True):
            self.assertEqual(client.post('/api/run', json={'text': 'x', 'memo': 'Memo'}).status_code, 503)
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}), patch.object(module, 'summarise', side_effect=RuntimeError('secret-value')):
            response = client.post('/api/run', json={'text': 'x', 'memo': 'Memo'})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('secret-value', response.text)
