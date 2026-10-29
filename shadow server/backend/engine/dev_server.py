"""Run one development server in its visible terminal tab."""
import json
import os
import shutil
import subprocess
import sys

import psutil
from engine.config import ROOT


def registry(service):
    return ROOT / '.runtime' / f'{service}-server.json'


def recorded_process(service):
    try:
        record = json.loads(registry(service).read_text())
        process = psutil.Process(record['pid'])
        if process.create_time() == record['created'] and process.exe() == record['executable']:
            return process
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    return None


def stop(service):
    process = recorded_process(service)
    if process:
        children = process.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.Error:
                pass
        try:
            process.terminate()
        except psutil.Error:
            pass
    registry(service).unlink(missing_ok=True)


def run(service):
    if recorded_process(service):
        print(f'{service.capitalize()} is already running. Use stop.bat before restarting.')
        return 1
    if service == 'backend':
        if os.getenv('SHADOWAI_DB_PASSWORD'):
            try:
                from engine.bootstrap import initialize
                initialize()
            except Exception:
                print('Database initialization failed. Check PostgreSQL and backend/.env. Starting the API so its status remains available.', flush=True)
        else:
            print('Database password is missing in backend/.env. API will start; database features require SHADOWAI_DB_PASSWORD. No password prompt will be shown.', flush=True)
        command = [sys.executable, '-m', 'uvicorn', 'engine.api:app', '--host', '127.0.0.1', '--port', '8000', '--no-access-log']
        directory = ROOT
    else:
        directory = ROOT.parent / 'frontend'
        vite = directory / 'node_modules/vite/bin/vite.js'
        node = shutil.which('node')
        if not node or not vite.exists():
            print('Install Node.js and run npm ci in frontend first.')
            return 1
        command = [node, str(vite), '--host', '127.0.0.1', '--port', '5173', '--strictPort']
    child = subprocess.Popen(command, cwd=directory)
    process = psutil.Process(child.pid)
    registry(service).parent.mkdir(exist_ok=True)
    registry(service).write_text(json.dumps({'pid': child.pid, 'created': process.create_time(), 'executable': process.exe()}))
    try:
        return child.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        stop(service)


if __name__ == '__main__':
    if sys.argv[1:] == ['stop']:
        for service in ('frontend', 'backend'):
            stop(service)
    elif sys.argv[1:] in (['frontend'], ['backend']):
        raise SystemExit(run(sys.argv[1]))
    else:
        raise SystemExit('Usage: python -m engine.dev_server frontend|backend|stop')
