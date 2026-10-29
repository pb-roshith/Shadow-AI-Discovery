"""Policy Intelligence: company loan policy checks on port 8102."""
import os
import uuid
from pathlib import Path
from typing import Literal
from dotenv import dotenv_values
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from policy_agent import assess, explain, load_policy, policy_document, PROVIDERS, provider_key, provider_model

HERE = Path(__file__).resolve().parent
app = FastAPI(title='Policy Intelligence')


class Loan(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)
    company_name: str = Field(min_length=1, max_length=160)
    industry: Literal['manufacturing', 'services', 'technology', 'trading', 'gambling', 'speculative_finance']
    purpose: Literal['working_capital', 'equipment', 'expansion', 'speculation', 'debt_refinancing']
    years_in_business: float = Field(ge=0, le=200)
    loan_amount: float = Field(gt=0, le=1e12)
    term_months: int = Field(ge=1, le=600)
    annual_revenue: float = Field(ge=0, le=1e12)
    annual_operating_cash_flow: float = Field(ge=-1e12, le=1e12)
    existing_annual_debt_service: float = Field(ge=0, le=1e12)
    collateral_value: float = Field(ge=0, le=1e12)
    credit_score: int = Field(ge=300, le=900)
    defaults_last_3_years: int = Field(ge=0, le=100)
    kyc_complete: bool
    audited_financials: bool


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')
    loan: Loan
    ai_explanation: bool = False
    provider: Literal['openai', 'mistral', 'gemini'] = 'openai'


def settings():
    config = dict(os.environ)
    config.update({key: value for key, value in dotenv_values(HERE / '.env').items() if value is not None})
    return config


@app.get('/api/health')
def health():
    return {'status': 'ok', 'repo': 'policy-intelligence'}


@app.get('/api/policy')
def policy():
    config = settings()
    providers = {name: {'label': spec['label'], 'available': bool(provider_key(config, name)), 'model': provider_model(config, name)}
                 for name, spec in PROVIDERS.items()}
    return {**load_policy(), 'document': policy_document(), 'ai_available': any(p['available'] for p in providers.values()), 'providers': providers}


@app.get('/api/policy/download')
def download():
    return FileResponse(HERE / 'bank_policy.json', media_type='application/json', filename='dummy-bank-lending-policy.json')


@app.post('/api/run')
def run(body: Request, response: Response):
    request_id = str(uuid.uuid4())
    response.headers['X-Request-ID'] = request_id
    result = assess(body.loan.model_dump())
    result.update(request_id=request_id, agent='Policy Intelligence', ai_status='not_requested', explanation=None, provider=body.provider)
    if body.ai_explanation:
        config = settings()
        spec = PROVIDERS[body.provider]
        result['model'] = provider_model(config, body.provider)
        if not provider_key(config, body.provider):
            result.update(ai_status='unavailable', ai_message=f"Configure {spec['key']} in policy-intelligence/.env to add a {spec['label']} explanation. Policy checks are complete.")
        else:
            try:
                result.update(explanation=explain(body.loan.model_dump(), result, config, request_id, provider=body.provider), ai_status='success')
            except Exception as error:
                code = getattr(error, 'status_code', None) or getattr(error, 'code', None)
                reason = {401: 'The provider rejected the API key.', 403: 'The API key cannot access this model.',
                          404: 'The configured model is unavailable.', 429: 'Provider quota or rate limit reached.'}.get(code, 'Check the API key, model and connectivity.')
                result.update(ai_status='failed', ai_message=f"{spec['label']} explanation failed. {reason} Policy checks are complete.")
    return result
