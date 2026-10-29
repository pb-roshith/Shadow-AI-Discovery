from engine.config import reference

def score(candidate):
    cfg = reference('scoring.yaml')
    signals = candidate['signals']
    types = {s['signal_type'] for s in signals}
    channels = {s['channel'] for s in signals}
    events = sum(s['event_count'] for s in signals)
    live_s1 = any(s['attributes'].get('live_scenario') == 'S1' for s in signals)
    live_app = any(s['attributes'].get('live_scenario') in ('S1', 'S2', 'S6', 'S7') for s in signals)
    if live_app:
        # Files and matching proxy/gateway events are not additional invocations.
        gateway = [s for s in signals if s['channel'] == 'Gateway']
        network_events = [s for s in signals if s['channel'] == 'Network']
        invocations = gateway + [s for s in network_events if s['attributes'].get('evidence_origin') == 'live_sdk'] + [s for s in signals if s['signal_type'] == 'local_model_call']
        counted = invocations or network_events
        request_ids = {rid for s in counted for rid in s['attributes'].get('request_ids', [])}
        events = len(request_ids) + sum(s['event_count'] for s in counted if not s['attributes'].get('request_ids'))
    c, r = cfg['confidence'], cfg['risk']
    factors, risks = [], []
    def factor(target, name, points, maximum, reason, used=None):
        target.append({'name': name, 'points': points, 'max': maximum, 'reason': reason,
                       'signal_ids': [s['signal_id'] for s in (signals if used is None else used)]})
    runtime = types & {'ai_network_call', 'gateway_call', 'ai_process', 'local_model_call'}
    credentials = [s for s in signals if s['signal_type'].startswith('credential_')]
    direct = c['direct']
    tier, reason = ('runtime', 'Runtime AI activity observed') if runtime else ('credential', 'Running MCP server or credential observed') if credentials or 'mcp_server_running' in types else ('sdk', 'AI SDK import or dependency') if types & {'sdk_import', 'sdk_dependency'} else ('model', 'Model artifact found') if 'model_file' in types else ('doc', 'Documentation mention only') if 'doc_mention' in types else (None, 'No direct runtime, credential, SDK, model or documentation evidence')
    factor(factors, 'Direct evidence', direct.get(tier, 0), direct['max'], reason)
    identity = 'direct' if any(s['attributes'].get('identity_source') in ('direct', 'endpoint_profile') for s in signals) else 'register' if candidate['user_id'] else None
    factor(factors, 'Identity link', c['identity'].get(identity, 0), c['identity']['max'], f'Identity source: {identity or "unresolved"}')
    factor(factors, 'Technology correlation', c['technology']['three' if len(types) >= 3 else 'two' if len(types) == 2 else 'one'], c['technology']['max'], f'{len(types)} distinct signal types')
    factor(factors, 'Recurrence', c['recurrence']['ten' if events >= 10 else 'two' if events >= 2 else 'one'], c['recurrence']['max'], f'{events} recorded runtime invocations/attempts' if live_app else f'{events} underlying observations/events')
    factor(factors, 'Independent channels', c['channels']['three' if len(channels) >= 3 else 'two' if len(channels) == 2 else 'one'], c['channels']['max'], f'{len(channels)} independent channels: {", ".join(sorted(channels))}')
    labels = {s['attributes'].get('label') for s in signals if s['channel'] == 'DLP'}
    pii, confidential = 'Customer PII' in labels, 'Confidential' in labels
    mcp = [s for s in signals if s['channel'] == 'MCP']
    write = any(t.get('write') for s in mcp for t in s['attributes'].get('tools', []))
    cmdb, repo, user = candidate['cmdb'] or {}, candidate['repo_register'] or {}, candidate['user']
    sensitive_store = bool(mcp) and cmdb.get('data_classification') == 'Confidential'
    data_points = r['data']['pii'] if pii else r['data']['confidential'] if confidential or sensitive_store else r['data']['credential'] if credentials else 0
    factor(risks, 'Data sensitivity', data_points, r['data']['max'], 'Customer PII blocked' if pii else 'Confidential data or MCP datastore' if confidential or sensitive_store else 'Plaintext credential in file/history' if credentials else 'No sensitive data observed')
    network = [s for s in signals if s['signal_type'] == 'ai_network_call']
    external_direct = any(not s['attributes'].get('via_gateway') for s in network)
    gateway_runtime = live_s1 and 'gateway_call' in types
    factor(risks, 'External exposure', r['external']['direct'] if external_direct else r['external']['gateway'] if network or gateway_runtime else 0, r['external']['max'], 'Direct external AI requests' if external_direct else 'Provider invocation through gateway' if gateway_runtime else 'External AI via gateway' if network else 'Local evidence only', network or [s for s in signals if s['channel'] == 'Gateway'])
    programmatic = any(s['attributes'].get('programmatic') for s in signals) or user.get('type') == 'service' and bool(runtime)
    autonomy = r['autonomy']['write'] if write else r['autonomy']['programmatic'] if mcp or programmatic else r['autonomy']['interactive'] if runtime else 0
    factor(risks, 'Autonomy / permissions', autonomy, r['autonomy']['max'], 'Write/destructive MCP tool exposed' if write else 'Programmatic API or read-only MCP' if mcp or programmatic else 'Interactive/local runtime' if runtime else 'No runtime observed')
    criticality = cmdb.get('criticality') or repo.get('criticality') or user.get('dept_criticality', 'Unknown')
    factor(risks, 'Business criticality', r['criticality'].get(criticality, r['criticality']['Unknown']), r['criticality']['max'], f'{criticality}; source: ' + ('CMDB' if cmdb else 'repo register' if repo else 'user department'))
    customer = cmdb.get('holds_customer_data') == 'yes' or repo.get('handles_customer_data') == 'yes'
    approved = candidate['inventory']['status'] == 'Approved'
    regulatory = r['regulatory']['pii_or_write'] if pii or write and customer else r['regulatory']['confidential_or_customer'] if confidential or customer and not approved else 0
    if live_s1 and not runtime and not labels and not credentials:
        regulatory = 0
    factor(risks, 'Regulatory / customer impact', regulatory, r['regulatory']['max'], 'PII or write access to customer store' if pii or write and customer else 'Confidential / unapproved customer-data use' if regulatory else 'No observed uncontrolled customer impact (approved route exempt)')
    weakness = external_direct or bool(credentials) or write or not (candidate['inventory'].get('owner') if approved else None) and bool(runtime or mcp)
    control = min(r['control']['max'], (0 if approved else r['control']['unapproved']) + (r['control']['weakness'] if weakness else 0))
    if live_s1 and not runtime and not credentials:
        control = 0
    weaknesses = []
    if external_direct:
        weaknesses.append('direct external AI requests')
    if credentials:
        weaknesses.append('exposed credential')
    if write:
        weaknesses.append('write/destructive MCP tool exposed')
    if not (candidate['inventory'].get('owner') if approved else None) and bool(runtime or mcp):
        weaknesses.append('unregistered AI owner')
    factor(risks, 'Control weakness', control, r['control']['max'], f'Inventory: {candidate["inventory"]["status"]}; ' + (', '.join(weaknesses) if weaknesses else 'no additional runtime weakness'))
    meanings = {
        'Direct evidence': 'This measures what proves AI is present or being used. Only the strongest evidence tier counts.',
        'Identity link': 'This measures whether the evidence can be attributed to a known user or service account, separately from proof of AI activity.',
        'Technology correlation': 'Different kinds of AI clues strengthen the evidence. Repeated clues of the same type do not add another signal type.',
        'Recurrence': 'Repeated observations strengthen the evidence that this is ongoing usage.',
        'Independent channels': 'Evidence from different collection channels provides additional support. Multiple clues in one channel count as one channel.',
        'Data sensitivity': 'Sensitive data or exposed credentials increase the potential harm.',
        'External exposure': 'Requests sent directly to an external AI provider carry more exposure than requests routed through the gateway.',
        'Autonomy / permissions': 'Programmatic activity and tools with write permissions can have greater impact than interactive activity.',
        'Business criticality': 'The importance of the affected system or department increases the potential impact.',
        'Regulatory / customer impact': 'Sensitive information and uncontrolled access to customer data can increase customer or regulatory impact.',
        'Control weakness': 'Missing approval, bypasses, exposed credentials or an unregistered AI owner can add control risk.',
    }
    rules = reference('rules.yaml')
    for group, rows in (('confidence', factors), ('risk', risks)):
        for row, rule in zip(rows, rules[group]):
            row['explanation'] = f'{meanings[row["name"]]} {row["reason"]}. This adds {row["points"]} of {row["max"]} possible points.'
            row['scoring_rule'] = rule['description'].format_map(cfg[group][rule['key']])
    recurrence = next(f for f in factors if f['name'] == 'Recurrence')
    recurrence['explanation'] += (' Only recorded gateway, application SDK and local Ollama attempts count, deduplicated by request ID. Proxy events are used only when invocation logs are absent. Code files do not add invocations. Failed attempts do not prove a successful provider response.' if live_app else ' This count includes underlying observations and events; it does not necessarily represent API calls.')
    candidate.update(confidence=sum(f['points'] for f in factors), risk=sum(f['points'] for f in risks), confidence_factors=factors, risk_factors=risks)
    return candidate
