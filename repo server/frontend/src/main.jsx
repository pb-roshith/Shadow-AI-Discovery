import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import './s3-demo.css';
import repos from './repos.js';
import MemoWorkspace from './MemoWorkspace';
import RiskClassifier from './RiskClassifier';
import PolicyIntelligence from './PolicyIntelligence';
import McpWorkspace from './McpWorkspace';
import S3Demo from './S3Demo';

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error((typeof data.detail === 'string' ? data.detail : 'Please check your input and try again.') + (response.headers.get('x-request-id') ? ` Request ID: ${response.headers.get('x-request-id')}` : ''));
  return data;
}

function ChatWorkspace({repo}) {
  const [messages,setMessages]=useState([]),[text,setText]=useState(''),[provider,setProvider]=useState('gemini');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[providers,setProviders]=useState(null);
  useEffect(()=>{request(`/api/repos/${repo.id}/providers`).then(setProviders).catch(err=>setError(err.message));},[repo.id]);
  async function send(event){
    event.preventDefault();if(!text.trim()||busy)return;
    setBusy(true);setError('');
    const prompt=text.trim();
    try{
      const result=await request(`/api/repos/${repo.id}/run`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:prompt,provider,history:messages.slice(-40).map(({role,content})=>({role,content}))})});
      setMessages(previous=>[...previous,{role:'user',content:prompt},{role:'assistant',content:result.text}]);setText('');
    }catch(err){setError(err.message);}finally{setBusy(false);}
  }
  return <><a className="back" href="#/">? All repositories</a><header><p className="eyebrow">CUSTOMER ASSISTANT</p><h1>{repo.name}</h1><p>Ask a question and continue the conversation with your chosen AI provider.</p></header>
    <section className="panel chat-workspace"><div className="chat-controls"><label>AI provider<select value={provider} disabled={busy} onChange={event=>{setProvider(event.target.value);setMessages([]);setError('');}}>{[['gemini','Gemini'],['mistral','Mistral'],['openai','OpenAI']].map(([value,label])=><option key={value} value={value}>{label}{providers&& !providers[value]?' (not configured)':''}</option>)}</select></label><button type="button" className="chat-clear" disabled={busy||!messages.length} onClick={()=>{setMessages([]);setError('');}}>New chat</button></div>
      <div className="chat-messages" role="log" aria-live="polite">{!messages.length&&<div className="empty"><p>How can I help you today?</p><small>Send a message to start a conversation.</small></div>}{messages.map((message,index)=><article className={'chat-message '+message.role} key={index}><b>{message.role==='user'?'You':'Assistant'}</b><p>{message.content}</p></article>)}{busy&&<p role="status">Thinking...</p>}</div>
      {error&&<p role="alert" className="error">{error}</p>}
      <form onSubmit={send}><label htmlFor="chat-message">Message</label><textarea id="chat-message" required maxLength={20000} disabled={busy} value={text} onChange={event=>setText(event.target.value)} placeholder="Type your message..."/><button disabled={busy||!text.trim()}>{busy?'Sending...':'Send message'}</button></form>
    </section></>;
}

function App() {
  const [route, setRoute] = useState(location.hash.slice(1) || '/');
  useEffect(() => { const update = () => {const raw=location.hash.slice(1)||'/';const next=raw==='/repos/creditdb'?'/repos/creditdb-MCP':raw==='/repos/loan-ops-helper'?'/repos/policy-intelligence':['/repos/ahmed-scratch','/repos/ai-risk-classifier'].includes(raw)?'/repos/loan-risk-classifier':raw;if(next!==raw)location.replace('#'+next);setRoute(next);};update();window.addEventListener('hashchange', update);return () => window.removeEventListener('hashchange', update); }, []);
  const repo = repos.find(item => route === `/repos/${item.id}`);
  return <><nav><a href="#/" className="brand"><span className="logo">S</span> repo server</a><span className="nav-label">REPOSITORY HUB</span></nav><main>
    {route === '/demos/customer-data' ? <S3Demo request={request}/> : repo ? repo.kind==='mcp'?<McpWorkspace key={repo.id} repo={repo} request={request}/>:repo.kind==='policy'?<PolicyIntelligence key={repo.id} request={request}/>:repo.kind==='classifier'?<RiskClassifier key={repo.id} request={request}/>:repo.kind==='memo'?<MemoWorkspace key={repo.id} request={request}/>:repo.kind==='chat'?<ChatWorkspace key={repo.id} repo={repo}/>:<p role="alert">This repository has no configured workspace.</p> : route !== '/' ? <><h1>Repository not found</h1><a href="#/">Return to repositories</a></> : <>
      <header><p className="eyebrow">APPLICATIONS AND MCP SERVERS.</p><h1>Your tools, connected.</h1><p>Choose a repository to open its workspace and use its backend.</p></header>
      <div className="section-title"><h2>Repositories</h2><span>{repos.length} workspaces</span></div>
      <div className="grid">{repos.map((item, index) => <a className={`card color-${index}`} key={item.id} href={`#/repos/${item.id}`}><div className="card-top"><span className="icon">{({'creditdb-MCP':'DB','credit-dossier':'CD','policy-intelligence':'PI','loan-risk-classifier':'RC','customer-assistant':'CA'})[item.id]}</span><span className="tag">{item.kind === 'mcp' ? 'MCP' : item.kind==='classifier'?'LOCAL AI':'AI'}</span></div><h2>{item.name}</h2><p>{item.description}</p><div className="card-footer"><code>{item.id}</code><span aria-hidden="true">↗</span></div></a>)}</div>
      <section className="s3-hub-banner"><div><p className="eyebrow">LIVE DEMONSTRATION · SCENARIO S3</p><h2>What happens when customer data goes to ChatGPT?</h2><p>Act as Priya, upload a fictional extract, and watch the corporate proxy block it.</p></div><a href="#/demos/customer-data">Open customer data demo <span aria-hidden="true">→</span></a></section>
    </>}
    <footer>REPO SERVER <span>A shared frontend for your repository backends.</span></footer>
  </main></>;
}

createRoot(document.getElementById('root')).render(<App/>);

