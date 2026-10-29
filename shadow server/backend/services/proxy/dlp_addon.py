"""Inspect buffered uploads before opening an upstream connection."""
import sys
from pathlib import Path
from mitmproxy import http
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.proxy.dlp_rules import scan
from services.proxy.shadow_common import append_jsonl, is_ai_host, load_config, normalize_host, proxy_user, started_at

class DLPAddon:
    def __init__(self):
        self.config = load_config()

    def running(self):
        from mitmproxy import ctx
        # Streaming would send bytes before request() can inspect them.
        ctx.options.update(stream_large_bodies=None, store_streamed_bodies=False,
                           save_stream_file=None, hardump='')

    def request(self, flow):
        if flow.response is not None or flow.request.method == 'CONNECT':
            return
        config = self.config
        user = proxy_user(flow)
        flow.comment = f'proxy_user={user}'
        if user not in config['users'] or not flow.metadata.get('proxyauth'):
            flow.response = http.Response.make(407, b'Proxy authentication required', {'Proxy-Authenticate': 'Basic realm="Shadow AI Demo"'})
            return
        ai = is_ai_host(flow.request.host, config['ai_hosts'])
        body = flow.request.raw_content or b''
        findings = scan(body[:config['inspect_max_bytes']], config['dlp_patterns']) if (
            ai and body and flow.request.method in config['inspect_methods']) else []
        blocked = bool(findings) and config['dlp_action'] == 'block'
        flow.metadata['dlp_labels'] = [finding['label'] for finding in findings]
        flow.metadata['dlp_blocked'] = blocked
        # Establish the safety decision before any disk I/O can fail.
        if blocked:
            flow.response = http.Response.make(403, b'Blocked by DLP policy (Shadow AI demo)', {
                'Content-Type': 'text/plain', 'X-ShadowAI-DLP': 'blocked'})
        elif config['offline_mode']:
            flow.response = http.Response.make(401 if ai else 200,
                b'{"error":"invalid_api_key (demo offline)"}' if ai else b'OK',
                {'Content-Type': 'application/json' if ai else 'text/plain'})
        for finding in findings:
            append_jsonl(config['logs_dir'] / 'dlp.jsonl', {
                'ts': started_at(flow), 'proxy_user': user,
                'host': normalize_host(flow.request.host), 'method': flow.request.method,
                **finding, 'bytes': len(body), 'blocked': blocked, 'flow_id': flow.id})

addons = [DLPAddon()]
