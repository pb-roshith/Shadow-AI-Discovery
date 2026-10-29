"""Customer Assistant: multi-provider SDK chatbot on port 8105."""
import uuid
from typing import Literal
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from assistant_llm import complete, settings

app = FastAPI(title='Customer Assistant')

class Message(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=20000)

class Request(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    provider: Literal['gemini', 'mistral', 'openai'] = 'gemini'
    history: list[Message] = Field(default_factory=list, max_length=40)

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Enter a message first.')
        return value

@app.get('/api/health')
def health():
    return {'status': 'ok', 'repo': 'customer-assistant'}

@app.get('/api/providers')
def providers():
    config = settings()
    return {name: bool(config.get(key) or (name == 'gemini' and config.get('GOOGLE_API_KEY')))
            for name, key in [('gemini', 'GEMINI_API_KEY'), ('mistral', 'MISTRAL_API_KEY'), ('openai', 'OPENAI_API_KEY')]}

@app.post('/api/run')
def run(body: Request, response: Response):
    config = settings()
    key = {'gemini': 'GEMINI_API_KEY', 'mistral': 'MISTRAL_API_KEY', 'openai': 'OPENAI_API_KEY'}[body.provider]
    if not (config.get(key) or (body.provider == 'gemini' and config.get('GOOGLE_API_KEY'))):
        raise HTTPException(503, f'Configure {key} in customer-assistant/.env. Gemini also reads credit-dossier/.env.')
    request_id = str(uuid.uuid4())
    response.headers['X-Request-ID'] = request_id
    messages = [item.model_dump() for item in body.history] + [{'role': 'user', 'content': body.text}]
    try:
        text = complete(messages, body.provider, config, request_id)
        return {'text': text, 'provider': body.provider, 'request_id': request_id}
    except Exception as error:
        code = getattr(error, 'status_code', None) or getattr(error, 'code', None)
        detail = {401: 'The provider rejected the API key.', 403: 'The API key cannot access this model.',
                  404: 'The configured model is unavailable.', 429: 'Provider quota or rate limit reached. Try again later.'}.get(code,
                  'The provider request failed. Check the API key, model and connectivity.')
        raise HTTPException(502, detail, headers={'X-Request-ID': request_id}) from None
