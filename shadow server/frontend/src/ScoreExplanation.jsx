import React from 'react';

export function ScoreExplanation({title, score, factors = [], risk = false, signals = []}) {
 const evidence = new Map(signals.map(s=>[s.signal_id,s]));
 return <section className="panel compact-factors score-explanation">
  <h2>{title}: {score}/100</h2>
  <p>{risk?'This score describes potential harm based on the observed evidence and controls.':'This score describes the strength of evidence for AI usage. It is a rule-based score, not a percentage probability.'}</p>
  <p className="score-calculation"><b>Why {score}?</b> {factors.map(f=>`${f.name} ${f.points}`).join(' + ')} = <b>{score}/100</b>.</p>
  {factors.length===0&&<p>Scoring details are unavailable for this saved result.</p>}
  {factors.map(f=><div className="compact-factor" key={f.name}>
   <div className="compact-factor-row"><span>{f.name}</span><div className={'compact-factor-bar '+(risk?'risk':'')} role="meter" aria-label={f.name} aria-valuemin={0} aria-valuemax={f.max} aria-valuenow={f.points}><i style={{width:(f.max?Math.min(100,Math.max(0,f.points/f.max*100)):0)+'%'}}/></div><b>{f.points}/{f.max}</b></div>
   <p>{f.explanation||`${f.reason}. This adds ${f.points} of ${f.max} possible points.`}</p>
   {f.scoring_rule&&<details><summary>Point rules for {f.name.toLowerCase()}</summary><p>{f.scoring_rule}</p><p>These weights were saved with this result.</p></details>}
   <details><summary>Evidence considered</summary><ul>{(f.signal_ids||[]).map(id=>{const s=evidence.get(id);return <li key={id}>{s?`${s.channel}: ${s.signal_type.replaceAll('_',' ')} — ${s.source_ref}`:id}</li>;})}</ul>{!f.signal_ids?.length&&<p>No linked signals were recorded for this factor. Context from registers or inventory may still contribute points.</p>}</details>
  </div>)}
  {!factors.some(f=>f.explanation)&&factors.length>0&&<p>This saved result has brief explanations. Run discovery again to save the expanded explanations and point rules.</p>}
 </section>;
}

export function DecisionExplanation({candidate:c}) {
 const trace=c.decision_trace||[];
 const winner=trace.findIndex(t=>t.fired);
 const displayedTrace=[...trace].sort((a,b)=>a.rule.localeCompare(b.rule,undefined,{numeric:true}));
 return <div className="decision-explanation-details"><p>Rules are listed by number. Credential exposure and high risk take priority over approved usage.</p><ol className="compact-rules">{displayedTrace.map(t=><li className={t.fired?'selected-rule':''} key={t.rule}><b>{t.rule}: {t.condition} → {t.decision}</b><p>{t.fired?'Applied: this rule determined the decision.':winner>=0&&trace.indexOf(t)>winner?'Not applied: a higher-priority rule already determined the decision.':t.matched?'Condition matched.':'Not matched: this condition was not met.'}</p></li>)}</ol></div>;
}
