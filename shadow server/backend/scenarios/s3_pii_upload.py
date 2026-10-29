"""S3: authenticated multipart upload, locally blocked by the demo DLP."""
import argparse
import sys
from pathlib import Path
from urllib.parse import quote

import requests


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', default='priya')
    parser.add_argument('--file', type=Path, default=Path(__file__).parent / 'data/dummy_customer_extract.csv')
    parser.add_argument('--proxy-port', type=int, default=8080, help='Override for isolated test runs')
    parser.add_argument('--ca', type=Path, default=Path.home() / '.mitmproxy/mitmproxy-ca-cert.pem')
    args = parser.parse_args(argv)
    ca = args.ca
    if not args.file.is_file():
        print('[S3] Dummy file missing. Run scenarios/data/make_dummy_extract.py first.')
        return 1
    if not ca.is_file():
        print('[S3] Certificate missing. Run setup/proxy_setup.ps1 first.')
        return 1
    size = args.file.stat().st_size / 1_000_000
    identity = 'Priya (Retail Lending)' if args.user == 'priya' else args.user
    print(f'[S3] {identity} uploads {args.file.name} ({size:.1f} MB) to chatgpt.com via the corporate proxy...')
    proxy = f'http://{quote(args.user, safe="")}:demo@127.0.0.1:{args.proxy_port}'
    session = requests.Session()
    session.trust_env = False
    try:
        with session, args.file.open('rb') as stream:
            response = session.post('https://chatgpt.com/backend-api/files',
                files={'file': (args.file.name, stream, 'text/csv')},
                proxies={'http': proxy, 'https': proxy}, verify=str(ca), timeout=45)
    except requests.exceptions.SSLError:
        print('[S3] Certificate error. Confirm the proxy uses the CA exported by setup; TLS verification stays enabled.')
        return 1
    except requests.exceptions.ProxyError as error:
        print('[S3] 407 authentication failure. Check the username and generated htpasswd.' if '407' in str(error)
              else '[S3] Proxy not running or unreachable. Start services/proxy/run_proxy.ps1.')
        return 1
    except (requests.exceptions.RequestException, OSError):
        print('[S3] Request failed or timed out. Check the proxy and file access; use -Offline if needed.')
        return 1
    if response.status_code == 403 and response.headers.get('X-ShadowAI-DLP') == 'blocked':
        print('[S3] Response: 403 Blocked by DLP policy  (X-ShadowAI-DLP: blocked)')
        print('[S3] Nothing left the AVD. Check logs\\proxy.jsonl and logs\\dlp.jsonl, then Run discovery.')
        return 0
    print('[S3] 407 authentication failure. Check proxy credentials.' if response.status_code == 407
          else f'[S3] Not blocked (HTTP {response.status_code}). Check AI hosts, DLP action and rules.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
