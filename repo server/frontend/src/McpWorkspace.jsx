import React, {useEffect, useState} from 'react';

export default function McpWorkspace({repo, request}) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setBusy(true); setError(''); setData(null);
    request(`/api/repos/${repo.id}/tools`)
      .then(result => {if (active) setData(result);})
      .catch(() => {if (active) setError('Unable to load tools. Start the CreditDB MCP server with start.bat, then refresh.');})
      .finally(() => {if (active) setBusy(false);});
    return () => {active = false;};
  }, [repo.id, request, refresh]);
  return <>
    <a className="back" href="#/">← All repositories</a>
    <header><p className="eyebrow">MCP SERVER</p><h1>{repo.name}</h1><p>Explore the tools available for working with the loan database.</p></header>
    <section className="panel mcp-workspace" aria-busy={busy}>
      <div className="section-title"><h2>Available tools{data ? ` (${data.tools.length})` : ''}</h2><button type="button" disabled={busy} onClick={() => setRefresh(value => value + 1)}>{busy ? 'Loading…' : 'Refresh tools'}</button></div>
      {data && <p className="mcp-endpoint">Endpoint: <code>{data.endpoint}</code></p>}
      {busy && <p role="status">Loading tools from CreditDB MCP…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {data && !data.tools.length && <p>No tools are currently exposed by this server.</p>}
      <div className="mcp-tools">{data?.tools.map(tool => <article className="mcp-tool" key={tool.name}>
        <div className="section-title"><h3><code>{tool.name}</code></h3><span className={'mcp-permission ' + (tool.annotations?.readOnlyHint ? 'read' : 'write')}>{tool.annotations?.readOnlyHint ? 'Read only' : 'Write access'}</span></div>
        <p>{tool.description || 'No description provided.'}</p>
        <h4>Inputs</h4>
        {Object.keys(tool.inputSchema?.properties || {}).length ? <dl>{Object.entries(tool.inputSchema.properties).map(([name, schema]) => <React.Fragment key={name}><dt><code>{name}</code> · {schema.type || 'value'}{tool.inputSchema.required?.includes(name) ? ' · required' : ' · optional'}</dt><dd>{schema.description || schema.title || name}</dd></React.Fragment>)}</dl> : <p>No inputs required.</p>}
      </article>)}</div>
    </section>
  </>;
}
