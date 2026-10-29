"""Exactly one allowlisted metadata record per completed HTTP flow."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.proxy.shadow_common import append_jsonl, is_ai_host, load_config, normalize_host, path_class, proxy_user, started_at

class MetadataLogger:
    def __init__(self):
        self.config = load_config()

    def record(self, flow):
        if flow.request.method == 'CONNECT' or flow.metadata.get('shadowai_logged'):
            return
        response = flow.response
        event = {
            'ts': started_at(flow), 'proxy_user': proxy_user(flow),
            'host': normalize_host(flow.request.host), 'method': flow.request.method,
            'path_class': path_class(flow.request.path, flow.request.headers.get('Content-Type', '')),
            'bytes_out': len(flow.request.raw_content or b''),
            'bytes_in': len(response.raw_content or b'') if response else 0,
            'status': response.status_code if response else 0,
            'ai_host': is_ai_host(flow.request.host, self.config['ai_hosts']),
            'dlp_blocked': flow.metadata.get('dlp_blocked', False), 'flow_id': flow.id}
        ended = response.timestamp_end if response else getattr(flow.error, 'timestamp', None)
        event['duration_ms'] = max(0, round((ended - flow.request.timestamp_start) * 1000, 3)) if ended is not None else None
        if not response:
            event['error'] = 'UpstreamError'
        append_jsonl(self.config['logs_dir'] / 'proxy.jsonl', event)
        flow.metadata['shadowai_logged'] = flow.id

    def response(self, flow):
        self.record(flow)

    def error(self, flow):
        self.record(flow)

addons = [MetadataLogger()]
