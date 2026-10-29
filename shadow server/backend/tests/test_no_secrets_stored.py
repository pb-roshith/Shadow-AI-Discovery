import json
import re
import unittest
from tests.test_scenarios import Scenarios
from engine.db import list_payloads

class Privacy(Scenarios):
    # Inherit a fresh isolated fixture, not the scenario methods.
    def test_privacy(self):
        from engine.pipeline import run
        run()
        from scenarios.demo import live
        live();run()
        for table in ('signals','candidates','issues','observations','runs'):
            serialized=json.dumps(list_payloads(table))
            self.assertFalse(re.search(r'sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}',serialized),table)
            self.assertFalse(re.search(r'ACC-\d{10}',serialized),table)
            self.assertNotIn('CONFIDENTIAL-INTERNAL',serialized,table)
            self.assertNotIn('from openai import',serialized,table)
        for log in (self.root/'logs').glob('*.jsonl'):
            content=log.read_text()
            self.assertFalse(re.search(r'sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|ACC-\d{10}|CONFIDENTIAL-INTERNAL',content),str(log))
        for database in (self.root/'data').glob('discovery.sqlite*'):
            raw=database.read_bytes()
            self.assertFalse(re.search(rb'sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|ACC-\d{10}|CONFIDENTIAL-INTERNAL',raw),str(database))

if __name__=='__main__':
    unittest.main(verbosity=2)
