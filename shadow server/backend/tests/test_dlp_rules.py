import json
import unittest
from tempfile import TemporaryDirectory

from scenarios.data.make_dummy_extract import FILLER, generate
from services.proxy.dlp_rules import scan
from services.proxy.shadow_common import is_ai_host, load_config, path_class


class DLPRules(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_extract(self):
        from pathlib import Path
        with TemporaryDirectory() as directory:
            data = generate(Path(directory) / 'dummy.csv').read_bytes()
        self.assertEqual(len(data), 2_400_000)
        self.assertEqual(scan(data, self.config['dlp_patterns']), [{'label': 'Customer PII', 'match_count': 14}])

    def test_labels_and_privacy(self):
        result = scan(b'ACC-0000123456 ABCDE1234F CONFIDENTIAL-INTERNAL', self.config['dlp_patterns'])
        self.assertEqual(result, [{'label': 'Customer PII', 'match_count': 2}, {'label': 'Confidential', 'match_count': 1}])
        self.assertNotIn('ACC-', json.dumps(result))
        self.assertNotIn('ABCDE1234F', json.dumps(result))
        self.assertEqual(scan(b'CONFIDENTIAL-INTERNAL', self.config['dlp_patterns']), [{'label': 'Confidential', 'match_count': 1}])

    def test_clean_and_filler(self):
        for data in (b'', b'clean text', FILLER.encode(), b'\xff clean'):
            self.assertEqual(scan(data, self.config['dlp_patterns']), [])

    def test_hosts(self):
        for host in ('chatgpt.com', 'ab.chatgpt.com', 'CHATGPT.COM.', 'files.oaiusercontent.com'):
            self.assertTrue(is_ai_host(host, self.config['ai_hosts']))
        for host in ('notchatgpt.com', 'chatgpt.com.example.com', 'example.com'):
            self.assertFalse(is_ai_host(host, self.config['ai_hosts']))

    def test_path_class(self):
        self.assertEqual(path_class('/backend-api/files?q=secret'), 'upload')
        self.assertEqual(path_class('/send', 'multipart/form-data'), 'upload')
        self.assertEqual(path_class('/v1/chat/completions'), 'api')
        self.assertEqual(path_class('/?next=/files'), 'web')
