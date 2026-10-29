"""Independent Credit Dossier FastAPI server (port 8101)."""
import os
import uuid
from pathlib import Path
from typing import Literal
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from dossier.llm import summarise
from dossier.memo import MAX_BYTES, MAX_TEXT, extract_memo, grounded_prompt

HERE = Path(__file__).resolve().parent
for key, value in dotenv_values(HERE / '.env').items():
    if value is not None:
        os.environ[key] = value
app = FastAPI(title='Credit Dossier')


class Request(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    memo: str = Field(min_length=1, max_length=MAX_TEXT)
    provider: Literal['gemini', 'mistral'] = os.getenv('DOSSIER_PROVIDER', 'gemini')


@app.get('/api/health')
def health():
    return {'status': 'ok', 'repo': HERE.name}


@app.post('/api/run')
def run(body: Request, response: Response):
    request_id = str(uuid.uuid4())
    response.headers['X-Request-ID'] = request_id
    if not body.text.strip():
        raise HTTPException(422, 'Enter some content first.')
    if not body.memo.strip():
        raise HTTPException(422, 'Upload a memo before asking a question.')
    key = 'GEMINI_API_KEY' if body.provider == 'gemini' else 'MISTRAL_API_KEY'
    if os.getenv('DOSSIER_ROUTE', 'gateway') == 'sdk' and not (os.getenv(key) or (body.provider == 'gemini' and os.getenv('GOOGLE_API_KEY'))):
        raise HTTPException(503, f'Configure {key} in repo server/credit-dossier/.env.')
    try:
        return {'text': summarise(grounded_prompt(body.memo, body.text), provider=body.provider, request_id=request_id), 'provider': body.provider, 'request_id': request_id}
    except Exception as error:
        status = getattr(error, 'code', None) or getattr(error, 'status_code', None)
        if getattr(error, 'response', None) is not None:
            status = error.response.status_code
        details = {
            400: 'The provider rejected the request. Check the configured API key and model.',
            401: 'The provider rejected the API key. Update the backend .env and restart the server.',
            403: 'The API key does not have permission to use this model.',
            404: 'The configured model is unavailable. Check GEMINI_MODEL or MISTRAL_MODEL.',
            429: 'Provider quota or rate limit reached. Check your provider quota and try again later.',
            503: 'The AI model is experiencing high demand. Try again shortly.',
            504: 'The AI provider timed out. Try again shortly.',
        }
        if status in details:
            raise HTTPException(502, details[status], headers={'X-Request-ID': request_id}) from None
        raise HTTPException(502, 'Provider request failed. Check backend credentials, model and connectivity.', headers={'X-Request-ID': request_id}) from None


@app.post('/api/memo')
async def upload_memo(file: UploadFile):
    try:
        content = await file.read(MAX_BYTES + 1)
        memo, sections = extract_memo(file.filename or '', content)
        return {'name': Path((file.filename or 'Memo').replace('\\', '/')).name, 'text': memo, 'sections': sections, 'characters': len(memo)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except Exception:
        raise HTTPException(422, 'Unable to read this document. Upload a valid PDF, Word or UTF-8 text file.') from None
    finally:
        await file.close()
