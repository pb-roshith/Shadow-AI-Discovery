import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import engine.config as config
import engine.db as db
import engine.collectors.local as local
import engine.collectors.hybrid as hybrid
import scenarios.demo as demo
from engine.pipeline import run


class LiveScenarioOne(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        shutil.copytree(config.ROOT / 'reference', cls.root / 'reference')
        cls.patches = [patch.dict(os.environ, {'SHADOWAI_DB_BACKEND': 'sqlite'})] + [patch.object(module, 'ROOT', cls.root) for module in (config, db, local, hybrid, demo)]
        for item in cls.patches:
            item.start()
        demo.baseline()
        cls.baseline = (cls.root / 'logs/gateway.jsonl').read_text()
        cls.proxy_baseline = (cls.root / 'logs/proxy.jsonl').read_text()

    @classmethod
    def tearDownClass(cls):
        # Demo fixtures have read-only Git object files on Windows.
        demo.reset()
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def setUp(self):
        (self.root / 'logs/gateway.jsonl').write_text(self.baseline)
        (self.root / 'logs/proxy.jsonl').write_text(self.proxy_baseline)

    def append(self, request_id, status='success'):
        event = {'ts':local.now(), 'app':'credit-dossier', 'provider':'Mistral', 'model':'mistral-small', 'origin':'live', 'request_id':request_id, 'status':status}
        with (self.root / 'logs/gateway.jsonl').open('a') as stream:
            stream.write(json.dumps(event) + '\n')

    def candidate(self):
        summary = run('hybrid')
        candidates = db.list_payloads('candidates')
        candidate = next(item for item in candidates if item['entity'] == 'credit-dossier' and item['provider'] == 'Mistral')
        return summary, candidate

    def test_seeded_s1_runtime_is_excluded_but_other_scenarios_remain(self):
        summary, candidate = self.candidate()
        self.assertEqual(candidate['channels'], ['Code'])
        self.assertLess(candidate['confidence'], 70)
        self.assertLessEqual(candidate['risk'], 20)
        signals = db.list_payloads('signals', summary['id'])
        self.assertFalse(any(s['user_id'] == 'gateway-svc' for s in signals))
        self.assertTrue(any(s['user_id'] == 'dev-svc' and s['host'] == 'api.openai.com' and s['channel'] == 'Network' for s in signals))

    def test_one_invocation_is_one_clue_even_after_duplicate_callbacks_and_rerun(self):
        _, before = self.candidate()
        self.append('one', 'pending')
        self.append('one', 'success')
        self.append('one', 'success')
        _, after = self.candidate()
        gateway = next(s for s in after['signals'] if s['channel'] == 'Gateway')
        self.assertEqual(gateway['event_count'], 1)
        self.assertEqual(gateway['attributes']['outcomes']['success'], 1)
        self.assertTrue(gateway['source_ref'].startswith('live:'))
        self.assertNotIn('Network', after['channels'])
        self.assertGreater(after['confidence'], before['confidence'])
        self.assertGreater(after['risk'], before['risk'])
        _, again = self.candidate()
        self.assertEqual(next(s for s in again['signals'] if s['channel'] == 'Gateway')['event_count'], 1)
        self.append('two', 'failed')
        _, two = self.candidate()
        gateway = next(s for s in two['signals'] if s['channel'] == 'Gateway')
        self.assertEqual(gateway['event_count'], 2)
        self.assertEqual(gateway['attributes']['outcomes']['failed'], 1)
        self.assertGreater(two['confidence'], after['confidence'])

    def test_network_clue_requires_an_actual_proxy_event(self):
        self.append('one')
        event = {'ts':local.now(), 'proxy_user':'gateway-svc', 'host':'api.mistral.ai', 'status':200, 'origin':'live', 'request_id':'proxy-one'}
        with (self.root / 'logs/proxy.jsonl').open('a') as stream:
            stream.write(json.dumps(event) + '\n')
        _, candidate = self.candidate()
        network = next(s for s in candidate['signals'] if s['channel'] == 'Network')
        self.assertEqual(network['event_count'], 1)
        self.assertEqual(network['attributes']['evidence_origin'], 'live')
