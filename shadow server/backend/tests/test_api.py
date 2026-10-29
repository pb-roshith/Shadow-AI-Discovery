import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from engine.api import app
from tests.test_scenarios import Scenarios

class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Scenarios.setUpClass()
        cls.client=TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Scenarios.tearDownClass()

    def test_run_evidence_and_issue_workflow(self):
        response=self.client.post('/discovery/run',json={'mode':'replay'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['candidates'],8)
        candidates=self.client.get('/candidates').json()
        for candidate in candidates:
            detail=self.client.get('/candidates/'+candidate['id']).json()
            self.assertTrue(detail['signals'])
            self.assertEqual(len(detail['confidence_factors']),5)
            self.assertEqual(len(detail['risk_factors']),6)
            self.assertEqual(sum(t['fired'] for t in detail['decision_trace']),1)
        issues=self.client.get('/issues').json()
        self.assertEqual(len(issues),3)
        url='/issues/'+issues[0]['id']
        self.assertEqual(self.client.patch(url,json={'status':'Resolved','resolution':'Remediated'}).status_code,409)
        self.assertEqual(self.client.patch(url,json={'status':'Investigating','owner':'Demo security'}).status_code,200)
        self.assertEqual(self.client.patch(url,json={'status':'Resolved'}).status_code,422)
        self.assertEqual(self.client.patch(url,json={'status':'Resolved','resolution':'Remediated'}).status_code,200)
        self.client.post('/discovery/run',json={'mode':'replay'})
        issue=self.client.get(url).json()
        self.assertEqual((issue['status'],issue['owner']),('Resolved','Demo security'))
        self.assertEqual(len(self.client.get('/issues').json()),3)
        c=next(c for c in candidates if c['decision']=='Monitor')
        response=self.client.post('/candidates/'+c['id']+'/issue')
        self.assertEqual(response.status_code,200)
        self.client.post('/candidates/'+c['id']+'/issue')
        self.assertEqual(len(self.client.get('/issues').json()),4)
        self.assertEqual(self.client.get('/reference/not-a-file').status_code,404)
        self.assertEqual(self.client.post('/discovery/run',json={'mode':'invalid'}).status_code,422)

if __name__=='__main__':
    unittest.main(verbosity=2)
