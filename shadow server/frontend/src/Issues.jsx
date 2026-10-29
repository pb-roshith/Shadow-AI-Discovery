import React,{useState} from 'react';
import {groupIssues,evidencePeriod,issueRelevance} from './issueRows';
import './issues.css';

const date=value=>value?new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'Not recorded';

function IssueRow({issue,candidates,onOpen,nested=false}) {
 const evidence=issue.evidence_pack||{},period=evidencePeriod(issue),relevance=issueRelevance(issue,candidates);
 return <tr className={nested?'issue-incident':''} tabIndex={0} aria-label={`Open issue ${issue.id}: ${issue.title}`} onClick={()=>onOpen(issue.id)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onOpen(issue.id);}}}>
  <td><b>{issue.id}</b></td><td>{issue.title}<small>{evidence.provider}</small></td>
  <td>{date(period.first)}{period.last&&period.last!==period.first&&<small>to {date(period.last)}</small>}</td><td>{date(issue.created_at)}</td>
  <td>{evidence.confidence??'—'} / {evidence.risk??'—'}</td><td>{issue.owner||evidence.suggested_owner||'—'}</td><td>{issue.status}</td><td>{relevance.reason}</td>
 </tr>;
}

export default function Issues({issues,candidates,onOpen}) {
 const [scope,setScope]=useState('current'),[expanded,setExpanded]=useState(new Set());
 const current=groupIssues(issues,candidates,'current'),history=groupIssues(issues,candidates,'history');
 const groups=scope==='current'?current:history;
 const count=groups=>groups.reduce((total,group)=>total+group.issues.length,0);
 function toggle(key){setExpanded(previous=>{const next=new Set(previous);if(next.has(key))next.delete(key);else next.add(key);return next;});}
 return <>
  <div className="filter-row issues-tabs" role="group" aria-label="Issue view">{[['current','Current issues',current],['history','History',history]].map(([key,label,rows])=><button key={key} className={scope===key?'selected':''} aria-pressed={scope===key} onClick={()=>setScope(key)}>{label} <span>{count(rows)}</span></button>)}</div>
  <p className="issues-view-note">{scope==='current'?'Unresolved issues supported by current findings, including manually raised issues.':'Resolved issues, older findings and findings that no longer meet issue rules. History retains the saved evidence and investigation status.'} Repeated findings are grouped; expand a group to inspect each incident. Dates use India Standard Time.</p>
  <p className="issues-view-count">{count(groups)} issues across {groups.length} findings</p>
  <div className="panel table-panel reference-table issues-table"><table><thead><tr>{['Issue','Finding','Evidence period (IST)','First raised (IST)','Confidence / Risk','Owner','Status','Relevance'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>
   {groups.map(group=>group.issues.length===1?<IssueRow key={group.key} issue={group.issues[0]} candidates={candidates} onOpen={onOpen}/>:<React.Fragment key={group.key}>
    <tr className="issue-group"><td><button type="button" className="issue-group-toggle" aria-expanded={expanded.has(group.key)} aria-label={`${expanded.has(group.key)?'Hide':'Show'} ${group.issues.length} issues for ${group.title}`} onClick={()=>toggle(group.key)}>{expanded.has(group.key)?'−':'+'} {group.issues.length} issues</button></td><td><b>{group.title}</b><small>{group.issues.length} separate usage incidents</small></td><td colSpan={2}>Expand to view dates and saved evidence for each incident</td><td>See incidents</td><td>{new Set(group.issues.map(issue=>issue.owner||issue.evidence_pack?.suggested_owner)).size===1?(group.issues[0].owner||group.issues[0].evidence_pack?.suggested_owner):'Multiple owners'}</td><td>{group.status}</td><td>{group.relevance.reason}</td></tr>
    {expanded.has(group.key)&&group.issues.map(issue=><IssueRow key={issue.id} issue={issue} candidates={candidates} onOpen={onOpen} nested/>)}
   </React.Fragment>)}
  </tbody></table>{!groups.length&&<p className="issues-empty">{scope==='current'?'No current issues need investigation. Historical issues remain available in History.':'No historical issues.'}</p>}</div>
 </>;
}
