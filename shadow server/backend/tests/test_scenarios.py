import unittest
import os
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import engine.config as config
import engine.db as db
import engine.collectors.local as collectors
import engine.collectors.hybrid as hybrid
import scenarios.demo as demo
from engine.pipeline import run

class Scenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil
        cls.temp = TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        shutil.copytree(config.ROOT / 'reference', cls.root / 'reference')
        cls.patches = [patch.dict(os.environ, {'SHADOWAI_DB_BACKEND': 'sqlite'})] + [patch.object(module, 'ROOT', cls.root) for module in (config, db, collectors, hybrid, demo)]
        for p in cls.patches:
            p.start()
        demo.baseline()

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        demo.ROOT = cls.root
        try:
            demo.reset()
        finally:
            demo.ROOT = config.ROOT
        cls.temp.cleanup()

    def test_01_baseline_s1_to_s6(self):
        summary = run()
        self.assertEqual(summary['warnings'], [])
        self.assertEqual((summary['candidates'], summary['issues']), (8, 3))
        expected = {'credit-dossier': (40,15,'Monitor'), 'policy-intelligence':(100,75,'Raise issue'),
                    'priya':(85,85,'Raise issue'), 'ahmed':(80,25,'Monitor'),
                    'creditdb-MCP':(75,80,'Raise issue'), 'customer-assistant':(40,10,'Monitor')}
        for c in db.list_payloads('candidates'):
            name = c['entity'] or ('risk-agent' if c['provider']=='creditdb MCP' else c['user_id'])
            with self.subTest(scenario=name):
                self.assertEqual((c['confidence'], c['risk'], c['decision']), expected[name])
                for group in ('confidence', 'risk'):
                    factors = c[group + '_factors']
                    self.assertEqual(sum(f['points'] for f in factors), c[group])
                    for factor in factors:
                        self.assertIn(f"{factor['points']} of {factor['max']}", factor['explanation'])
                        self.assertTrue(factor['scoring_rule'])
                        self.assertNotIn('{', factor['scoring_rule'])
        self.assertFalse(any(s['entity']=='non-ai-csv' for s in db.list_payloads('signals')))

    def test_02_repeat_does_not_duplicate_issues(self):
        run();run()
        self.assertEqual(len(db.list_payloads('issues')),3)

    def test_03_retired_s7_fixture_does_not_create_runtime(self):
        demo.live();demo.live()
        summary = run()
        self.assertEqual((summary['candidates'], summary['issues']), (9,3))
        candidates = db.list_payloads('candidates')
        live = next(c for c in candidates if c['entity']=='ahmed-scratch')
        self.assertEqual(live['channels'], ['Code'])
        self.assertEqual(len(db.list_payloads('issues')),3)
        self.assertEqual(len([c for c in candidates if c['provider'] in ('Anthropic','Ollama','creditdb MCP')]),3)

    def test_04_live_mode_excludes_replay_runtime(self):
        collector = collectors.Collector('test','observed')
        self.assertEqual(collector.read_events('proxy.jsonl'),[])

if __name__=='__main__':
    unittest.main(verbosity=2)
