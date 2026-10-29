import asyncio
import importlib.util
from pathlib import Path
import unittest
import sys
import json
import tempfile
from unittest.mock import patch, AsyncMock

from starlette.testclient import TestClient
from workspace_tools import workspace_services


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('creditdb_server', ROOT / 'repo server/creditdb-MCP/server.py')
creditdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(creditdb)


class CreditDB(unittest.TestCase):
    def test_scenario_card_uses_repository_name_even_with_old_catalogue(self):
        sys.path.insert(0, str(ROOT / 'shadow server/backend'))
        from engine import api
        with patch.object(api, 'list_payloads', side_effect=lambda table: [] if table == 'candidates' else [{'id':'S5', 'name':'risk-agent'}]):
            scenario, = api.scenarios()
        self.assertEqual(scenario['name'], 'creditdb-MCP')
        self.assertEqual(scenario['entity'], 'creditdb-MCP')
        self.assertEqual(scenario['source'], 'live')
        self.assertIsNone(scenario['result'])

    def test_live_discovery_uses_repository_identity_and_excludes_replay(self):
        sys.path.insert(0, str(ROOT / 'shadow server/backend'))
        from engine.collectors import local, hybrid
        from engine.detect import detect
        from engine.correlate import correlate
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'creditdb-MCP').mkdir()
            (base / 'creditdb-MCP/server.py').touch()
            (base / 'logs').mkdir()
            event = {'ts': '2026-10-28T00:00:00+00:00', 'server': 'creditdb', 'caller': 'risk-agent', 'tool': 'query_loans'}
            (base / 'logs/mcp_audit.jsonl').write_text(json.dumps(event) + '\n' + json.dumps({**event, 'origin': 'replay'}) + '\n')
            with patch.object(local, 'ROOT', base), patch.object(local, 'repository_root', return_value=base), patch.object(hybrid, 'ROOT', base), patch.object(hybrid, 'repository_root', return_value=base), patch.object(local, 'reference', side_effect=lambda name: {'sdks': {}} if name == 'ai_signatures.yaml' else []), patch.object(local, 'rows', return_value={}), patch.object(local, 'port_open', return_value=True), patch.object(local, 'fetch_tools', new=AsyncMock(return_value=[{'name':'execute_sql', 'write':True}])):
                collector = hybrid.HybridCollector('test', 'live')
                collector.collect_mcp()
            self.assertEqual(len(collector.matches), 3)
            candidate, = correlate(detect(collector.matches))
            self.assertEqual(candidate['entity'], 'creditdb-MCP')
            self.assertEqual(candidate['name'], 'creditdb-MCP')
            self.assertEqual(candidate['user_id'], 'risk-agent')
            calls = next(s for s in candidate['signals'] if s['signal_type'] == 'mcp_tool_calls')
            self.assertEqual(calls['event_count'], 1)
            self.assertTrue(all(s['attributes']['evidence_origin'] == 'live' for s in candidate['signals']))

    def test_health_and_live_tools_do_not_require_database(self):
        with patch.object(creditdb, 'connect', side_effect=AssertionError('Listing tools must not access database')):
            with TestClient(creditdb.server.streamable_http_app()) as client:
                self.assertEqual(client.get('/api/health').json(), {'status': 'ok', 'repo': 'creditdb-MCP'})
                response = client.get('/api/tools')
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data['endpoint'], 'http://127.0.0.1:8765/mcp')
                registered = asyncio.run(creditdb.server.list_tools())
                self.assertEqual(data['tools'], [tool.model_dump(mode='json', by_alias=True) for tool in registered])
                tools = {tool['name']: tool for tool in data['tools']}
                self.assertTrue(tools['query_loans']['annotations']['readOnlyHint'])
                self.assertFalse(tools['execute_sql']['annotations']['readOnlyHint'])
                self.assertTrue(tools['execute_sql']['annotations']['destructiveHint'])
                self.assertIn('sql', tools['execute_sql']['inputSchema']['required'])

    def test_write_tool_rejects_other_sql_before_connecting(self):
        with patch.object(creditdb, 'connect') as connect, patch.object(creditdb, 'audit') as audit:
            for sql in ('DROP TABLE loans', "UPDATE loans SET status = 'reviewed'", 'SELECT * FROM loans'):
                with self.subTest(sql=sql), self.assertRaises(ValueError):
                    creditdb.execute_sql(sql)
            connect.assert_not_called()
            audit.assert_not_called()

    def test_launcher_manages_independent_mcp_process(self):
        with patch.object(workspace_services.shutil, 'which', side_effect=lambda name: name + '.exe'):
            service = next(item for item in workspace_services.definitions() if item[0] == 'creditdb')
        self.assertEqual(service[1], ROOT / 'repo server/creditdb-MCP')
        self.assertEqual(service[2], [str(workspace_services.PYTHON), 'server.py'])
        self.assertEqual(service[3:], (8765, '/api/health'))

    def test_stop_terminates_owned_creditdb(self):
        from unittest.mock import Mock
        process = Mock()
        process.children.return_value = []
        record = {'name': 'creditdb', 'pid': 123}
        with patch.object(workspace_services, 'records', return_value=[record]), patch.object(workspace_services, 'owned', return_value=process), patch.object(workspace_services, 'save') as save, patch.object(workspace_services, 'stop_marker'), patch.object(workspace_services.psutil, 'wait_procs', return_value=([process], [])):
            self.assertFalse(workspace_services.stop())
        process.terminate.assert_called_once()
        save.assert_called_once_with([])
