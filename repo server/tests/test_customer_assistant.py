import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_repo_apps import load

module = load('customer-assistant')
import assistant_llm as llm


class CustomerAssistant(unittest.TestCase):
    def setUp(self):
        trace = patch.object(llm, 'write_model_trace')
        self.trace = trace.start()
        self.addCleanup(trace.stop)

    def test_failed_call_records_elapsed_time_without_inventing_token_counts(self):
        with patch('openai.OpenAI') as factory, patch.object(llm, 'record_invocation') as log:
            factory.return_value.__enter__.return_value.responses.create.side_effect=RuntimeError('provider unavailable')
            with self.assertRaises(RuntimeError):
                llm.complete([{'role':'user','content':'Hello'}], 'openai', {'OPENAI_API_KEY':'test'}, 'failure-id')
        self.assertEqual(log.call_args.args[:4],('openai','gpt-4o-mini','failure-id','failed'))
        self.assertIsNone(log.call_args.args[4]['input_tokens'])
        self.assertIsNone(log.call_args.args[4]['output_tokens'])
        self.assertGreaterEqual(log.call_args.args[4]['duration_ms'],0)
        self.assertEqual(self.trace.call_args.args[5], [{'role':'user','content':'Hello'}])
        self.assertIsNone(self.trace.call_args.args[6])

    def test_gemini_sdk_receives_conversation(self):
        messages = [{'role': 'user', 'content': 'Hello'}, {'role': 'assistant', 'content': 'Hi'},
                    {'role': 'user', 'content': 'Continue'}]
        with patch('google.genai.Client') as factory, patch.object(llm, 'record_invocation') as log:
            client = factory.return_value.__enter__.return_value
            client.models.generate_content.return_value.text = 'Gemini reply'
            client.models.generate_content.return_value.usage = None
            client.models.generate_content.return_value.usage_metadata = type('Usage', (), {'prompt_token_count': 20, 'candidates_token_count': 7})()
            self.assertEqual(llm.complete(messages, 'gemini', {'GEMINI_API_KEY': 'test', 'GEMINI_MODEL': 'configured'}, 'request'), 'Gemini reply')
            args = client.models.generate_content.call_args.kwargs
            self.assertEqual(args['model'], 'configured')
            self.assertEqual([item.role for item in args['contents']], ['user', 'model', 'user'])
            self.assertEqual(log.call_args.args[:4], ('gemini', 'configured', 'request', 'success'))
            self.assertGreaterEqual(log.call_args.args[4]['duration_ms'], 0)
            self.assertEqual(log.call_args.args[4]['input_tokens'], 20)
            self.assertEqual(log.call_args.args[4]['output_tokens'], 7)

    def test_mistral_sdk(self):
        messages = [{'role': 'user', 'content': 'Hello'}]
        with patch('mistralai.client.Mistral') as factory, patch.object(llm, 'record_invocation'):
            client = factory.return_value.__enter__.return_value
            client.chat.complete.return_value.choices[0].message.content = 'Mistral reply'
            self.assertEqual(llm.complete(messages, 'mistral', {'MISTRAL_API_KEY': 'test'}, 'request'), 'Mistral reply')
            client.chat.complete.assert_called_once_with(model='mistral-small-latest', messages=messages)

    def test_openai_sdk(self):
        messages = [{'role': 'user', 'content': 'Hello'}]
        with patch('openai.OpenAI') as factory, patch.object(llm, 'record_invocation'):
            client = factory.return_value.__enter__.return_value
            client.responses.create.return_value.output_text = 'OpenAI reply'
            self.assertEqual(llm.complete(messages, 'openai', {'OPENAI_API_KEY': 'test'}, 'request'), 'OpenAI reply')
            client.responses.create.assert_called_once_with(model='gpt-4o-mini', input=messages, store=False)

    def test_settings_never_read_other_servers_and_local_values_take_precedence(self):
        def values(path):
            return {'GEMINI_API_KEY': 'local-test-key', 'OPENAI_API_KEY': ''}
        with patch.dict(os.environ, {'GEMINI_API_KEY':'inherited-test-key', 'OPENAI_API_KEY':'inherited-test-key'}, clear=True), patch.object(llm, 'dotenv_values', side_effect=values) as read:
            self.assertEqual(llm.settings()['GEMINI_API_KEY'], 'local-test-key')
            self.assertEqual(llm.settings()['OPENAI_API_KEY'], '')
            self.assertTrue(all(call.args == (llm.HERE / '.env',) for call in read.call_args_list))

    def test_api_validation_missing_credentials_and_errors(self):
        client = TestClient(module.app)
        with patch.object(module, 'settings', return_value={}):
            self.assertEqual(client.post('/api/run', json={'text': 'Hi'}).status_code, 503)
            self.assertEqual(client.post('/api/run', json={'text': ' ', 'provider': 'gemini'}).status_code, 422)
            self.assertEqual(client.post('/api/run', json={'text': 'Hi', 'provider': 'invalid'}).status_code, 422)
        with patch.object(module, 'settings', return_value={'GEMINI_API_KEY': 'test'}), patch.object(module, 'complete', side_effect=RuntimeError('credential-must-not-leak')):
            response = client.post('/api/run', json={'text': 'Hi'})
            self.assertEqual(response.status_code, 502)
            self.assertNotIn('credential-must-not-leak', response.text)

    def test_telemetry_has_no_conversation_or_keys(self):
        with TemporaryDirectory() as temp:
            fake = Path(temp) / 'repo server/customer-assistant'
            fake.mkdir(parents=True)
            with patch.object(llm, 'HERE', fake):
                llm.record_invocation('gemini', 'test-model', 'unique-id', 'success')
            event = json.loads((Path(temp) / 'shadow server/backend/logs/sdk_calls.jsonl').read_text())
            self.assertEqual(set(event), {'ts', 'app', 'provider', 'model', 'request_id', 'status', 'origin'})
            self.assertEqual(event['app'], 'customer-assistant')
