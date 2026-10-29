"""Interactive first-run database setup without Windows encrypted credentials."""
import getpass
import os
import sys

from dotenv import set_key
from engine.config import ROOT
from engine.db import connection_parameters


def ensure_password(force=False):
    if os.getenv('SHADOWAI_DB_PASSWORD') and not force:
        return
    if not sys.stdin.isatty():
        raise RuntimeError('Set SHADOWAI_DB_PASSWORD in backend/.env, then run start.bat again.')
    print('Enter your existing PostgreSQL password. It will be saved in backend/.env.')
    password = getpass.getpass('PostgreSQL password: ')
    if not password:
        raise RuntimeError('A PostgreSQL password is required. Configure backend/.env.')
    os.environ['SHADOWAI_DB_PASSWORD'] = password
    import psycopg
    try:
        with psycopg.connect(**connection_parameters(database='postgres')):
            pass
    except psycopg.Error:
        os.environ.pop('SHADOWAI_DB_PASSWORD', None)
        raise RuntimeError('Cannot connect to PostgreSQL. Check that it is running and verify the host, user and password in backend/.env.') from None
    set_key(ROOT / '.env', 'SHADOWAI_DB_PASSWORD', password)


def main():
    try:
        if '--configure' in sys.argv:
            ensure_password(force=True)
        elif not os.getenv('SHADOWAI_DB_PASSWORD'):
            raise RuntimeError('Set SHADOWAI_DB_PASSWORD in backend/.env.')
        from engine.bootstrap import initialize
        initialize()
    except Exception:
        print('Database startup failed. Check PostgreSQL is running and set SHADOWAI_DB_HOST, SHADOWAI_DB_PORT, SHADOWAI_DB_USER, SHADOWAI_DB_NAME and SHADOWAI_DB_PASSWORD in backend/.env.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
