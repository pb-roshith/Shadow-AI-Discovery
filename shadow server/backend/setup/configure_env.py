"""Create independent server settings and migrate legacy shared values without printing secrets."""
import argparse
import json
from pathlib import Path
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / 'repo server'
SHADOW = ROOT / 'shadow server/backend/.env'
SERVER_FOLDERS = ['credit-dossier', 'policy-intelligence', 'loan-risk-classifier',
                  'customer-assistant', 'creditdb-MCP']


def configure(migrate_shared=False):
    shared_path = REPO / '.env'
    # Snapshot every legacy source before writing any destination.
    shared = dotenv_values(shared_path) if migrate_shared else {}
    shadow = dotenv_values(SHADOW) if migrate_shared else {}
    database_file = SHADOW.parent / '.runtime/database.json'
    if migrate_shared and database_file.exists():
        database = json.loads(database_file.read_text(encoding='utf-8-sig'))
        for name, field in [('HOST','host'), ('PORT','port'), ('NAME','database'), ('USER','user')]:
            if database.get(field) is not None:
                shadow.setdefault('SHADOWAI_DB_' + name, str(database[field]))
    dossier = dotenv_values(REPO / 'credit-dossier/.env') if migrate_shared else {}
    destinations = [REPO / name for name in SERVER_FOLDERS] + [SHADOW.parent / 'services/gateway', SHADOW.parent]
    known_keys = set()
    for folder in destinations:
        template = dotenv_values(folder / '.env.example')
        if not template:
            raise RuntimeError(f'Missing settings template for {folder.name}')
        known_keys.update(template)
    unknown = set(shared) - known_keys
    if unknown:
        raise RuntimeError('Shared .env contains unmapped settings; migrate them before removing it: ' + ', '.join(sorted(unknown)))
    for folder in destinations:
        path = folder / '.env'
        local = dotenv_values(path)
        defaults = dotenv_values(folder / '.env.example')
        if folder.name == 'customer-assistant':
            sources = [dossier, shared, shadow]
        elif folder.name in ('gateway', 'backend'):
            sources = [shadow, shared]
        else:
            sources = [shared, dossier, shadow] if folder.name == 'policy-intelligence' else [shared, shadow]
        path.touch(exist_ok=True)
        for key, default in defaults.items():
            if key in local and (local[key] or not migrate_shared):
                continue
            value = next((source[key] for source in sources if source.get(key)), default or '')
            set_key(str(path), key, value)
    if migrate_shared and shared_path.exists():
        migrated = [dotenv_values(folder / '.env') for folder in destinations]
        if any(value and not any(values.get(key) == value for values in migrated) for key, value in shared.items()):
            raise RuntimeError('A shared value differs from all local values; common .env retained for review.')
        shared_path.unlink()
    print('Independent server .env files configured; existing local settings preserved. No credentials displayed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--migrate-shared', action='store_true', help='Move legacy shared settings into server-local files.')
    configure(parser.parse_args().migrate_shared)
