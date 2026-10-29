"""Fingerprint discovery inputs using file metadata; never read application data."""
import hashlib
import os
from pathlib import Path
from engine.config import ROOT, repository_root
from engine.collectors.local import telemetry_path


def input_revision():
    records = []
    base = repository_root(ROOT)
    if base.exists():
        for repo in sorted(base.iterdir()):
            if not repo.is_dir() or repo.name in ('frontend', 'backend') or repo.is_symlink():
                continue
            for directory, folders, files in os.walk(repo):
                folders[:] = sorted(f for f in folders if f not in ('node_modules', '__pycache__', '.venv', 'dist') and not (Path(directory) / f).is_symlink())
                for name in sorted(files):
                    path = Path(directory) / name
                    if path.is_symlink():
                        continue
                    try:
                        stat = path.stat()
                        records.append(f'{path.relative_to(base)}:{stat.st_mtime_ns}:{stat.st_size}')
                    except OSError:
                        continue
    for name in ('sdk_calls.jsonl', 'gateway.jsonl', 'proxy.jsonl', 'dlp.jsonl', 'ollama_calls.jsonl', 'mcp_audit.jsonl'):
        path = telemetry_path(name, ROOT)
        if path.exists():
            stat = path.stat()
            records.append(f'{name}:{stat.st_mtime_ns}:{stat.st_size}')
    # A rule or scoring change must invalidate cached discovery even when the
    # application repositories and invocation logs have not changed.
    for directory in (Path(__file__).resolve().parent, ROOT / 'reference'):
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.yaml', '.csv'):
                stat = path.stat()
                records.append(f'{directory.name}/{path.relative_to(directory)}:{stat.st_mtime_ns}:{stat.st_size}')
    return hashlib.sha256('\n'.join(records).encode()).hexdigest()
