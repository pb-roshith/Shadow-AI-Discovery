"""Keep all launcher options explicit; never persist mitmproxy flow dumps."""
import argparse
import os
import sys
from pathlib import Path

from services.proxy.shadow_common import load_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true')
    args = parser.parse_args()
    config = load_config()
    # Refuse to listen when audit logs cannot be opened (including sandbox ACLs).
    config['logs_dir'].mkdir(parents=True, exist_ok=True)
    for name in ('proxy.jsonl', 'dlp.jsonl'):
        with (config['logs_dir'] / name).open('a', encoding='utf-8'):
            pass
    directory = Path(__file__).resolve().parent
    config_path = Path(os.environ.get('SHADOWAI_PROXY_CONFIG', directory / 'proxy_config.yaml'))
    password_file = config_path.resolve().with_name('htpasswd')
    if not password_file.is_file():
        parser.error('htpasswd missing; run setup/proxy_setup.ps1')
    sys.argv = ['mitmdump' if args.headless else 'mitmweb',
                '--listen-host', config['listen_host'], '--listen-port', str(config['listen_port']),
                '--set', f'proxyauth=@{password_file}', '--set', 'connection_strategy=lazy',
                '--set', 'upstream_cert=false',
                '--set', 'flow_detail=0', '--set', 'termlog_verbosity=error',
                '-s', str(directory / 'dlp_addon.py'), '-s', str(directory / 'log_addon.py')]
    if config.get('confdir'):
        sys.argv.extend(['--set', f'confdir={config["confdir"]}'])
    if args.headless:
        from mitmproxy.tools.main import mitmdump
        mitmdump()
    else:
        print(f'Open http://127.0.0.1:{config["web_port"]}/ (mitmweb password: demo)', flush=True)
        sys.argv.extend(['--web-host', '127.0.0.1', '--web-port', str(config['web_port']), '--no-web-open-browser'])
        from argon2 import PasswordHasher
        sys.argv.extend(['--set', 'web_password=' + PasswordHasher().hash('demo')])
        from mitmproxy.tools.main import mitmweb
        mitmweb()


if __name__ == '__main__':
    main()
