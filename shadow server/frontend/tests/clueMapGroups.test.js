import test from 'node:test';
import assert from 'node:assert/strict';
import {selectMapCandidates, groupClueMap, groupCandidateRows} from '../src/clueMapGroups.js';

function candidate(id,entity,provider,type,origin) {
 return {id,entity,provider,decision:'Monitor',confidence:60,channels:[type==='sdk_import'?'Code':'Endpoint'],signals:[{signal_id:id,signal_type:type,channel:type==='sdk_import'?'Code':'Endpoint',attributes:{evidence_origin:origin}}]};
}

test('new application activity and credentials are selected from evidence without a fixed app list',()=>{
 const activity=candidate('new-live','new-application','OpenAI','ai_network_call','live_sdk');
 const secret=candidate('secret','another-application','OpenAI','credential_in_history','live');
 const code=candidate('code','third-application','Mistral','sdk_import','live');
 const demo=candidate('demo','new-application','OpenAI','ai_network_call','static_fixture');
 assert.deepEqual(selectMapCandidates([activity,secret,code,demo],{includeCodeOnly:false}).map(c=>c.id),['new-live','secret']);
 assert.deepEqual(selectMapCandidates([activity,secret,code,demo]).map(c=>c.id),['new-live','secret','code']);
 assert.deepEqual(selectMapCandidates([activity,secret,code,demo],{includeCodeOnly:true}).map(c=>c.id),['new-live','secret','code']);
});

test('policy provider candidates appear as one live S2 application',()=>{
 const tools=['OpenAI','Mistral','Google'].map((provider,index)=>candidate('policy-'+index,'policy-intelligence',provider,'ai_network_call','live_sdk'));
 const scenarios=[{id:'S2',entity:'policy-intelligence',candidate_ids:tools.map(c=>c.id)}];
 assert.equal(selectMapCandidates(tools).length,3);
 const groups=groupClueMap(tools,scenarios);
 assert.equal(groups.length,1);
 assert.equal(groups[0].scenario.id,'S2');
 assert.equal(groups[0].candidates.length,3);
});

test('default map includes code-only integrations and local calls while excluding fixtures',()=>{
 const live=candidate('live','loan-risk-classifier','Ollama','local_model_call','live_local');
 const code=candidate('code','customer-assistant','OpenAI','sdk_import','live');
 const demo=candidate('demo','','Ollama','ai_process','static_fixture');
 assert.deepEqual(selectMapCandidates([live,code,demo]).map(c=>c.id),['live','code']);
 assert.deepEqual(selectMapCandidates([live,code,demo],{includeCodeOnly:false}).map(c=>c.id),['live']);
 assert.deepEqual(selectMapCandidates([live,code,demo],{includeCodeOnly:true}).map(c=>c.id),['live','code']);
 assert.equal(selectMapCandidates([live,code,demo],{includeDemo:true,includeCodeOnly:true}).length,3);
});

test('all providers remain visible within each application with their original evidence types',()=>{
 const applications=['customer-assistant','credit-dossier','policy-intelligence','new-application'];
 const candidates=applications.flatMap(app=>[
  candidate(app+'-google',app,'Google','ai_network_call','live_sdk'),
  candidate(app+'-mistral',app,'Mistral','sdk_import','live'),
  candidate(app+'-openai',app,'OpenAI','sdk_import','live'),
 ]);
 const groups=groupClueMap(selectMapCandidates(candidates),[]);
 assert.equal(groups.length,applications.length);
 for(const group of groups){
  assert.deepEqual(group.candidates.map(c=>c.provider),['Google','Mistral','OpenAI']);
  assert.equal(group.signals.filter(s=>s.signal_type==='sdk_import').length,2);
  assert.equal(group.signals.filter(s=>s.signal_type==='ai_network_call').length,1);
 }
});

test('classifier and ambient demo Ollama stay in separate groups and scenarios',()=>{
 const live=candidate('live','loan-risk-classifier','Ollama','local_model_call','live_local');
 const demo=candidate('demo','','Ollama','ai_process','static_fixture');
 const scenarios=[{id:'S4',result:{id:'demo'}},{id:'S7',entity:'loan-risk-classifier',candidate_ids:['live'],result:{id:'live'}}];
 const groups=groupClueMap([live,demo],scenarios);
 assert.equal(groups.length,2);
 assert.equal(groups.find(g=>g.representative.id==='live').scenario.id,'S7');
 assert.equal(groups.find(g=>g.representative.id==='demo').scenario.id,'S4');
 assert.equal(groups.reduce((n,g)=>n+g.signals.length,0),2);
});

function browserSession(id,user='priya',host='chatgpt.com',provider='OpenAI') {
 return {...candidate(id,'',provider,'ai_network_call','live'),user_id:user,channels:['Network','DLP'],
  signals:['Network','DLP'].map(channel=>({signal_id:`${id}-${channel}`,channel,host,
   signal_type:channel==='DLP'?'dlp_label':'ai_network_call',ts_first:'2026-10-28T15:26:38+05:30',attributes:{evidence_origin:'live'}}))};
}

test('application status follows current discovery rather than a code-only provider Monitor',()=>{
 const code=candidate('mistral','credit-dossier','Mistral','sdk_import','live');
 code.confidence=40;
 const live={...candidate('gemini','credit-dossier','Google','gateway_call','live'),decision:'Genuine',confidence:90,channels:['Code','Gateway']};
 const scenarios=[{id:'S1',entity:'credit-dossier',result:{id:live.id}}];
 for(const input of [[code,live],[live,code]]){
  const [group]=groupClueMap(input,scenarios);
  assert.equal(group.representative,live);
  assert.equal(group.representative.decision,'Genuine');
  assert.equal(group.candidates.length,2);
  assert.equal(group.signals.length,2);
 }
});

test('group status updates with discovery decisions and never forces Genuine',()=>{
 const code=candidate('code','another-app','Mistral','sdk_import','live');
 const live=candidate('live','another-app','Google','gateway_call','live');
 const scenarios=[{id:'new-scenario',entity:'another-app',result:{id:live.id}}];
 for(const decision of ['Genuine','Monitor','Raise issue','False positive']){
  const updated={...live,decision};
  const [group]=groupClueMap([code,updated],scenarios);
  assert.equal(group.representative,updated);
  assert.equal(group.representative.decision,decision);
 }
 const issue={...code,decision:'Raise issue'};
 assert.equal(groupClueMap([issue,{...live,decision:'Genuine'}],scenarios)[0].representative,issue);
});

test('applications without a scenario use observed activity before code-only evidence',()=>{
 const code={...candidate('code','new-app','Mistral','sdk_import','live'),confidence:60};
 const live={...candidate('live','new-app','Google','gateway_call','live'),decision:'Genuine',confidence:90};
 assert.equal(groupClueMap([code,live],[])[0].representative,live);
});

test('browser sessions share one named node with every original session and signal',()=>{
 const sessions=Array.from({length:5},(_,index)=>browserSession(`session-${index}`));
 sessions[0].signals.forEach(signal=>signal.ts_first='2026-10-28T16:26:38+05:30');
 sessions[3].decision='Raise issue';
 const groups=groupClueMap(sessions,[{id:'S3',result:{id:sessions[0].id},candidate_ids:sessions.map(s=>s.id)}]);
 assert.equal(groups.length,1);
 assert.equal(groups[0].label,'Priya → ChatGPT');
 assert.equal(groups[0].scenario.id,'S3');
 assert.equal(groups[0].representative.id,sessions[3].id);
 assert.equal(groups[0].sessions.length,5);
 assert.equal(groups[0].sessions.at(-1),sessions[0]);
 assert.equal(groups[0].signals.length,10);
 assert.deepEqual(new Set(groups[0].sessions),new Set(sessions));
});

test('browser grouping keeps different users, hosts, providers and applications separate',()=>{
 const sessions=[browserSession('priya'),browserSession('ahmed','ahmed'),
  browserSession('other-host','priya','api.openai.com'),browserSession('other-provider','priya','chatgpt.com','Other')];
 const app={...browserSession('app'),entity:'customer-assistant'};
 const groups=groupClueMap([...sessions,app],[]);
 assert.equal(groups.length,5);
 assert.equal(groups.find(group=>group.representative===app).sessions.length,0);
});

test('unidentified browser activity stays separate and repeated signal IDs are deduplicated',()=>{
 const anonymous=[browserSession('anon-1',''),browserSession('anon-2','')];
 assert.equal(groupClueMap(anonymous,[]).length,2);
 const first=browserSession('first'),second=browserSession('second');
 second.signals.push(first.signals[0]);
 const [group]=groupClueMap([first,second],[]);
 assert.equal(group.sessions.length,2);
 assert.equal(group.signals.length,4);
});

test('candidate table combines applications and browser sessions while preserving provider drilldowns',()=>{
 const sessions=Array.from({length:5},(_,index)=>browserSession(`priya-${index}`));
 sessions[2].decision='Raise issue';
 sessions[2].join_rules_fired=['J4'];
 const google=candidate('google','credit-dossier','Google','gateway_call','live');
 const mistral=candidate('mistral','credit-dossier','Mistral','sdk_import','live');
 const input=[google,...sessions,mistral];
 const rows=groupCandidateRows(input,[]);
 assert.equal(rows.length,2);
 const browser=rows.find(row=>row.sessions.length);
 assert.equal(browser.label,'Priya → ChatGPT');
 assert.equal(browser.candidate,sessions[2]);
 assert.deepEqual(browser.sessions,sessions);
 assert.equal(browser.signals.length,10);
 assert.deepEqual(browser.channels,['DLP','Network']);
 assert.deepEqual(browser.joinRules,['J4']);
 const application=rows.find(row=>!row.sessions.length);
 assert.equal(application.label,'credit-dossier');
 assert.deepEqual(new Set(application.records),new Set([google,mistral]));
 assert.equal(application.signals.length,2);
 assert.equal(input.length,7);
});

test('application rows dynamically prioritize credential issues over approved live providers',()=>{
 const exposed={...candidate('secret','policy-intelligence','OpenAI','credential_in_history','live'),decision:'Raise issue',channels:['Secret']};
 exposed.signals[0].channel='Secret';
 exposed.join_rules_fired=['J1'];
 const live={...candidate('live','policy-intelligence','Google','ai_network_call','live_sdk'),decision:'Genuine',channels:['Network']};
 live.signals[0].channel='Network';
 for(const input of [[exposed,live],[live,exposed]]){
  const [row]=groupCandidateRows(input,[{id:'S2',entity:'policy-intelligence',result:{id:live.id}}]);
  assert.equal(row.label,'policy-intelligence');
  assert.equal(row.candidate,exposed);
  assert.equal(row.candidate.decision,'Raise issue');
  assert.equal(row.records.length,2);
  assert.equal(row.signals.length,2);
  assert.deepEqual(row.channels,['Network','Secret']);
  assert.deepEqual(row.joinRules,['J1']);
 }
 const [clean]=groupCandidateRows([live],[]);
 assert.equal(clean.candidate.decision,'Genuine');
 assert.equal(clean.records.length,1);
 assert.deepEqual(groupCandidateRows([],[]),[]);
});

test('candidate table preserves identity boundaries and handles empty lists',()=>{
 assert.deepEqual(groupCandidateRows([],[]),[]);
 const input=[browserSession('priya-1'),browserSession('priya-2'),browserSession('ahmed','ahmed'),browserSession('other-host','priya','api.openai.com')];
 const rows=groupCandidateRows(input,[]);
 assert.equal(rows.length,3);
 assert.equal(rows.find(row=>row.label==='Priya → ChatGPT').sessions.length,2);
 assert.equal(rows.reduce((total,row)=>total+row.signals.length,0),8);
});
