import React, {useEffect, useState} from 'react';

const emptyLoan={currency:'INR',loan_amount:'',annual_interest_rate:'',term_months:'',monthly_income:'',monthly_expenses:'',existing_monthly_repayments:'',employment_type:'',employment_years:'',missed_payments:'',previous_default:'',savings:'',collateral_value:''};
const lowRiskExample={currency:'INR',loan_amount:100000,annual_interest_rate:12,term_months:12,monthly_income:50000,monthly_expenses:15000,existing_monthly_repayments:3000,employment_type:'salaried',employment_years:5,missed_payments:0,previous_default:'no',savings:100000,collateral_value:150000};
const highRiskExample={currency:'INR',loan_amount:500000,annual_interest_rate:18,term_months:24,monthly_income:20000,monthly_expenses:18000,existing_monthly_repayments:8000,employment_type:'self_employed',employment_years:0.5,missed_payments:6,previous_default:'yes',savings:0,collateral_value:0};
const groups=[
 ['Loan details',[
  ['loan_amount','Loan amount',0.01,1000000000,'0.01'],
  ['annual_interest_rate','Annual interest rate (%)',0,60,'0.01'],
  ['term_months','Loan term (months)',1,480,'1']]],
 ['Monthly affordability',[
  ['monthly_income','Monthly take-home income',0,1000000000,'0.01'],
  ['monthly_expenses','Monthly living expenses (excluding loan repayments)',0,1000000000,'0.01'],
  ['existing_monthly_repayments','Existing monthly loan repayments',0,1000000000,'0.01']]],
 ['Repayment history & financial cushion',[
  ['missed_payments','Missed payments in the last 12 months',0,120,'1'],
  ['savings','Available savings (optional)',0,1000000000,'0.01'],
  ['collateral_value','Collateral value (optional)',0,1000000000,'0.01']]],
];

export default function RiskClassifier({request}) {
 const [loan,setLoan]=useState(emptyLoan),[models,setModels]=useState([]),[model,setModel]=useState('');
 const [result,setResult]=useState(null),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('');
 async function refresh(){setLoading(true);setError('');try{const data=await request('/api/repos/loan-risk-classifier/models');setModels(data.models);setModel(previous=>data.models.includes(previous)?previous:data.models.includes(data.default)?data.default:data.models[0]||'');}catch(err){setError(err.message);}finally{setLoading(false);}}
 useEffect(()=>{refresh();},[]);
 function update(key,value){setLoan(previous=>({...previous,[key]:value}));setResult(null);setError('');}
 function loadExample(example){setLoan({...example});setResult(null);setError('');}
 async function classify(event){
  event.preventDefault();if(busy||!model)return;setBusy(true);setError('');setResult(null);
  const values=Object.fromEntries(Object.entries(loan).map(([key,value])=>[key,key==='currency'||key==='employment_type'?value:key==='previous_default'?value==='yes':value===''?null:Number(value)]));
  try{setResult(await request('/api/repos/loan-risk-classifier/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({loan:values,model})}));}catch(err){setError(err.message);}finally{setBusy(false);}
 }
 const money=value=>new Intl.NumberFormat('en-IN',{style:'currency',currency:result?.currency||loan.currency,maximumFractionDigits:2}).format(value);
 return <div className="risk-classifier"><a className="back" href="#/">Back to repositories</a><header><p className="eyebrow">LOCAL OLLAMA / LOAN ASSESSMENT</p><h1>Loan Risk Classifier</h1><p>Enter the loan and borrower values to assess repayment risk with local AI.</p></header>
  <div className="workspace loan-workspace"><form className="panel" onSubmit={classify}><div className="local-badge">Local Ollama</div><h2>Loan application</h2><p className="classifier-note">Enter all amounts in the same currency. Required values are marked *. Enter 0 when a required expense, repayment or missed-payment count is zero.</p>
   <div className="policy-examples"><button type="button" disabled={busy} onClick={()=>loadExample(lowRiskExample)}>Load low-risk example</button><button type="button" disabled={busy} onClick={()=>loadExample(highRiskExample)}>Load high-risk example</button></div><p className="classifier-note">Fictional examples for quick demos. Review or edit the values, then click Assess loan risk to run the model.</p>
   <label htmlFor="classifier-model">Local model</label><div className="model-selector"><select id="classifier-model" disabled={busy||loading} value={model} onChange={e=>{setModel(e.target.value);setResult(null);}}>{!models.length&&<option value="">{loading?'Checking Ollama...':'No local models available'}</option>}{models.map(name=><option key={name}>{name}</option>)}</select><button type="button" className="refresh-models" disabled={busy||loading} onClick={refresh}>Refresh</button></div>
   <label htmlFor="loan-currency">Currency *</label><select id="loan-currency" value={loan.currency} disabled={busy} onChange={e=>update('currency',e.target.value)}>{['INR','USD','EUR','GBP'].map(c=><option key={c}>{c}</option>)}</select>
   {groups.map(([title,fields],index)=><React.Fragment key={title}><fieldset className="loan-fields" disabled={busy}><legend>{title}</legend><div className="loan-field-grid">{fields.map(([key,label,min,max,step])=><label key={key} htmlFor={'loan-'+key}>{label}{key!=='savings'&&key!=='collateral_value'?' *':''}<input id={'loan-'+key} type="number" min={min} max={max} step={step} required={key!=='savings'&&key!=='collateral_value'} value={loan[key]} onChange={e=>update(key,e.target.value)}/></label>)}</div></fieldset>
   {index===1&&<fieldset className="loan-fields" disabled={busy}><legend>Employment stability</legend><div className="loan-field-grid"><label htmlFor="loan-employment">Income source *<select id="loan-employment" required value={loan.employment_type} onChange={e=>update('employment_type',e.target.value)}><option value="">Choose an income source</option><option value="salaried">Salaried</option><option value="self_employed">Self-employed</option><option value="retired">Retired / pension</option><option value="unemployed">Not employed</option></select></label><label htmlFor="loan-years">Years in current employment / income source *<input id="loan-years" type="number" required min="0" max="60" step="0.1" value={loan.employment_years} onChange={e=>update('employment_years',e.target.value)}/></label></div></fieldset>}</React.Fragment>)}
   <label htmlFor="loan-default">Previous loan default? *</label><select id="loan-default" required disabled={busy} value={loan.previous_default} onChange={e=>update('previous_default',e.target.value)}><option value="">Choose an answer</option><option value="no">No</option><option value="yes">Yes</option></select>
   <p className="classifier-note">Leave optional savings or collateral blank if unknown; enter 0 if none. Monthly payment estimates assume a fixed rate and exclude fees.</p>
   <button disabled={busy||!model}>{busy?'Assessing loan locally...':'Assess loan risk'}</button>{error&&<p className="error" role="alert">{error}</p>}
   <p className="classifier-note">The form values are sent to Ollama on this computer. Submitted inputs and model outputs are recorded in Analytics audit traces.</p>
  </form><section className="panel classifier-result" aria-live="polite" aria-busy={busy}><h2>Loan risk assessment</h2>{busy?<div className="empty"><p role="status">Ollama is assessing your loan values...</p></div>:result?<>
   <span className="classification-label">{result.classification}</span><div className="risk-number"><strong>{result.score}</strong><span>/100</span></div>
   <div className="risk-scale" role="meter" aria-label="Loan risk score" aria-valuemin={0} aria-valuemax={100} aria-valuenow={result.score}><i style={{width:result.score+'%'}}/></div><p className="classifier-note">Higher scores indicate greater loan repayment risk. This is an AI estimate, not a default probability or loan approval.</p>
   <h3>Affordability from your values</h3><dl className="loan-metrics"><dt>Proposed monthly payment</dt><dd>{money(result.metrics.monthly_payment)}</dd><dt>Total monthly loan repayments</dt><dd>{money(result.metrics.total_monthly_repayments)}</dd><dt>Repayments / monthly income</dt><dd>{result.metrics.repayment_to_income_percent===null?'Not available (zero income)':result.metrics.repayment_to_income_percent+'%'}</dd><dt>Surplus after expenses and repayments</dt><dd>{money(result.metrics.monthly_surplus)}</dd>{result.metrics.loan_to_collateral_percent!==null&&<><dt>Loan / collateral value</dt><dd>{result.metrics.loan_to_collateral_percent}%</dd></>}</dl>
   <h3>Why this score?</h3><p>{result.explanation}</p>
   {result.risk_factors.length>0&&<><h3>Factors increasing loan risk</h3><ul>{result.risk_factors.map((item,i)=><li key={i}>{item}</li>)}</ul></>}
   {result.mitigants.length>0&&<><h3>Factors reducing loan risk</h3><ul>{result.mitigants.map((item,i)=><li key={i}>{item}</li>)}</ul></>}
   {result.missing_information.length>0&&<><h3>Additional information to review</h3><ul>{result.missing_information.map((item,i)=><li key={i}>{item}</li>)}</ul></>}
   <details className="classifier-note"><summary>Model and request reference</summary><p>{result.model}</p><code>{result.request_id}</code></details>
  </>:<div className="empty"><p>Complete the loan form to get a score.</p><small>Ollama will assess the entered values and explain the result.</small></div>}
  <details className="scoring-guide"><summary>How to read the loan score</summary><p>0-25 Low / 26-50 Moderate / 51-75 High / 76-100 Severe</p><p>Monthly payment and ratios are calculated from your values. The score and explanation are generated by Ollama. This is an indicative assessment, not a validated lending model.</p></details>
  </section></div></div>;
}
