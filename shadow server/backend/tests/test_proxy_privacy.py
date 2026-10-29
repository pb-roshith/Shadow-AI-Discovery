import json
import re
import unittest
from unittest.mock import patch

from scenarios.data.make_dummy_extract import FILLER, generate
from tests.proxy_harness import ProxyHarness


class ProxyPrivacy(unittest.TestCase):
    def test_block_decision_survives_audit_write_failure(self):
        from mitmproxy.test import tflow
        from services.proxy.dlp_addon import DLPAddon
        flow = tflow.tflow()
        flow.request.host = 'chatgpt.com'
        flow.request.method = 'POST'
        flow.request.content = b'ACC-0000123456'
        flow.metadata['proxyauth'] = ('priya', 'demo')
        with patch('services.proxy.dlp_addon.append_jsonl', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                DLPAddon().request(flow)
        self.assertEqual(flow.response.status_code, 403)
        self.assertEqual(flow.comment, 'proxy_user=priya')
        self.assertEqual(flow.response.headers['X-ShadowAI-DLP'], 'blocked')
        flow.response = None
        addon = DLPAddon()
        addon.config.update(offline_mode=True, dlp_action='log_only')
        with patch('services.proxy.dlp_addon.append_jsonl', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                addon.request(flow)
        self.assertEqual(flow.response.status_code, 401)

    def test_real_logs_exclude_payload_paths_credentials_and_headers(self):
        with ProxyHarness() as proxy:
            data = generate(proxy.root / 'dummy_customer_extract.csv').read_bytes()
            response = proxy.request(files={'file': ('dummy_customer_extract.csv', data + b'ABCDE1234F')},
                                     headers={'X-Private': 'private-header-value'})
            self.assertEqual(response.status_code, 403)
            proxy.events('proxy', 1)
            network_keys = {'ts', 'proxy_user', 'host', 'method', 'path_class', 'bytes_out', 'bytes_in', 'status', 'ai_host', 'dlp_blocked', 'flow_id', 'duration_ms'}
            dlp_keys = {'ts', 'proxy_user', 'host', 'method', 'label', 'match_count', 'bytes', 'blocked', 'flow_id'}
            for name, keys in [('proxy', network_keys), ('dlp', dlp_keys)]:
                rows = proxy.events(name)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(set(row), keys)
                    if name == 'proxy':
                        self.assertIsInstance(row['duration_ms'], (int, float))
                        self.assertGreaterEqual(row['duration_ms'], 0)
                text = json.dumps(rows)
                for forbidden in ('ACC-', 'ABCDE1234F', FILLER, 'dummy_customer_extract.csv', '/backend-api',
                                  'private_query', 'private-header-value', 'demo', 'Proxy-Authorization'):
                    self.assertNotIn(forbidden, text)
                self.assertIsNone(re.search(r'\b[A-Z]{5}\d{4}[A-Z]\b', text))
