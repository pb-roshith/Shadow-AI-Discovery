"""Request measurements and explicitly captured model audit traces."""
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def field(value, name):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def measurements(response=None, seconds=None):
    """Normalize one call's measured usage and elapsed time, without text estimates.

    Providers name token counts differently. A missing side can be calculated
    from an actual total and the other known side. Ollama's model duration is
    supplied in nanoseconds; caller-measured elapsed seconds take precedence.
    """
    usage = field(response, 'usage') or field(response, 'usage_metadata')
    def first(*values):
        return next((number(value) for value in values if number(value) is not None), None)
    input_tokens = first(field(usage, 'input_tokens'), field(usage, 'prompt_tokens'), field(usage, 'prompt_token_count'), field(response, 'prompt_eval_count'))
    output_tokens = first(field(usage, 'output_tokens'), field(usage, 'completion_tokens'), field(usage, 'candidates_token_count'), field(response, 'eval_count'))
    total = first(field(usage, 'total_tokens'), field(usage, 'total_token_count'))
    if total is not None:
        if input_tokens is None and output_tokens is not None and total >= output_tokens:
            input_tokens = total - output_tokens
        elif output_tokens is None and input_tokens is not None and total >= input_tokens:
            output_tokens = total - input_tokens
    elapsed = number(seconds)
    if elapsed is None:
        nanoseconds = number(field(response, 'total_duration'))
        elapsed = nanoseconds / 1_000_000_000 if nanoseconds is not None else None
    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'duration_ms': round(elapsed * 1000, 3) if elapsed is not None else None,
    }


def write_request(app, request_id, status, metrics, provider=None, model=None):
    event = dict(ts=datetime.now(timezone.utc).isoformat(), app=app, request_id=str(request_id),
                 status=status, origin='live_metrics', provider=provider, model=model,
                 **{key: number(metrics.get(key)) for key in ('input_tokens', 'output_tokens', 'duration_ms')})
    try:
        path = ROOT / 'logs/request_metrics.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event) + '\n')
    except OSError:
        logging.getLogger(__name__).warning('Request measurements could not be written')


def write_model_trace(app, request_id, status, metrics, model, model_input, model_output=None, provider=None):
    """Capture model content separately from discovery's metadata evidence logs.

    Callers supply only the model messages and output, never SDK configuration,
    headers, exceptions, or credentials.
    """
    event = dict(ts=datetime.now(timezone.utc).isoformat(), app=app, request_id=str(request_id),
                 status=status, origin='model_trace', model=model, provider=provider,
                 model_input=model_input, model_output=model_output,
                 **{key: number(metrics.get(key)) for key in ('input_tokens', 'output_tokens', 'duration_ms')})
    try:
        path = ROOT / 'logs/model_traces.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
    except (OSError, TypeError, ValueError):
        logging.getLogger(__name__).warning('Model audit trace could not be written')
