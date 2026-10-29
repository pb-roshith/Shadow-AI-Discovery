"""Live application scenarios 1, 2, 6 and 7, with explicitly retained fixtures for other scenarios."""
import json
from datetime import datetime
from pathlib import Path
from engine.collectors.local import Collector, telemetry_path
from engine.config import ROOT, repository_root
from engine.audit import gateway_snapshot


class HybridCollector(Collector):
    def __init__(self, run_id, fixture_mode='database'):
        super().__init__(run_id, fixture_mode)
        self.fixture_mode = fixture_mode
        self.audit_events = {}

    def emit(self, channel, kind, provider, source, **kwargs):
        scenario_one = kwargs.get('entity') == 'credit-dossier' or kwargs.get('user') == 'gateway-svc'
        if kwargs.get('evidence_origin') == 'live' and channel in ('Network', 'DLP'):
            if not source.startswith('live:'):
                source = 'live:' + source
        elif kwargs.get('live_scenario') == 'S5':
            kwargs['evidence_origin'] = 'live'
        elif scenario_one:
            kwargs.update(evidence_origin='live_sdk' if source == 'logs/sdk_calls.jsonl' else 'live', live_scenario='S1')
            if channel in ('Gateway', 'Network', 'DLP'):
                source = 'live:' + source
        elif kwargs.get('entity') == 'policy-intelligence':
            kwargs.update(evidence_origin='live_sdk' if source == 'logs/sdk_calls.jsonl' else 'live', live_scenario='S2')
            if channel in ('Gateway', 'Network', 'DLP') and source != 'logs/sdk_calls.jsonl':
                source = 'live:' + source
        elif kwargs.get('entity') == 'customer-assistant' or kwargs.get('user') == 'customer-assistant-svc':
            kwargs.update(evidence_origin='live_sdk' if source == 'logs/sdk_calls.jsonl' else 'live', live_scenario='S6')
            if channel in ('Gateway', 'Network', 'DLP') and source != 'logs/sdk_calls.jsonl':
                source = 'live:' + source
        elif kwargs.get('entity') == 'loan-risk-classifier':
            kwargs.update(evidence_origin='live_local' if kind == 'local_model_call' else 'live', live_scenario='S7')
        elif channel in ('Gateway', 'Network', 'DLP', 'Endpoint', 'MCP'):
            kwargs['evidence_origin'] = 'static_fixture'
        if source == 'logs/sdk_calls.jsonl':
            source = 'live:' + source
        super().emit(channel, kind, provider, source, **kwargs)

    def collect_repos(self):
        super().collect_repos()
        for signal in self.matches:
            if signal['entity'] == 'ahmed-scratch' and signal['provider'] == 'Ollama':
                signal['entity'] = 'loan-risk-classifier'
                signal['attributes'].update(evidence_origin='live', live_scenario='S7')
        self.matches = [s for s in self.matches if not (s['entity'] == 'credit-dossier' and s['signal_type'] == 'doc_mention')]

    def collect_endpoint(self):
        # The endpoint profile/model artifacts belong to the retained demo environment.
        # Actual app-local inference is collected from ollama_calls.jsonl.
        if self.fixture_mode != 'live':
            super().collect_endpoint()

    def collect_mcp(self):
        if self.fixture_mode != 'live':
            super().collect_mcp()
        if (repository_root(ROOT) / 'creditdb-MCP/server.py').is_file():
            self.matches = [s for s in self.matches if not (s['channel'] == 'MCP' and s['attributes'].get('server') == 'creditdb')]
            self.collect_creditdb_live()

    def collect_logs(self):
        super().collect_logs()
        self.collect_local_invocations()
        path = ROOT / 'logs/sdk_calls.jsonl'
        if not path.exists():
            return
        groups = {}
        for line, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            try:
                event = json.loads(raw)
                if event.get('app') not in ('credit-dossier', 'customer-assistant', 'policy-intelligence') or event.get('origin') != 'live_sdk':
                    continue
                datetime.fromisoformat(event['ts'])
                if event['provider'] not in ('Google', 'Mistral', 'OpenAI') or event['status'] not in ('success', 'failed'):
                    raise ValueError('Invalid SDK event')
                if not isinstance(event['request_id'], str) or not event['request_id'].strip():
                    raise ValueError('Missing request ID')
                groups.setdefault((event['app'], event['provider']), {})[event['request_id']] = (line, event)
            except (ValueError, TypeError, KeyError):
                self.warnings.append(f'Invalid SDK metadata skipped: sdk_calls.jsonl:{line}')
        for (app, provider), unique in groups.items():
            events = sorted(unique.values(), key=lambda pair: pair[1]['ts'])
            self.observe('Network', 'logs/sdk_calls.jsonl', 'sdk_invocation_metadata')
            # This evidence is emitted by the app SDK wrapper, not a network capture.
            self.emit('Network', 'ai_network_call', provider, 'logs/sdk_calls.jsonl',
                      entity=app, user=self.register.get(app, {}).get('service_account', ''), identity_source='register',
                      count=len(events), ts=events[0][1]['ts'], last=events[-1][1]['ts'],
                      via_gateway=False, programmatic=True, evidence_origin='live_sdk', live_scenario={'credit-dossier':'S1', 'policy-intelligence':'S2', 'customer-assistant':'S6'}[app],
                      request_ids=list(unique), line_numbers=[line for line, _ in events],
                      outcomes={status: sum(e['status'] == status for _, e in events) for status in ('success', 'failed')})

    def collect_local_invocations(self):
        path = ROOT / 'logs/ollama_calls.jsonl'
        if not path.exists():
            return
        groups = {}
        for line, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            try:
                event = json.loads(raw)
                if event.get('app') != 'loan-risk-classifier' or event.get('origin') != 'live_local':
                    continue
                datetime.fromisoformat(event['ts'])
                if event.get('provider') != 'Ollama' or event.get('host') != '127.0.0.1:11434' or event.get('status') not in ('success', 'failed'):
                    raise ValueError('Invalid local invocation')
                if not isinstance(event.get('request_id'), str) or not event['request_id'].strip() or not isinstance(event.get('model'), str) or not event['model'].strip():
                    raise ValueError('Missing invocation identity')
                snapshot = gateway_snapshot(event, raw, line)
                snapshot.update(source_file='logs/ollama_calls.jsonl', host=event['host'])
                self.audit_events[snapshot['id']] = snapshot
                groups.setdefault(event['model'], {})[event['request_id']] = (line, event, snapshot['id'])
            except (ValueError, KeyError, TypeError, AttributeError):
                self.warnings.append(f'Invalid local metadata skipped: ollama_calls.jsonl:{line}')
        for model, unique in groups.items():
            events = sorted(unique.values(), key=lambda item: item[1]['ts'])
            self.observe('Endpoint', 'live:logs/ollama_calls.jsonl', 'local_invocation_metadata')
            self.emit('Endpoint', 'local_model_call', 'Ollama', 'live:logs/ollama_calls.jsonl',
                      entity='loan-risk-classifier', count=len(events), ts=events[0][1]['ts'], last=events[-1][1]['ts'],
                      identity_source='none', model=model, runtime='ollama', local_only=True, programmatic=True,
                      request_ids=list(unique), line_numbers=[row[0] for row in events],
                      audit_event_ids=[row[2] for row in events],
                      outcomes={status: sum(row[1]['status'] == status for row in events) for status in ('success', 'failed')})

    @staticmethod
    def scenario_one(name, event):
        return event.get('app') in ('credit-dossier', 'customer-assistant', 'policy-intelligence') or event.get('proxy_user') in ('gateway-svc', 'customer-assistant-svc') or (event.get('proxy_user') == 'dev-svc' and event.get('host') == 'api.openai.com' and ROOT.resolve() == Path(__file__).resolve().parents[2])

    @staticmethod
    def retired_demo(key, event):
        return (ROOT.resolve() == Path(__file__).resolve().parents[2] and event.get('origin') in ('replay', 'seeded_demo') and (event.get('app') in ('loan-ops-helper', 'policy-intelligence') or (event.get('proxy_user') == 'dev-svc' and event.get('host') == 'api.openai.com'))) or str(key).startswith('s7-') or (event.get('origin') in ('replay', 'seeded_demo')
            and event.get('proxy_user') == 'ahmed' and event.get('host') == 'api.anthropic.com')

    def read_events(self, name):
        previous = len(self.observations)
        fixtures = [] if self.fixture_mode == 'live' else super().read_events(name)
        # New proxy records are consumed below in every mode, deduplicated by flow.
        fixtures = [(key, event) for key, event in fixtures if not event.get('flow_id')]
        ignored = {f'postgresql:telemetry_events/{key}' if self.fixture_mode == 'database' else f'logs/{name}:{key}' for key, event in fixtures if self.scenario_one(name, event) or self.retired_demo(key, event)}
        self.observations[previous:] = [o for o in self.observations[previous:] if o['source_ref'] not in ignored]
        # Never reuse seeded S1 runtime evidence, even when live logs are missing.
        # Retire old S7 simulation events; the classifier now has its own real application.
        events = [(key, event) for key, event in fixtures if not self.scenario_one(name, event)
                  and not self.retired_demo(key, event)]
        if name not in ('gateway.jsonl', 'proxy.jsonl', 'dlp.jsonl'):
            return events
        path = telemetry_path(name, ROOT)
        unique = {}
        stages = {}
        if not path.exists():
            return events
        for index, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            try:
                event = json.loads(line)
                live_proxy = name in ('proxy.jsonl', 'dlp.jsonl') and bool(event.get('flow_id'))
                if not live_proxy and (event.get('origin') != 'live' or not self.scenario_one(name, event)):
                    continue
                datetime.fromisoformat(event['ts'])
                request_id = event.get('flow_id') or event.get('request_id') or (f'proxy-line-{index}' if name != 'gateway.jsonl' else None)
                if name == 'dlp.jsonl' and event.get('flow_id'):
                    request_id += ':' + event['label']
                if not request_id:
                    continue
                if name == 'gateway.jsonl':
                    snapshot = gateway_snapshot(event, line, index)
                    self.audit_events[snapshot['id']] = snapshot
                    stages.setdefault(request_id, []).append(snapshot['id'])
                old = unique.get(request_id)
                # A delayed duplicate pending callback cannot erase a final outcome.
                if old and old[1].get('status') in ('success', 'failed') and event.get('status') == 'pending':
                    continue
                unique[request_id] = (f'live:{index}', event)
            except (ValueError, TypeError, KeyError):
                self.warnings.append(f'Invalid live metadata skipped: {name}:{index}')
        live_identities = {(event.get('proxy_user'), event.get('host')) for _, event in unique.values() if event.get('flow_id')}
        events = [(key, event) for key, event in events
                  if not (event.get('origin') in ('replay', 'seeded_demo')
                          and (event.get('proxy_user'), event.get('host')) in live_identities)]
        for key, event in unique.values():
            event = dict(event)
            if name == 'gateway.jsonl':
                event['_audit_event_ids'] = stages[event['request_id']]
            self.observe('Gateway' if name == 'gateway.jsonl' else 'Network' if name == 'proxy.jsonl' else 'DLP', f'live:logs/{name}:{key}', 'live_event')
            events.append((key, event))
        return sorted(events, key=lambda pair: pair[1]['ts'])
