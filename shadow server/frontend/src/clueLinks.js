// Prefer neighboring signals while preserving the backend's actual joins.
export function layoutLinks(signals, edges) {
  const positions = new Map(signals.map((signal, i) => [signal.signal_id, i]));
  const parents = signals.map((_, i) => i);
  const root = i => parents[i] === i ? i : (parents[i] = root(parents[i]));
  const valid = edges.filter(edge => positions.has(edge.from) && positions.has(edge.to));
  const ordered = [...valid].sort((a, b) =>
    Math.abs(positions.get(a.from) - positions.get(a.to)) -
    Math.abs(positions.get(b.from) - positions.get(b.to)));
  const primary = [];
  for (const edge of ordered) {
    const left = root(positions.get(edge.from)), right = root(positions.get(edge.to));
    if (left !== right) {
      parents[right] = left;
      primary.push(edge);
    }
  }
  return {primary, additional: valid.filter(edge => !primary.includes(edge))};
}

export function sharedValue(edge, signals) {
  const a = signals.find(signal => signal.signal_id === edge.from);
  const b = signals.find(signal => signal.signal_id === edge.to);
  if (!a || !b) return edge.reason;
  const attrs = a.attributes || {};
  switch (edge.rule) {
    case 'J1':
      return `same ${[a.channel, b.channel].includes('Gateway') ? 'app' : 'entity'} ${a.entity} + ${a.provider}`;
    case 'J2':
      return `same credential fingerprint ${(a.fingerprint || '').slice(0, 12)}…`;
    case 'J3':
      return `repo service account = proxy user ${a.user_id} + ${a.provider}`;
    case 'J4':
      return `${a.user_id} + ${a.host} within two minutes`;
    case 'J5':
      return `device ${a.device_label} + ${attrs.runtime || 'local runtime'}`;
    case 'J6':
      return `${attrs.server || 'MCP server'} + ${attrs.url || 'same local endpoint'}`;
    default:
      return edge.reason;
  }
}
