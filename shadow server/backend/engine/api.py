import json
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import psycopg
from pydantic import BaseModel, Field
from typing import Literal
from engine.config import ROOT, reference
from engine.db import connection, list_payloads, decode, backend, status, document
from engine.pipeline import run, issue_for, RUN_LOCK

app = FastAPI(title='Shadow AI Discovery', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173'], allow_methods=['*'], allow_headers=['*'])
from engine.governance import router as governance_router
app.include_router(governance_router)
from engine.s3_demo import router as s3_demo_router
app.include_router(s3_demo_router)
from engine.analytics import router as analytics_router
app.include_router(analytics_router)

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16000)

@app.post('/ai/chat')
def chat(body: ChatRequest):
    provider = os.getenv('DOSSIER_PROVIDER', 'gemini').lower()
    key = 'MISTRAL_API_KEY' if provider == 'mistral' else 'GEMINI_API_KEY'
    if not (os.getenv(key) or (provider == 'gemini' and os.getenv('GOOGLE_API_KEY'))):
        raise HTTPException(503, f'Configure {key} in shadow server/backend/.env')
    from engine.llm import complete
    try:
        return {'provider': provider, 'content': complete(body.message)}
    except Exception:
        raise HTTPException(502, 'AI request failed. Check the backend key and model configuration.') from None

@app.exception_handler(psycopg.OperationalError)
def database_unavailable(request, error):
    return JSONResponse(status_code=503, content={'detail':'PostgreSQL is unavailable. Check the database service and local credential configuration.'})

class RunRequest(BaseModel):
    mode: Literal['live', 'hybrid', 'database', 'replay', 'observed'] | None = None

class IssueUpdate(BaseModel):
    status: Literal['Open', 'Investigating', 'Resolved'] | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=120)
    resolution: Literal['Registered', 'Remediated', 'False positive'] | None = None

def latest():
    runs = list_payloads('runs')
    return runs[-1] if runs else None

def find(table, id):
    result = next((x for x in list_payloads(table) if x['id'] == id), None)
    if not result:
        raise HTTPException(404, 'Record not found')
    return result

@app.get('/health')
def health():
    try:
        database = status()
    except Exception:
        raise HTTPException(503, 'PostgreSQL unavailable. Check the local service and database configuration.')
    return {'status': 'ok', 'root': str(ROOT), 'ui_built': (ROOT.parent / 'frontend/dist/index.html').exists(), 'database': database}

@app.post('/discovery/run')
def discovery(body: RunRequest = RunRequest()):
    return run(body.mode)

@app.get('/runs/latest')
def get_latest():
    return latest()


@app.post('/discovery/refresh')
def refresh_discovery():
    from engine.live_inputs import input_revision
    with RUN_LOCK:
        last = latest()
        if last and last.get('mode') == 'live' and last.get('input_revision') == input_revision():
            return {'changed': False, 'run_id': last['id']}
        result = run('live', trigger={'type': 'live_inputs_changed'})
        return {'changed': True, 'run_id': result['id']}

@app.get('/signals')
def signals(channel: str | None = None):
    last = latest()
    result = list_payloads('signals', last['id']) if last else []
    return [s for s in result if not channel or s['channel'] == channel]

@app.get('/candidates')
def candidates():
    return list_payloads('candidates')

@app.get('/candidates/{id}')
def candidate(id: str):
    return find('candidates', id)

@app.post('/candidates/{id}/issue')
def raise_issue(id: str):
    with RUN_LOCK:
        issue = issue_for(find('candidates', id))
        with connection() as db:
            old = db.execute('SELECT payload FROM issues WHERE candidate_id=?', (id,)).fetchone()
            if old:
                return decode(old[0])
            db.execute('INSERT INTO issues(id,candidate_id,payload) VALUES(?,?,?)', (issue['id'], id, json.dumps(issue)))
        return issue

@app.get('/issues')
def issues():
    return list_payloads('issues')

@app.get('/issues/{id}')
def issue(id: str):
    return find('issues', id)

@app.patch('/issues/{id}')
def update_issue(id: str, body: IssueUpdate):
    with RUN_LOCK:
        issue = find('issues', id)
        update = body.model_dump(exclude_none=True)
        target = update.get('status', issue['status'])
        allowed = {'Open': {'Open', 'Investigating'}, 'Investigating': {'Investigating', 'Resolved'}, 'Resolved': {'Resolved'}}
        if target not in allowed[issue['status']]:
            raise HTTPException(409, 'Follow Open → Investigating → Resolved')
        if target == 'Resolved' and not (update.get('resolution') or issue.get('resolution')):
            raise HTTPException(422, 'Select a resolution before resolving')
        if target != 'Resolved' and update.get('resolution'):
            raise HTTPException(422, 'Resolution applies only to Resolved issues')
        # Owner is free text, but must not become a secret/payload storage channel.
        import re
        if 'owner' in update and (re.search(r'sk-|ACC-\d|CONFIDENTIAL-INTERNAL', update['owner']) or not update['owner'].strip()):
            raise HTTPException(422, 'Owner must be a name or department')
        issue.update(update)
        with connection() as db:
            db.execute('UPDATE issues SET payload=? WHERE id=?', (json.dumps(issue), id))
        return issue

@app.get('/reference/{name}')
def get_reference(name: str):
    if backend() == 'postgresql':
        result = document('reference_documents', name)
        if result is None:
            raise HTTPException(404, 'Unknown reference')
        return result
    allowed = {p.name for p in (ROOT / 'reference').iterdir() if p.suffix in ('.yaml', '.csv')}
    if name not in allowed:
        raise HTTPException(404, 'Unknown reference')
    return reference(name)

@app.get('/reference-data')
def reference_data():
    # All business content is read from the same stored reference snapshot.
    from engine.config import reference_snapshot
    with reference_snapshot():
        rules = reference('rules.yaml')
        scoring = reference('scoring.yaml')
        result = dict(rules)
        result['decision_rules'] = [dict(row, condition=row['condition'].format_map(scoring['thresholds'])) for row in rules['decision_rules']]
        for group in ('confidence', 'risk'):
            result[group] = [dict(row, maximum=scoring[group][row['key']]['max'],
                description=row['description'].format_map(scoring[group][row['key']])) for row in rules[group]]
        result['inventory'] = reference('approved_ai_inventory.csv')
        result['repositories'] = reference('repo_register.csv')
        result['cmdb'] = reference('cmdb_applications.csv')
        result['users'] = reference('users.csv')
        result['devices'] = reference('devices.csv')
        result['signatures'] = reference('ai_signatures.yaml')
    return result

@app.post('/demo/baseline')
def demo_baseline():
    if backend() == 'postgresql':
        from engine.bootstrap import seed_telemetry
        with RUN_LOCK:
            seed_telemetry()
        return {'status': 'ready', 'mode': 'database'}
    from scenarios.demo import baseline
    # Avoid resetting an existing live demo accidentally.
    if (ROOT / 'logs/s7.state').exists():
        raise HTTPException(409, 'S7 already active; use setup/reset_demo.ps1 to reset')
    with RUN_LOCK:
        baseline()
    return {'status': 'ready', 'mode': 'replay'}

@app.post('/demo/live')
def demo_live():
    raise HTTPException(410, 'S7 now uses the Loan Risk Classifier application. Submit its form, then run discovery. Simulated S7 activity is retired.')

@app.get('/config')
def config():
    state = document('settings', 'demo_state') if backend() == 'postgresql' else None
    with connection() as db:
        names = [r[0] for r in db.execute('SELECT id FROM reference_documents ORDER BY id')] if backend() == 'postgresql' else sorted(p.name for p in (ROOT / 'reference').iterdir() if p.suffix in ('.yaml', '.csv'))
    return {'scan_root': str(ROOT), 'live_active': False,
        'references': names, 'database': status(), 'thresholds': reference('scoring.yaml')['thresholds'], 'default_mode': 'live' if backend() == 'postgresql' else 'replay'}

@app.get('/scenarios')
def scenarios():
    with RUN_LOCK:
        return scenario_results(list_payloads('candidates'), list_payloads('scenarios'))


def scenario_results(candidates, records):
    for item in records:
        if item['id'] == 'S5':
            matches = [c for c in candidates if c['entity'] == 'creditdb-MCP']
            result = max(matches, key=lambda c: c['confidence'], default=None)
            item.update(name='creditdb-MCP', entity='creditdb-MCP', provider='creditdb MCP',
                        title='CreditDB MCP database tools', channels=['MCP'],
                        description='Live MCP configuration, exposed read/write tools and actual audit calls from repo server/creditdb-MCP.',
                        source='live', expected_confidence=None, expected_risk=None, expected_decision='Not scanned',
                        candidate_ids=[c['id'] for c in matches])
            item['result'] = {key: result.get(key) for key in ('id','confidence','risk','decision','decision_explanation','inventory')} if result else None
            continue
        if item['id'] == 'S2':
            matches = [c for c in candidates if c['entity'] == 'policy-intelligence']
            matches.sort(key=lambda c: (c['decision'] == 'Raise issue', any(s['attributes'].get('live_scenario') == 'S2' and s['attributes'].get('evidence_origin') == 'live_sdk' for s in c['signals']), c['risk'], max((s['ts_last'] for s in c['signals']), default='')), reverse=True)
            result = matches[0] if matches else None
            item.update(title='Policy Intelligence company loan review', name='policy-intelligence / ' + (result['provider'] if result else 'OpenAI / Mistral / Gemini'),
                        entity='policy-intelligence', provider=result['provider'] if result else 'OpenAI', channels=['Code', 'Secret', 'Network'],
                        description='Company loan form checked against the sample bank policy. OpenAI, Mistral and Gemini explanation attempts are recorded as live SDK metadata. Historical credentials remain separate from runtime usage.',
                        source='live', expected_confidence=None, expected_risk=None, expected_decision='Not scanned',
                        candidate_ids=[c['id'] for c in matches])
            item['result'] = {key: result.get(key) for key in ('id','confidence','risk','decision','decision_explanation','inventory')} if result else None
            continue
        if item['id'] == 'S7':
            matches = [c for c in candidates if c['entity'] == 'loan-risk-classifier']
            matches.sort(key=lambda c: any(s['signal_type'] == 'local_model_call' for s in c['signals']), reverse=True)
            result = matches[0] if matches else None
            item.update(title='Loan Risk Classifier with local Ollama', name='loan-risk-classifier / Ollama',
                        entity='loan-risk-classifier', provider='Ollama', channels=['Code', 'Endpoint'],
                        description='Actual loan application code and recorded local Ollama inference attempts. No simulated network, DLP or endpoint evidence.',
                        source='live', expected_confidence=None, expected_risk=None, expected_decision='Not scanned',
                        candidate_ids=[c['id'] for c in matches])
            item['result'] = {key: result.get(key) for key in ('id','confidence','risk','decision','decision_explanation','inventory')} if result else None
            continue
        if item['id'] == 'S6':
            matches = [c for c in candidates if c['entity'] == 'customer-assistant']
            matches.sort(key=lambda c: (c['decision'] == 'Raise issue', any(s['attributes'].get('live_scenario') == 'S6' for s in c['signals']),
                                       max(s['ts_last'] for s in c['signals']), c['provider'] == 'Google'), reverse=True)
            result = matches[0] if matches else None
            item['candidate_ids'] = [c['id'] for c in matches]
            item.update(name='customer-assistant → ' + (result['provider'] if result else 'Gemini / Mistral / OpenAI'),
                        source='live', expected_confidence=None, expected_risk=None, expected_decision='Not scanned')
            item['result'] = {key: result.get(key) for key in
                             ('id','confidence','risk','decision','decision_explanation','inventory')} if result else None
            continue
        if item['id'] == 'S1':
            matches = [c for c in candidates if c['entity'] == 'credit-dossier']
            item['candidate_ids'] = [c['id'] for c in matches]
            preferred = 'Google' if os.getenv('DOSSIER_PROVIDER', 'gemini') == 'gemini' else 'Mistral'
            matches.sort(key=lambda c: (any(s['channel'] == 'Gateway' for s in c['signals']), c['provider'] == preferred, c['confidence']), reverse=True)
            result = matches[0] if matches else None
            item.update(name='credit-dossier → ' + (result['provider'] if result else preferred),
                        description='Actual credit-dossier code and live gateway, SDK or proxy invocation metadata. No simulated runtime evidence. S2, S6 and S7 also use their actual applications; other scenarios retain demo fixtures.',
                        expected_confidence=None, expected_risk=None, expected_decision='Not scanned', source='live')
            item['result'] = {key: result.get(key) for key in ('id','confidence','risk','decision','decision_explanation','inventory')} if result else None
            continue
        if item['id'] == 'S4':
            item.update(name='Local Ollama runtime (demo)', title='Local Ollama runtime (demo)')
        item['source'] = 'demo'
        matches = [c for c in candidates if c['provider'] == item['provider'] and
            (item['id'] != 'S4' or not c['entity']) and
            (not item.get('entity') or c['entity'] == item['entity']) and
            (not item.get('user_id') or c['user_id'] == item['user_id'])]
        item['candidate_ids'] = [c['id'] for c in matches]
        result = matches[0] if matches else None
        item['result'] = {key: result.get(key) for key in ('id','confidence','risk','decision','decision_explanation','inventory')} if result else None
    # Every card is derived from the same current candidate objects. Catalogue
    # expectations describe fixtures and must never appear as observed results.
    by_id = {candidate['id']: candidate for candidate in candidates}
    for item in records:
        matches = [by_id[key] for key in item.get('candidate_ids', []) if key in by_id]
        matches.sort(key=lambda candidate: (
            candidate['decision'] == 'Raise issue', candidate['risk'], candidate['confidence'],
            max((signal.get('ts_last', '') for signal in candidate['signals']), default=''), candidate['id']), reverse=True)
        result = matches[0] if matches else None
        item['candidate_ids'] = [candidate['id'] for candidate in matches]
        item['result'] = {key: result.get(key) for key in
                          ('id', 'run_id', 'provider', 'confidence', 'risk', 'decision', 'decision_explanation', 'inventory')} if result else None
        item['channels'] = sorted({channel for candidate in matches for channel in candidate.get('channels', [])})
        if result:
            item['provider'] = result['provider']
        for key in ('expected_decision', 'expected_confidence', 'expected_risk'):
            item.pop(key, None)
    return records


@app.get('/discovery/state')
def dashboard_state():
    # Discovery replaces candidates inside RUN_LOCK; hold it until all related
    # views have been read so a response cannot mix two discovery runs.
    with RUN_LOCK:
        current = latest()
        current_candidates = list_payloads('candidates')
        return {'latest': current, 'candidates': current_candidates,
                'signals': list_payloads('signals', current['id']) if current else [],
                'issues': list_payloads('issues'), 'config': config(),
                'scenarios': scenario_results(current_candidates, list_payloads('scenarios')),
                'references': reference_data()}

