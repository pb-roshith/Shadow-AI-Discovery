"""Deterministic, offline telemetry replay. No external requests or real secrets."""
import argparse
import json
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.config import repository_root

def commit(repo, message):
    for args in (['add', '.'], ['-c', 'user.name=ahmed' if repo.name == 'ahmed-scratch' else 'user.name=Demo', '-c', 'user.email=demo@example.invalid', 'commit', '-m', message]):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)

def repository(name, files):
    path = repository_root(ROOT) / name
    if (path / '.git').exists():
        return path, False
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', str(path)], check=True, capture_output=True)
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    commit(path, 'Initial demo code')
    return path, True

def seed_repos():
    # Synthetic application repositories exist only in isolated test roots.
    if ROOT.resolve() != Path(__file__).resolve().parents[1]:
        repo, new = repository('credit-dossier', {
            'requirements.txt': 'mistralai\nhttpx\n',
            'dossier/llm.py': 'import mistralai\nimport httpx\n\ndef summarise(text):\n    return httpx.post("http://127.0.0.1:4000/v1/chat/completions", headers={"x-app-id": "credit-dossier"}, json={"model":"mistral-small", "messages":[{"role":"user","content":text}]})\n',
        })
        if new:
            (repo / 'config').mkdir(exist_ok=True)
            (repo / 'config/gateway.yaml').write_text('model: mistral-small\n')
            commit(repo, 'Configure approved gateway')
            (repo / 'README.md').write_text('Credit dossier demo application.\n')
            commit(repo, 'Document demo app')
    repo, new = repository('policy-intelligence', {'requirements.txt': 'openai\n', 'helper/summarise.py': 'from openai import OpenAI\n\ndef summarise(text):\n    return OpenAI().chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":text}])\n'})
    if new:
        (repo / '.env').write_text('OPENAI_API_KEY=sk-proj-DEMO' + '0123456789abcdef' * 3 + '\n')
        commit(repo, 'Accidentally add fake DEMO credential')
        (repo / '.env').unlink()
        (repo / '.gitignore').write_text('.env\n')
        commit(repo, 'Remove credential from working tree')
    if ROOT.resolve() != Path(__file__).resolve().parents[1]:
        repository('customer-assistant', {'requirements.txt': 'google-genai\nmistralai\nopenai\n',
            'README.md': 'Customer chatbot using google-genai, mistralai and OpenAI SDKs.\n',
            'assistant_llm.py': 'from google import genai\nfrom mistralai.client import Mistral\nfrom openai import OpenAI\n'})
    if ROOT.resolve() != Path(__file__).resolve().parents[1]:
        repository('non-ai-csv', {'report.py': 'import csv\n\ndef rows(stream):\n    return list(csv.DictReader(stream))\n'})


def write_log(name, events):
    path = ROOT / 'logs' / (name + '.jsonl')
    path.parent.mkdir(exist_ok=True)
    retained = []
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                if json.loads(line).get('origin') not in ('replay', 'seeded_demo'):
                    retained.append(line + '\n')
            except (ValueError, AttributeError):
                retained.append(line + '\n')
    path.write_text(''.join(retained) + ''.join(json.dumps({**e, 'origin': 'replay'}) + '\n' for e in events), encoding='utf-8')

def baseline():
    seed_repos()
    (ROOT / 'endpoint/ahmed/.vscode').mkdir(parents=True, exist_ok=True)
    (ROOT / 'endpoint/endpoint_profile.yaml').write_text('device_label: AVD-ANL-03\nprimary_user: ahmed\n')
    (ROOT / 'endpoint/ahmed/.vscode/mcp.json').write_text(json.dumps({'mcpServers': {'creditdb': {'url': 'http://127.0.0.1:8765/mcp'}, 'docs': {'url': 'http://127.0.0.1:8766/mcp', 'discovery_role': 'non_ai_reference'}}}, indent=2))
    ts = datetime.now(timezone.utc).isoformat()
    proxy = [dict(ts=ts, proxy_user=('app-svc', 'priya', 'ahmed', 'dev-svc')[i % 4], host=('example.com', 'microsoft.com', 'wikipedia.org')[i % 3], method='GET', path_class='web', bytes_out=0, status=200) for i in range(200)]
    proxy += [dict(ts=ts, proxy_user='gateway-svc', host='api.mistral.ai', method='POST', path_class='api', bytes_out=120, status=401) for _ in range(20)] if ROOT.resolve() != Path(__file__).resolve().parents[1] else []
    proxy += [dict(ts=ts, proxy_user='dev-svc', host='api.openai.com', method='POST', path_class='api', bytes_out=100, status=401) for _ in range(12)] if ROOT.resolve() != Path(__file__).resolve().parents[1] else []
    proxy += [dict(ts=ts, proxy_user='priya', host='chatgpt.com', method='POST', path_class='upload', bytes_out=400, status=403)]
    write_log('proxy', proxy)
    write_log('gateway', [dict(ts=ts, app='credit-dossier', model='mistral-small', provider='Mistral', tokens=0, status='failed') for _ in range(20)] if ROOT.resolve() != Path(__file__).resolve().parents[1] else [])
    write_log('dlp', [dict(ts=ts, proxy_user='priya', host='chatgpt.com', label='Customer PII', match_count=14, bytes=400)])
    write_log('endpoint', [dict(ts=ts, signal_type=kind, runtime='ollama') for kind in ('ai_process', 'ai_port', 'model_file')])
    write_log('mcp_runtime', [dict(ts=ts, server='creditdb', url='http://127.0.0.1:8765/mcp', tools=[{'name':'query_loans', 'write':False}, {'name':'execute_sql', 'write':True}])])
    write_log('mcp_audit', [dict(ts=ts, server='creditdb', tool=tool, caller='risk-agent') for tool in ('query_loans', 'execute_sql')])
    (ROOT / 'logs/replay.state').write_text('baseline')

def live():
    if ROOT.resolve() == Path(__file__).resolve().parents[1]:
        raise ValueError('S7 simulation is retired. Use the Loan Risk Classifier application.')
    repository('ahmed-scratch', {'test_claude.py': 'import anthropic\n\nclient = anthropic.Anthropic()\n'})
    marker = ROOT / 'logs/s7.state'
    if marker.exists():
        return
    ts = datetime.now(timezone.utc).isoformat()
    for name, events in [('proxy', [dict(ts=ts, proxy_user='ahmed', host='api.anthropic.com', method='POST', path_class='api', bytes_out=80, status=403 if i == 4 else 401) for i in range(5)]), ('dlp', [dict(ts=ts, proxy_user='ahmed', host='api.anthropic.com', label='Confidential', match_count=1, bytes=80)])]:
        with (ROOT / 'logs' / (name + '.jsonl')).open('a', encoding='utf-8') as stream:
            for event in events:
                stream.write(json.dumps({**event, 'origin':'replay'}) + '\n')
    marker.write_text('active')

def reset():
    import shutil
    for name in ('logs', 'data', 'repos/ahmed-scratch'):
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or path == ROOT:
            raise ValueError('Unsafe reset target')
        if path.exists():
            def writable(function, path, exc):
                import os, stat
                os.chmod(path, stat.S_IWRITE)
                function(path)
            shutil.rmtree(path, onexc=writable)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['baseline', 'live', 'reset'])
    action = parser.parse_args().action
    globals()[action]()
    print(f'Demo {action} complete (offline replay).')
