from pathlib import Path
import csv
import yaml
from contextlib import contextmanager
from contextvars import ContextVar

ROOT = Path(__file__).resolve().parents[1]

def repository_root(root):
    # Isolated demo/test roots retain local fixtures; the installed app scans the shared repos.
    if root.resolve() == Path(__file__).resolve().parents[1]:
        return root.parents[1] / 'repo server'
    return root / 'repos'

from dotenv import load_dotenv
load_dotenv(ROOT / '.env', override=False)
_reference_context = ContextVar('reference_snapshot', default=None)

@contextmanager
def reference_snapshot():
    """One consistent database reference snapshot per discovery run."""
    from engine.db import backend, connection, decode
    if backend() != 'postgresql':
        yield
        return
    with connection() as db:
        documents = {name: decode(payload) for name, payload in db.execute('SELECT id,payload FROM reference_documents')}
    token = _reference_context.set(documents)
    try:
        yield
    finally:
        _reference_context.reset(token)

def within(path, base=ROOT):
    path = Path(path).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError('Path outside permitted scan root')
    return path

def reference_file(name):
    path = within(ROOT / 'reference' / name, ROOT / 'reference')
    if path.suffix == '.csv':
        with path.open(encoding='utf-8', newline='') as stream:
            return list(csv.DictReader(stream, skipinitialspace=True))
    return yaml.safe_load(path.read_text(encoding='utf-8'))

def reference(name):
    snapshot = _reference_context.get()
    if snapshot is not None:
        if name not in snapshot:
            raise ValueError(f'Reference not initialized: {name}')
        return snapshot[name]
    from engine.db import backend, document
    if backend() == 'postgresql':
        result = document('reference_documents', name)
        if result is None:
            raise ValueError(f'Reference not initialized: {name}. Run setup/configure_database.ps1')
        return result
    if name == 'approved_ai_inventory.csv':
        result = document('reference_documents', name)
        if result is not None:
            return result
    return reference_file(name)

def rows(name, key):
    return {row[key]: row for row in reference(name + '.csv')}
