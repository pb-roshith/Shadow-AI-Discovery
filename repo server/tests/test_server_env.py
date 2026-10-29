import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dotenv import dotenv_values
from workspace_tools import configure_env as config


class ServerEnvironment(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for source in [*(config.REPO / name for name in config.SERVER_FOLDERS), config.SHADOW.parent, config.SHADOW.parent / 'services/gateway']:
            destination = self.root / source.relative_to(config.ROOT)
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / '.env.example', destination / '.env.example')
        for name, value in [('REPO',self.root/'repo server'), ('SHADOW',self.root/'shadow server/backend/.env')]:
            setting = patch.object(config, name, value)
            setting.start()
            self.addCleanup(setting.stop)

    def test_migrates_keys_to_independent_files_preserves_local_values_and_removes_common(self):
        (config.REPO/'.env').write_text('GEMINI_API_KEY=shared-test-key\nMISTRAL_API_KEY=mistral-test-key\n')
        (config.REPO/'credit-dossier/.env').write_text('GEMINI_API_KEY=dossier-test-key\n')
        (config.REPO/'customer-assistant/.env').write_text('OPENAI_API_KEY=customer-test-key\n')
        config.configure(migrate_shared=True)
        self.assertFalse((config.REPO/'.env').exists())
        self.assertEqual(dotenv_values(config.REPO/'credit-dossier/.env')['GEMINI_API_KEY'],'dossier-test-key')
        self.assertEqual(dotenv_values(config.REPO/'customer-assistant/.env')['GEMINI_API_KEY'],'dossier-test-key')
        self.assertEqual(dotenv_values(config.REPO/'policy-intelligence/.env')['GEMINI_API_KEY'],'shared-test-key')
        self.assertEqual(dotenv_values(config.REPO/'customer-assistant/.env')['OPENAI_API_KEY'],'customer-test-key')
        for name in ('credit-dossier','customer-assistant','policy-intelligence'):
            self.assertEqual(dotenv_values(config.REPO/name/'.env')['MISTRAL_API_KEY'],'mistral-test-key')
        self.assertNotIn('GEMINI_API_KEY',dotenv_values(config.REPO/'loan-risk-classifier/.env'))
        config.configure()
        self.assertFalse((config.REPO/'.env').exists())

    def test_setup_does_not_read_shared_files_or_replace_explicitly_blank_local_keys(self):
        (config.REPO/'.env').write_text('GEMINI_API_KEY=shared-test-key\n')
        (config.REPO/'customer-assistant/.env').write_text('GEMINI_API_KEY=\n')
        config.configure()
        self.assertEqual(dotenv_values(config.REPO/'customer-assistant/.env')['GEMINI_API_KEY'],'')
        self.assertEqual(dotenv_values(config.REPO/'policy-intelligence/.env')['GEMINI_API_KEY'],'')
        self.assertEqual(dotenv_values(config.REPO/'customer-assistant/.env')['PORT'],'8105')

    def test_unmapped_settings_retain_common_file_for_review(self):
        path=config.REPO/'.env'
        path.write_text('UNMAPPED_SETTING=test-value\n')
        with self.assertRaisesRegex(RuntimeError,'unmapped settings'):
            config.configure(migrate_shared=True)
        self.assertTrue(path.exists())
