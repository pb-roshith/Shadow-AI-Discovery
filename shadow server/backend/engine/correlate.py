import hashlib
from datetime import datetime
from itertools import combinations

JOIN_DESCRIPTIONS = {
 'J1': 'Same entity and provider (documentation alone is excluded)',
 'J2': 'Same credential fingerprint',
 'J3': 'Executable repo evidence and network identity share account and provider',
 'J4': 'Network and DLP share user, host and a two-minute window',
 'J5': 'Same endpoint device and runtime family',
 'J6': 'Same MCP server identity and canonical local endpoint',
}

def correlate(signals):
    parents = list(range(len(signals)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    edges = []
    for i, j in combinations(range(len(signals)), 2):
        a, b = signals[i], signals[j]
        types = {a['signal_type'], b['signal_type']}
        rule = None
        if a['entity'] and a['entity'] == b['entity'] and a['provider'] == b['provider'] and 'doc_mention' not in types:
            rule = 'J1'
        if a.get('fingerprint') and a['fingerprint'] == b.get('fingerprint'):
            rule = 'J2'
        repo, network = (a, b) if a['channel'] in ('Code', 'Secret') else (b, a)
        if repo['channel'] in ('Code', 'Secret') and repo['signal_type'] != 'doc_mention' and network['signal_type'] == 'ai_network_call' and repo['user_id'] and repo['user_id'] == network['user_id'] and repo['provider'] == network['provider']:
            rule = 'J3'
        if types == {'ai_network_call', 'dlp_label'} and a['user_id'] == b['user_id'] and a['host'] == b['host']:
            gap = (max(datetime.fromisoformat(a['ts_first']), datetime.fromisoformat(b['ts_first'])) - min(datetime.fromisoformat(a['ts_last']), datetime.fromisoformat(b['ts_last']))).total_seconds()
            if gap <= 120:
                rule = 'J4'
        if a['channel'] == b['channel'] == 'Endpoint' and a['device_label'] and a['device_label'] == b['device_label'] and a['attributes'].get('runtime') == b['attributes'].get('runtime') and a['entity'] == b['entity']:
            rule = 'J5'
        if a['channel'] == b['channel'] == 'MCP' and a['attributes'].get('server') == b['attributes'].get('server') and a['attributes'].get('url') == b['attributes'].get('url'):
            rule = 'J6'
        if rule:
            parents[find(j)] = find(i)
            edges.append({'from': a['signal_id'], 'to': b['signal_id'], 'rule': rule, 'reason': JOIN_DESCRIPTIONS[rule]})
    groups = {}
    for i, signal in enumerate(signals):
        groups.setdefault(find(i), []).append(signal)
    candidates = []
    for group in groups.values():
        entities = sorted({s['entity'] for s in group if s['entity']})
        provider = group[0]['provider']
        entity = entities[0] if entities else ''
        user = next((s['user_id'] for s in group if s['signal_type'] == 'mcp_tool_calls' and s['user_id']), '') or next((s['user_id'] for s in group if s['user_id']), '')
        device = next((s['device_label'] for s in group if s['device_label']), '')
        host = next((s['host'] for s in group if s['host']), '')
        anchor = entity or (user + ':' + host) or device
        # Isolated sessions in different buckets cannot have colliding DB keys.
        # Repo/runtime/MCP joins use their stable entity or family anchor.
        if not entity and all(s['channel'] in ('Network', 'DLP') for s in group):
            bucket = min(int(datetime.fromisoformat(s['ts_first']).timestamp()) // 600 for s in group)
            anchor += ':' + str(bucket)
        cid = 'C-' + hashlib.sha256((anchor + ':' + provider).encode()).hexdigest()[:12]
        ids = {s['signal_id'] for s in group}
        joins = [e for e in edges if e['from'] in ids and e['to'] in ids]
        label = host if host == 'chatgpt.com' else provider
        display_name = 'Local Ollama runtime (demo)' if not entity and provider == 'Ollama' and all(s['attributes'].get('evidence_origin') == 'static_fixture' for s in group) else f'{entity or user} \u2192 {label}'
        if entity == 'creditdb-MCP':
            display_name = entity
        candidates.append({'id': cid, 'entity': entity, 'user_id': user, 'device_label': device, 'provider': provider,
            'name': display_name, 'signals': group,
            'channels': sorted({s['channel'] for s in group}), 'edges': joins,
            'join_rules_fired': sorted({e['rule'] for e in joins})})
    return candidates
