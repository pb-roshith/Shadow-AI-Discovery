"""Idempotent initialization and migration into the dedicated application DB."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from engine.config import ROOT, reference_file
from engine.db import connection, connection_parameters, document, decode, backend
from engine.inventory import global_entries
from engine.audit import append_audit, revision

def create_database():
    import psycopg
    from psycopg import sql
    name = os.environ.get('SHADOWAI_DB_NAME', 'shadow_ai_discovery')
    with psycopg.connect(**connection_parameters('postgres'), autocommit=True) as db:
        if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))

def seed_documents():
    with connection() as db:
        for path in sorted((ROOT / 'reference').iterdir()):
            if path.suffix in ('.csv', '.yaml'):
                db.execute('INSERT INTO reference_documents(id,payload) VALUES(?,?) ON CONFLICT(id) DO NOTHING', (path.name, json.dumps(reference_file(path.name))))
        row = db.execute('SELECT payload FROM reference_documents WHERE id=?', ('approved_ai_inventory.csv',)).fetchone()
        if row:
            before = decode(row[0])
            after = global_entries(before)
            if before != after:
                db.execute('UPDATE reference_documents SET payload=? WHERE id=?', (json.dumps(after), 'approved_ai_inventory.csv'))
                append_audit(db, 'inventory_changed', reason='Migrate tool approvals to global scope across every repository; stricter status retained for legacy conflicts.',
                             before=before, after=after, previous_revision=revision(before), revision=revision(after))
        catalogue = json.loads((ROOT / 'scenarios/catalogue.json').read_text(encoding='utf-8'))
        for item in catalogue:
            db.execute('INSERT INTO scenarios(id,payload) VALUES(?,?) ON CONFLICT(id) DO NOTHING', (item['id'], json.dumps(item)))
            if item['id'] in ('S2', 'S4', 'S6', 'S7'):
                db.execute('UPDATE scenarios SET payload=? WHERE id=?', (json.dumps(item), item['id']))
        row = db.execute('SELECT payload FROM reference_documents WHERE id=?', ('repo_register.csv',)).fetchone()
        if row:
            register = decode(row[0])
            if any(item['repo'] in ('readme-only', 'loan-ops-helper') for item in register):
                for item in register:
                    if item['repo'] == 'loan-ops-helper':
                        item['repo'] = 'policy-intelligence'
                    if item['repo'] == 'readme-only':
                        item['repo'] = 'customer-assistant'
                        item['service_account'] = 'customer-assistant-svc'
                db.execute('UPDATE reference_documents SET payload=? WHERE id=?', (json.dumps(register), 'repo_register.csv'))
        row = db.execute('SELECT payload FROM reference_documents WHERE id=?', ('users.csv',)).fetchone()
        if row:
            users = decode(row[0])
            if not any(item['user_id'] == 'customer-assistant-svc' for item in users):
                users.append({'user_id': 'customer-assistant-svc', 'display_name': 'Customer Assistant service',
                              'department': 'Operations', 'dept_criticality': 'Low', 'type': 'service'})
                db.execute('UPDATE reference_documents SET payload=? WHERE id=?', (json.dumps(users), 'users.csv'))
        row = db.execute('SELECT payload FROM reference_documents WHERE id=?', ('rules.yaml',)).fetchone()
        if row:
            rules = decode(row[0])
            note = reference_file('rules.yaml')['inventory_note']
            updated_rules = reference_file('rules.yaml')
            needs_rule = rules['decision_rules'] != updated_rules['decision_rules']
            control_rule = next(rule for rule in updated_rules['risk'] if rule['key'] == 'control')
            needs_control = any(rule['key'] == 'control' and rule != control_rule for rule in rules['risk'])
            migrate_joins = 'Anthropic use (S7)' in rules.get('over_merge_guard', '')
            if rules.get('inventory_note') != note or needs_rule or needs_control or migrate_joins:
                if migrate_joins:
                    updated_rules = reference_file('rules.yaml')
                    rules['over_merge_guard'] = updated_rules['over_merge_guard']
                    for join in rules['join_rules']:
                        join['used_in'] = next((r['used_in'] for r in updated_rules['join_rules'] if r['id'] == join['id']), join.get('used_in', ''))
                rules['inventory_note'] = note
                if needs_rule:
                    rules['decision_rules'] = updated_rules['decision_rules']
                if needs_control:
                    rules['risk'] = [control_rule if rule['key'] == 'control' else rule for rule in rules['risk']]
                db.execute('UPDATE reference_documents SET payload=? WHERE id=?', (json.dumps(rules), 'rules.yaml'))

def migrate_sqlite():
    source = ROOT / 'data/discovery.sqlite'
    if not source.exists() or document('settings', 'sqlite_migrated'):
        return
    legacy = sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True)
    try:
        with connection() as db:
            for table, columns in [('runs','id,payload'), ('signals','id,run_id,payload'), ('candidates','id,run_id,payload'), ('issues','id,candidate_id,payload')]:
                for row in legacy.execute(f'SELECT {columns} FROM {table} ORDER BY rowid'):
                    marks = ','.join('?' for _ in row)
                    db.execute(f'INSERT INTO {table}({columns}) VALUES({marks}) ON CONFLICT DO NOTHING', row)
            for row in legacy.execute('SELECT run_id,payload FROM observations ORDER BY id'):
                db.execute('INSERT INTO observations(run_id,payload) VALUES(?,?)', row)
            db.execute('INSERT INTO settings(id,payload) VALUES(?,?) ON CONFLICT(id) DO NOTHING', ('sqlite_migrated', json.dumps({'completed':True})))
    finally:
        legacy.close()

def seed_telemetry():
    if document('settings', 'demo_state'):
        return
    from scenarios.demo import baseline
    if not (ROOT / 'logs/replay.state').exists():
        baseline()
    with connection() as db:
        for path in sorted((ROOT / 'logs').glob('*.jsonl')):
            for index, line in enumerate(path.read_text(encoding='utf-8').splitlines()):
                event = json.loads(line)
                if event.get('app') in ('credit-dossier', 'customer-assistant') or event.get('proxy_user') in ('gateway-svc', 'customer-assistant-svc'):
                    continue
                if event.get('origin') != 'replay':
                    continue
                event['origin'] = 'seeded_demo'
                event_id = f'baseline-{path.stem}-{index:06d}'
                db.execute('INSERT INTO telemetry_events(id,stream,payload) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING', (event_id, path.name, json.dumps(event)))
        state = {'prepared': True, 's7_active': (ROOT / 'logs/s7.state').exists(), 'source': 'seeded_demo'}
        db.execute('INSERT INTO settings(id,payload) VALUES(?,?) ON CONFLICT(id) DO NOTHING', ('demo_state', json.dumps(state)))

def simulate_live():
    if ROOT.resolve() == Path(__file__).resolve().parents[1]:
        raise ValueError('S7 simulation is retired. Use the Loan Risk Classifier application.')
    from scenarios.demo import repository
    repository('ahmed-scratch', {'test_claude.py': 'import anthropic\n\nclient = anthropic.Anthropic()\n'})
    with connection() as db:
        # Lock the state row for concurrent, idempotent S7 requests.
        row = db.execute('SELECT payload FROM settings WHERE id=?' + (' FOR UPDATE' if backend() == 'postgresql' else ''), ('demo_state',)).fetchone()
        if not row:
            raise ValueError('Initialize the database demo first')
        state = decode(row[0])
        if state.get('s7_active'):
            return
        ts = datetime.now(timezone.utc).isoformat()
        for index in range(5):
            event = dict(ts=ts, proxy_user='ahmed', host='api.anthropic.com', method='POST', path_class='api', bytes_out=80,
                status=403 if index == 4 else 401, origin='seeded_demo')
            db.execute('INSERT INTO telemetry_events(id,stream,payload) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING', (f's7-proxy-{index}', 'proxy.jsonl', json.dumps(event)))
        event = dict(ts=ts, proxy_user='ahmed', host='api.anthropic.com', label='Confidential', match_count=1, bytes=80, origin='seeded_demo')
        db.execute('INSERT INTO telemetry_events(id,stream,payload) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING', ('s7-dlp-0','dlp.jsonl',json.dumps(event)))
        state['s7_active'] = True
        db.execute('UPDATE settings SET payload=? WHERE id=?', (json.dumps(state),'demo_state'))

def initialize():
    create_database()
    seed_documents()
    migrate_sqlite()
    seed_telemetry()
    print('PostgreSQL application database initialized; existing records preserved.')

def reset_demo_results():
    """Only explicit demo reset calls this; reference edits and custom events survive."""
    with connection() as db:
        for table in ('issues','candidates','signals','observations','runs'):
            db.execute(f'DELETE FROM {table}')
        db.execute("DELETE FROM telemetry_events WHERE payload->>'origin' = ?", ('seeded_demo',))
        db.execute('DELETE FROM settings WHERE id=?', ('demo_state',))

if __name__ == '__main__':
    initialize()
