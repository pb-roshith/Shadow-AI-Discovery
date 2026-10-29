import unittest
import subprocess
import sys
from pathlib import Path

import requests

from scenarios.data.make_dummy_extract import generate
from tests.proxy_harness import ProxyHarness, free_port


class ProxyIntegration(unittest.TestCase):
    def test_https_block_never_forwarded_clean_forwarded_and_identity(self):
        with ProxyHarness() as proxy:
            data = generate(proxy.root / 'dummy_customer_extract.csv').read_bytes()
            response = proxy.request(files={'file': ('dummy_customer_extract.csv', data, 'text/csv')})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers['X-ShadowAI-DLP'], 'blocked')
            dlp = proxy.events('dlp', 1)
            network = proxy.events('proxy', 1)
            self.assertEqual(len(dlp), 1)
            self.assertEqual(len(network), 1)
            self.assertEqual((dlp[0]['proxy_user'], dlp[0]['label'], dlp[0]['match_count'], dlp[0]['blocked']),
                             ('priya', 'Customer PII', 14, True))
            self.assertEqual((network[0]['status'], network[0]['path_class'], network[0]['dlp_blocked']), (403, 'upload', True))
            self.assertEqual(dlp[0]['flow_id'], network[0]['flow_id'])
            self.assertEqual(proxy.server.requests_received, 0)
            self.assertEqual(proxy.server.connections_received, 0)
            response = proxy.request(data=b'clean request')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(proxy.server.requests_received, 1)
            events = proxy.events('proxy', 2)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[1]['proxy_user'], 'priya')
            self.assertFalse(events[1]['dlp_blocked'])

    def test_authentication_offline_and_all_identities(self):
        with ProxyHarness(offline=True) as proxy:
            # Plain HTTP exposes the 407 response; requests raises ProxyError for CONNECT 407.
            self.assertEqual(proxy.request('http://example.com/', user=None).status_code, 407)
            with self.assertRaisesRegex(requests.exceptions.ProxyError, '407'):
                proxy.request('https://chatgpt.com/', user=None)
            self.assertEqual(proxy.request('http://example.com/', user='intruder').status_code, 407)
            for user, host in [('priya', 'chatgpt.com'), ('dev-svc', 'api.openai.com'), ('ahmed', 'api.anthropic.com'),
                               ('app-svc', 'example.com'), ('gateway-svc', 'api.openai.com')]:
                response = proxy.request(f'https://{host}/v1/demo', user=user, data=b'clean')
                self.assertEqual(response.status_code, 200 if host == 'example.com' else 401)
            response = proxy.request('https://chatgpt.com/backend-api/files', files={'file': ('dummy.csv', generate(proxy.root / 'dummy.csv').read_bytes())})
            self.assertEqual(response.status_code, 403)
            response = proxy.request('https://api.anthropic.com/v1/messages', user='ahmed', data=b'CONFIDENTIAL-INTERNAL')
            self.assertEqual(response.status_code, 403)
            events = proxy.events('proxy', 9)
            self.assertEqual(len(events), 9)  # CONNECT itself adds no record.
            self.assertEqual([e['proxy_user'] for e in events[2:7]], ['priya', 'dev-svc', 'ahmed', 'app-svc', 'gateway-svc'])
            self.assertEqual(proxy.server.connections_received, 0)

    def test_multiple_labels_log_only_and_errors(self):
        with ProxyHarness(action='log_only') as proxy:
            response = proxy.request(data=b'ACC-0000123456 CONFIDENTIAL-INTERNAL')
            self.assertEqual(response.status_code, 200)
            events = proxy.events('dlp', 2)
            self.assertEqual(len(events), 2)
            self.assertTrue(all(not row['blocked'] for row in events))
            response = proxy.request(f'https://localhost:{free_port()}/private?key=secret', data=b'clean')
            self.assertEqual(response.status_code, 502)
            events = proxy.events('proxy', 2)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[-1]['status'], 0)
            self.assertEqual(events[-1]['error'], 'UpstreamError')

    def test_multiple_labels_blocked(self):
        with ProxyHarness() as proxy:
            response = proxy.request(data=b'CONFIDENTIAL-INTERNAL ACC-0000123456')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.content, b'Blocked by DLP policy (Shadow AI demo)')
            self.assertTrue(all(row['blocked'] for row in proxy.events('dlp', 2)))
            self.assertEqual(len(proxy.events('proxy', 1)), 1)

    def test_s3_cli_end_to_end(self):
        with ProxyHarness(offline=True, production_launcher=True) as proxy:
            path = generate(proxy.root / 'dummy_customer_extract.csv')
            script = Path(__file__).resolve().parents[1] / 'scenarios/s3_pii_upload.py'
            result = subprocess.run([sys.executable, str(script), '--file', str(path),
                                     '--ca', str(proxy.ca), '--proxy-port', str(proxy.port)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Response: 403 Blocked by DLP policy', result.stdout)
            self.assertIn('Nothing left the AVD', result.stdout)
            self.assertEqual(proxy.events('dlp', 1)[0]['match_count'], 14)
            self.assertEqual(len(proxy.events('proxy', 1)), 1)
