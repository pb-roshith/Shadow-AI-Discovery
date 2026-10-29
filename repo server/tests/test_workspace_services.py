import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workspace_tools import workspace_services as services


class ProxyLifecycle(unittest.TestCase):
    def test_deployed_proxy_starts_with_its_own_environment(self):
        directory = Path('C:/ShadowAI-Demo')
        with patch.object(services, 'proxy_root', return_value=directory), patch.object(services.shutil, 'which', side_effect=lambda name: name + '.exe'):
            proxy = next(item for item in services.definitions() if item[0] == 'mitmweb')
        self.assertEqual(proxy, ('mitmweb', directory, [str(directory / '.venv/Scripts/python.exe'), '-m', 'services.proxy.launch_proxy'], 8081, '/'))

    def test_deployment_accepts_powershell_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(services, 'SHADOW', Path(directory)):
            deployment = Path(directory) / 'backend/services/proxy/deployment.json'
            deployment.parent.mkdir(parents=True)
            deployment.write_text('{"logs_dir": "C:/ShadowAI-Demo/logs"}', encoding='utf-8-sig')
            self.assertEqual(services.proxy_root(), Path('C:/ShadowAI-Demo'))

    def test_password_protected_ui_is_ready_only_with_proxy_port(self):
        error = urllib.error.HTTPError('http://127.0.0.1:8081/', 403, 'Forbidden', {}, None)
        with patch.object(services.urllib.request, 'urlopen', side_effect=error), patch.object(services.socket, 'socket') as socket:
            connection = socket.return_value.__enter__.return_value
            connection.connect_ex.return_value = 0
            self.assertTrue(services.service_ready('mitmweb', 8081, '/'))
            connection.connect_ex.assert_called_with(('127.0.0.1', 8080))
            connection.connect_ex.return_value = 1
            self.assertFalse(services.service_ready('mitmweb', 8081, '/'))
            self.assertFalse(services.service_ready('shadow-backend', 8000, '/health'))

    def test_unavailable_ui_is_not_ready(self):
        with patch.object(services.urllib.request, 'urlopen', side_effect=OSError('refused')):
            self.assertFalse(services.service_ready('mitmweb', 8081, '/'))

    def test_unrelated_listener_is_not_reused(self):
        listeners = [Mock(laddr=Mock(port=8080, ip='127.0.0.1'), pid=10, status=services.psutil.CONN_LISTEN),
                     Mock(laddr=Mock(port=8081, ip='127.0.0.1'), pid=11, status=services.psutil.CONN_LISTEN)]
        with patch.object(services.psutil, 'net_connections', return_value=listeners):
            self.assertFalse(services.existing_proxy(Path('C:/ShadowAI-Demo'), ['python.exe']))

    def test_existing_venv_proxy_is_reused_with_base_python_executable(self):
        directory = Path('C:/ShadowAI-Demo')
        command = [str(directory / '.venv/Scripts/python.exe'), '-m', 'services.proxy.launch_proxy']
        listeners = [Mock(laddr=Mock(port=port, ip='127.0.0.1'), pid=10, status=services.psutil.CONN_LISTEN)
                     for port in (8080, 8081)]
        process = Mock()
        process.cwd.return_value = str(directory)
        process.cmdline.return_value = command
        process.exe.return_value = 'C:/Program Files/Python314/python.exe'
        with patch.object(services.psutil, 'net_connections', return_value=listeners), patch.object(services.psutil, 'Process', return_value=process), patch.object(services, 'service_ready', return_value=True):
            self.assertTrue(services.existing_proxy(directory, command))
            process.cmdline.return_value = ['python.exe', '-m', 'http.server']
            self.assertFalse(services.existing_proxy(directory, command))

    def test_tab_configures_offline_proxy_and_shutdown_ownership(self):
        child = Mock(pid=123)
        child.wait.return_value = 0
        process = Mock()
        process.create_time.return_value = 42
        process.exe.return_value = 'python.exe'
        with tempfile.TemporaryDirectory() as directory, patch.object(services, 'RUNTIME', Path(directory)), patch.object(services, 'definitions', return_value=[('mitmweb', Path(directory), ['python.exe', '-m', 'services.proxy.launch_proxy'], 8081, '/')]), patch.object(services.subprocess, 'Popen', return_value=child), patch.object(services.psutil, 'Process', return_value=process), patch.dict(services.os.environ, {}, clear=False):
            self.assertEqual(services.run_tab('mitmweb'), 0)
            self.assertEqual(services.os.environ['SHADOWAI_PROXY_OFFLINE'], '1')
            self.assertEqual(services.os.environ['SHADOWAI_PROXY_CONFIG'], str(Path(directory) / 'services/proxy/proxy_config.yaml'))
            self.assertTrue(services.tab_record('mitmweb').exists())


class OllamaLifecycle(unittest.TestCase):
    def setUp(self):
        existing = patch.object(services, 'existing_ollama', return_value=False)
        self.existing_ollama = existing.start()
        self.addCleanup(existing.stop)

    def test_tab_reuses_ollama_started_after_preflight_without_spawning(self):
        self.existing_ollama.return_value = True
        with tempfile.TemporaryDirectory() as directory, patch.object(services, 'RUNTIME', Path(directory)), patch.object(services, 'definitions', return_value=[('ollama', services.ROOT, ['ollama.exe', 'serve'], 11434, '/api/tags')]), patch.object(services.subprocess, 'Popen') as launch:
            self.assertEqual(services.run_tab('ollama'), 0)
            self.assertIn('"external": true', services.tab_record('ollama').read_text())
            launch.assert_not_called()

    def test_gateway_uses_its_private_mcp_environment(self):
        with patch.object(services.shutil, 'which', side_effect=lambda name: name + '.exe'):
            definitions = services.definitions()
        gateway = next(item for item in definitions if item[0] == 'gateway')
        creditdb = next(item for item in definitions if item[0] == 'creditdb')
        self.assertEqual(gateway[2][0], str(services.GATEWAY_PYTHON))
        self.assertEqual(creditdb[2][0], str(services.PYTHON))
        self.assertNotEqual(gateway[2][0], creditdb[2][0])

    def test_gateway_loads_only_its_own_dotenv(self):
        child = Mock(pid=123)
        child.wait.return_value = 0
        process = Mock()
        process.create_time.return_value = 42
        process.exe.return_value = 'python.exe'
        with tempfile.TemporaryDirectory() as directory, patch.object(services, 'RUNTIME', Path(directory)), patch.object(services, 'definitions', return_value=[('gateway', services.SHADOW / 'backend', ['python.exe'], 4000, '/health/liveliness')]), patch.object(services.subprocess, 'Popen', return_value=child), patch.object(services.psutil, 'Process', return_value=process), patch('dotenv.load_dotenv') as load, patch.dict(services.os.environ, {}, clear=False):
            self.assertEqual(services.run_tab('gateway'), 0)
            load.assert_called_once_with(services.SHADOW / 'backend/services/gateway/.env', override=True)

    def test_ollama_starts_before_application_services(self):
        with patch.object(services.shutil, 'which', side_effect=lambda name: name + '.exe'):
            definitions = services.definitions()
        self.assertEqual(definitions[0], ('ollama', services.ROOT, ['ollama.exe', 'serve'], 11434, '/api/tags'))

    def test_stop_terminates_owned_ollama(self):
        process = Mock()
        process.children.return_value = []
        record = {'name': 'ollama', 'pid': 123}
        with patch.object(services, 'records', return_value=[record]), patch.object(services, 'owned', return_value=process), patch.object(services, 'save') as save, patch.object(services, 'stop_marker') as marker, patch.object(services.psutil, 'wait_procs', return_value=([process], [])):
            self.assertFalse(services.stop())
        process.terminate.assert_called_once()
        save.assert_called_once_with([])

    def test_tab_runs_ollama_on_localhost_and_records_ownership(self):
        child = Mock(pid=123)
        child.wait.return_value = 0
        process = Mock()
        process.create_time.return_value = 42
        process.exe.return_value = 'ollama.exe'
        with tempfile.TemporaryDirectory() as directory, patch.object(services, 'RUNTIME', Path(directory)), patch.object(services, 'definitions', return_value=[('ollama', services.ROOT, ['ollama.exe', 'serve'], 11434, '/api/tags')]), patch.object(services.subprocess, 'Popen', return_value=child) as launch, patch.object(services.psutil, 'Process', return_value=process), patch.dict(services.os.environ, {}, clear=False):
            self.assertEqual(services.run_tab('ollama'), 0)
            self.assertEqual(services.os.environ['OLLAMA_HOST'], '127.0.0.1:11434')
            self.assertTrue(services.tab_record('ollama').exists())
        launch.assert_called_once_with(['ollama.exe', 'serve'], cwd=services.ROOT)

    def test_deliberate_stop_closes_tab_with_success_status(self):
        child = Mock(pid=123)
        process = Mock()
        process.create_time.return_value = 42
        process.exe.return_value = 'ollama.exe'
        with tempfile.TemporaryDirectory() as directory, patch.object(services, 'RUNTIME', Path(directory)), patch.object(services, 'definitions', return_value=[('ollama', services.ROOT, ['ollama.exe', 'serve'], 11434, '/api/tags')]), patch.object(services.subprocess, 'Popen', return_value=child), patch.object(services.psutil, 'Process', return_value=process), patch.dict(services.os.environ, {}, clear=False):
            def stopped():
                services.stop_marker('ollama').write_text('stop')
                return 1
            child.wait.side_effect = stopped
            self.assertEqual(services.run_tab('ollama'), 0)

    def test_unexpected_failure_retains_failure_status(self):
        child = Mock(pid=123)
        child.wait.return_value = 1
        process = Mock()
        process.create_time.return_value = 42
        process.exe.return_value = 'ollama.exe'
        with tempfile.TemporaryDirectory() as directory, patch.object(services, 'RUNTIME', Path(directory)), patch.object(services, 'definitions', return_value=[('ollama', services.ROOT, ['ollama.exe', 'serve'], 11434, '/api/tags')]), patch.object(services.subprocess, 'Popen', return_value=child), patch.object(services.psutil, 'Process', return_value=process), patch.dict(services.os.environ, {}, clear=False):
            self.assertEqual(services.run_tab('ollama'), 1)
