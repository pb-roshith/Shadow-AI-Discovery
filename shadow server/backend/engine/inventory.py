"""Global tool approvals shared by every application and repository."""
PROVIDER_TOOLS = {'Google': 'Gemini', 'OpenAI': 'GPT / ChatGPT', 'Anthropic': 'Claude',
                  'Microsoft': 'Copilot', 'Mistral': 'Mistral', 'Ollama': 'Ollama'}
STATUS_PRIORITY = {'Approved': 0, 'Unknown': 1, 'Restricted': 2, 'Revoked': 3}


def tool_name(entry):
    return entry.get('tool_name') or PROVIDER_TOOLS.get(entry['provider']) or (
        entry.get('match_value') if entry.get('match_type') == 'tool' else None) or entry['provider']


def tool_key(entry):
    return entry['provider'].casefold(), tool_name(entry).casefold()


def combined_status(statuses):
    return max(statuses, key=lambda status: STATUS_PRIORITY[status], default='Unknown')


def global_entries(entries):
    """Migrate old scopes, retaining the stricter status when legacy rows conflict."""
    result = {}
    for row in entries:
        name = tool_name(row)
        entry = {**row, 'tool_name': name, 'match_type': 'tool', 'match_value': name, 'required_route': 'any'}
        key = tool_key(entry)
        if key not in result:
            result[key] = entry
        elif STATUS_PRIORITY[entry['status']] > STATUS_PRIORITY[result[key]['status']]:
            result[key]['status'] = entry['status']
    return list(result.values())


def candidate_tools(candidate):
    if candidate['provider'] == 'AI framework':
        names = sorted({signal['attributes'].get('sdk', 'AI framework') for signal in candidate['signals']})
    else:
        names = [PROVIDER_TOOLS.get(candidate['provider'], candidate['provider'])]
    return [{'provider': candidate['provider'], 'tool_name': name} for name in names]


def apply_application_status(candidates):
    applications = {}
    for candidate in candidates:
        if candidate['entity']:
            tools = applications.setdefault(candidate['entity'], {})
            for tool in candidate['inventory']['tools']:
                tools[tool_key(tool)] = tool
    for candidate in candidates:
        inventory = candidate['inventory']
        tools = list(applications.get(candidate['entity'], {}).values()) if candidate['entity'] else inventory['tools']
        inventory['tool_status'] = inventory['status']
        inventory['tools'] = sorted(tools, key=lambda tool: tool['tool_name'])
        inventory['status'] = combined_status(tool['status'] for tool in tools)
        pending = [tool['tool_name'] + ' (' + tool['status'] + ')' for tool in tools if tool['status'] != 'Approved']
        inventory['reason'] = (('Application requires approval for every detected tool. Pending: ' + ', '.join(pending))
                               if pending else 'All detected AI tools are globally approved for use in every repository.')
        if inventory.get('inv_id'):
            inventory['reason'] += ' Tool registry entry: ' + inventory['inv_id'] + '.'
    return candidates
