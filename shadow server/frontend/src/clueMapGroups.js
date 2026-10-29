const runtimeTypes = new Set(['gateway_call', 'ai_network_call', 'local_model_call', 'ai_process', 'mcp_server_running', 'mcp_tool_calls']);

export function observedActivity(candidate) {
  return candidate.signals.some(signal => runtimeTypes.has(signal.signal_type) &&
    ['live', 'live_sdk', 'live_local'].includes(signal.attributes?.evidence_origin));
}

export function selectMapCandidates(candidates, {includeDemo = false, includeCodeOnly = true} = {}) {
  return candidates.filter(candidate => (includeDemo || !candidate.signals.some(s => s.attributes?.evidence_origin === 'static_fixture')) &&
    (includeCodeOnly || observedActivity(candidate) ||
      candidate.signals.some(s => s.signal_type.startsWith('credential_')) ||
      includeDemo && candidate.signals.some(s => !['Code', 'Secret'].includes(s.channel))));
}

export function evidenceSource(signal) {
  if (signal.attributes?.evidence_origin === 'static_fixture' || signal.source_ref?.startsWith('postgresql:')) return 'Demo';
  if (signal.channel === 'Code') return 'Code only';
  if (signal.channel === 'Secret') return 'Credential';
  if (signal.attributes?.evidence_origin === 'live_local') return 'Local call';
  if (signal.attributes?.evidence_origin === 'live_sdk') return 'SDK event';
  if (signal.attributes?.evidence_origin === 'live') return 'Observed';
  return 'Source evidence';
}

export function groupClueMap(candidates, scenarios) {
  const groups = new Map();
  for (const candidate of candidates) {
    const hosts = [...new Set(candidate.signals.map(signal => signal.host).filter(Boolean))].sort();
    const browserUsage = !candidate.entity && Boolean(candidate.user_id) && hosts.length > 0 &&
      candidate.signals.every(signal => ['Network', 'DLP'].includes(signal.channel));
    const key = candidate.entity ? `app:${candidate.entity}` : browserUsage ?
      `browser:${JSON.stringify([candidate.user_id, candidate.provider, hosts])}` : `case:${candidate.id}`;
    const scenario = scenarios.find(item => item.result?.id === candidate.id ||
      item.candidate_ids?.includes(candidate.id) || (candidate.entity && item.entity === candidate.entity));
    if (!groups.has(key)) groups.set(key, {key, scenario, browserUsage, hosts, candidates: []});
    const group = groups.get(key);
    group.scenario ||= scenario;
    group.candidates.push(candidate);
  }
  return [...groups.values()].map(group => {
    // Follow the current discovery result. A code-only Monitor must not replace
    // the application's observed usage; any raised issue still takes priority.
    const rank = candidate => [
      Number(candidate.decision === 'Raise issue'),
      Number(group.scenario?.result?.id === candidate.id),
      Number(observedActivity(candidate)),
      Number(candidate.channels.some(channel => channel !== 'Code')),
      candidate.confidence ?? 0,
      candidate.risk ?? 0,
    ];
    const representative = [...group.candidates].sort((a, b) => {
      const left = rank(a), right = rank(b);
      for (let index = 0; index < left.length; index++) {
        if (left[index] !== right[index]) return right[index] - left[index];
      }
      return a.id.localeCompare(b.id);
    })[0];
    const signals = [...new Map(group.candidates.flatMap(candidate => candidate.signals)
      .map(signal => [signal.signal_id, signal])).values()];
    const user = representative.user_id || '';
    const label = group.browserUsage ? `${user.charAt(0).toUpperCase() + user.slice(1)} → ${group.hosts.map(host => host === 'chatgpt.com' ? 'ChatGPT' : host).join(', ')}` : '';
    const sessionStart = candidate => candidate.signals.map(signal => signal.ts_first).filter(Boolean).sort()[0] || '';
    const sessions = group.browserUsage ? [...group.candidates].sort((a, b) => sessionStart(a).localeCompare(sessionStart(b))) : [];
    return {...group, representative, signals, label, sessions};
  }).sort((a, b) => {
    const order = group => {const index = scenarios.indexOf(group.scenario); return index < 0 ? scenarios.length : index;};
    return order(a) - order(b);
  });
}

export function groupCandidateRows(candidates, scenarios) {
  return groupClueMap(candidates, scenarios).map(group => ({
    candidate: group.representative,
    signals: group.signals,
    label: group.label || group.representative.entity || group.representative.name,
    sessions: group.sessions,
    records: group.candidates,
    channels: [...new Set(group.signals.map(signal => signal.channel))].sort(),
    joinRules: [...new Set(group.candidates.flatMap(candidate => candidate.join_rules_fired || []))].sort(),
  }));
}
