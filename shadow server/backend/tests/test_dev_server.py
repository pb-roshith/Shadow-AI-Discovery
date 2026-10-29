import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine import dev_server


class DevelopmentServers(unittest.TestCase):
    @patch.dict(os.environ, {'SHADOWAI_DB_PASSWORD': ''})
    @patch('getpass.getpass', side_effect=AssertionError('Must never prompt'))
    @patch('engine.dev_server.stop')
    @patch('engine.dev_server.recorded_process', return_value=None)
    @patch('engine.dev_server.psutil.Process')
    @patch('engine.dev_server.subprocess.Popen')
    def test_backend_starts_without_password_prompt(self, spawn, process, recorded, stop, prompt):
        with TemporaryDirectory() as directory, patch.object(dev_server, 'ROOT', Path(directory)):
            spawn.return_value.pid = 123
            spawn.return_value.wait.return_value = 0
            process.return_value.create_time.return_value = 123.0
            process.return_value.exe.return_value = 'python.exe'
            self.assertEqual(dev_server.run('backend'), 0)
            self.assertIn('engine.api:app', spawn.call_args.args[0])
            prompt.assert_not_called()
            stop.assert_called_once_with('backend')

    @patch('engine.dev_server.psutil.Process')
    def test_recycled_pid_is_not_owned(self, process):
        with TemporaryDirectory() as directory, patch.object(dev_server, 'ROOT', Path(directory)):
            dev_server.registry('frontend').parent.mkdir()
            dev_server.registry('frontend').write_text('{"pid":123,"created":1,"executable":"node.exe"}')
            process.return_value.create_time.return_value = 2
            self.assertIsNone(dev_server.recorded_process('frontend'))
            process.return_value.terminate.assert_not_called()
