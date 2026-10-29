"""Give LiteLLM its MCP version without changing the discovery/CreditDB SDK."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[3]


def configure():
    backend = ROOT / 'shadow server/backend'
    target = backend / 'services/gateway/.venv'
    # Use a private site-packages first, followed by our workspace's shared
    # packages. Do not inherit machine-wide or user-installed Python packages.
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(target)
    (target / 'Lib/site-packages/workspace_backend.pth').write_text(
        'import site; site.addsitedir(' + repr(str(backend / '.venv/Lib/site-packages')) + ')\n', encoding='utf-8')
    subprocess.run([str(target / 'Scripts/python.exe'), '-m', 'pip', 'install',
                    '-r', str(backend / 'services/gateway/requirements.txt')], check=True)


if __name__ == '__main__':
    configure()
