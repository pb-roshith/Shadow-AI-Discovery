import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

WORKSPACE=Path(__file__).resolve().parents[2]
ROOT=WORKSPACE/'shadow server'/'backend'
sys.path.insert(0, str(ROOT))
from engine.request_metrics import measurements
load_dotenv(Path(__file__).with_name('.env'), override=True)
server=FastMCP('creditdb',host='127.0.0.1',port=8765)

def audit(tool, request_id=None, status='unknown', metrics=None):
    (ROOT/'logs').mkdir(exist_ok=True)
    event = {'ts':datetime.now(timezone.utc).isoformat(),'server':'creditdb','tool':tool,'caller':'risk-agent',
             'origin':'live', 'request_id':request_id or str(uuid.uuid4()), 'status':status}
    if metrics is not None:
        event.update(metrics)
    with (ROOT/'logs/mcp_audit.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(event)+'\n')


@contextmanager
def measured_tool(tool):
    started = time.perf_counter()
    status = 'failed'
    try:
        yield
        status = 'success'
    finally:
        audit(tool, status=status, metrics=measurements(seconds=time.perf_counter() - started))

def connect():
    import pg8000.dbapi
    from urllib.parse import urlparse, unquote
    # Optional real PostgreSQL connection, never written to logs.
    parsed=urlparse(os.environ.get('CREDITDB_DSN','postgresql://postgres@127.0.0.1:5432/creditdb'))
    if parsed.hostname not in ('localhost','127.0.0.1') or parsed.path != '/creditdb':
        raise ValueError('Only the local fictional creditdb database is allowed')
    return pg8000.dbapi.connect(user=unquote(parsed.username or 'postgres'), password=unquote(parsed.password) if parsed.password else None,
        host=parsed.hostname, port=parsed.port or 5432, database='creditdb')

@server.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False))
def query_loans() -> list[dict]:
    """Read up to twenty loan records from the local fictional credit database."""
    with measured_tool('query_loans'), connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT loan_id, customer_ref, amount, status FROM loans ORDER BY loan_id LIMIT 20')
            return [dict(zip(('loan_id','customer_ref','amount','status'),row)) for row in cursor.fetchall()]

@server.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=True))
def execute_sql(sql: str) -> str:
    """Mark demo loan 1 as reviewed. Only UPDATE loans SET status = 'reviewed' WHERE loan_id = 1 is allowed."""
    # Demonstrates write permission while restricting the demo to a fictional row.
    if sql.strip().rstrip(';').lower() != "update loans set status = 'reviewed' where loan_id = 1":
        raise ValueError('Only the documented demo-row UPDATE is allowed')
    with measured_tool('execute_sql'), connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE loans SET status = 'reviewed' WHERE loan_id = 1")
        connection.commit()
    return 'Demo loan updated'

@server.custom_route('/api/health', methods=['GET'])
async def health(request):
    return JSONResponse({'status': 'ok', 'repo': 'creditdb-MCP'})

@server.custom_route('/api/tools', methods=['GET'])
async def tools(request):
    # Use the MCP registry so the UI reflects the tools actually exposed.
    registered = await server.list_tools()
    return JSONResponse({'server': 'creditdb', 'endpoint': 'http://127.0.0.1:8765/mcp',
                         'tools': [tool.model_dump(mode='json', by_alias=True) for tool in registered]})

if __name__=='__main__':
    server.run(transport='streamable-http')
