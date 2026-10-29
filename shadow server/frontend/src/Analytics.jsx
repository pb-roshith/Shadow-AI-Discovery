import React, {useEffect, useRef, useState} from 'react';
import {Activity, ArrowDownLeft, ArrowUpRight, Clock3, RefreshCw, CheckCircle2, XCircle, Eye, X} from 'lucide-react';
import './analytics.css';

const periods=[['today','Today'],['week','This week'],['month','This month'],['all','All time']];
const count=value=>value==null?'—':new Intl.NumberFormat('en-IN').format(value);
const duration=value=>value==null?'—':value<1000?`${Math.round(value)} ms`:`${(value/1000).toFixed(2)} s`;
const date=value=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
const colors={success:'#219879',blocked:'#d38b28',failed:'#d15865',pending:'#6282bc',unknown:'#a4afbf'};
const content=value=>typeof value==='string'?value:JSON.stringify(value,null,2);

function TracePopup({trace,application,onDismiss}) {
 const ref=useRef(null);
 useEffect(()=>{
  const dialog=ref.current,opener=document.activeElement,overflow=document.body.style.overflow;
  dialog.showModal();document.body.style.overflow='hidden';
  return()=>{dialog.close();document.body.style.overflow=overflow;if(opener?.isConnected)opener.focus();};
 },[]);
 return <dialog ref={ref} className="analytics-trace-popup" aria-labelledby="trace-popup-title" onCancel={event=>{event.preventDefault();onDismiss();}} onClick={event=>{if(event.target===event.currentTarget)onDismiss();}}>
  <div className="trace-popup-inner"><header><div><h2 id="trace-popup-title">Model input and output</h2><p>{application} · {trace.model||'Model not recorded'} · {date(trace.ts)} IST</p><small className="trace-id">{trace.request_id}</small></div><button type="button" className="trace-icon-button" aria-label="Close model input and output" onClick={onDismiss}><X size={20}/></button></header>
  <div className="trace-popup-body">{[['Model input',trace.model_input],['Model output',trace.model_output]].map(([label,value])=><section key={label}><h3>{label}</h3>{value==null?<p className="trace-unavailable">Not recorded</p>:<pre>{content(value)}</pre>}</section>)}</div></div>
 </dialog>;
}

function RequestChart({series}) {
 const width=820,height=220,pad=34,maximum=Math.max(1,...series.map(day=>day.requests));
 const step=(width-pad*2)/Math.max(1,series.length),barWidth=Math.min(44,Math.max(1,step*.66));
 return <svg className="analytics-chart" viewBox={`0 0 ${width} ${height+36}`} role="img" aria-label="Recorded requests per day in India Standard Time">
  {[0,.25,.5,.75,1].map(tick=><g key={tick}><line x1={pad} y1={height-tick*(height-20)} x2={width-10} y2={height-tick*(height-20)} stroke="#e7edf4"/><text x={pad-8} y={height-tick*(height-20)+4} textAnchor="end">{Math.round(tick*maximum)}</text></g>)}
  {series.map((day,index)=>{
   const barHeight=day.requests/maximum*(height-20),x=pad+index*step+(step-barWidth)/2;
   const label=new Date(day.date+'T00:00:00+05:30').toLocaleDateString('en-IN',{day:'numeric',month:'short',timeZone:'Asia/Kolkata'});
   return <g key={day.date}><rect x={x} y={height-barHeight} width={barWidth} height={barHeight} rx="4" fill="#3864da"><title>{label}: {day.requests} requests · {day.success} successful · {day.blocked} blocked · {day.failed} failed</title></rect>
    {(index===0||index===series.length-1||index%Math.max(1,Math.ceil(series.length/8))===0)&&<text x={x+barWidth/2} y={height+24} textAnchor="middle">{label}</text>}
   </g>;
  })}
 </svg>;
}

export default function Analytics() {
 const [period,setPeriod]=useState('week'),[application,setApplication]=useState('all');
 const [data,setData]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[revision,setRevision]=useState(0);
 const [tracePage,setTracePage]=useState(1),[traceData,setTraceData]=useState(null),[traceError,setTraceError]=useState('');
 const [selectedTrace,setSelectedTrace]=useState(null);
 useEffect(()=>{setTracePage(1);},[period,application]);
 useEffect(()=>{
  let active=true,controller;
  setTraceData(null);
  async function refresh(){
   controller?.abort();controller=new AbortController();
   try{
    const response=await fetch(`/discovery/analytics/traces?period=${period}&application=${encodeURIComponent(application)}&page=${tracePage}`,{cache:'no-store',signal:controller.signal});
    if(!response.ok)throw new Error('Audit traces could not load. Retry using Refresh analytics.');
    const result=await response.json();
    if(active){setTraceData(result);setTraceError('');}
   }catch(e){if(active&&e.name!=='AbortError')setTraceError(e.message);}
  }
  refresh();const timer=setInterval(refresh,10000);
  return()=>{active=false;controller?.abort();clearInterval(timer);};
 },[period,application,tracePage,revision]);
 useEffect(()=>{
  let active=true,controller;
  async function refresh(){
   controller?.abort();controller=new AbortController();
   try{
    const response=await fetch(`/discovery/analytics?period=${period}&application=${encodeURIComponent(application)}`,{cache:'no-store',signal:controller.signal});
    if(!response.ok)throw new Error('Analytics could not load. Check that the discovery backend is running.');
    const result=await response.json();
    if(active){setData(result);setError('');setLoading(false);}
   }catch(e){if(active&&e.name!=='AbortError'){setError(e.message);setLoading(false);}}
  }
  setLoading(true);refresh();const timer=setInterval(refresh,10000);
  return()=>{active=false;controller?.abort();clearInterval(timer);};
 },[period,application,revision]);
 const summary=data?.summary;
 const metrics=[['Requests',summary?.requests,Activity,'Unique recorded attempts'],['Input tokens',summary?.input_tokens,ArrowDownLeft,'Reported by the model provider'],['Output tokens',summary?.output_tokens,ArrowUpRight,'Reported by the model provider'],['Average request time',duration(summary?.avg_duration_ms),Clock3,'Across measured requests'],['Failed requests',summary?.failed,XCircle,'Requests that ended in an error'],['Successful requests',summary?.success,CheckCircle2,'Completed successfully']];
 const name=id=>data?.applications.find(app=>app.id===id)?.name||id;
 return <div className="analytics-dashboard" aria-busy={loading}>
  <div className="analytics-controls"><div className="analytics-periods" role="group" aria-label="Reporting period">{periods.map(([key,label])=><button key={key} aria-pressed={period===key} className={period===key?'selected':''} onClick={()=>setPeriod(key)}>{label}</button>)}</div>
   <div className="analytics-actions"><label>Application <select value={application} onChange={event=>setApplication(event.target.value)}><option value="all">All applications</option>{data?.applications.map(app=><option key={app.id} value={app.id}>{app.name}</option>)}</select></label><button className="secondary" aria-label="Refresh analytics" onClick={()=>setRevision(value=>value+1)}><RefreshCw size={16}/></button></div>
  </div>
  {error&&<p className="message error" role="alert">{error}</p>}
  <div className="analytics-status"><span><i/> {loading?'Updating analytics…':'Live request telemetry'}</span><span>India Standard Time · Week starts Monday{data&&` · Updated ${date(data.generated_at)}`}</span></div>
  <div className="analytics-kpis">{metrics.map(([label,value,Icon,hint])=><section className="panel analytics-kpi" key={label}><div><span>{label}</span><Icon size={18}/></div><strong>{typeof value==='number'?count(value):value??'—'}</strong><small>{hint}</small></section>)}</div>
  <div className="analytics-overview"><section className="panel analytics-trend"><div className="analytics-panel-heading"><div><h2>Requests per day</h2><p>{application==='all'?'All six applications':name(application)} · {periods.find(([key])=>key===period)?.[1]}</p></div><span className="analytics-pill">{count(summary?.requests)} requests</span></div>
   {data?<RequestChart series={data.series}/>:<p className="analytics-empty">Loading request history…</p>}
   {data&&summary.requests===0&&<p className="analytics-note">No recorded requests in this period. New activity appears automatically.</p>}
   {data?.chart_truncated&&<p className="analytics-note">Chart shows the latest 366 days. Totals cover the full selection.</p>}
  </section><section className="panel analytics-outcomes"><div className="analytics-panel-heading"><div><h2>Request outcomes</h2><p>Every recorded attempt, counted once</p></div></div><div className="analytics-outcome-total"><strong>{count(summary?.requests)}</strong><span>total requests</span></div>
   <div className="analytics-outcome-bar" aria-hidden="true">{Object.keys(colors).map(key=><span key={key} style={{width:`${summary?.requests?summary[key]/summary.requests*100:0}%`,background:colors[key]}}/>)}</div>
   {Object.entries(colors).map(([key,color])=><div className="analytics-outcome-row" key={key}><span><i style={{background:color}}/>{({success:'Successful',blocked:'Blocked by policy',failed:'Failed',pending:'Pending',unknown:'Outcome not recorded'})[key]}</span><b>{count(summary?.[key])}</b></div>)}
  </section></div>
  <div className="analytics-section-heading"><div><h2>Application activity</h2><p>Today, week to date and month to date · token and time metrics follow the selected period</p></div><button className="analytics-reset" onClick={()=>setApplication('all')}>Show all applications</button></div>
  <div className="analytics-apps">{data?.applications.map((app,index)=><section className={'panel analytics-app '+(application===app.id?'active':'')} key={app.id}>
   <button className="analytics-app-heading" onClick={()=>setApplication(app.id)} aria-label={`Filter analytics to ${app.name}`}><span className={`analytics-app-icon tone-${index}`}>{['CD','PI','PC','DB','CA','RC'][index]}</span><span><b>{app.name}</b><small>{app.kind}</small></span><ArrowUpRight size={18}/></button>
   <div className="analytics-app-counts">{[['today','Today'],['week','This week'],['month','This month']].map(([key,label])=><div key={key}><strong>{count(app.counts[key])}</strong><span>{label}</span></div>)}</div>
   <div className="analytics-app-measurements"><div><span>Input tokens</span><b>{count(app.input_tokens)}</b></div><div><span>Output tokens</span><b>{count(app.output_tokens)}</b></div><div><span>Avg. request time</span><b>{duration(app.avg_duration_ms)}</b></div><div><span>Selected period requests</span><b>{count(app.requests)}</b></div><div><span>Successful requests</span><b>{count(app.success)}</b></div><div><span>Failed requests</span><b className="analytics-failed-count">{count(app.failed)}</b></div></div>
  </section>)}</div>
  <div className="analytics-footnote"><b>Measurement coverage</b><p>{count(summary?.token_measured_requests)} of {count(summary?.requests)} requests include both token counts; {count(summary?.timed_requests)} include timing. “—” means unavailable or not applicable. Historical records are retained without estimated values. Browser uploads and database tools do not produce model tokens.</p><p>Token totals sum measured usage for unique requests. Average request time is total measured time divided by timed requests. Counts include successful, failed, blocked, pending and unknown outcomes. Gateway lifecycle events are deduplicated by request ID. Metrics update every 10 seconds.</p></div>
  {data?.warnings?.map(warning=><p key={warning} className="message error" role="status">{warning}</p>)}
  <section className="panel analytics-requests" aria-label="AI call audit traces">
   <div className="analytics-panel-heading"><div><h2>AI call audit traces</h2><p>Individual calls for the selected period and application · newest first. Click the eye icon to view model input and output.</p></div><span className="analytics-pill">{count(traceData?.total)} traces</span></div>
   {traceError&&<p className="message error" role="alert">{traceError}</p>}
   <div className="analytics-table-scroll"><table className="analytics-trace-table"><thead><tr>{['Time (IST) / Request ID','Application','Provider / Model','Status','Input tokens','Output tokens','Total tokens','Time taken','Details'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>
    {traceData?.traces.map(trace=><tr key={`${trace.app}:${trace.request_id}`}><td>{date(trace.ts)}<small className="trace-id">{trace.request_id}</small></td><td>{name(trace.app)}</td><td>{trace.provider||'Not recorded'}<small className="trace-id">{trace.model||'Not recorded'}</small></td><td><span className="analytics-request-status" style={{color:colors[trace.status]}}>{trace.status}</span></td><td>{count(trace.input_tokens)}</td><td>{count(trace.output_tokens)}</td><td>{count(trace.total_tokens)}</td><td>{duration(trace.duration_ms)}</td><td><button type="button" className="trace-icon-button" aria-label={`View model input and output for request ${trace.request_id}`} title="View model input and output" onClick={()=>setSelectedTrace(trace)}><Eye size={18}/></button></td></tr>)}
    {!traceData?.traces.length&&<tr><td colSpan={9} className="analytics-empty">{traceData?'No calls recorded for this selection.':'Loading audit traces…'}</td></tr>}
   </tbody></table></div>
   <div className="analytics-trace-footer"><p>Historical input and output were not captured. Browser and database activity shows available measurements; model-only fields are unavailable.</p><div><button className="secondary" disabled={tracePage===1} onClick={()=>setTracePage(page=>page-1)}>Previous</button><span>Page {tracePage} of {Math.max(1,Math.ceil((traceData?.total||0)/25))}</span><button className="secondary" disabled={!traceData||tracePage*25>=traceData.total} onClick={()=>setTracePage(page=>page+1)}>Next</button></div></div>
  </section>
  {selectedTrace&&<TracePopup trace={selectedTrace} application={name(selectedTrace.app)} onDismiss={()=>setSelectedTrace(null)}/>}
 </div>;
}
