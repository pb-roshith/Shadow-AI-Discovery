import React, {useLayoutEffect, useRef, useState} from 'react';
import {groupClueMap, evidenceSource} from './clueMapGroups';

const colors={'Genuine':['#218a57','#dcf1e5'],'Raise issue':['#d44c56','#fbe0e2'],'Monitor':['#b78a20','#fff1cc'],'False positive':['#8e9aa9','#ebedf0']};
const appNames={'policy-intelligence':'Policy Intelligence','credit-dossier':'Credit Dossier','customer-assistant':'Customer Assistant','loan-risk-classifier':'Loan Risk Classifier'};

export default function ClueMap({candidates,scenarios,onOpen,describe,signalLabel}) {
 const visible=candidates;
 const contentRefs=useRef(new Map());
 const [rowHeights,setRowHeights]=useState({});
 useLayoutEffect(()=>{
  const measured={};
  contentRefs.current.forEach((node,id)=>{measured[id]=Math.max(72,Math.ceil(node.scrollHeight)+16);});
  if(JSON.stringify(measured)!==JSON.stringify(rowHeights))setRowHeights(measured);
 });
 let nextY=74;
 const groups=groupClueMap(visible,scenarios).map(group=>{
  const groupTop=nextY;
  const height=60+group.sessions.length*40;
  const rows=group.signals.map(signal=>{
   const height=rowHeights[signal.signal_id]||72;
   const top=nextY;
   nextY+=height+12;
   return {signal,top,height,y:top+height/2,label:signalLabel?signalLabel(signal):signal.signal_id};
  });
  const center=Math.max(rows.length?(rows[0].y+rows[rows.length-1].y)/2:nextY,groupTop+height/2);
  nextY=Math.max(nextY,center+height/2)+62;
  return {...group,rows,center,height};
 });
 const open=(event,candidate)=>{event.stopPropagation();onOpen(candidate);};
 const keyboard=(event,candidate)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open(event,candidate);}};
 return <>{!visible.length&&<p role="status">No evidence yet. Run discovery to populate the map.</p>}<div className="panel clue-map-panel"><div className="map-legend">{Object.entries(colors).map(([name,[stroke]])=><span key={name}><i style={{background:stroke}}/>{name}</span>)}<small>Click an application to inspect its evidence · application name and decision</small></div><div className="clue-map-scroll"><svg className="clue-map-svg" viewBox={`0 0 1240 ${nextY+12}`} role="img" aria-label="AI evidence grouped by application with application names and decisions">
  <text className="map-column" x="24" y="30">AI SIGNALS</text><text className="map-column" x="865" y="30">APPLICATIONS / AI USAGE</text>
  {groups.map(({key,representative:c,rows,center,height,label:groupLabel,sessions})=>{
   const [stroke,fill]=colors[c.decision]||colors.Monitor;
   const appName=groupLabel||appNames[c.entity]||c.entity||(c.provider==='Ollama'?'Local Ollama runtime (demo)':c.user_id||c.name);
   return <g key={key}>{rows.map(({signal:s,y,top,height:rowHeight,label})=><g key={s.signal_id}><title>{s.signal_id}: {describe(s)} — {s.source_ref}</title>
    <path d={`M 554 ${y} C 700 ${y}, 744 ${center}, 865 ${center}`} fill="none" stroke={stroke} strokeWidth="2" opacity=".8"/>
    <rect x="24" y={top} width="530" height={rowHeight} rx="8" fill="#fff" stroke="#c7d6ed" strokeWidth="1.3"/>
    <foreignObject x="35" y={top+8} width="508" height={rowHeight-16}><div className="map-signal-content" ref={node=>{if(node)contentRefs.current.set(s.signal_id,node);else contentRefs.current.delete(s.signal_id);}}><span className="map-channel">{s.channel}</span><span className="map-signal-id">{label}</span><span className="map-evidence-source">{evidenceSource(s)}</span><span className="map-signal-description">{s.provider}: {describe(s)}</span></div></foreignObject>
   </g>)}
   <g>
    <rect x="865" y={center-height/2} width="350" height={height} rx="10" fill={fill} stroke="#c3d4ed" strokeWidth="1.3"/>
    <g className="map-case" role="button" tabIndex="0" aria-label={`Open ${appName}: ${c.decision}`} onClick={event=>open(event,c)} onKeyDown={event=>keyboard(event,c)}>
    <title>{appName}: {c.decision}</title><rect x="865" y={center-height/2} width="350" height="60" rx="10" fill={fill}/>
    <text x="879" y={center-height/2+22} className="map-case-id">{appName}</text>
    <text x="879" y={center-height/2+44} className="map-case-label">{c.decision}{sessions.length>0?` · ${sessions.length} ${sessions.length===1?'session':'sessions'}`:''}</text>
    </g>
    {sessions.map((session,index)=>{
     const first=session.signals.map(signal=>signal.ts_first).filter(Boolean).sort()[0];
     const timestamp=first?new Date(first).toLocaleString():`Session ${index+1}`;
     const top=center-height/2+60+index*40;
     return <g key={session.id} className="map-case" role="button" tabIndex="0" aria-label={`Open ${appName} session ${timestamp}: ${session.decision}`} onClick={event=>open(event,session)} onKeyDown={event=>keyboard(event,session)}>
      <title>{timestamp}: {session.decision} · {session.signals.length} signals</title>
      <rect x="875" y={top} width="330" height="34" rx="5" fill="#fff" stroke="#c3d4ed"/>
      <text x="884" y={top+14} className="map-case-label">{timestamp}</text>
      <text x="884" y={top+28} className="map-case-label">{session.decision} · {session.signals.length} signals</text>
     </g>;
    })}
   </g></g>;
  })}
 </svg></div></div></>;
}
