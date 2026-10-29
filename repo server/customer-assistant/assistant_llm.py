"""Official provider SDKs. Credentials remain in server configuration."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shadow server/backend'))
from engine.request_metrics import measurements, write_model_trace
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent

def settings():
    config = dict(os.environ)
    config.update({key: value for key, value in dotenv_values(HERE / '.env').items() if value is not None})
    return config

def complete(messages, provider, config, request_id):
    model = config.get({'gemini': 'GEMINI_MODEL', 'mistral': 'MISTRAL_MODEL', 'openai': 'OPENAI_MODEL'}[provider]) or {
        'gemini': 'gemini-2.5-flash', 'mistral': 'mistral-small-latest', 'openai': 'gpt-4o-mini'}[provider]
    outcome = 'failed'
    started = time.perf_counter()
    response = None
    text = None
    try:
        if provider == 'gemini':
            from google import genai
            from google.genai import types
            contents = [types.Content(role='model' if item['role'] == 'assistant' else 'user',
                                     parts=[types.Part.from_text(text=item['content'])]) for item in messages]
            with genai.Client(api_key=config.get('GEMINI_API_KEY') or config.get('GOOGLE_API_KEY'),
                              http_options=types.HttpOptions(timeout=60000)) as client:
                response = client.models.generate_content(model=model, contents=contents)
                text = response.text
        elif provider == 'mistral':
            from mistralai.client import Mistral
            with Mistral(api_key=config['MISTRAL_API_KEY'], timeout_ms=60000) as client:
                response = client.chat.complete(model=model, messages=messages)
                text = response.choices[0].message.content
        elif provider == 'openai':
            from openai import OpenAI
            with OpenAI(api_key=config['OPENAI_API_KEY'], timeout=60, max_retries=0) as client:
                response = client.responses.create(model=model, input=messages, store=False)
                text = response.output_text
        else:
            raise ValueError('Unsupported provider')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Provider returned no text')
        outcome = 'success'
        return text
    finally:
        record_invocation(provider, model, request_id, outcome, measurements(response, time.perf_counter() - started))
        write_model_trace('customer-assistant', request_id, outcome, measurements(response, time.perf_counter() - started), model, messages, text, provider)


def record_invocation(provider, model, request_id, outcome, metrics=None):
    # Application SDK telemetry, not a proxy capture. No messages, responses or keys.
    event = {'ts': datetime.now(timezone.utc).isoformat(), 'app': 'customer-assistant',
             'provider': {'gemini': 'Google', 'mistral': 'Mistral', 'openai': 'OpenAI'}[provider],
             'model': model, 'request_id': request_id, 'status': outcome, 'origin': 'live_sdk'}
    if metrics is not None:
        event.update(metrics)
    path = HERE.parents[1] / 'shadow server/backend/logs/sdk_calls.jsonl'
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event) + '\n')
    except OSError:
        import logging
        logging.getLogger(__name__).warning('SDK invocation telemetry could not be written')
