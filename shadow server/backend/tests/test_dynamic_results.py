import copy
import unittest
from unittest.mock import patch

from engine.api import dashboard_state, scenario_results


def candidate(key, entity, provider, decision, risk, confidence=90, channels=None):
    return {'id': key, 'entity': entity, 'provider': provider, 'decision': decision,
            'risk': risk, 'confidence': confidence, 'channels': channels or ['Code'],
            'run_id': 'current-run', 'inventory': {'status': 'Approved'},
            'decision_explanation': decision + ' from current evidence',
            'signals': [{'channel': 'Code', 'signal_type': 'sdk_import',
                         'attributes': {}, 'ts_last': '2026-10-28T12:00:00Z'}]}


class DynamicResults(unittest.TestCase):
    def test_missing_evidence_never_displays_catalogue_predictions(self):
        records = [{'id': 'S3', 'provider': 'OpenAI', 'user_id': 'priya',
                    'channels': ['Network', 'DLP'], 'expected_decision': 'Raise issue',
                    'expected_risk': 85, 'expected_confidence': 85}]
        result = scenario_results([], records)[0]
        self.assertIsNone(result['result'])
        self.assertEqual(result['candidate_ids'], [])
        self.assertEqual(result['channels'], [])
        self.assertFalse(any(key.startswith('expected_') for key in result))

    def test_every_application_prioritizes_current_issue_and_links_exact_candidate(self):
        for scenario, entity in [('S1', 'credit-dossier'), ('S2', 'policy-intelligence'),
                                 ('S5', 'creditdb-MCP'), ('S6', 'customer-assistant'),
                                 ('S7', 'loan-risk-classifier')]:
            with self.subTest(scenario=scenario):
                safe = candidate('safe', entity, 'Google', 'Genuine', 30, 100)
                issue = candidate('issue', entity, 'OpenAI', 'Raise issue', 75, 65, ['Code', 'Secret'])
                for candidates in ([safe, issue], [issue, safe]):
                    result = scenario_results(candidates, [{'id': scenario}])[0]
                    self.assertEqual(result['result']['id'], issue['id'])
                    for key in ('decision', 'risk', 'confidence', 'run_id', 'inventory'):
                        self.assertEqual(result['result'][key], issue[key])
                    self.assertEqual(set(result['candidate_ids']), {'safe', 'issue'})
                    self.assertEqual(result['channels'], ['Code', 'Secret'])

    def test_scenario_updates_when_decision_changes_or_candidate_disappears(self):
        records = [{'id': 'S5', 'expected_decision': 'Raise issue'}]
        current = candidate('mcp', 'creditdb-MCP', 'creditdb MCP', 'Raise issue', 80)
        self.assertEqual(scenario_results([current], copy.deepcopy(records))[0]['result']['decision'], 'Raise issue')
        current.update(decision='Genuine', risk=35)
        updated = scenario_results([current], copy.deepcopy(records))[0]['result']
        self.assertEqual((updated['decision'], updated['risk']), ('Genuine', 35))
        self.assertIsNone(scenario_results([], copy.deepcopy(records))[0]['result'])

    def test_dashboard_reuses_one_candidate_snapshot_for_both_pages(self):
        current = candidate('mcp', 'creditdb-MCP', 'creditdb MCP', 'Raise issue', 80)
        signals = current['signals']
        def payloads(table, run_id=None):
            if table == 'candidates':
                return [current]
            if table == 'scenarios':
                return [{'id': 'S5'}]
            if table == 'signals':
                self.assertEqual(run_id, 'current-run')
                return signals
            return []
        with patch('engine.api.latest', return_value={'id': 'current-run'}), \
             patch('engine.api.list_payloads', side_effect=payloads) as reads, \
             patch('engine.api.config', return_value={}), \
             patch('engine.api.reference_data', return_value={}):
            state = dashboard_state()
        self.assertEqual(sum(call.args[0] == 'candidates' for call in reads.call_args_list), 1)
        self.assertEqual(state['scenarios'][0]['result']['decision'], state['candidates'][0]['decision'])
        self.assertEqual(state['scenarios'][0]['result']['run_id'], state['latest']['id'])
        self.assertEqual(state['signals'], signals)
