# CreditDB MCP

Independent MCP server for Scenario 5, running at http://127.0.0.1:8765/mcp.
Root `start.bat` and `stop.bat` manage its own named process alongside the repository applications.
To run separately, install requirements.txt and run `python server.py` from this folder.

Open http://127.0.0.1:5174/#/repos/creditdb-MCP to inspect the live tool list.
The UI reads `GET /api/tools` from the MCP tool registry; `GET /api/health` checks server readiness.
Listing tools does not connect to PostgreSQL or execute them.

- `query_loans`: read up to twenty records from the fictional `loans` table.
- `execute_sql`: write tool restricted to `UPDATE loans SET status = 'reviewed' WHERE loan_id = 1`.

Tool execution requires the existing local PostgreSQL `creditdb` database and `loans` table.
Set `CREDITDB_DSN` in this folder's `.env` or the process environment.
Copy `.env.example` to `.env` in this folder; this server does not read the discovery backend or shared `.env`. Connections are restricted to localhost and database `creditdb`.
Audit metadata still goes to `shadow server/backend/logs/mcp_audit.jsonl` so discovery can correlate Scenario 5.
