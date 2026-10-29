import copy
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from test_repo_apps import load

SAMPLE = dict(company_name='Acme Manufacturing', industry='manufacturing', purpose='equipment', years_in_business=8,
              loan_amount=5000000, term_months=48, annual_revenue=30000000, annual_operating_cash_flow=4000000,
              existing_annual_debt_service=500000, collateral_value=7500000, credit_score=760,
              defaults_last_3_years=0, kyc_complete=True, audited_financials=True)


class PolicyIntelligence(unittest.TestCase):
    def setUp(self):
        trace = patch.object(self.agent, 'write_model_trace')
        self.trace = trace.start()
        self.addCleanup(trace.stop)

    @classmethod
    def setUpClass(cls):
        cls.module = load('policy-intelligence')
        cls.client = TestClient(cls.module.app)
        cls.agent = sys.modules['policy_agent']

    def run_loan(self, **changes):
        return self.client.post('/api/run', json={'loan': {**SAMPLE, **changes}})

    def test_settings_read_only_this_servers_dotenv(self):
        with patch.object(self.module, 'dotenv_values', return_value={'GEMINI_API_KEY':'local-test-key','OPENAI_API_KEY':''}) as read, patch.dict(self.module.os.environ, {'GEMINI_API_KEY':'inherited-test-key','OPENAI_API_KEY':'inherited-test-key'}, clear=True):
            values = self.module.settings()
        read.assert_called_once_with(self.module.HERE / '.env')
        self.assertEqual(values['GEMINI_API_KEY'], 'local-test-key')
        self.assertEqual(values['OPENAI_API_KEY'], '')

    def test_compliant_and_policy_download(self):
        result = self.run_loan()
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual(data['verdict'], 'complies')
        self.assertEqual(len(data['checks']), 13)
        self.assertEqual(data['request_id'], result.headers['x-request-id'])
        policy = self.client.get('/api/policy').json()
        self.assertEqual(self.client.get('/api/policy/download').json()['clauses'], policy['clauses'])
        for clause in policy['clauses']:
            self.assertIn(clause['text'], policy['document'])

    def test_each_clause_can_independently_fail(self):
        changes = [('P01',dict(years_in_business=2)), ('P02',dict(industry='gambling')),
                   ('P03',dict(purpose='speculation')), ('P04',dict(loan_amount=499999)),
                   ('P05',dict(term_months=61)), ('P06',dict(annual_revenue=9999999)),
                   ('P07',dict(annual_revenue=10000000)), ('P08',dict(annual_operating_cash_flow=0)),
                   ('P09',dict(collateral_value=0)), ('P10',dict(credit_score=699)),
                   ('P11',dict(defaults_last_3_years=1)), ('P12',dict(kyc_complete=False)),
                   ('P13',dict(audited_financials=False))]
        for clause, values in changes:
            with self.subTest(clause=clause):
                data = self.run_loan(**values).json()
                self.assertEqual(data['verdict'], 'violates_policy')
                self.assertEqual(next(c for c in data['checks'] if c['id']==clause)['status'], 'violation')

    def test_boundaries_and_zero_revenue(self):
        data=self.run_loan(years_in_business=3, credit_score=700, collateral_value=6250000, term_months=60).json()
        self.assertEqual(data['verdict'],'complies')
        data=self.run_loan(annual_revenue=0).json()
        self.assertIsNone(data['metrics']['loan_to_revenue_percent'])
        self.assertEqual(data['verdict'],'violates_policy')
        policy=copy.deepcopy(self.agent.load_policy())
        policy['clauses'][0]['value']=10
        with patch.object(self.agent,'load_policy',return_value=policy):
            self.assertEqual(self.run_loan().json()['checks'][0]['status'],'violation')

    def test_missing_invalid_and_unknown_inputs(self):
        for values in [dict(loan_amount=0),dict(term_months=1.5),dict(credit_score=901),dict(company_name='   '),dict(industry='unknown'),dict(annual_revenue=-1)]:
            self.assertEqual(self.run_loan(**values).status_code,422)
        self.assertEqual(self.client.post('/api/run',json={'loan':{'company_name':'x'}}).status_code,422)

    def test_ai_failure_does_not_change_policy_verdict(self):
        for config, expected in [({}, 'unavailable'), ({'OPENAI_API_KEY':'test'}, 'failed')]:
            with patch.object(self.module,'settings',return_value=config), patch.object(self.module,'explain',side_effect=RuntimeError('secret')):
                response=self.client.post('/api/run',json={'loan':SAMPLE,'ai_explanation':True})
                self.assertEqual(response.json()['verdict'],'complies')
                self.assertEqual(response.json()['ai_status'],expected)
                self.assertNotIn('secret',response.text)

    def test_provider_selection_and_availability(self):
        config={'OPENAI_API_KEY':'test-openai','MISTRAL_API_KEY':'test-mistral','GOOGLE_API_KEY':'test-google'}
        with patch.object(self.module, 'settings', return_value=config), patch.object(self.module, 'explain', return_value='Review P01.') as explain:
            policy = self.client.get('/api/policy').json()
            self.assertEqual(set(policy['providers']), {'openai','mistral','gemini'})
            self.assertTrue(all(p['available'] for p in policy['providers'].values()))
            self.assertNotIn('test-google',json.dumps(policy))
            for provider in ('openai','mistral','gemini'):
                response = self.client.post('/api/run',json={'loan':SAMPLE,'ai_explanation':True,'provider':provider})
                self.assertEqual(response.json()['ai_status'],'success')
                self.assertEqual(response.json()['provider'],provider)
                self.assertEqual(explain.call_args.kwargs,{'provider':provider})
                self.assertEqual(response.json()['verdict'],'complies')
        self.assertEqual(self.client.post('/api/run',json={'loan':SAMPLE,'provider':'unknown'}).status_code,422)

    def test_unconfigured_providers_and_local_checks_do_not_call_sdk(self):
        with patch.object(self.module,'settings',return_value={}), patch.object(self.module,'explain') as explain:
            for provider in ('openai','mistral','gemini'):
                for enabled in (False,True):
                    response=self.client.post('/api/run',json={'loan':SAMPLE,'provider':provider,'ai_explanation':enabled})
                    self.assertEqual(response.json()['ai_status'],'unavailable' if enabled else 'not_requested')
                    self.assertEqual(response.json()['verdict'],'complies')
            explain.assert_not_called()

    def test_mistral_sdk_receives_policy_and_records_provider(self):
        with TemporaryDirectory() as temp, patch.object(self.agent,'HERE',Path(temp)/'repos'/'policy-intelligence'), patch.object(self.agent,'load_policy',return_value={'id':'test'}), patch('mistralai.client.Mistral') as sdk:
            client=sdk.return_value.__enter__.return_value
            client.chat.complete.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Review P01.'))])
            config={'MISTRAL_API_KEY':'private','MISTRAL_MODEL':'configured-mistral'}
            self.assertEqual(self.agent.explain(SAMPLE,{},config,'mistral-one',provider='mistral'),'Review P01.')
            call=client.chat.complete.call_args.kwargs
            self.assertEqual(call['model'],'configured-mistral')
            self.assertIn('policy',call['messages'][1]['content'])
            event=json.loads((Path(temp)/'shadow server/backend/logs/sdk_calls.jsonl').read_text())
            self.assertEqual((event['provider'],event['status']),('Mistral','success'))

    def test_gemini_sdk_receives_policy_and_system_instruction(self):
        with TemporaryDirectory() as temp, patch.object(self.agent,'HERE',Path(temp)/'repos'/'policy-intelligence'), patch.object(self.agent,'load_policy',return_value={'id':'test'}), patch('google.genai.Client') as sdk:
            client=sdk.return_value.__enter__.return_value
            client.models.generate_content.return_value=SimpleNamespace(text='Review P01.')
            config={'GOOGLE_API_KEY':'private','GEMINI_MODEL':'configured-gemini'}
            self.assertEqual(self.agent.explain(SAMPLE,{},config,'gemini-one',provider='gemini'),'Review P01.')
            self.assertEqual(sdk.call_args.kwargs['api_key'],'private')
            call=client.models.generate_content.call_args.kwargs
            self.assertEqual(call['model'],'configured-gemini')
            self.assertIn('policy',call['contents'])
            self.assertIn('Never alter the verdict',call['config'].system_instruction)
            event=json.loads((Path(temp)/'shadow server/backend/logs/sdk_calls.jsonl').read_text())
            self.assertEqual((event['provider'],event['status']),('Google','success'))

    def test_sdk_failures_are_recorded_without_sensitive_details(self):
        for provider, target in [('openai','policy_agent.OpenAI'),('mistral','mistralai.client.Mistral'),('gemini','google.genai.Client')]:
            with self.subTest(provider=provider), TemporaryDirectory() as temp, patch.object(self.agent,'HERE',Path(temp)/'repos'/'policy-intelligence'), patch.object(self.agent,'load_policy',return_value={'id':'test'}), patch(target,side_effect=RuntimeError('private')):
                with self.assertRaises(RuntimeError):
                    self.agent.explain(SAMPLE,{}, {},'failed-one',provider=provider)
                event=json.loads((Path(temp)/'shadow server/backend/logs/sdk_calls.jsonl').read_text())
                self.assertEqual(event['status'],'failed')
                self.assertNotIn('private',json.dumps(event))

    def test_sdk_records_metadata_only_and_sends_document(self):
        with TemporaryDirectory() as temp, patch.object(self.agent,'HERE',Path(temp)/'repos'/'policy-intelligence'), patch.object(self.agent,'OpenAI') as sdk, patch.object(self.agent,'load_policy',return_value={'id':'test'}):
            client=sdk.return_value.__enter__.return_value
            client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Review P01.'))])
            self.assertEqual(self.agent.explain(SAMPLE,{}, {'OPENAI_API_KEY':'private'},'request-one'),'Review P01.')
            event=json.loads((Path(temp)/'shadow server/backend/logs/sdk_calls.jsonl').read_text())
            self.assertEqual(event['app'],'policy-intelligence')
            self.assertEqual(event['status'],'success')
            self.assertNotIn('Acme',json.dumps(event))
            self.assertNotIn('private',json.dumps(event))
            self.assertIn('policy',client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
