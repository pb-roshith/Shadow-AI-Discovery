export function issueRelevance(issue,candidates) {
 const current=candidates.find(candidate=>candidate.id===issue.candidate_id);
 if(issue.status==='Resolved')return {scope:'history',reason:'Resolved',current};
 if(!current)return {scope:'history',reason:'Not detected in latest discovery',current};
 const manual=typeof issue.evidence_pack?.decision==='string'&&issue.evidence_pack.decision!=='Raise issue';
 if(current.decision!=='Raise issue'&&!manual)return {scope:'history',reason:`Current decision: ${current.decision}`,current};
 return {scope:'current',reason:manual?'Manually raised · current candidate':'Detected in latest discovery',current};
}

export function evidencePeriod(issue) {
 const signals=issue.evidence_pack?.signals||[];
 const first=signals.map(signal=>signal.ts_first).filter(value=>Number.isFinite(Date.parse(value)));
 const last=signals.map(signal=>signal.ts_last).filter(value=>Number.isFinite(Date.parse(value)));
 return {first:first.length?new Date(Math.min(...first.map(Date.parse))).toISOString():null,
         last:last.length?new Date(Math.max(...last.map(Date.parse))).toISOString():null};
}

export function groupIssues(issues,candidates,scope) {
 const groups=new Map();
 for(const issue of issues){
  const relevance=issueRelevance(issue,candidates);
  if(relevance.scope!==scope)continue;
  const evidence=issue.evidence_pack||{};
  const host=evidence.signals?.find(signal=>signal.host)?.host||'';
  const identity=evidence.entity?['application',evidence.entity]:evidence.user_id?['user',evidence.user_id,host]:['issue',issue.id];
  const key=JSON.stringify([identity,evidence.provider,evidence.inventory?.tool_name,issue.status,relevance.reason]);
  if(!groups.has(key))groups.set(key,{key,title:issue.title,status:issue.status,relevance,issues:[]});
  groups.get(key).issues.push(issue);
 }
 const time=issue=>Date.parse(evidencePeriod(issue).last||evidencePeriod(issue).first||issue.created_at)||0;
 const result=[...groups.values()];
 for(const group of result)group.issues.sort((a,b)=>time(b)-time(a)||a.id.localeCompare(b.id));
 return result.sort((a,b)=>time(b.issues[0])-time(a.issues[0])||a.key.localeCompare(b.key));
}
