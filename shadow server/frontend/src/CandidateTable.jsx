import React from 'react';

export default function CandidateTable({rows, scenarios, candidateLabel, onOpen, Badge, Chip, empty}) {
 return <div className="panel table-panel reference-table candidate-table"><table>
  <thead><tr>{['ID','Scenario','AI usage','Clues linked','Channels','Inventory','Confidence','Risk','Decision'].map(label=><th key={label}>{label}</th>)}</tr></thead>
  <tbody>{rows.map(row=>{
   const c=row.candidate;
   const scenario=scenarios.find(s=>s.result?.id===c.id||s.candidate_ids?.includes(c.id));
   return <tr key={c.id} onClick={()=>onOpen(c)} tabIndex={0} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onOpen(c);}}} aria-label={'Open '+row.label}>
    <td><b>{candidateLabel(c)}</b></td><td>{scenario?.displayNumber||'\u2014'}</td>
    <td><b>{row.label}</b><small>{scenario?.title||c.entity||'Linked AI usage'}</small>
     {!row.sessions.length&&row.records.length>1&&<details className="candidate-sessions" onClick={event=>event.stopPropagation()} onKeyDown={event=>event.stopPropagation()}>
      <summary>{row.records.length} provider records</summary>
      <small>Scores and decision follow current discovery. Raised issues take priority. Open a provider to inspect its evidence.</small>
      {row.records.map(record=><button type="button" className="candidate-link" key={record.id} onClick={()=>onOpen(record)}>
       <span>{candidateLabel(record)} · {record.provider}</span><Badge value={record.decision}/>
      </button>)}
     </details>}
     {row.sessions.length>0&&<details className="candidate-sessions" onClick={event=>event.stopPropagation()} onKeyDown={event=>event.stopPropagation()}>
      <summary>{row.sessions.length} {row.sessions.length===1?'session':'sessions'}</summary>
      <small>Scores and decision reflect the highest-priority session. Open a session to inspect its evidence.</small>
      {row.sessions.map(session=>{
       const first=session.signals.map(signal=>signal.ts_first).filter(Boolean).sort()[0];
       return <button type="button" className="candidate-link" key={session.id} onClick={()=>onOpen(session)}>
        <span>{candidateLabel(session)} · {first?new Date(first).toLocaleString():'Time unavailable'}</span><Badge value={session.decision}/>
       </button>;
      })}
     </details>}
    </td>
    <td>{row.signals.length} via {row.joinRules.join(', ')||'single clue'}</td>
    <td>{row.channels.map(channel=><Chip key={channel}>{channel}</Chip>)}</td>
    <td><Badge value={c.inventory.status}/></td><td><b>{c.confidence}</b></td><td><b>{c.risk}</b></td><td><Badge value={c.decision}/></td>
   </tr>;
  })}</tbody>
 </table>{!rows.length&&empty}</div>;
}
