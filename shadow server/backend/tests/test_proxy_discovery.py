"""Collector/J4 contract using the exact live proxy log schema."""
import json
import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from engine.collectors import hybrid, local
from engine.correlate import correlate
from engine import live_inputs


class ProxyDiscovery(unittest.TestCase):
    def test_live_metadata_collected_joined_and_deduplicated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path(__file__).resolve().parents[1]
            if not (source / 'engine').exists():
                self.skipTest('Discovery engine is in the source workspace, outside standalone proxy deployment')
            shutil.copytree(source / 'reference', root / 'reference')
            logs = root / 'external-proxy-logs'
            logs.mkdir()
            event = dict(ts='2026-10-28T12:00:00.000+05:30', proxy_user='priya', host='chatgpt.com', method='POST', flow_id='real-s3')
            network = dict(event, path_class='upload', bytes_out=2400000, bytes_in=36, status=403, ai_host=True, dlp_blocked=True)
            dlp = dict(event, label='Customer PII', match_count=14, bytes=2400000, blocked=True)
            for name, row in [('proxy', network), ('dlp', dlp)]:
                (logs / f'{name}.jsonl').write_text((json.dumps(row) + '\n') * 2)
            with patch.object(local, 'ROOT', root), patch.object(hybrid, 'ROOT', root), patch.dict(os.environ, {'SHADOWAI_PROXY_LOGS_DIR': str(logs)}):
                collector = hybrid.HybridCollector('proxy-contract', 'live')
                collector.collect_logs()
                self.assertEqual(len(collector.matches), 2)
                for index, signal in enumerate(collector.matches):
                    signal['signal_id'] = str(index)
                    self.assertEqual(signal['attributes']['evidence_origin'], 'live')
                    self.assertEqual(signal['event_count'], 1)
                candidates = correlate(collector.matches)
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]['channels'], ['DLP', 'Network'])
                self.assertEqual(candidates[0]['join_rules_fired'], ['J4'])
                # An actual upload replaces its older fixture in hybrid/replay mode.
                fixture = dict(network, origin='replay')
                fixture.pop('flow_id')
                with patch.object(local.Collector, 'read_events', return_value=[('fixture', fixture)]):
                    rows = hybrid.HybridCollector('replace-fixture', 'replay').read_events('proxy.jsonl')
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0][1]['flow_id'], 'real-s3')

            pointer = root / 'services/proxy/deployment.json'
            pointer.parent.mkdir(parents=True)
            pointer.write_text(json.dumps({'logs_dir': str(logs)}))
            with patch.object(live_inputs, 'ROOT', root), patch.dict(os.environ, {'SHADOWAI_PROXY_LOGS_DIR': ''}):
                self.assertEqual(local.telemetry_path('proxy.jsonl', root), logs / 'proxy.jsonl')
                before = live_inputs.input_revision()
                with (logs / 'proxy.jsonl').open('a') as stream:
                    stream.write('\n')
                self.assertNotEqual(live_inputs.input_revision(), before)

    def test_subdomain_provider_matching(self):
        collector = local.Collector('host-contract', 'observed')
        self.assertEqual(collector.host_provider('ab.chatgpt.com'), 'OpenAI')
        self.assertEqual(collector.host_provider('files.oaiusercontent.com'), 'OpenAI')
        self.assertIsNone(collector.host_provider('notchatgpt.com'))
