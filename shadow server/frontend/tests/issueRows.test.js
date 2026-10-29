import test from 'node:test';
import assert from 'node:assert/strict';
import {issueRelevance,groupIssues,evidencePeriod} from '../src/issueRows.js';

const candidate=(id,decision='Raise issue')=>({id,decision});
const issue=(id,candidate_id,extra={})=>({id,candidate_id,title:'priya → chatgpt.com',status:'Open',created_at:'2026-10-28T12:00:00Z',evidence_pack:{decision:'Raise issue',entity:'',user_id:'priya',provider:'OpenAI',signals:[{host:'chatgpt.com',ts_first:'2026-10-28T11:00:00Z',ts_last:'2026-10-28T11:01:00Z'}]},...extra});

test('current issues exclude missing candidates, resolved issues and downgraded findings',()=>{
 const candidates=[candidate('active'),candidate('downgraded','Monitor')];
 assert.equal(issueRelevance(issue('one','active'),candidates).scope,'current');
 for(const row of [issue('old','absent'),issue('fixed','active',{status:'Resolved'}),issue('lower-risk','downgraded')])assert.equal(issueRelevance(row,candidates).scope,'history');
});

test('manually raised issues remain current even when the candidate is Monitor',()=>{
 const row=issue('manual','one');row.evidence_pack.decision='Monitor';
 assert.equal(issueRelevance(row,[candidate('one','Monitor')]).scope,'current');
});

test('separate browser incidents group without deleting or merging stored issues',()=>{
 const issues=[issue('a','one'),issue('b','two')],before=JSON.stringify(issues);
 const groups=groupIssues(issues,[candidate('one'),candidate('two')],'current');
 assert.equal(groups.length,1);assert.equal(groups[0].issues.length,2);
 assert.equal(JSON.stringify(issues),before);
});

test('different investigation statuses, users and hosts stay separate',()=>{
 const rows=[issue('a','one'),issue('b','two',{status:'Investigating'}),issue('c','three'),issue('d','four')];
 rows[2].evidence_pack.user_id='another-user';rows[3].evidence_pack.signals[0].host='another-host';
 assert.equal(groupIssues(rows,rows.map(row=>candidate(row.candidate_id)),'current').length,4);
});

test('evidence dates use the full session and missing dates are not invented',()=>{
 const row=issue('a','one');row.evidence_pack.signals.push({ts_first:'2026-10-28T10:00:00Z',ts_last:'2026-10-28T12:00:00Z'});
 assert.deepEqual(evidencePeriod(row),{first:'2026-10-28T10:00:00.000Z',last:'2026-10-28T12:00:00.000Z'});
 assert.deepEqual(evidencePeriod({}),{first:null,last:null});
});
