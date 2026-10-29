"""Append-only application audit records and metadata-only evidence snapshots."""
from datetime import datetime, timezone
import getpass
import hashlib
import json
import uuid
from engine.db import backend, decode


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def revision(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def operator():
    return {'name': getpass.getuser(), 'source': 'local_server_os_account'}


def append_audit(db, event_type, **details):
    order = 'sequence' if backend() == 'postgresql' else 'rowid'
    row = db.execute(f'SELECT payload FROM audit_events ORDER BY {order} DESC LIMIT 1').fetchone()
    previous = decode(row[0])['hash'] if row else None
    event = {'id': 'AUD-' + str(uuid.uuid4()), 'recorded_at': datetime.now(timezone.utc).isoformat(),
             'event_type': event_type, 'actor': operator(), 'previous_hash': previous, **details}
    event['hash'] = revision(event)
    db.execute('INSERT INTO audit_events(id,payload) VALUES(?,?)', (event['id'], canonical(event)))
    return event


def verify_chain(events):
    previous = None
    for event in events:
        body = {key: value for key, value in event.items() if key != 'hash'}
        if event['previous_hash'] != previous or revision(body) != event['hash']:
            return False
        previous = event['hash']
    return True


def gateway_snapshot(event, raw_line, line_number):
    allowed = ('request_id', 'ts', 'app', 'provider', 'model', 'status', 'tokens', 'origin', 'schema_version')
    payload = {key: event[key] for key in allowed if key in event}
    digest = hashlib.sha256(raw_line.encode('utf-8')).hexdigest()
    return {'id': 'EVT-' + digest, **payload, 'source_file': 'logs/gateway.jsonl',
            'source_line': line_number, 'source_sha256': digest}


def gateway_snapshots(root):
    path = root / 'logs/gateway.jsonl'
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        try:
            event = json.loads(line)
            if isinstance(event, dict) and event.get('origin') == 'live' and event.get('request_id'):
                events.append(gateway_snapshot(event, line, number))
        except (ValueError, TypeError):
            continue
    return events
