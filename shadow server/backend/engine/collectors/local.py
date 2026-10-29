"""Bounded, metadata-only collectors. No source/body is persisted."""
import ast
import hashlib
import json
import os
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from engine.config import ROOT, reference, rows, within, repository_root

def now():
    return datetime.now(timezone.utc).isoformat()


def telemetry_path(name, root=None):
    root = root or ROOT
    if name in ('proxy.jsonl', 'dlp.jsonl') and os.environ.get('SHADOWAI_PROXY_LOGS_DIR'):
        return Path(os.environ['SHADOWAI_PROXY_LOGS_DIR']) / name
    if name in ('proxy.jsonl', 'dlp.jsonl'):
        deployment = root / 'services/proxy/deployment.json'
        if deployment.exists():
            return Path(json.loads(deployment.read_text(encoding='utf-8-sig'))['logs_dir']) / name
    return root / 'logs' / name

def git(repo, *args):
    if not (Path(repo) / '.git').exists():
        return ''
    command = ['git', '-C', str(repo), *args]
    options = dict(capture_output=True, timeout=15, encoding='utf-8', errors='replace')
    result = subprocess.run(command, **options)
    if result.returncode and 'dubious ownership' in result.stderr.lower():
        # The workspace explicitly authorizes scanning this repository. Trust
        # only its resolved path for this read, without changing Git config.
        result = subprocess.run(['git', '-c', f'safe.directory={Path(repo).resolve().as_posix()}',
                                 '-C', str(repo), *args], **options)
    if result.returncode:
        # Git output can include source or credentials; report only metadata.
        reason = 'repository access failed'
        error = result.stderr.lower()
        if 'dubious ownership' in error:
            reason = 'repository ownership is not trusted by Git'
        elif 'not a git repository' in error:
            reason = 'Git did not recognize the repository'
        elif 'permission denied' in error or 'access is denied' in error:
            reason = 'repository permission denied'
        raise RuntimeError(f'Git {args[0]} failed (exit {result.returncode}): {reason}')
    return result.stdout

def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.15):
            return True
    except OSError:
        return False

class Collector:
    def __init__(self, run_id, mode='replay'):
        self.run_id, self.mode = run_id, mode
        self.observations, self.matches, self.warnings = [], [], []
        self.catalog = reference('ai_signatures.yaml')
        self.catalog['sdks'].setdefault('google-genai', 'Google')
        self.register = rows('repo_register', 'repo')
        self.users = rows('users', 'user_id')
        self.devices = {r['primary_user']: r['device_label'] for r in reference('devices.csv')}

    def observe(self, channel, source, kind='item'):
        self.observations.append({'channel': channel, 'source_ref': source, 'kind': kind})

    def read_git(self, repo, *args):
        try:
            return git(repo, *args)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
            warning = f'Git history scan incomplete for {repo.name}: {reason}.'
            if not any(item.startswith(f'Git history scan incomplete for {repo.name}:') for item in self.warnings):
                self.warnings.append(warning)
            return ''

    def emit(self, channel, kind, provider, source, entity='', user='', host='', count=1, ts=None, last=None, fingerprint=None, **attributes):
        if channel == 'MCP' and attributes.get('server') == 'creditdb':
            entity = 'creditdb-MCP'
        if self.mode == 'database' and source.startswith('logs/'):
            source = 'postgresql:telemetry_events/' + source[5:]
        direct = channel in ('Network', 'DLP', 'Gateway', 'MCP')
        attributes.setdefault('identity_source', 'direct' if direct and user else 'register' if user else 'none')
        self.matches.append(dict(run_id=self.run_id, channel=channel, signal_type=kind, provider=provider, entity=entity,
            user_id=user, device_label=self.devices.get(user, ''), fingerprint=fingerprint, host=host,
            event_count=count, ts_first=ts or now(), ts_last=last or ts or now(), attributes=attributes, source_ref=source))

    def read_events(self, name):
        if self.mode == 'database':
            from engine.db import connection, decode
            with connection() as db:
                records = list(db.execute('SELECT id,payload FROM telemetry_events WHERE stream=? ORDER BY id', (name,)))
            events = []
            for event_id, payload in records:
                event = decode(payload)
                datetime.fromisoformat(event['ts'])
                events.append((event_id, event))
                channel = {'proxy': 'Network', 'dlp': 'DLP', 'mcp_runtime': 'MCP', 'mcp_audit': 'MCP'}.get(name.split('.')[0], name.split('.')[0].title())
                self.observe(channel, f'postgresql:telemetry_events/{event_id}', 'database_event')
            return events
        path = telemetry_path(name)
        if not path.exists():
            return []
        events = []
        for index, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            try:
                event = json.loads(line)
                # Replay and observed telemetry cannot silently mix.
                if (event.get('origin') == 'replay') != (self.mode == 'replay'):
                    continue
                datetime.fromisoformat(event['ts'])
                events.append((index, event))
                self.observe(name.split('.')[0].title(), f'logs/{name}:{index}', 'event')
            except (ValueError, KeyError, TypeError):
                self.warnings.append(f'Invalid metadata event skipped: {name}:{index}')
        return events

    def collect_repos(self):
        base = repository_root(ROOT)
        if not base.exists():
            return
        for repo in sorted(base.iterdir()):
            if not repo.is_dir() or repo.is_symlink():
                continue
            if repo.name in ('frontend', 'backend'):
                continue
            within(repo, base)
            register = self.register.get(repo.name, {})
            # Live scratch ownership is provided by explicit git author metadata.
            author = self.read_git(repo, 'log', '-1', '--format=%an').strip()
            user = register.get('service_account') or (author if author in self.users else '')
            for path in repo.rglob('*'):
                if not path.is_file() or path.is_symlink() or '.git' in path.parts or not path.resolve().is_relative_to(base.resolve()) or path.stat().st_size > 1_000_000:
                    continue
                if path.suffix not in ('.py', '.txt', '.json', '.yaml', '.yml', '.toml', '.md', '.js', '.ts', '.env') and path.name not in ('.env', 'requirements.txt'):
                    continue
                source = 'repos/' + str(path.relative_to(base)).replace('\\', '/')
                self.observe('Code', source, 'file')
                content = path.read_text(encoding='utf-8', errors='replace')
                doc = path.suffix == '.md' or path.name.lower().startswith('readme')
                imports = set()
                if path.suffix == '.py':
                    try:
                        for node in ast.walk(ast.parse(content)):
                            if isinstance(node, ast.Import):
                                imports.update(a.name.split('.')[0] for a in node.names)
                            elif isinstance(node, ast.ImportFrom) and node.module:
                                imports.add(node.module.split('.')[0])
                    except SyntaxError:
                        self.warnings.append(f'Cannot parse Python: {source}')
                for sdk, provider in self.catalog['sdks'].items():
                    kind = None
                    if doc and re.search(r'\b' + re.escape(sdk) + r'\b', content, re.I):
                        kind = 'doc_mention'
                    elif sdk.replace('-', '_') in imports or path.suffix in ('.js', '.ts') and re.search(r'(?:from|require\()\s*[\x27\x22]' + re.escape(sdk), content):
                        kind = 'sdk_import'
                    elif sdk == 'google-genai' and re.search(r'from google(?:\.genai)? import|import google\.genai', content) and path.suffix == '.py':
                        kind = 'sdk_import'
                    elif path.name in ('requirements.txt', 'pyproject.toml', 'package.json') and re.search(r'(?<![\w-])' + re.escape(sdk) + r'(?![\w-])', content):
                        kind = 'sdk_dependency'
                    if kind:
                        self.emit('Code', kind, provider, source, entity=repo.name, user=user, sdk=sdk, programmatic=False,
                            identity_source='register' if register else 'direct' if user else 'none',
                            file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            line_numbers=[index for index, line in enumerate(content.splitlines(), 1) if sdk in line or sdk == 'google-genai' and ('from google' in line or 'import google.genai' in line)])
                self.detect_secrets(content, source, repo.name, user, 'credential_in_file')
            commits = self.read_git(repo, 'rev-list', '--all').splitlines()
            seen = set()
            for commit in commits:
                for name in self.read_git(repo, 'ls-tree', '-r', '--name-only', commit).splitlines():
                    # No checkout or external path access; read git object in memory.
                    if '..' in Path(name).parts:
                        continue
                    source = f'repos/{repo.name}/git:{commit[:12]}:{name}'
                    self.observe('Secret', source, 'history_blob')
                    content = self.read_git(repo, 'show', f'{commit}:{name}')
                    self.detect_secrets(content, source, repo.name, user, 'credential_in_history', seen, commit)

        # Keep documentation-only hints only when no executable integration exists.
        # Otherwise the isolated doc hint would collide with the repo/provider candidate.
        integrations = {(s['entity'], s['provider']) for s in self.matches
                        if s['signal_type'] in ('sdk_import', 'sdk_dependency')}
        self.matches = [s for s in self.matches if s['signal_type'] != 'doc_mention'
                        or (s['entity'], s['provider']) not in integrations]

    def detect_secrets(self, content, source, entity, user, kind, seen=None, commit=None):
        patterns = list(self.catalog['key_patterns'].items()) + [('Mistral', r'(?i:MISTRAL)[A-Z_]*\s*=\s*[\x27\x22]?([A-Za-z0-9]{32})\b')]
        for provider, pattern in patterns:
            for match in re.finditer(pattern, content):
                value = match.group(1) if provider == 'Mistral' else match.group(0)
                if provider == 'OpenAI' and value.startswith('sk-ant-'):
                    continue
                fingerprint = hashlib.sha256(value.encode()).hexdigest()
                if seen is not None and fingerprint in seen:
                    continue
                if seen is not None:
                    seen.add(fingerprint)
                self.emit('Secret', kind, provider, source, entity=entity, user=user, fingerprint=fingerprint,
                    masked=value[:4] + '…' + value[-4:], commit=commit)

    def collect_logs(self):
        gateway_events = self.read_events('gateway.jsonl')
        grouped = {}
        for line, event in gateway_events:
            key = (event['app'], event['model'], event['provider'])
            grouped.setdefault(key, []).append((line, event))
        for (app, model, provider), events in grouped.items():
            self.emit('Gateway', 'gateway_call', provider, 'logs/gateway.jsonl', entity=app,
                user=self.register.get(app, {}).get('service_account', ''), count=len(events), ts=events[0][1]['ts'], last=events[-1][1]['ts'], model=model, via_gateway=True, programmatic=True,
                outcomes={status: sum(e.get('status') == status for _, e in events) for status in ('pending', 'success', 'failed')},
                request_ids=[e['request_id'] for _, e in events if e.get('request_id')],
                audit_event_ids=sorted({eid for _, e in events for eid in e.get('_audit_event_ids', [])}))
        networks = {}
        for line, event in self.read_events('proxy.jsonl'):
            host, user = event['host'], event['proxy_user']
            provider = self.host_provider(host)
            if not provider:
                continue
            bucket = int(datetime.fromisoformat(event['ts']).timestamp()) // 600
            apps = ['']
            if user == 'gateway-svc':
                apps = sorted({e['app'] for _, e in gateway_events if e['provider'] == provider and int(datetime.fromisoformat(e['ts']).timestamp()) // 600 == bucket}) or ['']
            for app in apps:
                networks.setdefault((user, host, bucket, app), []).append(event)
        for (user, host, bucket, app), events in networks.items():
            self.emit('Network', 'ai_network_call', self.host_provider(host), 'logs/proxy.jsonl', user=user, host=host,
                entity=app, count=len(events), ts=events[0]['ts'], last=events[-1]['ts'], via_gateway=bool(app),
                **({'evidence_origin': 'live'} if any(e.get('flow_id') for e in events) else {}),
                bytes_out=sum(e.get('bytes_out', 0) for e in events), programmatic=user in ('dev-svc', 'app-svc', 'gateway-svc') or host.startswith('api.'))
        for line, event in self.read_events('dlp.jsonl'):
            provider = self.host_provider(event['host'])
            if provider:
                self.emit('DLP', 'dlp_label', provider, f'logs/dlp.jsonl:{line}', user=event['proxy_user'], host=event['host'],
                    ts=event['ts'], label=event['label'], match_count=event['match_count'], blocked=event.get('blocked', True),
                    **({'evidence_origin': 'live'} if event.get('flow_id') else {}))

    def host_provider(self, host):
        host = host.lower().rstrip('.')
        for known in sorted(self.catalog['hosts'], key=len, reverse=True):
            if host == known or host.endswith('.' + known):
                return self.catalog['hosts'][known]
        if host == 'files.oaiusercontent.com' or host.endswith('.files.oaiusercontent.com'):
            return 'OpenAI'
        return None

    def collect_endpoint(self):
        profile_path = ROOT / 'endpoint' / 'endpoint_profile.yaml'
        if not profile_path.exists():
            return
        import yaml
        profile = yaml.safe_load(profile_path.read_text(encoding='utf-8'))
        user = profile['primary_user']
        if self.mode in ('replay', 'database'):
            events = self.read_events('endpoint.jsonl')
            for line, e in events:
                self.emit('Endpoint', e['signal_type'], e['runtime'].title(), f'logs/endpoint.jsonl:{line}', user=user, ts=e['ts'], runtime=e['runtime'], identity_source='endpoint_profile')
            return
        try:
            import psutil
            processes = [p.info for p in psutil.process_iter(['name', 'exe'])]
        except (ImportError, OSError):
            processes = []
            self.warnings.append('Endpoint process inventory unavailable; install psutil')
        for runtime, port in self.catalog['processes'].items():
            # Observe only process executables installed under the permitted root.
            matches = [p for p in processes if runtime in (p.get('name') or '').lower() and p.get('exe') and Path(p['exe']).resolve().is_relative_to(ROOT)]
            self.observe('Endpoint', f'endpoint/{runtime}', 'runtime_check')
            if matches:
                self.emit('Endpoint', 'ai_process', runtime.title(), f'endpoint/{runtime}', user=user, runtime=runtime, identity_source='endpoint_profile')
                if port_open(port):
                    self.emit('Endpoint', 'ai_port', runtime.title(), f'127.0.0.1:{port}', user=user, runtime=runtime, identity_source='endpoint_profile')
            model_root = ROOT / 'endpoint' / 'models'
            if model_root.exists() and (matches or runtime == profile.get('runtime', 'ollama')):
                for path in model_root.rglob('*'):
                    if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(model_root.resolve()) and (path.suffix in self.catalog['model_file_ext'] or path.name.startswith('sha256-')):
                        self.observe('Endpoint', str(path.relative_to(ROOT)), 'model_artifact')
                        self.emit('Endpoint', 'model_file', runtime.title(), str(path.relative_to(ROOT)), user=user, runtime=runtime, identity_source='endpoint_profile')
                        break

    def collect_mcp(self):
        for config in (ROOT / 'endpoint').rglob('*.json'):
            if config.name not in self.catalog['mcp_config_files'] or config.is_symlink() or not config.resolve().is_relative_to(ROOT / 'endpoint'):
                continue
            data = json.loads(config.read_text(encoding='utf-8'))
            for name, settings in data.get('mcpServers', {}).items():
                url = settings.get('url', '')
                self.observe('MCP', str(config.relative_to(ROOT)), 'mcp_configuration')
                # The non-AI documentation control is inspected but is not AI use.
                if settings.get('discovery_role') == 'non_ai_reference':
                    continue
                self.emit('MCP', 'mcp_config_server', f'{name} MCP', str(config.relative_to(ROOT)), user='ahmed', server=name, url=url)
                if self.mode == 'observed':
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    if parsed.hostname not in ('127.0.0.1', 'localhost') or not parsed.port or not port_open(parsed.port):
                        continue
                    import asyncio
                    try:
                        tools = asyncio.run(fetch_tools(url))
                        self.emit('MCP', 'mcp_server_running', f'{name} MCP', url, user='ahmed', server=name, url=url, tools=tools)
                    except Exception:
                        self.warnings.append(f'MCP tools/list unavailable: {name}')
        for line, event in self.read_events('mcp_runtime.jsonl') if self.mode in ('replay', 'database') else []:
            self.emit('MCP', 'mcp_server_running', f'{event["server"]} MCP', f'logs/mcp_runtime.jsonl:{line}', user='ahmed', server=event['server'], url=event['url'], tools=event['tools'], ts=event['ts'])
        groups = {}
        for line, event in self.read_events('mcp_audit.jsonl'):
            groups.setdefault(event['server'], []).append(event)
        for name, events in groups.items():
            self.emit('MCP', 'mcp_tool_calls', f'{name} MCP', 'logs/mcp_audit.jsonl', user=events[0]['caller'], count=len(events), ts=events[0]['ts'], last=events[-1]['ts'], server=name, url=f'http://127.0.0.1:{8765 if name == "creditdb" else 8766}/mcp')

    def collect_creditdb_live(self):
        repo = repository_root(ROOT) / 'creditdb-MCP'
        if not (repo / 'server.py').is_file():
            return
        url = 'http://127.0.0.1:8765/mcp'
        common = dict(entity='creditdb-MCP', server='creditdb', url=url,
                      evidence_origin='live', live_scenario='S5')
        self.observe('MCP', 'repos/creditdb-MCP/server.py', 'mcp_configuration')
        self.emit('MCP', 'mcp_config_server', 'creditdb MCP', 'repos/creditdb-MCP/server.py', **common)
        if port_open(8765):
            import asyncio
            try:
                tools = asyncio.run(fetch_tools(url))
                self.emit('MCP', 'mcp_server_running', 'creditdb MCP', url, tools=tools, **common)
            except Exception:
                self.warnings.append('MCP tools/list unavailable: creditdb-MCP')
        path = ROOT / 'logs/mcp_audit.jsonl'
        groups = {}
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    event = json.loads(line)
                    if event.get('server') != 'creditdb' or event.get('origin') in ('replay', 'seeded_demo'):
                        continue
                    datetime.fromisoformat(event['ts'])
                    groups.setdefault(event['caller'], []).append(event)
                except (ValueError, KeyError, TypeError):
                    self.warnings.append('Invalid CreditDB audit event skipped')
        for caller, events in groups.items():
            events.sort(key=lambda e: e['ts'])
            self.emit('MCP', 'mcp_tool_calls', 'creditdb MCP', 'live:logs/mcp_audit.jsonl',
                      user=caller, count=len(events), ts=events[0]['ts'], last=events[-1]['ts'], **common)

    def run(self):
        for name in ('repos', 'logs', 'endpoint', 'mcp'):
            try:
                getattr(self, 'collect_' + name)()
            except Exception as error:
                self.warnings.append(f'{name} collector failed ({type(error).__name__}); run incomplete')
        return self

async def fetch_tools(url):
    import asyncio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with asyncio.timeout(8):
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [{'name': t.name, 'write': bool(t.annotations and (t.annotations.destructiveHint or not t.annotations.readOnlyHint)) or t.name.startswith(('execute', 'update', 'delete', 'write'))} for t in result.tools]
