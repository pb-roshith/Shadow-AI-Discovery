import os
import unittest
from unittest.mock import patch, MagicMock

from engine.configure_start import ensure_password
from engine.db import connection_parameters


class DatabaseConfiguration(unittest.TestCase):
    @patch.dict(os.environ, {'SHADOWAI_DB_PASSWORD': 'test-only'})
    @patch('engine.db.saved_password', side_effect=AssertionError('Legacy credential accessed'))
    def test_environment_password_bypasses_legacy_credential(self, legacy):
        self.assertEqual(connection_parameters()['password'], 'test-only')

    @patch.dict(os.environ, {'SHADOWAI_DB_PASSWORD': ''})
    @patch('engine.configure_start.sys.stdin')
    def test_noninteractive_missing_password_is_actionable(self, stdin):
        stdin.isatty.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'backend/.env'):
            ensure_password()

    @patch.dict(os.environ, {'SHADOWAI_DB_PASSWORD': ''})
    @patch('engine.configure_start.set_key')
    @patch('psycopg.connect')
    @patch('engine.configure_start.getpass.getpass', return_value='test-only')
    @patch('engine.configure_start.sys.stdin')
    def test_prompt_validates_before_saving(self, stdin, prompt, connect, save):
        stdin.isatty.return_value = True
        ensure_password()
        self.assertTrue(connect.called)
        self.assertEqual(save.call_args.args[1:], ('SHADOWAI_DB_PASSWORD', 'test-only'))

    @patch.dict(os.environ, {'SHADOWAI_DB_PASSWORD': ''})
    @patch('engine.configure_start.set_key')
    @patch('psycopg.connect')
    @patch('engine.configure_start.getpass.getpass', return_value='test-only')
    @patch('engine.configure_start.sys.stdin')
    def test_invalid_password_is_not_saved(self, stdin, prompt, connect, save):
        import psycopg
        stdin.isatty.return_value = True
        connect.side_effect = psycopg.OperationalError('Rejected')
        with self.assertRaisesRegex(RuntimeError, 'Cannot connect'):
            ensure_password()
        save.assert_not_called()
