"""Presenter controls for S3. Only a server-generated fictional file can be sent."""
import json
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from engine.collectors.local import telemetry_path
from engine.request_metrics import measurements, write_request
from scenarios.data.make_dummy_extract import generate, TARGET_BYTES

router = APIRouter(prefix='/demos/s3', tags=['S3 demo'])
UPLOAD_LOCK = threading.Lock()
PROXY = 'http://priya:demo@127.0.0.1:8080'
CA = Path.home() / '.mitmproxy/mitmproxy-ca-cert.pem'
DESTINATION = 'https://chatgpt.com/backend-api/files'
NETWORK_FIELDS = {'ts', 'proxy_user', 'host', 'method', 'path_class', 'bytes_out', 'bytes_in', 'status', 'ai_host', 'dlp_blocked', 'flow_id'}
DLP_FIELDS = {'ts', 'proxy_user', 'host', 'method', 'label', 'match_count', 'bytes', 'blocked', 'flow_id'}


def records(name):
    path = telemetry_path(name + '.jsonl')
    if not path.exists():
        return []
    # Read a bounded tail; do not return unrelated users' telemetry to this page.
    with path.open('rb') as stream:
        size = stream.seek(0, 2)
        start = max(0, size - 256_000)
        stream.seek(start)
        if start:
            stream.readline()
        lines = stream.read().decode('utf-8', errors='replace').splitlines()
    result = []
    for line in lines:
        try:
            row = json.loads(line)
            if row.get('proxy_user') == 'priya' and row.get('host') == 'chatgpt.com' and row.get('flow_id'):
                result.append(row)
        except (ValueError, AttributeError):
            continue
    return result


@router.get('/status')
def status():
    reachable = False
    try:
        with socket.create_connection(('127.0.0.1', 8080), timeout=.5):
            reachable = True
    except OSError:
        pass
    return {'proxy_reachable': reachable, 'certificate_ready': CA.is_file(),
            'ready': reachable and CA.is_file(), 'identity': 'priya',
            'department': 'Retail Lending', 'destination': 'chatgpt.com',
            'file_name': 'dummy_customer_extract.csv', 'file_bytes': TARGET_BYTES, 'rows': 14,
            'setup_hint': 'Run start.bat from the Shadow AI Discovery workspace to start the demo proxy.',
            'proxy_ui_url': 'http://127.0.0.1:8081', 'discovery_url': 'http://127.0.0.1:5173'}


@router.post('/run')
def upload():
    if not UPLOAD_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'An S3 upload is already running. Wait for its result.')
    try:
        if not status()['ready']:
            raise HTTPException(503, 'Start the demo proxy on port 8080 and run proxy setup to create its certificate, then check readiness again.')
        known = {row['flow_id'] for row in records('proxy')}
        started = datetime.now(timezone.utc)
        started_timer = time.perf_counter()
        session = requests.Session()
        session.trust_env = False
        try:
            with session, TemporaryDirectory() as directory:
                file = generate(Path(directory) / 'dummy_customer_extract.csv')
                with file.open('rb') as stream:
                    response = session.post(DESTINATION, files={'file': (file.name, stream, 'text/csv')},
                                            proxies={'http': PROXY, 'https': PROXY}, verify=str(CA), timeout=45)
        except requests.exceptions.SSLError:
            raise HTTPException(502, 'Proxy certificate verification failed. Check the CA from proxy setup.') from None
        except requests.exceptions.ProxyError as error:
            message = 'Proxy authentication failed (407). Check the demo credentials.' if '407' in str(error) else 'The demo proxy is unreachable. Start it and retry.'
            raise HTTPException(502, message) from None
        except requests.exceptions.RequestException:
            raise HTTPException(502, 'The upload could not complete. Check the proxy and retry in offline mode.') from None
        elapsed = time.perf_counter() - started_timer
        blocked = response.status_code == 403 and response.headers.get('X-ShadowAI-DLP') == 'blocked'
        evidence = None
        for _ in range(25):
            candidates = []
            for row in records('proxy'):
                try:
                    current = datetime.fromisoformat(row['ts']) >= started
                except (KeyError, ValueError, TypeError):
                    continue
                if current and row['flow_id'] not in known and row.get('method') == 'POST' and row.get('path_class') == 'upload':
                    candidates.append(row)
            dlp = records('dlp')
            pairs = [(network, [row for row in dlp if row['flow_id'] == network['flow_id']]) for network in candidates]
            pairs = [(network, labels) for network, labels in pairs if labels]
            if len(pairs) == 1:
                network, labels = pairs[0]
                evidence = {'network': {k: v for k, v in network.items() if k in NETWORK_FIELDS},
                            'dlp': [{k: v for k, v in row.items() if k in DLP_FIELDS} for row in labels]}
                break
            time.sleep(.04)
        verified = bool(blocked and evidence and evidence['network'].get('status') == 403
                        and evidence['network'].get('dlp_blocked')
                        and any(row.get('label') == 'Customer PII' and row.get('match_count') == 14 and row.get('blocked') for row in evidence['dlp']))
        if evidence:
            write_request('priya-chatgpt', evidence['network']['flow_id'],
                          'blocked' if blocked else 'success' if response.ok else 'failed',
                          measurements(seconds=elapsed), provider='OpenAI')
        return {'blocked': blocked, 'verified': verified, 'http_status': response.status_code,
                'policy_header': 'blocked' if blocked else None, 'evidence': evidence,
                'message': 'The proxy blocked Priya\'s fictional customer upload.' if verified else
                'A block response was received, but matching audit evidence could not be verified. Check proxy logs.' if blocked else
                'The expected DLP block was not received. Check the proxy configuration before presenting.'}
    finally:
        UPLOAD_LOCK.release()


class DiscoveryRequest(BaseModel):
    flow_id: str = Field(min_length=1, max_length=80)


@router.post('/discover')
def discover(body: DiscoveryRequest | None = None):
    from engine.pipeline import run
    from engine.db import list_payloads
    target = None
    if body:
        target = next((row for row in records('proxy') if row['flow_id'] == body.flow_id), None)
        if target is None:
            raise HTTPException(409, 'The upload evidence is no longer available. Run the upload again.')
    summary = run('live', trigger={'type': 's3_presenter_demo'})
    def relevant(row):
        if row.get('user_id') != 'priya' or 'J4' not in row.get('join_rules_fired', []):
            return False
        for signal in row.get('signals', []):
            if signal.get('host') != 'chatgpt.com' or signal.get('channel') != 'DLP':
                continue
            if target is None:
                return True
            instant = datetime.fromisoformat(target['ts'])
            if datetime.fromisoformat(signal['ts_first']) <= instant <= datetime.fromisoformat(signal['ts_last']):
                return True
        return False
    candidates = [row for row in list_payloads('candidates') if relevant(row)]
    fields = {'id', 'name', 'channels', 'confidence', 'risk', 'decision', 'join_rules_fired'}
    return {'run_id': summary['id'], 'candidates': [{k: v for k, v in row.items() if k in fields} for row in candidates]}
