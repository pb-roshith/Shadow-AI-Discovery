import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from test_repo_apps import load

module = load('loan-risk-classifier')


class LoanRiskClassifier(unittest.TestCase):
    def setUp(self):
        trace = patch.object(module, 'write_model_trace')
        self.trace = trace.start()
        self.addCleanup(trace.stop)
        self.api = TestClient(module.app)
        self.loan = dict(currency='INR',loan_amount=100000,annual_interest_rate=12,term_months=12,
                         monthly_income=50000,monthly_expenses=15000,existing_monthly_repayments=3000,
                         employment_type='salaried',employment_years=5,missed_payments=0,
                         previous_default=False,savings=50000,collateral_value=None)
        self.answer = dict(score=20,explanation='Income covers the proposed repayment.',risk_factors=[],
                           mitigants=['Positive monthly surplus'],missing_information=[])
        models = patch.object(module,'local_models',return_value=['qwen2.5:1.5b'])
        models.start()
        self.addCleanup(models.stop)
        recorder = patch.object(module,'record_invocation')
        self.recorder = recorder.start()
        self.addCleanup(recorder.stop)

    def classify(self, answer=None, loan=None):
        with patch.object(module.client,'chat',return_value=SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.answer if answer is None else answer)))) as model:
            response=self.api.post('/api/run',json={'loan':self.loan if loan is None else loan})
        return response,model

    def test_entered_values_and_calculated_metrics_are_sent_to_ollama(self):
        response,model=self.classify()
        self.assertEqual(response.status_code,200)
        result=response.json()
        self.assertEqual(result['score'],20)
        self.assertEqual(result['classification'],'Low loan risk')
        payload=json.loads(model.call_args.kwargs['messages'][-1]['content'])
        self.assertEqual(payload['loan']['loan_amount'],100000)
        self.assertEqual(payload['loan']['previous_default'],False)
        self.assertEqual(payload['computed_metrics'],result['metrics'])
        self.assertIn('LOAN RISK',model.call_args.kwargs['messages'][0]['content'])
        self.assertEqual(result['request_id'],response.headers['x-request-id'])
        self.assertEqual(self.recorder.call_args.args[:3], ('qwen2.5:1.5b',result['request_id'],'success'))
        self.assertGreaterEqual(self.recorder.call_args.args[3]['duration_ms'], 0)
        self.assertEqual(self.trace.call_args.args[5], model.call_args.kwargs['messages'])
        self.assertEqual(json.loads(self.trace.call_args.args[6]), self.answer)

    def test_payment_calculation_and_affordability(self):
        result=module.affordability(module.Loan(**self.loan))
        self.assertAlmostEqual(result['monthly_payment'],8884.88,places=2)
        self.assertAlmostEqual(result['monthly_surplus'],23115.12,places=2)
        self.assertAlmostEqual(result['repayment_to_income_percent'],23.77,places=2)
        result=module.affordability(module.Loan(**dict(self.loan,annual_interest_rate=0,loan_amount=12000,term_months=12,monthly_income=0,collateral_value=24000)))
        self.assertEqual(result['monthly_payment'],1000)
        self.assertIsNone(result['repayment_to_income_percent'])
        self.assertEqual(result['loan_to_collateral_percent'],50)
        self.assertEqual(result['monthly_surplus'],-19000)

    def test_bad_or_missing_form_values_do_not_invoke_ai(self):
        with patch.object(module.client,'chat') as model:
            for changes in [{'loan_amount':0},{'term_months':0},{'term_months':12.5},{'monthly_income':-1},
                            {'annual_interest_rate':61},{'missed_payments':-1},{'previous_default':'yes'}]:
                response=self.api.post('/api/run',json={'loan':dict(self.loan,**changes)})
                self.assertEqual(response.status_code,422)
            for body in [{'text':'old free-text input'}, {'loan':{}}, {'loan':self.loan,'model':'unknown'}]:
                self.assertEqual(self.api.post('/api/run',json=body).status_code,422)
            model.assert_not_called()
            self.recorder.assert_not_called()

    def test_optional_values_remain_unknown_in_prompt(self):
        loan={k:v for k,v in self.loan.items() if k not in ('savings','collateral_value')}
        response,model=self.classify(loan=loan)
        self.assertEqual(response.status_code,200)
        payload=json.loads(model.call_args.kwargs['messages'][-1]['content'])
        self.assertIsNone(payload['loan']['savings'])
        self.assertIsNone(payload['loan']['collateral_value'])

    def test_model_output_score_and_fields_are_validated(self):
        for score in [-1,101,'20',None]:
            response,_=self.classify(dict(self.answer,score=score))
            self.assertEqual(response.status_code,502)
        response,_=self.classify({'score':20})
        self.assertEqual(response.status_code,502)

    def test_score_bands_have_consistent_boundaries(self):
        for score,label in [(0,'Low'),(25,'Low'),(26,'Moderate'),(50,'Moderate'),(51,'High'),(75,'High'),(76,'Severe'),(100,'Severe')]:
            response,_=self.classify(dict(self.answer,score=score))
            self.assertEqual(response.json()['classification'],label+' loan risk')

    def test_local_inference_errors_are_actionable(self):
        for error,status in [(httpx.ReadTimeout('test'),504),(ConnectionError('private details'),503)]:
            with patch.object(module.client,'chat',side_effect=error):
                response=self.api.post('/api/run',json={'loan':self.loan})
            self.assertEqual(response.status_code,status)
            self.assertNotIn('private details',response.text)
