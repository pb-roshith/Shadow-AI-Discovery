import React, {useEffect, useState} from 'react';

export default function S3Demo({request}) {
  const [status, setStatus] = useState(null), [result, setResult] = useState(null);
  const [busy, setBusy] = useState(''), [error, setError] = useState('');
  async function readiness() {
    setBusy('checking'); setError('');
    try { setStatus(await request('/api/demos/s3/status')); }
    catch { setError('The discovery backend is unavailable. Start the workspace backend, then check readiness again.'); }
    finally { setBusy(''); }
  }
  useEffect(() => { readiness(); }, []);
  async function upload() {
    setBusy('upload'); setError(''); setResult(null);
    try { setResult(await request('/api/demos/s3/run', {method:'POST'})); }
    catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }
  const network = result?.evidence?.network;
  const pii = result?.evidence?.dlp?.find(row => row.label === 'Customer PII');
  return <div className="s3-demo">
    <a className="back" href="#/">← All repositories</a>
    <header><p className="eyebrow">SCENARIO S3 · DATA LOSS PREVENTION</p><h1>A customer upload, stopped.</h1>
      <p>Show how a corporate proxy identifies an employee, detects customer data, and blocks an upload to ChatGPT.</p></header>
    <div className="s3-story" aria-label="Upload journey">
      <article><span className="s3-step">01 · EMPLOYEE</span><h2>Priya</h2><p>Retail Lending</p><small>Authenticated as priya</small></article>
      <span className="s3-arrow" aria-hidden="true">→</span>
      <article><span className="s3-step">02 · CORPORATE PROXY</span><h2>DLP inspection</h2><p>Customer PII policy</p><small>Inspect, identify, block</small></article>
      <span className="s3-arrow" aria-hidden="true">→</span>
      <article><span className="s3-step">03 · DESTINATION</span><h2>ChatGPT</h2><p>chatgpt.com</p><small>{result?.verified ? 'Upload blocked at the proxy' : 'External AI website'}</small></article>
    </div>
    <div className="workspace s3-layout">
      <section className="panel s3-controls"><h2>Present the scenario</h2>
        <div className="s3-file"><span aria-hidden="true">CSV</span><div><b>Fictional customer extract</b><p>14 fictional customers · 2.4 MB</p><small>dummy_customer_extract.csv</small></div></div>
        <p className="s3-note">The demo generates its own fictional file. Click below to send it through the local proxy using Priya’s identity.</p>
        <div className="s3-readiness"><span className={'s3-dot ' + (status?.ready ? 'ready' : '')}/><span>{busy === 'checking' ? 'Checking the demo…' : status?.ready ? 'Proxy and certificate available' : 'Demo setup needed'}</span>
          <button className="s3-text-button" disabled={!!busy} onClick={readiness}>Check again</button></div>
        {status && !status.ready && <p className="s3-note">{status.setup_hint} {!status.certificate_ready && 'Run proxy_setup.ps1 to create the certificate.'}</p>}
        <button className="s3-primary" disabled={!!busy || !status?.ready} onClick={upload}>{busy === 'upload' ? 'Uploading through the proxy…' : result ? 'Run the upload again' : 'Upload fictional customer extract'}<span aria-hidden="true">→</span></button>
        <p className="s3-note">Offline proxy mode supports this demonstration. Each run appends fresh metadata evidence.</p>
        <div className="s3-links"><a href="http://127.0.0.1:8081" target="_blank" rel="noreferrer">Open proxy viewer ↗</a><small>mitmweb password: demo</small></div>
      </section>
      <section className="panel s3-result" aria-live="polite" aria-busy={!!busy}>
        <h2>What the control observed</h2>
        {!result ? <div className="s3-empty"><span aria-hidden="true">◇</span><h3>{busy === 'upload' ? 'Inspecting the fictional upload' : 'Ready for a live demonstration'}</h3><p>{busy === 'upload' ? 'Waiting for the proxy response and matching audit records.' : 'Run the upload to see its actual HTTP response and captured metadata.'}</p></div> : <>
          <div className={'s3-outcome ' + (result.verified ? 'blocked' : 'unverified')}><b>{result.verified ? 'Upload blocked' : result.blocked ? 'Block received · evidence needs review' : 'Expected block not received'}</b><span>HTTP {result.http_status}</span><p>{result.message}</p></div>
          {result.verified && <div className="s3-metrics"><div><strong>{pii.match_count}</strong><span>Customer PII matches</span></div><div><strong>403</strong><span>Policy block response</span></div></div>}
          {network && <dl className="s3-facts"><dt>Employee</dt><dd>{network.proxy_user}</dd><dt>Destination</dt><dd>{network.host}</dd><dt>Activity</dt><dd>{network.method} · {network.path_class}</dd><dt>DLP label</dt><dd>{pii?.label || 'See evidence'}</dd><dt>Recorded at</dt><dd>{new Date(network.ts).toLocaleString()}</dd><dt>Flow ID</dt><dd><code>{network.flow_id}</code></dd></dl>}
          {result.evidence && <details className="s3-evidence"><summary>Inspect captured metadata</summary><p className="s3-note">The audit records contain metadata and match counts. File contents and matched values are excluded.</p><h3>Network record</h3><pre>{JSON.stringify(network, null, 2)}</pre><h3>DLP record</h3><pre>{JSON.stringify(result.evidence.dlp, null, 2)}</pre></details>}
        </>}
      </section>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
