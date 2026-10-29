"""Provider-neutral text generation using the official Gemini and Mistral SDKs."""
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'shadow server/backend'))
from engine.request_metrics import measurements, write_model_trace
import uuid


def summarise(text, provider=None, model=None, route=None, request_id=None, app_id='credit-dossier'):
    provider = (provider or os.getenv('DOSSIER_PROVIDER', 'gemini')).lower()
    if provider not in ('gemini', 'mistral'):
        raise ValueError('Supported providers: gemini, mistral')
    route = route or os.getenv('DOSSIER_ROUTE', 'gateway')
    if route == 'gateway':
        import httpx
        request_id = request_id or str(uuid.uuid4())
        selected = model or (os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite') if provider == 'gemini' else 'mistral-small')
        started = time.perf_counter()
        payload, result, outcome = None, None, 'failed'
        try:
            response = httpx.post(
                os.getenv('GATEWAY_URL', 'http://127.0.0.1:4000').rstrip('/') + '/v1/chat/completions',
                headers={'x-app-id': app_id, 'x-request-id': request_id},
                json={'model': selected, 'messages': [{'role': 'user', 'content': text}],
                      'metadata': {'app': app_id, 'request_id': request_id}},
                timeout=45,
            )
            response.raise_for_status()
            payload = response.json()
            result = payload['choices'][0]['message']['content']
            outcome = 'success'
            return result
        finally:
            write_model_trace(app_id, request_id, outcome, measurements(payload, time.perf_counter() - started),
                              (payload or {}).get('model') or selected, [{'role': 'user', 'content': text}], result,
                              'Google' if provider == 'gemini' else 'Mistral')
    if route != 'sdk':
        raise ValueError('Supported routes: gateway, sdk')
    key = (os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')) if provider == 'gemini' else os.getenv('MISTRAL_API_KEY')
    if not key:
        raise ValueError('Provider API key is required')
    selected = model or (os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite') if provider == 'gemini' else os.getenv('MISTRAL_MODEL', 'mistral-small-latest'))
    outcome = 'failed'
    started = time.perf_counter()
    metrics = {}
    result = None
    request_id = request_id or str(uuid.uuid4())
    try:
        result = _sdk_summarise(text, provider, selected, metrics)
        outcome = 'success'
        return result
    finally:
        metrics['duration_ms'] = round((time.perf_counter() - started) * 1000, 3)
        record_invocation(provider, selected, request_id, outcome, app_id, metrics)
        write_model_trace(app_id, request_id, outcome, metrics, selected, text, result, 'Google' if provider == 'gemini' else 'Mistral')


def record_invocation(provider, model, request_id, status, app_id, metrics=None):
    import json
    import logging
    from pathlib import Path
    from datetime import datetime, timezone
    if app_id != 'credit-dossier':
        return
    path = Path(__file__).resolve().parents[3] / 'shadow server/backend/logs/sdk_calls.jsonl'
    event = dict(ts=datetime.now(timezone.utc).isoformat(), app=app_id,
                 provider='Google' if provider == 'gemini' else 'Mistral', model=model,
                 request_id=request_id, status=status, origin='live_sdk')
    if metrics is not None:
        event.update(metrics)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event) + '\n')
    except OSError:
        logging.getLogger(__name__).warning('SDK invocation telemetry could not be written')


def _sdk_summarise(text, provider, model, metrics=None):
    if provider == 'gemini':
        from google import genai
        from google.genai import types
        key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if not key:
            raise ValueError('GEMINI_API_KEY is required')
        with genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000)) as client:
            response = client.models.generate_content(model=model or os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite'), contents=text)
            if metrics is not None:
                metrics.update(measurements(response))
            if not response.text:
                raise ValueError('Gemini returned no text')
            return response.text
    if provider == 'mistral':
        from mistralai.client import Mistral
        if not os.getenv('MISTRAL_API_KEY'):
            raise ValueError('MISTRAL_API_KEY is required')
        with Mistral(api_key=os.environ['MISTRAL_API_KEY'], timeout_ms=60000) as client:
            response = client.chat.complete(model=model or os.getenv('MISTRAL_MODEL', 'mistral-small-latest'), messages=[{'role': 'user', 'content': text}])
            if metrics is not None:
                metrics.update(measurements(response))
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError('Mistral returned no text')
            return content
    raise ValueError('Supported providers: gemini, mistral')
