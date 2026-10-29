import json
import unittest
from fastapi.testclient import TestClient
from engine.api import app
from engine.audit import verify_chain
from engine.db import connection, list_payloads
from engine.pipeline import run
from tests.test_live_s1 import LiveScenarioOne


class Governance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LiveScenarioOne.setUpClass()
        cls.root = LiveScenarioOne.root
        cls.client = TestClient(app)
        with (cls.root / 'repos/credit-dossier/requirements.txt').open('a') as stream:
            stream.write('\ngoogle-genai\n')
        with (cls.root / 'repos/credit-dossier/dossier/llm.py').open('a') as stream:
            stream.write('\nfrom google import genai\n')

    @classmethod
    def tearDownClass(cls):
        LiveScenarioOne.tearDownClass()

    def setUp(self):
        with connection() as db:
            for table in ('runs','signals','candidates','issues','audit_events','evidence_events'):
                db.execute(f'DELETE FROM {table}')
            db.execute('DELETE FROM reference_documents WHERE id=?', ('approved_ai_inventory.csv',))
        event = {'ts':'2026-10-26T12:00:00+00:00', 'app':'credit-dossier', 'provider':'Google', 'model':'gemini-3.5-flash-lite', 'origin':'live', 'request_id':'test-request-one', 'tokens':5}
        stages = [{**event,'status':'pending'}, {**event,'status':'success','ts':'2026-10-26T12:00:01+00:00'}]
        (self.root / 'logs/gateway.jsonl').write_text(LiveScenarioOne.baseline + ''.join(json.dumps(stage)+'\n' for stage in stages))
        (self.root / 'logs/proxy.jsonl').write_text(LiveScenarioOne.proxy_baseline)

    def candidate(self):
        return next(c for c in self.client.get('/candidates').json() if c['entity']=='credit-dossier' and c['provider']=='Google')

    def approve(self):
        current = self.client.get('/inventory').json()
        entry = {'inv_id':'AI-TEST-GOOGLE','asset':'Credit Gemini','tool_name':'Gemini','match_type':'app','match_value':'credit-dossier','provider':'Google','required_route':'gateway','status':'Approved','owner':'Test owner'}
        response = self.client.put('/inventory',json={'entries':current['entries']+[entry], 'expected_revision':current['revision'], 'reason':'Approve the verified gateway route'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json(), current

    def test_approval_reruns_discovery_and_updates_explanation_and_audit(self):
        run('hybrid')
        before = self.candidate()
        self.assertEqual(before['inventory']['status'],'Unknown')
        result, old = self.approve()
        self.assertIsNotNone(result['discovery'])
        after = self.candidate()
        self.assertEqual(after['inventory']['status'],'Approved')
        self.assertEqual(after['decision'],'Genuine')
        self.assertLess(after['risk'],before['risk'])
        self.assertEqual(after['inventory_revision'],result['revision'])
        self.assertIn('AI-TEST-GOOGLE',after['decision_explanation'])
        self.assertEqual(result['discovery']['trigger']['audit_id'],result['audit_id'])
        audit = self.client.get('/audit/events').json()
        self.assertTrue(audit['chain_verified'])
        changed = next(e for e in audit['events'] if e['id']==result['audit_id'])
        self.assertEqual(changed['changes'][0]['action'],'added')
        self.assertEqual(changed['changes'][0]['after']['tool_name'],'Gemini')
        self.assertEqual(next(row for row in self.client.get('/inventory').json()['entries'] if row['inv_id']=='AI-TEST-GOOGLE')['tool_name'],'Gemini')
        self.assertTrue(changed['actor']['name'])
        self.assertEqual(changed['actor']['source'],'local_server_os_account')
        self.assertEqual(changed['before'],old['entries'])
        stale = self.client.put('/inventory',json={'entries':old['entries'],'expected_revision':old['revision'],'reason':'Stale change must fail'})
        self.assertEqual(stale.status_code,409)

    def test_revocation_recalculates_and_has_before_after_record(self):
        self.approve()
        current = self.client.get('/inventory').json()
        for row in current['entries']:
            if row['inv_id']=='AI-TEST-GOOGLE':
                row['status']='Revoked'
        response = self.client.put('/inventory',json={'entries':current['entries'],'expected_revision':current['revision'],'reason':'Revoke this test approval'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.candidate()['inventory']['status'],'Revoked')
        audit = self.client.get('/audit/events').json()
        event = next(e for e in audit['events'] if e['id']==response.json()['audit_id'])
        self.assertEqual(event['changes'][0]['before']['status'],'Approved')
        self.assertEqual(event['changes'][0]['after']['status'],'Revoked')

    def test_invocation_counts_are_backed_by_archived_logs_after_file_removal(self):
        run('hybrid')
        candidate = self.candidate()
        gateway = next(s for s in candidate['signals'] if s['channel']=='Gateway')
        response = self.client.get('/signals/'+gateway['signal_id']+'/audit')
        bundle = response.json()
        self.assertTrue(bundle['verified'])
        self.assertEqual(bundle['verified_count'],1)
        self.assertEqual(len(bundle['requests'][0]['stages']),2)
        self.assertTrue(bundle['requests'][0]['stages'][0]['source_sha256'])
        (self.root / 'logs/gateway.jsonl').unlink()
        self.assertTrue(self.client.get('/signals/'+gateway['signal_id']+'/audit').json()['verified'])
        trace = self.client.get('/candidates/'+candidate['id']+'/audit').json()
        self.assertEqual(trace['inventory_snapshot'],candidate['inventory_snapshot'])
        archived = self.client.get('/audit/gateway?request_id=test-request-one').json()
        self.assertEqual(archived['total_invocations'],1)
        self.assertEqual(archived['outcomes']['success'],1)
        audit = list_payloads('audit_events')
        self.assertTrue(verify_chain(audit))
        audit[0]['mode']='tampered'
        self.assertFalse(verify_chain(audit))

    def test_manual_tool_can_be_added_and_restricted(self):
        current = self.client.get('/inventory').json()
        entry = {'inv_id': 'AI-MANUAL-GEMINI', 'asset': 'Gemini', 'tool_name': 'Gemini',
                 'match_type': 'tool', 'match_value': 'Gemini', 'provider': 'Google',
                 'required_route': 'any', 'status': 'Approved', 'owner': 'Test owner'}
        response = self.client.put('/inventory', json={'entries': current['entries'] + [entry],
            'expected_revision': current['revision'], 'reason': 'Manually add Gemini'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.candidate()['inventory']['status'], 'Approved')
        current = self.client.get('/inventory').json()
        next(row for row in current['entries'] if row['inv_id'] == entry['inv_id'])['status'] = 'Restricted'
        response = self.client.put('/inventory', json={'entries': current['entries'],
            'expected_revision': current['revision'], 'reason': 'Restrict manually added Gemini'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.candidate()['inventory']['status'], 'Restricted')
        self.assertEqual(len([row for row in self.client.get('/inventory').json()['entries']
                              if row['inv_id'] == entry['inv_id']]), 1)

    def test_duplicate_scopes_and_actor_impersonation_are_rejected(self):
        current = self.client.get('/inventory').json()
        duplicate = {**current['entries'][0], 'inv_id':'duplicate'}
        response = self.client.put('/inventory',json={'entries':current['entries']+[duplicate],'expected_revision':current['revision'],'reason':'Duplicate must fail'})
        self.assertEqual(response.status_code,422)
        response = self.client.put('/inventory',json={'entries':current['entries'],'expected_revision':current['revision'],'reason':'Trying actor override','actor':'another user'})
        self.assertEqual(response.status_code,422)
