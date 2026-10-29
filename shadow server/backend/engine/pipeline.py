import json
import threading
import uuid
from collections import Counter
from engine.collectors.local import now
from engine.collectors.hybrid import HybridCollector
from engine.correlate import correlate
from engine.db import connection, decode, backend
from engine.detect import detect
from engine.reconcile import reconcile
from engine.inventory import apply_application_status
from engine.score import score
from engine.decide import decide
from engine.config import reference_snapshot
from engine.audit import append_audit
from engine.live_inputs import input_revision

RUN_LOCK = threading.RLock()

def recommendation(candidate):
    types = {s['signal_type'] for s in candidate['signals']}
    labels = {s['attributes'].get('label') for s in candidate['signals']}
    if 'Customer PII' in labels:
        return 'Investigate the blocked upload. Confirm no data escaped, notify the data owner and route future use through approved AI controls.'
    if any(t.get('write') for s in candidate['signals'] for t in s['attributes'].get('tools', [])):
        return 'Disable unrestricted execute_sql, enforce read-only roles and allowlisted queries, and register the agent with the datastore owner.'
    if types & {'credential_in_file', 'credential_in_history'}:
        return 'Revoke and rotate the exposed credential, remove it from repository history, enable secret scanning and adopt the approved AI gateway.'
    return 'Register the AI use with the department owner, review confidentiality controls and route API traffic through the approved gateway.'

def issue_for(candidate):
    return {'id': 'ISS-' + candidate['id'][2:], 'candidate_id': candidate['id'], 'title': candidate['name'],
            'owner': candidate['suggested_owner'], 'status': 'Open', 'resolution': None, 'created_at': now(),
            'recommended_action': recommendation(candidate), 'evidence_pack': candidate}

def run(mode=None, trigger=None):
    mode = mode or ('live' if backend() == 'postgresql' else 'replay')
    with RUN_LOCK, reference_snapshot():
        run_id = str(uuid.uuid4())
        revision = input_revision() if mode == 'live' else None
        # S1/S2/S5/S6/S7 always use application evidence, regardless of the other scenarios' mode.
        fixture_mode = ('database' if backend() == 'postgresql' else 'replay') if mode == 'hybrid' else mode
        collector = HybridCollector(run_id, fixture_mode).run()
        signals = detect(collector.matches)
        candidates = [decide(score(c)) for c in apply_application_status([reconcile(c) for c in correlate(signals)])]
        summary = {'id': run_id, 'timestamp': now(), 'mode': mode, 'items_scanned': len(collector.observations),
            'trigger': trigger or {'type': 'manual_discovery'},
            'signals': len(signals), 'candidates': len(candidates), 'issues': sum(c['decision'] == 'Raise issue' for c in candidates),
            'decisions': dict(Counter(c['decision'] for c in candidates)), 'warnings': collector.warnings,
            'collectors': dict(Counter(o['channel'] for o in collector.observations)),
            'storage': backend(), 'input_revision': revision, 'source': 'Actual repository code, Git credentials and recorded application invocations; no demo telemetry' if mode == 'live' else 'S1/S2/S5/S6/S7: actual application code and live invocation logs; other scenarios: ' + fixture_mode,
            'stages': {'collect': len(collector.observations), 'detect': len(signals), 'correlate': len(candidates), 'reconcile': len(candidates), 'score': len(candidates), 'decide': sum(c['decision'] == 'Raise issue' for c in candidates)}}
        with connection() as db:
            for evidence in getattr(collector, 'audit_events', {}).values():
                db.execute('INSERT INTO evidence_events(id,payload) VALUES(?,?) ON CONFLICT(id) DO NOTHING', (evidence['id'], json.dumps(evidence)))
            for o in collector.observations:
                db.execute('INSERT INTO observations(run_id,payload) VALUES(?,?)', (run_id, json.dumps(o)))
            for s in signals:
                db.execute('INSERT INTO signals(id,run_id,payload) VALUES(?,?,?)', (s['signal_id'], run_id, json.dumps(s)))
            # Candidate history is embedded in each issue evidence pack; current candidates reflect latest run.
            db.execute('DELETE FROM candidates')
            for c in candidates:
                c['run_id'] = run_id
                db.execute('INSERT INTO candidates(id,run_id,payload) VALUES(?,?,?)', (c['id'], run_id, json.dumps(c)))
                if c['decision'] == 'Raise issue':
                    issue = issue_for(c)
                    existing = db.execute('SELECT payload FROM issues WHERE candidate_id=?', (c['id'],)).fetchone()
                    if existing:
                        old = decode(existing[0])
                        for key in ('id', 'owner', 'status', 'resolution', 'created_at'):
                            issue[key] = old[key]
                    db.execute('INSERT INTO issues(id,candidate_id,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (issue['id'], c['id'], json.dumps(issue)))
            db.execute('INSERT INTO runs(id,payload) VALUES(?,?)', (run_id, json.dumps(summary)))
            append_audit(db, 'discovery_completed', run_id=run_id, mode=mode, trigger=summary['trigger'],
                         inventory_revision=candidates[0].get('inventory_revision') if candidates else None,
                         results=[{'candidate_id': c['id'], 'confidence': c['confidence'], 'risk': c['risk'], 'decision': c['decision']} for c in candidates])
        return summary
