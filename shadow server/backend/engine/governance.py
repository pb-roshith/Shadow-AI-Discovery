"""Versioned registry editing, automatic discovery and auditable evidence APIs."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from engine import config
from engine.audit import append_audit, canonical, gateway_snapshots, operator, revision, verify_chain
from engine.db import backend, connection, decode, list_payloads
from engine.pipeline import RUN_LOCK, run
from engine.inventory import global_entries, tool_key

router = APIRouter()
DOCUMENT = 'approved_ai_inventory.csv'


class InventoryEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    inv_id: str = Field(min_length=1, max_length=100)
    asset: str = Field(min_length=1, max_length=200)
    tool_name: str = Field(default='', max_length=200)
    match_type: Literal['app', 'host', 'tool']
    match_value: str = Field(min_length=1, max_length=250)
    provider: str = Field(min_length=1, max_length=100)
    required_route: Literal['gateway', 'direct', 'any', 'n/a']
    status: Literal['Approved', 'Restricted', 'Revoked'] = 'Approved'
    owner: str = Field(min_length=1, max_length=200)


class InventoryUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    entries: list[InventoryEntry] = Field(max_length=500)
    expected_revision: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=3, max_length=1000)


@router.get('/inventory')
def inventory():
    entries = config.reference(DOCUMENT)
    return {'entries': entries, 'revision': revision(entries), 'operator': operator()}


@router.put('/inventory')
def update_inventory(body: InventoryUpdate):
    entries = [item.model_dump(exclude={'tool_name'} if 'tool_name' not in item.model_fields_set else set()) for item in body.entries]
    if len({item['inv_id'] for item in entries}) != len(entries):
        raise HTTPException(422, 'Inventory IDs must be unique.')
    scopes = [tool_key(item) for item in entries]
    if len(set(scopes)) != len(scopes):
        raise HTTPException(422, 'Each AI tool must have one global registry entry.')
    entries = global_entries(entries)
    with RUN_LOCK:
        with connection() as db:
            db.execute('INSERT INTO reference_documents(id,payload) VALUES(?,?) ON CONFLICT(id) DO NOTHING', (DOCUMENT, canonical(config.reference_file(DOCUMENT))))
            suffix = ' FOR UPDATE' if backend() == 'postgresql' else ''
            before = decode(db.execute('SELECT payload FROM reference_documents WHERE id=?' + suffix, (DOCUMENT,)).fetchone()[0])
            if revision(before) != body.expected_revision:
                raise HTTPException(409, 'The registry changed. Reload it before saving your edit.')
            if before == entries:
                raise HTTPException(400, 'No registry changes to save.')
            old = {item['inv_id']: item for item in before}
            new = {item['inv_id']: item for item in entries}
            changes = [{'inv_id': key, 'action': 'added' if key not in old else 'removed' if key not in new else 'updated',
                        'before': old.get(key), 'after': new.get(key)} for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]
            db.execute('UPDATE reference_documents SET payload=? WHERE id=?', (canonical(entries), DOCUMENT))
            event = append_audit(db, 'inventory_changed', reason=body.reason.strip(), before=before, after=entries,
                                 previous_revision=revision(before), revision=revision(entries), changes=changes)
        # The committed registry is captured in a fresh reference snapshot by this run.
        try:
            discovery = run('live' if backend() == 'postgresql' else 'hybrid', trigger={'type': 'inventory_changed', 'audit_id': event['id']})
        except Exception:
            with connection() as db:
                append_audit(db, 'discovery_failed', trigger={'type': 'inventory_changed', 'audit_id': event['id']})
            return {'saved': True, 'revision': revision(entries), 'audit_id': event['id'], 'discovery': None,
                    'discovery_error': 'Registry saved and audited, but discovery failed. Run discovery again to refresh scores.'}
    return {'saved': True, 'revision': revision(entries), 'audit_id': event['id'], 'discovery': discovery}


@router.get('/audit/events')
def audit_events(limit: int = Query(100, ge=1, le=500)):
    events = list_payloads('audit_events')
    return {'events': list(reversed(events[-limit:])), 'total': len(events), 'chain_verified': verify_chain(events)}


def requests_from(events):
    groups = {}
    for event in sorted(events, key=lambda item: item.get('ts', '')):
        groups.setdefault(event['request_id'], []).append(event)
    result = []
    for request_id, stages in groups.items():
        selected = stages[0]
        for stage in stages[1:]:
            if stage.get('status') != 'pending' or selected.get('status') not in ('success', 'failed'):
                selected = stage
        result.append({'request_id': request_id, 'app': selected.get('app'), 'provider': selected.get('provider'),
                       'model': selected.get('model'), 'status': selected.get('status'), 'ts': selected.get('ts'),
                       'tokens': selected.get('tokens', 0), 'stages': stages})
    return result


@router.get('/audit/gateway')
def gateway_audit(app: str | None = None, request_id: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    events = {item['id']: item for item in list_payloads('evidence_events')}
    events.update({item['id']: item for item in gateway_snapshots(config.ROOT)})
    selected = [event for event in events.values() if event.get('source_file') == 'logs/gateway.jsonl' and (not app or event.get('app') == app) and (not request_id or event.get('request_id') == request_id)]
    requests = sorted(requests_from(selected), key=lambda item: item.get('ts', ''), reverse=True)
    return {'requests': requests[offset:offset + limit], 'total_invocations': len(requests), 'total_log_records': len(selected),
            'outcomes': {status: sum(item['status'] == status for item in requests) for status in ('success', 'failed', 'pending')}}


def signal_bundle(signal):
    attrs = signal['attributes']
    ids = attrs.get('audit_event_ids', [])
    with connection() as db:
        records = []
        for event_id in ids:
            row = db.execute('SELECT payload FROM evidence_events WHERE id=?', (event_id,)).fetchone()
            if row:
                records.append(decode(row[0]))
    requests = requests_from(records)
    outcomes = {status: sum(item['status'] == status for item in requests) for status in ('success', 'failed', 'pending')}
    live_gateway = (signal['channel'] == 'Gateway' and attrs.get('evidence_origin') == 'live') or (signal['signal_type'] == 'local_model_call' and attrs.get('evidence_origin') == 'live_local')
    verified = (len(requests) == signal['event_count'] and set(attrs.get('request_ids', [])) == {r['request_id'] for r in requests}
                and outcomes == {status: attrs.get('outcomes', {}).get(status, 0) for status in ('success', 'failed', 'pending')}
                and len(records) == len(ids)) if live_gateway else None
    return {'signal': signal, 'requests': requests, 'outcomes': outcomes, 'verified': verified,
            'expected_count': signal['event_count'], 'verified_count': len(requests),
            'code_proof': {'file_sha256': attrs.get('file_sha256'), 'line_numbers': attrs.get('line_numbers', []), 'source_ref': signal['source_ref']} if signal['channel'] == 'Code' else None,
            'provenance': attrs.get('evidence_origin', 'static_fixture' if signal['source_ref'].startswith('postgresql:') else 'source_snapshot')}


@router.get('/signals/{signal_id}/audit')
def signal_audit(signal_id: str):
    with connection() as db:
        row = db.execute('SELECT payload FROM signals WHERE id=?', (signal_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Signal not found.')
    return signal_bundle(decode(row[0]))


@router.get('/candidates/{candidate_id}/audit')
def candidate_audit(candidate_id: str):
    with connection() as db:
        row = db.execute('SELECT payload FROM candidates WHERE id=?', (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Candidate not found.')
    candidate = decode(row[0])
    return {'candidate_id': candidate_id, 'run_id': candidate['run_id'], 'inventory_revision': candidate.get('inventory_revision'),
            'inventory_snapshot': candidate.get('inventory_snapshot', []), 'signals': [signal_bundle(s) for s in candidate['signals']]}
