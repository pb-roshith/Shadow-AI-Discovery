import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from engine.analytics import build_analytics, read_requests, IST
from engine.api import app
from engine.request_metrics import measurements, write_model_trace


def event(identifier, ts='2026-10-28T12:00:00+05:30', app='credit-dossier', **extra):
    return dict(app=app, request_id=identifier, ts=ts, status='success', provider='Google', model='test-model',
                input_tokens=None, output_tokens=None, duration_ms=None, **extra)


class Analytics(unittest.TestCase):
    def test_audit_content_enriches_completed_gateway_without_leaking_into_summary(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); (root/'logs').mkdir()
            gateway=dict(ts='2026-10-28T12:00:00+05:30', app='credit-dossier', request_id='one',
                         provider='Google', model='gemini-test', origin='live', status='success',
                         input_tokens=10, output_tokens=5, duration_ms=200)
            (root/'logs/gateway.jsonl').write_text(json.dumps(gateway))
            with patch('engine.request_metrics.ROOT',root):
                write_model_trace('credit-dossier','one','pending',{},'gemini-test',[{'role':'user','content':'audit input'}])
                write_model_trace('credit-dossier','one','success',{},'gemini-test',None,'audit output')
            with patch('engine.analytics.ROOT',root),patch('engine.analytics.telemetry_path',side_effect=lambda name,base:base/'logs'/name):
                events,_=read_requests(include_content=True)
                metadata,_=read_requests()
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]['status'],'success')
            self.assertEqual(events[0]['model_input'][0]['content'],'audit input')
            self.assertEqual(events[0]['model_output'],'audit output')
            self.assertEqual(events[0]['input_tokens'],10)
            self.assertNotIn('audit input',json.dumps(metadata))
            self.assertNotIn('audit output',json.dumps(metadata))

    def test_trace_pagination_filter_total_tokens_and_missing_history(self):
        first=event('one'); first.update(input_tokens=10,output_tokens=0,model_input='hello',model_output='world')
        failed=event('two',ts='2026-10-28T13:00:00+05:30')
        failed['status']='failed'
        rows=[first,failed,event('other',app='customer-assistant')]
        client=TestClient(app)
        with patch('engine.analytics.read_requests',return_value=(rows,[])):
            result=client.get('/discovery/analytics/traces?period=all&application=credit-dossier&page_size=1').json()
            second=client.get('/discovery/analytics/traces?period=all&application=credit-dossier&page_size=1&page=2').json()
        self.assertEqual(result['total'],2)
        self.assertEqual(result['traces'][0]['request_id'],'two')
        self.assertIsNone(result['traces'][0]['total_tokens'])
        self.assertEqual(second['traces'][0]['total_tokens'],10)
        self.assertEqual(second['traces'][0]['model_output'],'world')
        self.assertEqual(client.get('/discovery/analytics/traces?page=0').status_code,422)

    def test_provider_usage_and_duration_are_measured_without_estimates(self):
        cases = [({'usage': {'prompt_tokens': 12, 'completion_tokens': 4}}, (12, 4)),
                 ({'usage': {'input_tokens': 9, 'output_tokens': 0}}, (9, 0)),
                 (SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=25, candidates_token_count=5)), (25, 5)),
                 ({'prompt_eval_count': 30, 'eval_count': 8}, (30, 8)), (None, (None, None))]
        for response, expected in cases:
            result = measurements(response, .125)
            self.assertEqual((result['input_tokens'], result['output_tokens']), expected)
            self.assertEqual(result['duration_ms'], 125)
        self.assertIsNone(measurements({'usage': {'prompt_tokens': float('nan'), 'completion_tokens': -1}})['input_tokens'])

    def test_calculates_missing_token_side_and_converts_local_model_time(self):
        self.assertEqual(measurements({'usage': {'total_tokens': 25, 'input_tokens': 20}})['output_tokens'],5)
        self.assertEqual(measurements({'usage': {'total_tokens': 25, 'output_tokens': 5}})['input_tokens'],20)
        self.assertEqual(measurements({'usage': {'total_tokens': 0, 'input_tokens': 0}})['output_tokens'],0)
        self.assertIsNone(measurements({'usage': {'total_tokens': 5, 'input_tokens': 20}})['output_tokens'])
        response={'prompt_eval_count': 20, 'eval_count': 5, 'total_duration': 125_000_000}
        self.assertEqual(measurements(response),{'input_tokens':20,'output_tokens':5,'duration_ms':125})
        self.assertEqual(measurements(response, .25)['duration_ms'],250)

    def test_timezone_calendar_counts_and_selected_period(self):
        events = [event('today'),event('yesterday','2026-10-27T12:00:00+05:30'),
                  event('previous-week','2026-10-25T12:00:00+05:30'),event('previous-month','2026-09-30T12:00:00+05:30'),
                  event('ist-today','2026-10-27T20:00:00+00:00'),event('future','2026-11-01T12:00:00+05:30')]
        data=build_analytics(events,now=datetime(2026,10,28,18,tzinfo=IST))
        self.assertEqual(data['summary']['requests'],3)
        self.assertEqual(data['applications'][0]['counts'],{'today':2,'week':3,'month':4})
        self.assertEqual(sum(day['requests'] for day in data['series']),3)
        self.assertEqual(len(data['applications']),6)
        self.assertIsNone(data['summary']['input_tokens'])

    def test_filter_coverage_failures_and_per_application_counts(self):
        first=event('one'); first.update(input_tokens=10,output_tokens=5,duration_ms=100)
        second=event('two'); second.update(duration_ms=500,status='failed')
        other=event('other',app='customer-assistant')
        data=build_analytics([first,second,other],application='credit-dossier',now=datetime(2026,10,28,18,tzinfo=IST))
        self.assertEqual(data['summary']['input_tokens'],10)
        self.assertEqual(data['summary']['avg_duration_ms'],300)
        self.assertNotIn('p95_duration_ms', data['summary'])
        self.assertNotIn('recent_requests', data)
        self.assertEqual(data['applications'][0]['failed'],1)
        self.assertEqual(data['summary']['token_measured_requests'],1)
        self.assertEqual(data['summary']['failed'],1)
        self.assertEqual(data['summary']['requests'],2)
        self.assertEqual(next(a for a in data['applications'] if a['id']=='customer-assistant')['requests'],1)

    def test_deduplicates_lifecycle_and_browser_metrics_excludes_fixtures_and_private_data(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); (root/'logs').mkdir()
            gateway=dict(ts='2026-10-28T12:00:00+05:30',app='credit-dossier',request_id='gateway-one',provider='Google',origin='live',status='pending')
            rows=[gateway,{**gateway,'status':'success','input_tokens':10,'output_tokens':5,'duration_ms':123},
                  {**gateway,'status':'success','input_tokens':10,'output_tokens':5,'duration_ms':123},
                  {**gateway,'request_id':'fake','origin':'seeded_demo'}]
            (root/'logs/gateway.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            proxy=dict(ts=gateway['ts'],proxy_user='priya',host='chatgpt.com',flow_id='flow-one',dlp_blocked=True,status=403,prompt='must-not-return')
            (root/'logs/proxy.jsonl').write_text(json.dumps(proxy))
            metric=dict(ts=gateway['ts'],app='priya-chatgpt',request_id='flow-one',origin='live_metrics',status='blocked',duration_ms=50)
            (root/'logs/request_metrics.jsonl').write_text(json.dumps(metric)+'\nnot-json')
            with patch('engine.analytics.ROOT',root),patch('engine.analytics.telemetry_path',side_effect=lambda name,base:base/'logs'/name):
                events,warnings=read_requests()
            self.assertEqual(len(events),2)
            self.assertEqual(next(e for e in events if e['app']=='credit-dossier')['status'],'success')
            self.assertEqual(next(e for e in events if e['app']=='priya-chatgpt')['duration_ms'],50)
            self.assertNotIn('must-not-return',json.dumps(events))
            self.assertEqual(len(warnings),1)

    def test_api_validation_and_empty_state(self):
        client=TestClient(app)
        with patch('engine.analytics.read_requests',return_value=([],[])):
            result=client.get('/discovery/analytics').json()
        self.assertEqual(len(result['applications']),6)
        self.assertEqual(result['summary']['requests'],0)
        self.assertIsNone(result['summary']['avg_duration_ms'])
        self.assertEqual(client.get('/discovery/analytics?application=missing').status_code,422)
        self.assertEqual(client.get('/discovery/analytics?period=year').status_code,422)
