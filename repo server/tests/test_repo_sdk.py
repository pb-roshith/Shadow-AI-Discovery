import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[2] / 'repo server/credit-dossier/dossier/llm.py'
spec = importlib.util.spec_from_file_location('dossier_llm', path)
llm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm)


class SDKTests(unittest.TestCase):
    def setUp(self):
        # Mocked SDK requests must never enter the application telemetry log.
        recorder = patch.object(llm, 'record_invocation')
        self.record = recorder.start()
        self.addCleanup(recorder.stop)
        trace = patch.object(llm, 'write_model_trace')
        self.trace = trace.start()
        self.addCleanup(trace.stop)

    def test_gemini_uses_official_sdk(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test', 'GEMINI_MODEL': 'configured-gemini'}), patch('google.genai.Client') as factory:
            client = factory.return_value.__enter__.return_value
            client.models.generate_content.return_value.text = 'Gemini response'
            client.models.generate_content.return_value.usage = None
            client.models.generate_content.return_value.usage_metadata = type('Usage', (), {'prompt_token_count': 13, 'candidates_token_count': 4})()
            self.assertEqual(llm.summarise('Any document', provider='gemini', route='sdk'), 'Gemini response')
            client.models.generate_content.assert_called_once_with(model='configured-gemini', contents='Any document')
            self.assertEqual(factory.call_args.kwargs['api_key'], 'test')
            self.assertEqual(self.record.call_args.args[5]['input_tokens'], 13)
            self.assertEqual(self.record.call_args.args[5]['output_tokens'], 4)
            self.assertEqual(self.trace.call_args.args[5:7], ('Any document', 'Gemini response'))

    def test_mistral_uses_official_sdk(self):
        with patch.dict(os.environ, {'MISTRAL_API_KEY': 'test', 'MISTRAL_MODEL': 'configured-mistral'}), patch('mistralai.client.Mistral') as factory:
            client = factory.return_value.__enter__.return_value
            client.chat.complete.return_value.choices[0].message.content = 'Mistral response'
            self.assertEqual(llm.summarise('Any document', provider='mistral', route='sdk'), 'Mistral response')
            client.chat.complete.assert_called_once_with(model='configured-mistral', messages=[{'role': 'user', 'content': 'Any document'}])

    def test_unknown_provider(self):
        with self.assertRaises(ValueError):
            llm.summarise('text', provider='unknown')

    def test_gateway_routes_with_app_and_unique_request_identity(self):
        from unittest.mock import Mock
        response = Mock()
        response.json.return_value = {'choices': [{'message': {'content': 'Gateway response'}}]}
        with patch.dict(os.environ, {'GATEWAY_URL': 'http://127.0.0.1:4000', 'GEMINI_MODEL': 'configured-gemini'}), patch('httpx.post', return_value=response) as post:
            self.assertEqual(llm.summarise('Document', provider='gemini', route='gateway'), 'Gateway response')
            first = post.call_args.kwargs['json']
            llm.summarise('Document', provider='gemini', route='gateway')
            second = post.call_args.kwargs['json']
        self.assertEqual(first['metadata']['app'], 'credit-dossier')
        self.assertEqual(first['model'], 'configured-gemini')
        self.assertNotEqual(first['metadata']['request_id'], second['metadata']['request_id'])
