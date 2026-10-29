"""Loan Risk Classifier: structured loan assessment with local Ollama."""
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shadow server/backend'))
from engine.request_metrics import measurements, write_model_trace
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import ollama
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from dotenv import dotenv_values

app = FastAPI(title='Loan Risk Classifier')
client = ollama.Client(host='http://127.0.0.1:11434', timeout=180)
CONFIG = {**os.environ, **{key: value for key, value in dotenv_values(Path(__file__).with_name('.env')).items() if value is not None}}
DEFAULT_MODEL = CONFIG.get('OLLAMA_MODEL') or 'qwen2.5:1.5b'


class Loan(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    currency: Literal['INR', 'USD', 'EUR', 'GBP'] = 'INR'
    loan_amount: float = Field(gt=0, le=1_000_000_000)
    annual_interest_rate: float = Field(ge=0, le=60)
    term_months: int = Field(ge=1, le=480, strict=True)
    monthly_income: float = Field(ge=0, le=1_000_000_000)
    monthly_expenses: float = Field(ge=0, le=1_000_000_000)
    existing_monthly_repayments: float = Field(ge=0, le=1_000_000_000)
    employment_type: Literal['salaried', 'self_employed', 'retired', 'unemployed']
    employment_years: float = Field(ge=0, le=60)
    missed_payments: int = Field(ge=0, le=120, strict=True)
    previous_default: bool = Field(strict=True)
    savings: float | None = Field(default=None, ge=0, le=1_000_000_000)
    collateral_value: float | None = Field(default=None, ge=0, le=1_000_000_000)


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')
    loan: Loan
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=150)


class Assessment(BaseModel):
    score: int = Field(ge=0, le=100, strict=True)
    explanation: str = Field(min_length=1, max_length=1200, description='Two or three qualitative sentences about the main loan-risk factors. Do not repeat numeric amounts or percentages; exact metrics are displayed separately.')
    risk_factors: list[str] = Field(max_length=5)
    mitigants: list[str] = Field(max_length=5)
    missing_information: list[str] = Field(max_length=5)


PROMPT = """Assess LOAN RISK using only the supplied structured loan application and computed
affordability metrics. Return a 0-100 loan-risk severity score and explain the values that
support it. Higher means greater repayment risk. It is NOT probability of default, a credit
rating, or an approval/rejection decision. Do not classify whether a situation is credit risk:
every request is a loan assessment.
Consider the proposed monthly instalment, existing repayments, total repayment-to-income
ratio, monthly surplus after expenses and all repayments, employment stability, missed
payments, previous defaults, savings and collateral. Income and expenses are monthly;
interest is annual percentage; amounts are in the supplied currency. Ratios and payment
amounts have already been calculated: use them, do not invent different values.
The UI displays the exact figures separately. Explain the direction of the factors in
words, without repeating any numeric amounts, ratios or percentages in the explanation.
Low 0-25: affordable payments, positive surplus, stable income and no adverse repayment
history. Moderate 26-50: some affordability or stability concerns. High 51-75: substantial
repayment stress or arrears. Severe 76-100: inability to afford payments or serious default
history. Multiple adverse factors increase risk; strong affordability and clean history
reduce it. Unknown optional savings/collateral are not zero and not proof of weakness.
An affordable loan with low repayment/income, positive surplus and no missed payments is
LOW risk: higher income and surplus REDUCE risk, they do not increase it. Negative surplus,
repayments exceeding income, missed payments and defaults INCREASE risk.
List adverse factors separately from mitigants. Explain missing information without
inventing facts. A savings/collateral value of zero explicitly means none, NOT unknown.
Keep explanation to 2-3 sentences and each list item to one short sentence.
Do not repeat the input fields. Do not use protected personal characteristics. Return only the JSON schema.
"""


def affordability(loan):
    rate = loan.annual_interest_rate / 1200
    payment = loan.loan_amount / loan.term_months if rate == 0 else loan.loan_amount * (rate / -math.expm1(-loan.term_months * math.log1p(rate)))
    total = loan.existing_monthly_repayments + payment
    return dict(monthly_payment=round(payment, 2), total_monthly_repayments=round(total, 2),
                repayment_to_income_percent=round(total / loan.monthly_income * 100, 2) if loan.monthly_income else None,
                monthly_surplus=round(loan.monthly_income - loan.monthly_expenses - total, 2),
                loan_to_collateral_percent=round(loan.loan_amount / loan.collateral_value * 100, 2) if loan.collateral_value else None)


def messages_for(loan, metrics):
    messages = [{'role': 'system', 'content': PROMPT}]
    # Reference examples teach the rubric; the submitted form remains the final input.
    for income, expenses, existing, missed, default, score, explanation, factors, mitigants in [
        (12000, 4000, 0, 0, False, 10, 'Income comfortably covers the proposed repayment and living expenses, leaving a positive surplus. Stable employment and clean repayment history reduce loan risk.', [], ['Low repayment-to-income ratio', 'Positive surplus', 'No missed payments or defaults']),
        (1000, 800, 500, 6, True, 95, 'Total repayments exceed income and the monthly surplus is negative. Missed payments and a previous default add severe repayment risk.', ['Repayments exceed income', 'Negative monthly surplus', 'Missed payments and previous default'], []),
    ]:
        example = Loan(loan_amount=12000, annual_interest_rate=0, term_months=12, monthly_income=income,
                       monthly_expenses=expenses, existing_monthly_repayments=existing,
                       employment_type='salaried', employment_years=5, missed_payments=missed, previous_default=default)
        messages.extend([{'role': 'user', 'content': json.dumps({'loan': example.model_dump(), 'computed_metrics': affordability(example)})},
                         {'role': 'assistant', 'content': json.dumps(dict(score=score, explanation=explanation, risk_factors=factors, mitigants=mitigants, missing_information=[]))}])
    messages.append({'role': 'user', 'content': json.dumps({'loan': loan.model_dump(), 'computed_metrics': metrics})})
    return messages


def local_models():
    return [m.model for m in client.list().models if m.model and not getattr(m, 'remote_host', None)
            and 'cloud' not in m.model.lower() and m.model != 'qwen3:0.6b']


@app.get('/api/health')
def health():
    return {'status': 'ok', 'repo': 'loan-risk-classifier'}


@app.get('/api/models')
def models():
    try:
        return {'models': local_models(), 'default': DEFAULT_MODEL}
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError):
        raise HTTPException(503, 'Ollama is unavailable. Start Ollama on this computer and retry.') from None


def record_invocation(model, request_id, status, metrics=None):
    path = Path(__file__).resolve().parents[2] / 'shadow server/backend/logs/ollama_calls.jsonl'
    event = dict(ts=datetime.now(timezone.utc).isoformat(), app='loan-risk-classifier', provider='Ollama',
                 model=model, request_id=request_id, status=status, origin='live_local', host='127.0.0.1:11434')
    if metrics is not None:
        event.update(metrics)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event) + chr(10))
    except OSError:
        logging.getLogger(__name__).warning('Local invocation metadata could not be written')


@app.post('/api/run')
def run(body: Request, response: Response):
    request_id = str(uuid.uuid4())
    response.headers['X-Request-ID'] = request_id
    try:
        installed = local_models()
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError):
        raise HTTPException(503, 'Ollama is unavailable. Start Ollama on this computer and retry.') from None
    if body.model not in installed:
        raise HTTPException(422, 'Choose an installed local model, then retry.')
    metrics = affordability(body.loan)
    outcome = 'failed'
    started = time.perf_counter()
    result = None
    messages = messages_for(body.loan, metrics)
    try:
        result = client.chat(model=body.model,
                             messages=messages,
                             format=Assessment.model_json_schema(), stream=False, think=False,
                             options={'temperature': 0, 'repeat_penalty': 1.15, 'num_predict': 700, 'num_ctx': 8192})
        assessment = Assessment.model_validate_json(result.message.content)
        outcome = 'success'
        return {**assessment.model_dump(), 'model': body.model, 'request_id': request_id,
                'currency': body.loan.currency, 'metrics': metrics,
                'classification': 'Low loan risk' if assessment.score <= 25 else 'Moderate loan risk' if assessment.score <= 50 else 'High loan risk' if assessment.score <= 75 else 'Severe loan risk'}
    except (ValidationError, ValueError):
        raise HTTPException(502, 'The model returned an invalid loan assessment. Try again or choose another local model.', headers={'X-Request-ID': request_id}) from None
    except httpx.TimeoutException:
        raise HTTPException(504, 'Local inference timed out. Retry after the model has loaded.', headers={'X-Request-ID': request_id}) from None
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError):
        raise HTTPException(503, 'Local inference failed. Check Ollama and the selected model.', headers={'X-Request-ID': request_id}) from None
    finally:
        record_invocation(body.model, request_id, outcome, measurements(result, time.perf_counter() - started))
        write_model_trace('loan-risk-classifier', request_id, outcome, measurements(result, time.perf_counter() - started), body.model, messages, result.message.content if result is not None else None, 'Ollama')
