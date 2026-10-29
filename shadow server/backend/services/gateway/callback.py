import json
from pathlib import Path
from datetime import datetime, timezone
import uuid
import threading
from litellm.integrations.custom_logger import CustomLogger
from engine.request_metrics import measurements, write_model_trace, field

ROOT = Path(__file__).resolve().parents[2]
WRITE_LOCK = threading.Lock()

class MetadataCallback(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        metadata = data.setdefault('metadata', {})
        metadata.setdefault('request_id', str(uuid.uuid4()))
        # Record actual gateway acceptance even if the upstream later times out.
        self.record({'model': data.get('model'), 'messages': data.get('messages'), 'litellm_params': {'metadata': metadata}}, None, 'pending')
        return data

    def record(self, kwargs, response, status, start_time=None, end_time=None):
        params=kwargs.get('litellm_params',{})
        standard = kwargs.get('standard_logging_object') or {}
        metadata = {**(params.get('metadata') or {}), **(standard.get('metadata') or {})}
        headers=(params.get('proxy_server_request',{}) or {}).get('headers',{}) or {}
        app=metadata.get('app') or headers.get('x-app-id','unattributed')
        # Allowlisted application ID only; never serialize kwargs or exceptions.
        if app not in ('credit-dossier','policy-intelligence','shadow-discovery'):
            app='unattributed'
        usage=getattr(response,'usage',None)
        (ROOT/'logs').mkdir(exist_ok=True)
        model=kwargs.get('model') or params.get('model') or 'unknown'
        provider = ('Google' if 'gemini' in model else 'Mistral' if 'mistral' in model else 'Anthropic' if 'claude' in model else 'OpenAI' if 'gpt' in model else model.split('/', 1)[0].title())
        request_id = metadata.get('request_id') or kwargs.get('litellm_call_id') or standard.get('id')
        if not request_id:
            return
        event={'ts':datetime.now(timezone.utc).isoformat(),'app':app,'model':model,'provider':provider,
               'tokens':getattr(usage,'total_tokens',0) or 0,'status':status,
               'request_id':str(request_id), 'origin':'live', 'schema_version':1}
        seconds = (end_time - start_time).total_seconds() if isinstance(start_time, datetime) and isinstance(end_time, datetime) else None
        event.update(measurements(response, seconds))
        with WRITE_LOCK:
            choices = field(response, 'choices') or []
            output = field(field(choices[0], 'message'), 'content') if choices else None
            write_model_trace(app, request_id, status, event, model, kwargs.get('messages'), output, provider)
            with (ROOT/'logs/gateway.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(event)+'\n')

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.record(kwargs,response_obj,'success',start_time,end_time)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self.record(kwargs,response_obj,'failed',start_time,end_time)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.record(kwargs,response_obj,'success',start_time,end_time)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self.record(kwargs,response_obj,'failed',start_time,end_time)

metadata_callback=MetadataCallback()
