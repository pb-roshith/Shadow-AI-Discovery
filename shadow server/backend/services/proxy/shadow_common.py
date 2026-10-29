"""Shared metadata helpers; deliberately independent of mitmproxy."""
import base64
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import yaml

_WRITE_LOCK = threading.Lock()


def resolve_path(base, value):
    return (Path(base) / Path(str(value).replace('\\', '/'))).resolve()


def load_config(path=None):
    path = Path(path or os.environ.get('SHADOWAI_PROXY_CONFIG', Path(__file__).with_name('proxy_config.yaml'))).resolve()
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['logs_dir'] = resolve_path(path.parent, config['logs_dir'])
    catalog = resolve_path(path.parent, config['ai_hosts_from'])
    hosts = yaml.safe_load(catalog.read_text(encoding='utf-8'))['hosts']
    config['ai_hosts'] = list(hosts) + config.get('extra_ai_hosts', [])
    if config['dlp_action'] not in ('block', 'log_only'):
        raise ValueError('dlp_action must be block or log_only')
    if int(config['inspect_max_bytes']) < 1:
        raise ValueError('inspect_max_bytes must be positive')
    for pattern in config['dlp_patterns']:
        re.compile(pattern['regex'])
    config['offline_mode'] = config.get('offline_mode', False) or os.environ.get('SHADOWAI_PROXY_OFFLINE') == '1'
    return config


def normalize_host(host):
    return host.lower().rstrip('.')


def is_ai_host(host, hosts):
    host = normalize_host(host)
    return any(host == normalize_host(h) or host.endswith('.' + normalize_host(h)) for h in hosts)


def path_class(path, content_type=''):
    path = path.split('?', 1)[0].lower()
    if 'multipart/' in content_type.lower() or '/files' in path or '/upload' in path:
        return 'upload'
    return 'api' if path.startswith(('/v1', '/backend-api', '/api')) else 'web'


def proxy_user(flow):
    credentials = flow.metadata.get('proxyauth')
    if credentials:
        return credentials[0]
    header = flow.request.headers.get('Proxy-Authorization', '')
    try:
        scheme, value = header.split(' ', 1)
        if scheme.lower() == 'basic':
            return base64.b64decode(value, validate=True).decode('utf-8').split(':', 1)[0]
    except (ValueError, UnicodeError):
        pass
    return 'unauthenticated'


def started_at(flow):
    return datetime.fromtimestamp(flow.request.timestamp_start).astimezone().isoformat(timespec='milliseconds')


def append_jsonl(path, event):
    path = Path(path)
    # One proxy process owns these files. All its hooks share this module/lock.
    with _WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(event, ensure_ascii=True, separators=(',', ':')) + '\n')
            stream.flush()
