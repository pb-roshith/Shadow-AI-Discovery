from engine.config import reference, rows
from engine.audit import revision

from engine.inventory import global_entries, candidate_tools, combined_status, tool_key


def reconcile(candidate):
    signals = candidate['signals']
    via_gateway = any(s['signal_type'] == 'gateway_call' or s['attributes'].get('via_gateway') for s in signals)
    registry = global_entries(reference('approved_ai_inventory.csv'))
    tools = candidate_tools(candidate)
    evaluations = []
    matches = []
    for tool in tools:
        matched = next((row for row in registry if tool_key(row) == tool_key(tool)), None)
        tool['status'] = matched['status'] if matched else 'Unknown'
        tool['inv_id'] = matched['inv_id'] if matched else None
        if matched:
            matches.append(matched)
    for row in registry:
        matched = any(tool_key(row) == tool_key(tool) for tool in tools)
        evaluations.append({'inv_id': row['inv_id'], 'matched': matched,
                            'reason': f"Global tool status: {row['status']}" if matched else 'Different AI tool'})
    inventory = {**(matches[0] if matches else {}), 'inv_id': matches[0]['inv_id'] if matches else None,
                 'status': combined_status(tool['status'] for tool in tools), 'tools': tools,
                 'reason': 'Global AI tool approvals apply to every repository.'}
    cmdb = rows('cmdb_applications', 'ci_name').get(candidate['entity'])
    register = rows('repo_register', 'repo').get(candidate['entity'])
    user = rows('users', 'user_id').get(candidate['user_id'], {})
    if not cmdb:
        targets = [s['attributes'].get('server') for s in signals if s['channel'] == 'MCP']
        cmdb = next((rows('cmdb_applications', 'ci_name')[t] for t in targets if t in rows('cmdb_applications', 'ci_name')), None)
    candidate.update(inventory=inventory, cmdb=cmdb, repo_register=register, user=user, via_gateway=via_gateway,
        inventory_snapshot=registry, inventory_revision=revision(registry), inventory_evaluations=evaluations,
        suggested_owner=(cmdb or register or {}).get('owner') or user.get('department', 'Unassigned'))
    return candidate
