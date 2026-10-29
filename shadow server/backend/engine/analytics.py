"""Live measurements aggregated independently of discovery's evidence sessions."""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from engine.config import ROOT
from engine.collectors.local import telemetry_path
from engine.request_metrics import number

router = APIRouter(prefix='/discovery', tags=['Analytics'])
IST = timezone(timedelta(hours=5, minutes=30))
APPLICATIONS = [
    ('credit-dossier', 'Credit Dossier', 'AI gateway / SDK'),
    ('policy-intelligence', 'Policy Intelligence', 'AI SDK'),
    ('priya-chatgpt', 'Priya → ChatGPT', 'Browser / DLP'),
    ('creditdb-MCP', 'CreditDB MCP', 'Database tools'),
    ('customer-assistant', 'Customer Assistant', 'AI SDK'),
    ('loan-risk-classifier', 'Loan Risk Classifier', 'Local Ollama'),
]
APP_IDS = {item[0] for item in APPLICATIONS}


def read_requests(include_content=False):
    requests, warnings = {}, []
    sources = [('sdk_calls.jsonl', 'live_sdk'), ('gateway.jsonl', 'live'),
               ('ollama_calls.jsonl', 'live_local'), ('mcp_audit.jsonl', None),
               ('proxy.jsonl', None), ('request_metrics.jsonl', 'live_metrics'),
               ('model_traces.jsonl', 'model_trace')]
    for name, origin in sources:
        path = telemetry_path(name, ROOT)
        if not path.exists():
            continue
        invalid = 0
        try:
            with path.open(encoding='utf-8') as stream:
                for index, line in enumerate(stream, 1):
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError()
                        if event.get('origin') in ('replay', 'seeded_demo', 'static_fixture'):
                            continue
                        if origin and event.get('origin') != origin:
                            continue
                        app = event.get('app')
                        request_id = event.get('request_id')
                        status = event.get('status', 'unknown')
                        if name == 'proxy.jsonl':
                            if event.get('proxy_user') != 'priya' or event.get('host') != 'chatgpt.com' or not event.get('flow_id'):
                                continue
                            app, request_id = 'priya-chatgpt', event['flow_id']
                            code = event.get('status', 0)
                            status = 'blocked' if event.get('dlp_blocked') else 'success' if isinstance(code, int) and 200 <= code < 400 else 'failed'
                        if name == 'mcp_audit.jsonl':
                            if event.get('server') != 'creditdb':
                                continue
                            app = 'creditdb-MCP'
                        if app not in APP_IDS:
                            continue
                        instant = datetime.fromisoformat(event['ts'].replace('Z', '+00:00'))
                        if instant.tzinfo is None:
                            raise ValueError()
                        request_id = str(request_id or f'{name}:{index}')
                        key = (app, request_id)
                        metrics = {key: number(event.get(key)) for key in ('input_tokens', 'output_tokens', 'duration_ms')}
                        row = dict(app=app, request_id=request_id, ts=instant.isoformat(), status=status if status in ('pending', 'success', 'failed', 'blocked') else 'unknown',
                                   provider=event.get('provider') or ('OpenAI' if app == 'priya-chatgpt' else 'MCP' if app == 'creditdb-MCP' else None),
                                   model=event.get('model'), **metrics)
                        if include_content:
                            row.update(model_input=event.get('model_input') if name == 'model_traces.jsonl' else None,
                                       model_output=event.get('model_output') if name == 'model_traces.jsonl' else None)
                        previous = requests.get(key)
                        if previous:
                            if previous['status'] != 'pending' and row['status'] == 'pending':
                                # A pre-call content trace can enrich a completed
                                # metadata row without reverting its outcome.
                                row.update({field: value for field, value in previous.items() if value is not None})
                            # Completion and app-side measurements enrich the same request.
                            for field in ('input_tokens', 'output_tokens', 'duration_ms', 'provider', 'model') + (('model_input', 'model_output') if include_content else ()):
                                if row[field] is None:
                                    row[field] = previous[field]
                        requests[key] = row
                    except (ValueError, KeyError, TypeError, AttributeError):
                        invalid += 1
        except OSError:
            warnings.append(f'Could not read {name}.')
        if invalid:
            warnings.append(f'{invalid} invalid metadata records skipped in {name}.')
    return list(requests.values()), warnings


def summarize(events):
    durations = sorted(e['duration_ms'] for e in events if e['duration_ms'] is not None)
    def token_total(key):
        values = [e[key] for e in events if e[key] is not None]
        return sum(values) if values else None
    return dict(requests=len(events), success=sum(e['status'] == 'success' for e in events),
                failed=sum(e['status'] == 'failed' for e in events), blocked=sum(e['status'] == 'blocked' for e in events),
                pending=sum(e['status'] == 'pending' for e in events), unknown=sum(e['status'] == 'unknown' for e in events),
                input_tokens=token_total('input_tokens'), output_tokens=token_total('output_tokens'),
                avg_duration_ms=round(sum(durations) / len(durations), 2) if durations else None,
                token_measured_requests=sum(e['input_tokens'] is not None and e['output_tokens'] is not None for e in events),
                timed_requests=len(durations))


def build_analytics(events, period='week', application='all', now=None):
    now = (now or datetime.now(IST)).astimezone(IST)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    events = [event for event in events if datetime.fromisoformat(event['ts']) <= now]
    first = min((datetime.fromisoformat(e['ts']).astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0) for e in events), default=today)
    start = {'today': today, 'week': week, 'month': month, 'all': first}[period]
    selected = [e for e in events if datetime.fromisoformat(e['ts']) >= start and (application == 'all' or e['app'] == application)]
    applications = []
    for app_id, name, kind in APPLICATIONS:
        all_app = [e for e in events if e['app'] == app_id]
        current = [e for e in all_app if datetime.fromisoformat(e['ts']) >= start]
        counts = {key: sum(datetime.fromisoformat(e['ts']) >= beginning for e in all_app) for key, beginning in [('today', today), ('week', week), ('month', month)]}
        applications.append(dict(id=app_id, name=name, kind=kind, counts=counts, **summarize(current)))
    # Keep the chart bounded while totals and request counts cover the full selection.
    chart_start = max(start, today - timedelta(days=365))
    days = (today - chart_start).days + 1
    series = []
    for index in range(days):
        day = chart_start + timedelta(days=index)
        daily = [e for e in selected if datetime.fromisoformat(e['ts']).astimezone(IST).date() == day.date()]
        series.append(dict(date=day.date().isoformat(), **summarize(daily)))
    return dict(generated_at=now.isoformat(), timezone='Asia/Kolkata', period=period, application=application,
                period_start=start.isoformat(), period_end=now.isoformat(), summary=summarize(selected),
                applications=applications, series=series, chart_truncated=chart_start > start)


@router.get('/analytics')
def analytics(period: str = Query('week', pattern='^(today|week|month|all)$'),
              application: str = Query('all', pattern='^(all|credit-dossier|policy-intelligence|priya-chatgpt|creditdb-MCP|customer-assistant|loan-risk-classifier)$')):
    events, warnings = read_requests()
    return {**build_analytics(events, period, application), 'warnings': warnings}


@router.get('/analytics/traces')
def audit_traces(period: str = Query('week', pattern='^(today|week|month|all)$'),
                 application: str = Query('all', pattern='^(all|credit-dossier|policy-intelligence|priya-chatgpt|creditdb-MCP|customer-assistant|loan-risk-classifier)$'),
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    events, warnings = read_requests(include_content=True)
    report = build_analytics(events, period, application)
    start, end = datetime.fromisoformat(report['period_start']), datetime.fromisoformat(report['period_end'])
    selected = sorted((e for e in events if start <= datetime.fromisoformat(e['ts']) <= end
                       and (application == 'all' or e['app'] == application)), key=lambda e: datetime.fromisoformat(e['ts']), reverse=True)
    rows = []
    for event in selected[(page - 1) * page_size:page * page_size]:
        total = event['input_tokens'] + event['output_tokens'] if event['input_tokens'] is not None and event['output_tokens'] is not None else None
        rows.append({**event, 'total_tokens': total})
    return dict(traces=rows, total=len(selected), page=page, page_size=page_size, warnings=warnings)
