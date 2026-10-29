import React from 'react';
import {ScoreExplanation, DecisionExplanation} from './ScoreExplanation';

function Table({headings, rows}) {
 return <div className="reference-scroll"><table className="reference-grid"><thead><tr>{headings.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j}>{cell ?? '–'}</td>)}</tr>)}</tbody></table></div>;
}

export default function ReferencePage({data,onManage}) {
 if (!data) return <p role="status">Loading reference data…</p>;
 const s=data.signatures;
 const repositories=data.repositories.map(r=>[r.repo,r.owner,r.service_account,r.criticality,r.handles_customer_data]);
 const repoNames=new Set(data.repositories.map(r=>r.repo));
 repositories.push(...data.cmdb.filter(r=>!repoNames.has(r.ci_name)&&r.ci_type==='datastore').map(r=>[r.ci_name+' (CMDB)',r.owner,'–',r.criticality,r.holds_customer_data]));
 return <div className="reference-layout">
  <section className="panel"><h2>How clues are linked (join rules)</h2><Table headings={['Rule','Links two clues when','Used in']} rows={data.join_rules.map(r=>[<b>{r.id}</b>,r.description,r.used_in])}/><div className="merge-guard"><b>Over-merge guard: </b>{data.over_merge_guard}</div></section>
  <section className="panel"><h2>Decision rules (first match wins)</h2><ol className="reference-decisions">{data.decision_rules.map(r=><li key={r.id}><code>{r.id} · {r.condition} → {r.decision}</code></li>)}</ol>{['confidence','risk'].map(group=><div className="reference-scoring" key={group}><h2>{group==='confidence'?'Confidence: how sure is it real AI usage?':'Risk: how harmful could it be?'} ({data[group].reduce((sum,r)=>sum+r.maximum,0)})</h2><Table headings={[]} rows={data[group].map(r=>[`${r.label} (${r.maximum})`,r.description])}/></div>)}</section>
  <section className="panel"><h2>Approved AI inventory</h2><button className="secondary" onClick={onManage}>View / edit approved registry</button><Table headings={['ID','Asset','Match','Route','Status']} rows={data.inventory.map(r=>[r.inv_id,r.asset,`${r.match_type} = ${r.match_value}`,r.required_route,<span className={'badge '+(r.status==='Approved'?'success':'danger')}>{r.status}</span>])}/><p className="reference-note">{data.inventory_note}</p></section>
  <section className="panel"><h2>Repo register and CMDB</h2><Table headings={['Repo / CI','Owner','Service account','Criticality','Customer data']} rows={repositories}/></section>
  <section className="panel"><h2>Demo identities</h2><Table headings={['User','Department','Device']} rows={data.users.map(r=>[r.user_id,r.department+(r.type==='human'?` (${r.dept_criticality})`:''),data.devices.find(d=>d.primary_user===r.user_id)?.device_label||'–'])}/></section>
  <section className="panel"><h2>AI signature catalogue (extract)</h2><Table headings={[]} rows={[
   ['Websites',Object.keys(s.hosts).join(', ')],['Libraries',Object.keys(s.sdks).join(', ')],['Key patterns',Object.entries(s.key_patterns).map(([provider,pattern])=>`${provider}: ${pattern}`).join(' · ')],['Programs / ports',Object.entries(s.processes).map(([name,port])=>`${name} : ${port}`).join(', ')],['Model files',s.model_file_ext.join(', ')],['Agent configs',s.mcp_config_files.join(', ')]
  ]}/></section>
 </div>;
}

export function IssuePage({issue,label,candidateLabel,scenario,signalLabel,description,referenceData,save,go,busy,relevance,hasCurrentCandidate=true}) {
 const c=issue.evidence_pack;
 const rule=c.decision_trace?.find(r=>r.fired);
 const riskDrivers=[...(c.risk_factors||[])].sort((a,b)=>b.points-a.points).filter(f=>f.points>0).slice(0,3);
 const [resolution,setResolution]=React.useState('Remediated');
 return <>
  <div className="issue-heading"><div><button className="back" onClick={()=>go('issues')}>← Issues</button><h1>{label} · {issue.title}</h1><p>From {candidateLabel}{scenario?` (${scenario.displayNumber})`:''} · {rule?`${rule.rule} · ${rule.condition} → ${rule.decision.toUpperCase()}`:'Raised manually'}</p></div>
   {issue.status==='Open'&&<button className="secondary" disabled={busy} onClick={()=>save({status:'Investigating'})}>Start investigation</button>}
   {issue.status==='Investigating'&&<div className="issue-resolve"><select aria-label="Resolution" value={resolution} onChange={e=>setResolution(e.target.value)}>{['Registered','Remediated','False positive'].map(s=><option key={s}>{s}</option>)}</select><button className="secondary" disabled={busy} onClick={()=>save({status:'Resolved',resolution})}>Resolve issue</button></div>}
  </div>
  {relevance?.scope==='history'&&<div className="issue-history-note" role="status"><b>Historical issue: {relevance.reason}.</b> This page shows the saved discovery evidence. Investigation status remains {issue.status}.</div>}
  <div className="issue-workflow" aria-label="Issue status">{['Open','Investigating','Resolved'].map(s=><div key={s} aria-current={issue.status===s?'step':undefined} className={issue.status===s?'current':''}>{s}</div>)}</div>
  <div className="issue-summary">
   <section className="panel"><h2>Why this was raised</h2><p>{scenario?.description||c.name}</p><dl><dt>Clues linked</dt><dd>{c.signals.length} ({c.join_rules_fired?.join(', ')||'single clue'})</dd><dt>Channels</dt><dd>{c.channels.join(', ')}</dd><dt>Inventory</dt><dd>{c.inventory.status}{!c.inventory.inv_id?' · no approved inventory record':''}</dd><dt>Confidence</dt><dd>{c.confidence}/100</dd><dt>Risk</dt><dd>{c.risk}/100</dd><dt>Top risk drivers</dt><dd>{riskDrivers.map(f=>`${f.name} (${f.points})`).join(', ')}</dd></dl>{hasCurrentCandidate&&<button className="text-button" onClick={()=>go('detail',issue.candidate_id)}>See linked clues and full scoring →</button>}</section>
   <section className="panel"><h2>Recommended action</h2><p>{issue.recommended_action}</p><dl><dt>Suggested owner</dt><dd>{issue.owner||c.suggested_owner}</dd><dt>Due</dt><dd>{issue.due||referenceData?.issue_due||'–'}</dd>{issue.resolution&&<><dt>Resolution</dt><dd>{issue.resolution}</dd></>}</dl></section>
  </div>
  <section className="panel"><h2>Decision at discovery</h2><p>{c.decision_explanation}</p><DecisionExplanation candidate={c}/><p>This is the saved discovery decision. An issue may also have been raised manually.</p></section>
  <div className="two-col"><ScoreExplanation title="Discovery confidence" score={c.confidence} factors={c.confidence_factors} signals={c.signals}/><ScoreExplanation title="AI risk" score={c.risk} factors={c.risk_factors} signals={c.signals} risk/></div>
  <section className="panel issue-evidence"><h2>Evidence pack</h2><Table headings={['Signal','Channel','Detected','Source']} rows={c.signals.map((s,i)=>[signalLabel(s)||`SIG-${i+1}`,<span className="chip">{s.channel}</span>,description(s),<span className="muted">{s.source_ref}</span>])}/></section>
 </>;
}
