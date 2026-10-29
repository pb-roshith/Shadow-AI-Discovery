import React, {useState} from 'react';

export default function MemoWorkspace({request}) {
 const [memo,setMemo]=useState(null),[question,setQuestion]=useState(''),[answers,setAnswers]=useState([]);
 const [provider,setProvider]=useState('gemini'),[busy,setBusy]=useState(''),[error,setError]=useState('');
 async function upload(event) {
  const file=event.target.files?.[0]; event.target.value='';
  if(!file)return;
  setMemo(null);setAnswers([]);setQuestion('');setError('');
  if(file.size>5*1024*1024){setError('Choose a memo up to 5 MB.');return;}
  setBusy('upload');
  try {
   const form=new FormData();form.append('file',file);
   setMemo(await request('/api/repos/credit-dossier/memo',{method:'POST',body:form}));
  } catch(err){setError(err.message);} finally{setBusy('');}
 }
 async function ask(event) {
  event.preventDefault();if(!memo||busy||!question.trim())return;
  const text=question.trim();setError('');setBusy('answer');
  try {
   const result=await request('/api/repos/credit-dossier/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,memo:memo.text,provider})});
   setAnswers(previous=>[...previous,{question:text,...result}]);setQuestion('');
  } catch(err){setError(err.message);} finally{setBusy('');}
 }
 return <div className="memo-review"><a className="back" href="#/">← All repositories</a>
  <header><p className="eyebrow">CREDIT DOSSIER / MEMO REVIEW</p><h1>Understand the credit memo.</h1><p>Upload a memo, inspect its contents, and ask questions with answers grounded in the document.</p></header>
  {error&&<p className="error" role="alert">{error}</p>}
  <div className="memo-layout"><aside className="panel memo-document"><div className="memo-step">1 · SOURCE DOCUMENT</div><h2>Your credit memo</h2>
   <label className="memo-upload">{memo?'Replace memo':'Upload a credit memo'}<input type="file" accept=".pdf,.docx,.txt,.md" disabled={!!busy} onChange={upload}/><small>PDF, Word (.docx), TXT or Markdown · up to 5 MB</small></label>
   {busy==='upload'&&<p role="status">Reading your memo…</p>}
   {memo?<><div className="memo-file"><b>{memo.name}</b><small>{memo.sections} source sections · {memo.characters.toLocaleString()} characters</small></div><details open><summary>Extracted document text</summary><pre className="memo-preview">{memo.text}</pre></details><button type="button" className="memo-secondary" disabled={!!busy} onClick={()=>{setMemo(null);setAnswers([]);setQuestion('');setError('');}}>Remove memo</button></>:<div className="memo-placeholder"><span aria-hidden="true">▤</span><p>Your document is the source of every answer.</p><small>Upload a memo to begin. Scanned PDFs need selectable text.</small></div>}
   <p className="memo-note">The memo is held in this tab and is sent to your selected AI provider when you ask a question. Refreshing clears the review.</p>
  </aside><section className="panel memo-questions"><div className="memo-step">2 · DOCUMENT QUESTIONS</div><h2>Ask about this memo</h2>
   <p className="memo-note">Answers should cite pages or paragraphs. When information is absent, the assistant should say so. Check citations against the source text.</p>
   <form onSubmit={ask}><label htmlFor="memo-provider">AI provider</label><select id="memo-provider" value={provider} disabled={!!busy} onChange={e=>setProvider(e.target.value)}><option value="gemini">Gemini</option><option value="mistral">Mistral</option></select>
    <label htmlFor="memo-question">Your question</label><textarea id="memo-question" value={question} disabled={!memo||!!busy} maxLength={4000} required onChange={e=>setQuestion(e.target.value)} placeholder={memo?'For example: What are the repayment risks identified in this memo?':'Upload a memo first to ask a question.'}/>
    <div className="memo-suggestions">{['Summarize the borrower’s credit profile.','What risks and mitigants does the memo identify?','What repayment terms and collateral are stated?'].map(text=><button type="button" key={text} disabled={!memo||!!busy} onClick={()=>setQuestion(text)}>{text}</button>)}</div>
    <button disabled={!memo||!!busy||!question.trim()}>{busy==='answer'?'Reviewing the memo…':'Ask about memo'} <span aria-hidden="true">→</span></button>
   </form>
   <div className="memo-answers" aria-live="polite" aria-busy={busy==='answer'}>{!answers.length?<div className="memo-answer-empty"><h3>Evidence before answers.</h3><p>Ask about the borrower, financial position, repayment terms, risks or recommendations recorded in your memo.</p></div>:answers.map((answer,index)=><article className="memo-answer" key={index}><p className="memo-step">QUESTION {index+1} · {answer.provider==='gemini'?'GEMINI':'MISTRAL'}</p><h3>{answer.question}</h3><div className="memo-answer-text">{answer.text}</div><details className="request-id"><summary>Request reference</summary><code>{answer.request_id}</code></details></article>)}</div>
  </section></div>
 </div>;
}
