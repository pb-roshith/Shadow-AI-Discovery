"""Integration tests use a disposable schema in the dedicated app database."""
import copy
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid
from fastapi.testclient import TestClient
from engine import config, db, bootstrap
from engine.collectors import local, hybrid
from engine.api import app
from engine.pipeline import run
from scenarios import demo

@unittest.skipUnless(os.environ.get('SHADOWAI_TEST_POSTGRES') == '1', 'Set SHADOWAI_TEST_POSTGRES=1 for PostgreSQL integration tests')
class PostgreSQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters = db.connection_parameters()
        cls.temp = TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.schema = 'shadowai_test_' + uuid.uuid4().hex
        shutil.copytree(config.ROOT / 'reference', cls.root / 'reference')
        (cls.root / 'scenarios').mkdir()
        shutil.copyfile(config.ROOT / 'scenarios/catalogue.json', cls.root / 'scenarios/catalogue.json')
        cls.patches = [patch.dict(os.environ, {'SHADOWAI_DB_BACKEND':'postgresql', 'SHADOWAI_DB_SCHEMA':cls.schema,
            'SHADOWAI_DB_PASSWORD':cls.parameters['password']})] + [patch.object(m, 'ROOT', cls.root) for m in (config, db, local, hybrid, demo, bootstrap)]
        for p in cls.patches:
            p.start()
        demo.baseline()
        bootstrap.seed_documents()
        bootstrap.seed_telemetry()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        import psycopg
        from psycopg import sql
        with psycopg.connect(**cls.parameters, autocommit=True) as connection:
            # Generated identifier is the only deletion target; application/public data is untouched.
            if not re.fullmatch(r'shadowai_test_[0-9a-f]{32}', cls.schema):
                raise ValueError('Unsafe test schema')
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))
        demo.reset()
        for p in reversed(cls.patches):
            p.stop()
        cls.temp.cleanup()

    def test_01_baseline_uses_postgresql(self):
        summary = run('database')
        self.assertEqual(summary['warnings'], [])
        self.assertEqual((summary['candidates'], summary['issues'], summary['storage']), (8,3,'postgresql'))
        self.assertEqual(summary['collectors']['MCP'],5)
        expected={'credit-dossier':(40,15),'policy-intelligence':(100,75),'priya':(85,85),'ahmed':(80,25),'creditdb-MCP':(75,80),'customer-assistant':(40,10)}
        for c in db.list_payloads('candidates'):
            key=c['entity'] or c['user_id']
            self.assertEqual((c['confidence'],c['risk']), expected[key])
        network=[s for s in db.list_payloads('signals',summary['id']) if s['channel']=='Network']
        self.assertTrue(all(s['source_ref'].startswith('postgresql:') for s in network))
        self.assertEqual(len(self.client.get('/scenarios').json()),7)
        self.assertEqual(self.client.get('/health').json()['database']['backend'],'postgresql')

    def test_02_database_traffic_changes_next_run(self):
        with db.connection() as connection:
            rows=list(connection.execute('SELECT payload FROM telemetry_events WHERE stream=?',('proxy.jsonl',)))
            event=copy.deepcopy(next(db.decode(r[0]) for r in rows if db.decode(r[0])['host']=='api.openai.com'))
            connection.execute('INSERT INTO telemetry_events(id,stream,payload) VALUES(?,?,?)',('test-extra-request','proxy.jsonl',json.dumps(event)))
        summary=run('database')
        signal=next(s for s in db.list_payloads('signals',summary['id']) if s['host']=='api.openai.com')
        self.assertEqual(signal['event_count'],13)
        self.assertEqual((summary['candidates'],summary['issues']),(8,3))
        with db.connection() as connection:
            connection.execute('DELETE FROM telemetry_events WHERE id=?',('test-extra-request',))

    def test_03_database_scoring_changes_decisions(self):
        original=db.document('reference_documents','scoring.yaml')
        changed=copy.deepcopy(original)
        changed['thresholds']['issue_risk']=90
        try:
            db.put_document('reference_documents','scoring.yaml',changed)
            summary=run('database')
            # Exposed credentials still raise an issue above the risk threshold.
            self.assertEqual(summary['issues'],1)
            self.assertEqual(self.client.get('/config').json()['thresholds']['issue_risk'],90)
        finally:
            db.put_document('reference_documents','scoring.yaml',original)

    def test_04_issue_workflow_survives_rerun(self):
        run('database')
        issue=self.client.get('/issues').json()[0]
        url='/issues/'+issue['id']
        self.assertEqual(self.client.patch(url,json={'status':'Investigating','owner':'Database reviewer'}).status_code,200)
        self.assertEqual(self.client.patch(url,json={'status':'Resolved','resolution':'Remediated'}).status_code,200)
        run('database')
        self.assertEqual(self.client.get(url).json()['owner'],'Database reviewer')
        self.assertEqual(self.client.get(url).json()['status'],'Resolved')
        self.assertEqual(len(self.client.get('/issues').json()),3)

    def test_05_live_activity_and_privacy(self):
        self.assertEqual(self.client.post('/demo/live').status_code,410)
        summary=self.client.post('/discovery/run',json={'mode':'database'}).json()
        self.assertEqual(summary['issues'],3)
        self.assertFalse(any(c['entity']=='loan-risk-classifier' and 'Endpoint' in c['channels'] for c in db.list_payloads('candidates')))
        for table in ('telemetry_events','observations','signals','candidates','issues','runs'):
            payload=json.dumps(db.list_payloads(table))
            self.assertFalse(re.search(r'sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|ACC-\d{10}|CONFIDENTIAL-INTERNAL',payload),table)
            self.assertNotIn('password',payload.lower(),table)

    def test_06_reference_page_uses_database_edits(self):
        rules = db.document('reference_documents', 'rules.yaml')
        scoring = db.document('reference_documents', 'scoring.yaml')
        changed_rules, changed_scoring = copy.deepcopy(rules), copy.deepcopy(scoring)
        changed_rules['join_rules'][0]['description'] = 'Database-edited join description'
        changed_rules['issue_due'] = '3 working days'
        changed_scoring['thresholds']['issue_risk'] = 91
        changed_scoring['confidence']['direct']['runtime'] = 28
        try:
            db.put_document('reference_documents', 'rules.yaml', changed_rules)
            db.put_document('reference_documents', 'scoring.yaml', changed_scoring)
            response = self.client.get('/reference-data')
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['join_rules'][0]['description'], 'Database-edited join description')
            self.assertEqual(data['issue_due'], '3 working days')
            self.assertIn('91', next(rule for rule in data['decision_rules'] if rule['id'] == 'R3')['condition'])
            self.assertIn('Runtime activity 28', data['confidence'][0]['description'])
            self.assertEqual(data['inventory'], db.document('reference_documents', 'approved_ai_inventory.csv'))
            self.assertEqual(data['devices'], db.document('reference_documents', 'devices.csv'))
        finally:
            db.put_document('reference_documents', 'rules.yaml', rules)
            db.put_document('reference_documents', 'scoring.yaml', scoring)

if __name__=='__main__':
    unittest.main(verbosity=2)
