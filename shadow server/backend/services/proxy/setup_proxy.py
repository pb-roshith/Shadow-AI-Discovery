"""Generate credentials and CA without changing OS proxy or certificate trust."""
import argparse
import shutil
from pathlib import Path

import bcrypt

from services.proxy.shadow_common import load_config


def generate_htpasswd(config_path=None):
    config = load_config(config_path)
    path = Path(config_path).resolve() if config_path else Path(__file__).with_name('proxy_config.yaml')
    destination = path.with_name('htpasswd')
    destination.write_text(''.join(f'{user}:{bcrypt.hashpw(b"demo", bcrypt.gensalt()).decode()}\n'
                                   for user in config['users']), encoding='ascii')
    from mitmproxy.addons.proxyauth import Htpasswd
    validator = Htpasswd('@' + str(destination))
    if not all(validator(user, 'demo') and not validator(user, 'wrong') for user in config['users']):
        raise RuntimeError('Installed mitmproxy does not support generated bcrypt hashes')
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confdir', type=Path, default=Path.home() / '.mitmproxy')
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    generate_htpasswd(args.config)
    from mitmproxy.certs import CertStore
    CertStore.from_store(args.confdir, 'mitmproxy', 2048)
    directory = Path(__file__).with_name('certs')
    directory.mkdir(exist_ok=True)
    source = args.confdir / 'mitmproxy-ca-cert.pem'
    for suffix in ('pem', 'cer'):
        shutil.copyfile(source, directory / f'mitmproxy-ca-cert.{suffix}')
    config = load_config(args.config)
    config['logs_dir'].mkdir(parents=True, exist_ok=True)
    for name in ('proxy.jsonl', 'dlp.jsonl'):
        (config['logs_dir'] / name).touch(exist_ok=True)
    from scenarios.data.make_dummy_extract import generate
    generate()
    print('Generated bcrypt credentials, fictional extract and public CA exports. No OS trust changed.')


if __name__ == '__main__':
    main()
