import React, {useEffect, useState} from 'react';
import './governance.css';

async function api(path, options) {
 const response=await fetch(path,{...options,headers:{'Content-Type':'application/json'}});
 const body=await response.json();
 if(!response.ok){
  const detail=body.detail;
  const message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map(issue=>`${(issue.loc||[]).filter(part=>part!=='body').join('.')}: ${issue.msg}`).join('; '):`Request failed (${response.status}).`;
  throw Error(message);
 }
 return body;
}
const when=value=>value?new Date(value).toLocaleString():'—';

function Requests({requests}) {
 return <div className="gov-scroll"><table className="gov-table"><thead><tr>{['Request ID','Time','Application / model','Outcome','Tokens','Source records'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{requests.map(request=><tr key={request.request_id}>
  <td><code>{request.request_id}</code></td><td>{when(request.ts)}</td><td>{request.app}<small>{request.provider} · {request.model}</small></td><td>{request.status}</td><td>{request.tokens}</td>
  <td><details><summary>{request.stages.length} log records</summary>{request.stages.map(stage=><div key={stage.id} className="audit-stage"><b>{stage.status} · {when(stage.ts)}</b><p>{stage.source_file}:{stage.source_line}</p><code>{stage.id}</code><p>SHA-256: <code>{stage.source_sha256}</code></p><pre>{JSON.stringify(stage,null,2)}</pre></div>)}</details></td>
 </tr>)}</tbody></table></div>;
}

const providerTools={Google:'Gemini',OpenAI:'GPT / ChatGPT',Anthropic:'Claude',Microsoft:'Copilot',Mistral:'Mistral',Ollama:'Ollama'};
const toolName=item=>item.tool_name||providerTools[item.provider]||item.provider;
const toolKey=item=>JSON.stringify([item.provider,toolName(item)]);

function detectedTools(signals) {
 const groups=new Map();
 for(const signal of signals.filter(item=>item.channel==='Code')){
  const row={provider:signal.provider,tool_name:signal.provider==='AI framework'?(signal.attributes?.sdk||signal.provider):toolName(signal)};
  const key=toolKey(row);
  if(!groups.has(key))groups.set(key,{...row,repos:new Set()});
  if(signal.entity)groups.get(key).repos.add(signal.entity);
 }
 return [...groups.values()].sort((a,b)=>toolName(a).localeCompare(toolName(b)));
}

function RepositoryTools({signals}) {
 const rows=detectedTools(signals);
 return <section className="panel gov-panel"><h2>AI tools detected in repositories</h2><p>AI tools found in repository code. Imports alone do not prove an invocation.</p>
 <div className="gov-scroll"><table className="gov-table"><thead><tr><th>AI tool name</th></tr></thead><tbody>{rows.map(row=><tr key={toolKey(row)}><td><b>{toolName(row)}</b></td></tr>)}</tbody></table></div>
 {!rows.length&&<p>No AI tools detected yet. Run discovery to scan the repositories.</p>}
 </section>;
}

export function Registry({candidate,onChanged}) {
 const [signals,setSignals]=useState(null),[signalsError,setSignalsError]=useState('');
 const [editing,setEditing]=useState(null),[editName,setEditName]=useState('');
 const [adding,setAdding]=useState(false),[manualName,setManualName]=useState(''),[manualStatus,setManualStatus]=useState('Approved');
 const [registry,setRegistry]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 async function load(){setRegistry(await api('/inventory'));}
 async function loadSignals(){try{setSignals(await api('/signals'));setSignalsError('');}catch(error){setSignalsError(error.message);}}
 useEffect(()=>{load().catch(error=>setError(error.message));},[]);
 useEffect(()=>{loadSignals();},[candidate?.run_id]);
 async function addManual(event){
  event.preventDefault();
  const name=manualName.trim();
  if(!name)return;
  const aliases={gemini:'Google',google:'Google',gpt:'OpenAI',chatgpt:'OpenAI','gpt / chatgpt':'OpenAI',openai:'OpenAI',claude:'Anthropic',anthropic:'Anthropic',copilot:'Microsoft',mistral:'Mistral',ollama:'Ollama'};
  const provider=aliases[name.toLowerCase()]||name;
  const display=providerTools[provider]||name;
  if(await decide({provider,tool_name:display,manual:true},manualStatus)){setAdding(false);setManualName('');}
 }
 async function decide(tool,status){
  if(!registry||busy)return;
  setBusy(true);setError('');setNotice('');
  try{
   const key=toolKey(tool);
   const entries=registry.entries.map(item=>toolKey(item)===key?{...item,status,match_type:'tool',match_value:toolName(tool),required_route:'any'}:{...item});
   if(!entries.some(item=>toolKey(item)===key)){
    entries.push({inv_id:'AI-INV-'+crypto.randomUUID(),tool_name:toolName(tool),asset:toolName(tool),match_type:'tool',match_value:toolName(tool),provider:tool.provider,required_route:'any',status,owner:registry.operator.name||'Registry operator'});
   }
   if(JSON.stringify(entries)===JSON.stringify(registry.entries)){
    setNotice(`${toolName(tool)} is already ${status.toLowerCase()} in the registry.`);return true;
   }
   const result=await api('/inventory',{method:'PUT',body:JSON.stringify({entries,expected_revision:registry.revision,reason:`Set ${toolName(tool)} to ${status} from the AI tool registry.`})});
   await load();
   if(result.discovery_error)setError(result.discovery_error);
   else setNotice(`${toolName(tool)} is now ${status.toLowerCase()} in the registry.`);
   await loadSignals();await onChanged?.();return true;
  }catch(error){setError(error.message);}finally{setBusy(false);}
 }
 async function changeTool(tool,name){
  if(!registry||busy)return;
  const key=toolKey(tool),renaming=name!==undefined;
  const trimmed=name?.trim();
  if(renaming&&!trimmed)return;
  if(renaming&&trimmed===toolName(tool)){setEditing(null);return;}
  if(renaming&&registry.entries.some(item=>toolKey(item)!==key&&item.provider.toLowerCase()===tool.provider.toLowerCase()&&toolName(item).toLowerCase()===trimmed.toLowerCase())){
   setError('A tool with this name already exists for this provider.');return;
  }
  const entries=renaming?registry.entries.map(item=>toolKey(item)===key?{...item,tool_name:trimmed,asset:trimmed,match_type:'tool',match_value:trimmed,required_route:'any'}:item):registry.entries.filter(item=>toolKey(item)!==key);
  setBusy(true);setError('');setNotice('');
  try{
   const result=await api('/inventory',{method:'PUT',body:JSON.stringify({entries,expected_revision:registry.revision,reason:renaming?`Rename ${toolName(tool)} to ${trimmed}.`:`Delete ${toolName(tool)} from the AI registry.`})});
   setEditing(null);
   await load();
   setNotice(renaming?`Tool renamed to ${trimmed}.`:`${toolName(tool)} deleted from the AI registry.`);
   if(result.discovery_error)setError(result.discovery_error);
   await loadSignals();await onChanged?.();
  }catch(error){setError(error.message);}finally{setBusy(false);}
 }
 const groups=new Map();
 for(const item of registry?.entries||[]){
  const key=toolKey(item);
  if(!groups.has(key))groups.set(key,{...item,statuses:new Set()});
  groups.get(key).statuses.add(item.status);
 }
 const rows=[...groups.values()].sort((a,b)=>toolName(a).localeCompare(toolName(b)));
 return <><section className="panel gov-panel" id="approved-registry"><div className="gov-heading"><div><h2>AI registry</h2><p>Tool approvals apply to every repository. An application is Approved only when all its detected tools are approved.</p></div><button className="secondary" disabled={busy||!registry} onClick={()=>setAdding(true)}>Add tool</button></div>
 {error&&<p role="alert" className="gov-error">{error} <button className="text-button" disabled={busy} onClick={()=>load().catch(e=>setError(e.message))}>Reload registry</button></p>}
 {notice&&<p role="status" className="gov-notice">{notice}</p>}
 {adding&&<form className="gov-editor" onSubmit={addManual}><div className="gov-fields"><label>AI tool name<input autoFocus required maxLength={100} value={manualName} disabled={busy} onChange={event=>setManualName(event.target.value)} placeholder="For example Gemini, GPT or Claude"/></label><label>Status<select value={manualStatus} disabled={busy} onChange={event=>setManualStatus(event.target.value)}><option>Approved</option><option>Restricted</option></select></label></div><div className="gov-actions"><button className="primary" disabled={busy||!manualName.trim()}>Save tool</button><button type="button" className="secondary" disabled={busy} onClick={()=>setAdding(false)}>Cancel</button></div></form>}
 {busy&&<p role="status">Saving registry and rerunning discovery...</p>}
 {!registry?<p>Loading registry...</p>:<div className="gov-scroll"><table className="gov-table"><thead><tr><th>AI tool name</th><th>Status</th><th>Actions</th></tr></thead><tbody>{rows.map(item=><tr key={toolKey(item)}><td>{editing===toolKey(item)?<form className="gov-editor" onSubmit={event=>{event.preventDefault();changeTool(item,editName);}}><label>AI tool name<input autoFocus required maxLength={200} value={editName} disabled={busy} onChange={event=>setEditName(event.target.value)}/></label><div className="registry-buttons"><button className="primary" disabled={busy||!editName.trim()}>Save</button><button type="button" className="secondary" disabled={busy} onClick={()=>setEditing(null)}>Cancel</button></div></form>:<b>{toolName(item)}</b>}</td><td><select className="registry-status" aria-label={`Status for ${toolName(item)}`} disabled={busy} value={item.statuses.size===1&&['Approved','Restricted'].includes([...item.statuses][0])?[...item.statuses][0]:''} onChange={event=>decide(item,event.target.value)}>{(item.statuses.size!==1||!['Approved','Restricted'].includes([...item.statuses][0]))&&<option value="" disabled>{item.statuses.size>1?'Mixed':'Select status'}</option>}{['Approved','Restricted'].map(status=><option key={status}>{status}</option>)}</select></td><td><div className="registry-buttons"><button className="secondary" aria-label={`Edit ${toolName(item)}`} disabled={busy} onClick={()=>{setEditing(toolKey(item));setEditName(toolName(item));}}>Edit</button><button className="secondary" aria-label={`Delete ${toolName(item)}`} disabled={busy} onClick={()=>changeTool(item)}>Delete</button></div></td></tr>)}</tbody></table>{!rows.length&&<p>No tools registered yet. Use Add tool to create a registry entry.</p>}</div>}
 </section>{signalsError?<section className="panel gov-panel"><h2>AI tools detected in repositories</h2><p role="alert" className="gov-error">{signalsError}</p><button className="secondary" onClick={loadSignals}>Retry</button></section>:signals?<RepositoryTools signals={signals}/>:<p role="status">Loading repository tools...</p>}</>;
}

export function CandidateAudit({candidate}) {
 const [audit,setAudit]=useState(null),[error,setError]=useState('');
 useEffect(()=>{setAudit(null);setError('');api(`/candidates/${candidate.id}/audit`).then(setAudit).catch(error=>setError(error.message));},[candidate.id,candidate.run_id]);
 return <section className="panel gov-panel"><h2>Invocation and evidence audit</h2><p>Live gateway and local Ollama counts are reconciled to archived request records from the discovery run. Expand a request to inspect all of its log stages.</p>
  {error&&<p role="alert" className="gov-error">{error}</p>}{!audit&&!error&&<p>Loading evidence audit…</p>}
  {audit&&<><p className="gov-meta">Run <code>{audit.run_id}</code> · Registry revision <code>{audit.inventory_revision}</code></p>
   {audit.signals.map(bundle=><details className="signal-audit" key={bundle.signal.signal_id} open={(bundle.signal.channel==='Gateway'||bundle.signal.signal_type==='local_model_call')}><summary><b>{bundle.signal.channel} · {bundle.signal.signal_id}</b> · {bundle.expected_count} {(bundle.signal.channel==='Gateway'||bundle.signal.signal_type==='local_model_call')?'invocation(s)':'finding(s)'} · {bundle.verified===true?'Count verified against archived logs':bundle.verified===false?'Evidence mismatch — investigate':bundle.provenance==='static_fixture'?'Demo fixture':'Source evidence'}</summary>
    <p>{bundle.signal.source_ref}</p>
    {(bundle.signal.channel==='Gateway'||bundle.signal.signal_type==='local_model_call')&&['live','live_local'].includes(bundle.provenance)&&<><p>Verified {bundle.verified_count}/{bundle.expected_count} unique requests: {bundle.outcomes.success} succeeded, {bundle.outcomes.failed} failed, {bundle.outcomes.pending} pending.</p><Requests requests={bundle.requests}/></>}
    {bundle.code_proof&&<p>Source-file SHA-256: <code>{bundle.code_proof.file_sha256||'Unavailable for this older run'}</code><br/>Source line(s): {bundle.code_proof.line_numbers.join(', ')||'See source finding'}. A code finding is not an API invocation.</p>}
    {bundle.provenance==='static_fixture'&&<p>This is retained scenario fixture data, not verified live traffic.</p>}
   </details>)}
   <details className="signal-audit"><summary>Exact registry snapshot used for this decision</summary><pre>{JSON.stringify(audit.inventory_snapshot,null,2)}</pre></details>
  </>}
 </section>;
}

export function AuditTrail({refreshKey}) {
 const [changes,setChanges]=useState(null),[gateway,setGateway]=useState(null),[app,setApp]=useState(''),[requestId,setRequestId]=useState(''),[offset,setOffset]=useState(0),[error,setError]=useState('');
 async function load(){setError('');try{const [a,g]=await Promise.all([api('/audit/events'),api(`/audit/gateway?limit=50&offset=${offset}&app=${encodeURIComponent(app)}&request_id=${encodeURIComponent(requestId)}`)]);setChanges(a);setGateway(g);}catch(error){setError(error.message);}}
 useEffect(()=>{load();},[refreshKey,offset]);
 return <div className="governance-layout"><section className="panel gov-panel"><div className="gov-heading"><div><h2>Gateway invocation log</h2><p>Metadata from current logs and archived discovery evidence. Prompts, responses and API keys are excluded.</p></div><button className="secondary" onClick={load}>Refresh audit</button></div>
  {error&&<p role="alert" className="gov-error">{error}</p>}
  <form className="gov-filter" onSubmit={event=>{event.preventDefault();if(offset)setOffset(0);else load();}}><label>Application<input value={app} onChange={event=>setApp(event.target.value)} placeholder="credit-dossier"/></label><label>Request ID<input value={requestId} onChange={event=>setRequestId(event.target.value)} placeholder="Paste a request ID from the app"/></label><button className="secondary">Filter</button></form>
  {gateway&&<><p>{gateway.total_invocations} unique invocations · {gateway.outcomes.success} succeeded · {gateway.outcomes.failed} failed · {gateway.outcomes.pending} pending · {gateway.total_log_records} log records</p><Requests requests={gateway.requests}/><div className="gov-actions"><button className="text-button" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-50))}>Previous</button><span>Showing {gateway.requests.length?offset+1:0}–{offset+gateway.requests.length} of {gateway.total_invocations}</span><button className="text-button" disabled={offset+50>=gateway.total_invocations} onClick={()=>setOffset(offset+50)}>Next</button></div></>}
 </section><section className="panel gov-panel"><h2>Registry and discovery audit</h2><p>Operator identity is the local server OS account. This app does not have individual signed-in user accounts.</p>
  {changes&&<><p>Audit hash chain: <b>{changes.chain_verified?'verified':'verification failed'}</b> · {changes.total} events (latest {changes.events.length} shown)</p>{changes.events.map(event=><details className="signal-audit" key={event.id}><summary>{when(event.recorded_at)} · <b>{event.event_type}</b> · {event.actor.name}</summary><p>Audit ID: <code>{event.id}</code></p>{event.reason&&<p>Reason: {event.reason}</p>}{event.run_id&&<p>Run: <code>{event.run_id}</code></p>}{event.changes?.map(change=><div className="audit-stage" key={change.inv_id}><b>{change.action}: {change.inv_id}</b><div className="gov-fields"><div>Before<pre>{JSON.stringify(change.before,null,2)}</pre></div><div>After<pre>{JSON.stringify(change.after,null,2)}</pre></div></div></div>)}<details><summary>Complete audit record and hashes</summary><pre>{JSON.stringify(event,null,2)}</pre></details></details>)}</>}
 </section></div>;
}
