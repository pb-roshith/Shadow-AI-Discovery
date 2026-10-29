import test from 'node:test';
import assert from 'node:assert/strict';
import {scenarioToolApprovals} from '../src/scenarioTools.js';

const candidate=(id,provider,name,status='Approved')=>({id,provider,inventory:{provider,tool_name:name,tool_status:status}});

test('separate usage records produce one row for the same global tool approval',()=>{
 const records=Array.from({length:6},(_,i)=>candidate(`session-${i}`,'OpenAI','GPT / ChatGPT'));
 const tools=scenarioToolApprovals(records);
 assert.equal(tools.length,1);
 assert.equal(tools[0].name,'GPT / ChatGPT');
 assert.equal(tools[0].candidate.id,'session-0');
 assert.equal(records.length,6);
});

test('distinct tools from the same provider and other providers stay separate',()=>{
 const tools=scenarioToolApprovals([candidate('a','OpenAI','GPT / ChatGPT'),candidate('b','OpenAI','Another registered tool'),candidate('c','Google','Gemini')]);
 assert.equal(tools.length,3);
});

test('conflicting records retain the stricter approval status and its candidate link',()=>{
 const tools=scenarioToolApprovals([candidate('a','OpenAI','GPT / ChatGPT'),candidate('b','OpenAI','GPT / ChatGPT','Restricted')]);
 assert.equal(tools.length,1);
 assert.equal(tools[0].status,'Restricted');
 assert.equal(tools[0].candidate.id,'b');
});

test('legacy candidates without inventory remain visible and empty scenarios have no tools',()=>{
 assert.equal(scenarioToolApprovals([{id:'legacy',provider:'Ollama'}])[0].status,'Unknown');
 assert.deepEqual(scenarioToolApprovals([]),[]);
});
