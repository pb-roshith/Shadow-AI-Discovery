"""Manage this workspace's development processes with persistent PID ownership."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / '.runtime'
REGISTRY = RUNTIME / 'services.json'
SHADOW = ROOT / 'shadow server'
REPO = ROOT / 'repo server'
PYTHON = SHADOW / 'backend/.venv/Scripts/python.exe'
GATEWAY_PYTHON = SHADOW / 'backend/services/gateway/.venv/Scripts/python.exe'


def proxy_root():
    deployment = SHADOW / 'backend/services/proxy/deployment.json'
    if deployment.exists():
        return Path(json.loads(deployment.read_text(encoding='utf-8-sig'))['logs_dir']).parent
    return SHADOW / 'backend'


def definitions():
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Install Node.js first.')
    ollama = shutil.which('ollama')
    if not ollama:
        installed = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Ollama/ollama.exe'
        if installed.is_file():
            ollama = str(installed)
    if not ollama:
        raise RuntimeError('Install Ollama first, then run start.bat again.')
    proxy = proxy_root()
    return [
        ('ollama', ROOT, [ollama, 'serve'], 11434, '/api/tags'),
        ('mitmweb', proxy, [str(proxy / '.venv/Scripts/python.exe'), '-m', 'services.proxy.launch_proxy'], 8081, '/'),
        ('shadow-backend', SHADOW / 'backend', [str(PYTHON), '-m', 'engine.dev_server', 'backend'], 8000, '/health'),
        ('shadow-frontend', SHADOW / 'frontend', [node, 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], 5173, '/'),
        *[(name, REPO / name, [str(PYTHON), '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)], port, '/api/health')
          for name, port in [('credit-dossier', 8101), ('policy-intelligence', 8102), ('loan-risk-classifier', 8103), ('customer-assistant', 8105)]],
        ('creditdb', REPO / 'creditdb-MCP', [str(PYTHON), 'server.py'], 8765, '/api/health'),
        ('repo-frontend', REPO / 'frontend', [node, 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5174', '--strictPort'], 5174, '/'),
        ('gateway', SHADOW / 'backend', [str(GATEWAY_PYTHON), '-c', 'from litellm import run_server; run_server()', '--config', 'services/gateway/config.yaml', '--host', '127.0.0.1', '--port', '4000'], 4000, '/health/liveliness'),
    ]


def owned(record):
    try:
        process = psutil.Process(record['pid'])
        if process.create_time() == record['created'] and process.exe() == record['executable']:
            return process
    except (psutil.Error, KeyError):
        pass


def records():
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []


def save(entries):
    RUNTIME.mkdir(exist_ok=True)
    REGISTRY.write_text(json.dumps(entries, indent=2))


def tab_record(name):
    return RUNTIME / f'{name}-tab.json'


def stop_marker(name):
    return RUNTIME / f'{name}-stop.request'


def existing_ollama():
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/version', timeout=2) as response:
            return response.status == 200 and bool(json.load(response).get('version'))
    except Exception:
        return False


def run_tab(name):
    service = next((item for item in definitions() if item[0] == name), None)
    if not service:
        raise RuntimeError('Unknown service')
    _, directory, command, port, _ = service
    # The desktop app can start Ollama after the coordinator checks the port.
    if name == 'ollama' and existing_ollama():
        RUNTIME.mkdir(exist_ok=True)
        tab_record(name).write_text(json.dumps({'name': name, 'external': True}))
        print('Using existing Ollama on http://127.0.0.1:11434', flush=True)
        return 0
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    if name == 'ollama':
        os.environ['OLLAMA_HOST'] = '127.0.0.1:11434'
    if name == 'mitmweb':
        os.environ['SHADOWAI_PROXY_CONFIG'] = str(directory / 'services/proxy/proxy_config.yaml')
        os.environ['SHADOWAI_PROXY_OFFLINE'] = '1'
    if name == 'gateway':
        from dotenv import load_dotenv
        load_dotenv(SHADOW / 'backend/services/gateway/.env', override=True)
        os.environ['DEBUG'] = 'false'
    print(f'{name} — http://127.0.0.1:{port}', flush=True)
    stop_marker(name).unlink(missing_ok=True)
    child = subprocess.Popen(command, cwd=directory)
    process = psutil.Process(child.pid)
    record = {'name': name, 'pid': child.pid, 'created': process.create_time(), 'executable': process.exe()}
    RUNTIME.mkdir(exist_ok=True)
    target = tab_record(name)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(record))
    temporary.replace(target)
    try:
        code = child.wait()
        # A deliberate shutdown is a successful tab exit, even on Windows where
        # terminating the child reports a nonzero process status.
        return 0 if stop_marker(name).exists() else code
    except KeyboardInterrupt:
        if owned(record):
            child.terminate()
        return 0


def stop():
    survivors = []
    for record in reversed(records()):
        process = owned(record)
        if not process:
            continue
        try:
            stop_marker(record['name']).write_text('stop', encoding='utf-8')
            processes = process.children(recursive=True) + [process]
            for child in reversed(processes):
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(processes, timeout=5)
            for child in alive:
                child.kill()
            print('Stopped', record['name'])
        except psutil.Error:
            survivors.append(record)
            print('Could not stop', record['name'])
    save(survivors)
    return bool(survivors)


def service_ready(name, port, health):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{health}', timeout=1) as response:
            ready = response.status == 200
    except urllib.error.HTTPError as error:
        # mitmweb rejects unauthenticated requests even when its UI is ready.
        ready = name == 'mitmweb' and error.code == 403
    except Exception:
        return False
    if ready and name == 'mitmweb':
        with socket.socket() as connection:
            connection.settimeout(1)
            return connection.connect_ex(('127.0.0.1', 8080)) == 0
    return ready


def existing_proxy(directory, command):
    """Recognize our configured proxy; never reuse unrelated port listeners."""
    try:
        listeners = {item.laddr.port: item.pid for item in psutil.net_connections(kind='tcp')
                     if item.status == psutil.CONN_LISTEN and item.laddr.ip == '127.0.0.1'
                     and item.laddr.port in (8080, 8081)}
        if not listeners.get(8080) or listeners.get(8080) != listeners.get(8081):
            return False
        process = psutil.Process(listeners[8080])
        actual = process.cmdline()
        return (Path(process.cwd()) == directory and bool(actual) and Path(actual[0]) == Path(command[0])
                and actual[1:] == command[1:] and service_ready('mitmweb', 8081, '/'))
    except (psutil.Error, OSError):
        return False


def start():
    terminal = shutil.which('wt.exe')
    if not terminal:
        raise RuntimeError('Windows Terminal (wt.exe) is required to open each server in a tab.')
    services = definitions()
    if not PYTHON.exists():
        raise RuntimeError('Run setup.bat first.')
    if not GATEWAY_PYTHON.exists():
        raise RuntimeError('Run setup.bat first to configure the gateway environment.')
    proxy = proxy_root()
    if not (proxy / '.venv/Scripts/python.exe').is_file() or not (proxy / 'services/proxy/htpasswd').is_file():
        raise RuntimeError('Run shadow server/backend/setup/proxy_setup.ps1 first to configure mitmweb.')
    for folder in (SHADOW, REPO):
        if not (folder / 'frontend/node_modules/vite/bin/vite.js').exists():
            raise RuntimeError('Run setup.bat first to install frontend dependencies.')
    entries = records()
    external = set()
    # Check every port before launching anything; never terminate an unknown listener.
    for name, directory, command, port, health in services:
        if any(item['name'] == name and owned(item) for item in entries):
            continue
        if name == 'mitmweb' and existing_proxy(directory, command):
            external.add(name)
            continue
        for checked_port in ((8080, 8081) if name == 'mitmweb' else (port,)):
            with socket.socket() as connection:
                if connection.connect_ex(('127.0.0.1', checked_port)) == 0:
                    if name == 'ollama':
                        if existing_ollama():
                            external.add(name)
                            continue
                    raise RuntimeError(f'Port {checked_port} is already in use. Stop its existing service first.')
    for name, directory, command, port, health in services:
        if name in external:
            print(f'Using existing {name}; stop.bat leaves this independently started server running.')
            continue
        if any(item['name'] == name and owned(item) for item in entries):
            print('Already running:', name)
            continue
        RUNTIME.mkdir(exist_ok=True)
        target = tab_record(name)
        target.unlink(missing_ok=True)
        subprocess.run([terminal, '-w', 'shadow-ai-workspace', 'new-tab', '--title', name,
                        '-d', str(directory), str(PYTHON), str(Path(__file__).resolve()), 'run', name], check=True)
        deadline = time.monotonic() + 15
        while not target.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        if not target.exists():
            stop()
            raise RuntimeError(f'{name} did not launch. Check its Windows Terminal tab.')
        record = json.loads(target.read_text())
        if record.get('external') and name == 'ollama' and existing_ollama():
            print('Using existing Ollama; continuing workspace startup.', flush=True)
            continue
        entries = [item for item in entries if item['name'] != name] + [record]
        save(entries)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and owned(record):
            if service_ready(name, port, health):
                break
            time.sleep(.3)
        else:
            # Also cover a desktop Ollama launch racing with subprocess.Popen.
            if name == 'ollama' and existing_ollama():
                entries = [item for item in entries if item['name'] != name]
                save(entries)
                print('Using existing Ollama; continuing workspace startup.', flush=True)
                continue
            stop()
            raise RuntimeError(f'{name} failed to start. Check its Windows Terminal tab; services have been stopped.')
        print('Started', name, flush=True)
    print('Discovery: http://127.0.0.1:5173\nRepository hub: http://127.0.0.1:5174\nmitmweb: http://127.0.0.1:8081 (password: demo)')
    return 0


if __name__ == '__main__':
    if '--hidden' in sys.argv:
        sys.argv.remove('--hidden')
        RUNTIME.mkdir(exist_ok=True)
        log = (RUNTIME / 'launcher.log').open('a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = log
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'run'])
    parser.add_argument('service', nargs='?')
    try:
        args = parser.parse_args()
        raise SystemExit(run_tab(args.service) if args.action == 'run' else start() if args.action == 'start' else stop())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
