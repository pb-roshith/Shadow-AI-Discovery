import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from engine.api import refresh_discovery
from engine.live_inputs import input_revision


class LiveRefresh(unittest.TestCase):
    def test_no_scan_until_inputs_change(self):
        previous={'id':'one','mode':'live','input_revision':'same'}
        with patch('engine.api.latest',return_value=previous), patch('engine.live_inputs.input_revision',return_value='same'), patch('engine.api.run') as run:
            self.assertEqual(refresh_discovery(),{'changed':False,'run_id':'one'})
            run.assert_not_called()
        with patch('engine.api.latest',return_value=previous), patch('engine.live_inputs.input_revision',return_value='new'), patch('engine.api.run',return_value={'id':'two'}) as run:
            self.assertEqual(refresh_discovery(),{'changed':True,'run_id':'two'})
            self.assertEqual(run.call_args.args,('live',))

    def test_revision_tracks_logs_code_and_git_but_ignores_frontend_builds(self):
        with TemporaryDirectory() as temp, patch('engine.live_inputs.ROOT',Path(temp)):
            root=Path(temp)
            repo=root/'repos'/'new-app'
            repo.mkdir(parents=True)
            logs=root/'logs'
            logs.mkdir()
            first=input_revision()
            self.assertEqual(input_revision(),first)
            (repo/'app.py').write_text('import openai')
            second=input_revision()
            self.assertNotEqual(first,second)
            (logs/'sdk_calls.jsonl').write_text('metadata')
            third=input_revision()
            self.assertNotEqual(second,third)
            (repo/'.git').mkdir()
            (repo/'.git'/'HEAD').write_text('ref: refs/heads/main')
            fourth=input_revision()
            self.assertNotEqual(third,fourth)
            frontend=root/'repos'/'frontend'
            frontend.mkdir()
            (frontend/'bundle.js').write_text('build')
            self.assertEqual(input_revision(),fourth)
            references = root / 'reference'
            references.mkdir()
            (references / 'scoring.yaml').write_text('thresholds: {issue_risk: 70}')
            fifth = input_revision()
            self.assertNotEqual(fourth, fifth)
            (references / 'scoring.yaml').write_text('thresholds: {issue_risk: 80}')
            self.assertNotEqual(fifth, input_revision())

    def test_revision_tracks_collector_changes(self):
        with TemporaryDirectory() as temp, patch('engine.live_inputs.ROOT',Path(temp)), patch('engine.live_inputs.__file__',str(Path(temp)/'engine/live_inputs.py')):
            collector=Path(temp)/'engine/collectors/local.py'
            collector.parent.mkdir(parents=True)
            collector.write_text('# before')
            before=input_revision()
            collector.write_text('# changed history collection')
            self.assertNotEqual(before,input_revision())
