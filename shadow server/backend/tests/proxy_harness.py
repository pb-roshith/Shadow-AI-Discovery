"""Real mitmdump + trusted local HTTPS origin; never calls external hosts."""
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from mitmproxy.certs import CertStore

from services.proxy.setup_proxy import generate_htpasswd
from services.proxy.shadow_common import load_config

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Origin(ThreadingHTTPServer):
    daemon_threads = True
    requests_received = 0
    connections_received = 0

    def get_request(self):
        connection = super().get_request()
        self.connections_received += 1
        return connection


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.server.requests_received += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'clean origin response')

    do_GET = do_POST

    def log_message(self, *args):
        pass


class ProxyHarness:
    def __init__(self, offline=False, action='block', inspect_max_bytes=None, production_launcher=False):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.process = None
        self.server = None
        self.session = requests.Session()
        self.session.trust_env = False
        self.port = free_port()
        self.production_launcher = production_launcher
        self.config_path = self.root / 'proxy_config.yaml'
        config = yaml.safe_load((ROOT / 'services/proxy/proxy_config.yaml').read_text())
        config.update(logs_dir=str(self.root / 'logs'), listen_port=self.port, confdir=str(self.root / 'ca'),
                      ai_hosts_from=str(ROOT / 'reference/ai_signatures.yaml'),
                      extra_ai_hosts=['localhost', 'files.oaiusercontent.com'],
                      offline_mode=offline, dlp_action=action)
        if inspect_max_bytes is not None:
            config['inspect_max_bytes'] = inspect_max_bytes
        self.config_path.write_text(yaml.safe_dump(config))
        generate_htpasswd(self.config_path)
        self.ca_dir = self.root / 'ca'
        CertStore.from_store(self.ca_dir, 'mitmproxy', 2048)
        self.ca = self.ca_dir / 'mitmproxy-ca-cert.pem'
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=2))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        self.origin_cert = self.root / 'origin.pem'
        self.origin_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path = self.root / 'origin-key.pem'
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.server = Origin(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.origin_cert), str(key_path))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'https://localhost:{self.server.server_port}/backend-api/files?private_query=secret'

    def __enter__(self):
        env = os.environ.copy()
        env['SHADOWAI_PROXY_CONFIG'] = str(self.config_path)
        env.pop('SHADOWAI_PROXY_OFFLINE', None)
        args = [sys.executable, '-c', 'from mitmproxy.tools.main import mitmdump; mitmdump()',
                '--listen-host', '127.0.0.1', '--listen-port', str(self.port),
                '--set', f'confdir={self.ca_dir}', '--set', f'proxyauth=@{self.root / "htpasswd"}',
                '--set', 'connection_strategy=lazy', '--set', 'upstream_cert=false',
                '--set', f'ssl_verify_upstream_trusted_ca={self.origin_cert}', '--set', 'flow_detail=0',
                '--set', 'termlog_verbosity=error',
                '-s', str(ROOT / 'services/proxy/dlp_addon.py'),
                '-s', str(ROOT / 'services/proxy/log_addon.py')]
        if self.production_launcher:
            args = [sys.executable, '-m', 'services.proxy.launch_proxy', '--headless']
        self.output = (self.root / 'process.txt').open('w+', encoding='utf-8')
        self.process = subprocess.Popen(args, env=env, cwd=ROOT, stdout=self.output, stderr=subprocess.STDOUT)
        for _ in range(150):
            if self.process.poll() is not None:
                self.output.seek(0)
                message = self.output.read()
                self.__exit__()
                raise RuntimeError(message)
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=.1):
                    return self
            except OSError:
                time.sleep(.1)
        self.__exit__()
        raise RuntimeError('mitmdump did not start')

    def request(self, url=None, user='priya', **kwargs):
        auth = f'{user}:demo@' if user else ''
        proxy = f'http://{auth}127.0.0.1:{self.port}'
        return self.session.post(url or self.url, proxies={'http': proxy, 'https': proxy},
                                 verify=str(self.ca), timeout=15, **kwargs)

    def events(self, name, expected=None):
        path = self.root / 'logs' / f'{name}.jsonl'
        for _ in range(100):
            rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
            if expected is None or len(rows) >= expected:
                return rows
            time.sleep(.02)
        return rows

    def __exit__(self, *args):
        self.session.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=15)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.output.close()
        self.temp.cleanup()
