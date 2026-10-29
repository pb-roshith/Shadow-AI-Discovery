import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from engine.collectors.local import Collector, git
from engine.config import reference_file
from engine.decide import decide


class GitCredentials(unittest.TestCase):
    def test_ownership_failure_retries_only_the_specific_repository(self):
        with TemporaryDirectory() as temp:
            repo = Path(temp) / 'application'
            (repo / '.git').mkdir(parents=True)
            failure = subprocess.CompletedProcess([], 128, stdout='', stderr='fatal: detected dubious ownership')
            success = subprocess.CompletedProcess([], 0, stdout='commit-id\n', stderr='')
            with patch('engine.collectors.local.subprocess.run', side_effect=[failure, success]) as run:
                self.assertEqual(git(repo, 'rev-list', '--all'), 'commit-id\n')
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0], ['git', '-c', f'safe.directory={repo.resolve().as_posix()}', '-C', str(repo), 'rev-list', '--all'])

    def test_removed_historical_credential_overrides_approved_tool(self):
        secret = 'sk-' + 'FAKE_TEST_ONLY_12345678901234567890'
        with TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / 'policy-intelligence'
            (repo / '.git').mkdir(parents=True)
            (repo / 'app.py').write_text('import openai\n')

            def command(args, **kwargs):
                operation = args[3]
                output = {'log': 'dev-svc\n', 'rev-list': 'old-commit\n',
                          'ls-tree': '.env\n', 'show': 'OPENAI_API_KEY=' + secret + '\n'}[operation]
                return subprocess.CompletedProcess(args, 0, stdout=output, stderr='')

            with patch('engine.collectors.local.reference', side_effect=reference_file), patch('engine.collectors.local.rows', return_value={}), patch('engine.collectors.local.repository_root', return_value=base), patch('engine.collectors.local.subprocess.run', side_effect=command):
                collector = Collector('test', 'live')
                collector.collect_repos()
            history = [s for s in collector.matches if s['signal_type'] == 'credential_in_history']
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]['entity'], 'policy-intelligence')
            self.assertEqual(history[0]['attributes']['commit'], 'old-commit')
            self.assertNotIn(secret, json.dumps(collector.matches))
            with patch('engine.decide.reference', side_effect=reference_file):
                result = decide(dict(signals=collector.matches, confidence=90, risk=25,
                                     inventory={'status': 'Approved', 'reason': 'Tool approved'}))
            self.assertEqual((result['decision'], result['rule']), ('Raise issue', 'R0'))

    def test_git_failure_is_visible_without_leaking_command_output(self):
        with TemporaryDirectory() as temp:
            repo = Path(temp) / 'policy-intelligence'
            (repo / '.git').mkdir(parents=True)
            with patch('engine.collectors.local.reference', side_effect=reference_file), patch('engine.collectors.local.rows', return_value={}), patch('engine.collectors.local.subprocess.run', return_value=subprocess.CompletedProcess([], 128, stdout='', stderr='sensitive output')):
                collector = Collector('test', 'live')
                self.assertEqual(collector.read_git(repo, 'rev-list', '--all'), '')
                self.assertEqual(collector.read_git(repo, 'log', '-1'), '')
            self.assertEqual(len(collector.warnings), 1)
            self.assertIn('policy-intelligence', collector.warnings[0])
            self.assertNotIn('sensitive output', json.dumps(collector.warnings))
