# Manual setup and run guide (Windows PowerShell)

This guide starts the services manually, without `setup.bat` or `start.bat`.
Part 1 is for the first installation. Part 2 is for every later run.

Replace `C:\path\Shadow AI Discovery` with the actual project folder.
Run the commands in order and resolve any error before continuing.

## Part 1 — Initial setup

### 1. Install prerequisites and open the project

Install Python with pip, Node.js with npm, Git, PostgreSQL and Ollama.
This workspace has been tested with Python 3.14. The proxy setup requires
Python 3.11 or newer and selects a compatible mitmproxy version.
Ensure PostgreSQL is running and its `psql` command is available on PATH.
Internet access is needed for dependency and model downloads.

Use a source copy of the project. Recreate `.venv` folders and `node_modules`
on this laptop; do not transfer those folders or `.runtime` from another laptop.
Keep the server-local `.env.example` files so setup can create local settings.

```powershell
$ProjectRoot = 'C:\path\Shadow AI Discovery'
Set-Location $ProjectRoot

python --version
python -m pip --version
node --version
npm.cmd --version
git --version
psql --version
ollama --version
```

### 2. Create the shared Python environment and install packages

From the project root:

```powershell
python -m venv '.\shadow server\backend\.venv'

& '.\shadow server\backend\.venv\Scripts\python.exe' -m pip install `
  -r '.\shadow server\backend\requirements.txt' `
  -r '.\shadow server\backend\requirements-services.txt' `
  -r '.\repo server\requirements.txt'
```

Discovery, the four repository APIs and CreditDB MCP use this environment.
The commands invoke its interpreter directly, so activation is unnecessary.

### 3. Create and configure each server's own .env

```powershell
& '.\shadow server\backend\.venv\Scripts\python.exe' `
  '.\shadow server\backend\setup\configure_env.py'
```

This creates missing settings from each server's `.env.example` and preserves
existing values. If your source copy includes someone else's `.env`, replace
its credentials with the settings for this laptop.

| Local configuration file | What to configure |
| --- | --- |
| `shadow server\backend\.env` | PostgreSQL host, port, database and user. The next step prompts for its password. Optional discovery chat route/provider settings also belong here. |
| `shadow server\backend\services\gateway\.env` | Provider API keys used by gateway-routed requests, including Credit Dossier's default route. |
| `repo server\credit-dossier\.env` | `DOSSIER_ROUTE`, `DOSSIER_PROVIDER`, `GATEWAY_URL` and model names. Its local provider keys are used when `DOSSIER_ROUTE=sdk`. |
| `repo server\policy-intelligence\.env` | Keys and models for the providers you want to use for AI explanations. Local policy checks work without provider keys. |
| `repo server\customer-assistant\.env` | Keys and models for the chatbot providers you want to use. |
| `repo server\loan-risk-classifier\.env` | `OLLAMA_MODEL`, initially `qwen2.5:1.5b`. No cloud key is needed. |
| `repo server\creditdb-MCP\.env` | `CREDITDB_DSN` for the local `creditdb` database. |

Open a file with Notepad, for example:

```powershell
notepad '.\shadow server\backend\.env'
notepad '.\shadow server\backend\services\gateway\.env'
notepad '.\repo server\credit-dossier\.env'
notepad '.\repo server\policy-intelligence\.env'
notepad '.\repo server\customer-assistant\.env'
notepad '.\repo server\creditdb-MCP\.env'
```

Set `GEMINI_API_KEY`, `MISTRAL_API_KEY` or `OPENAI_API_KEY` only for the providers
you intend to use. Each server reads its own file; settings are not shared.
For CreditDB, a password-based connection looks like:
`postgresql://postgres:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:5432/creditdb`.
URL-encode special characters in the password portion of that connection string.
HOST/PORT settings document the fixed launcher ports; these manual commands use
the explicit ports shown in Part 2.

### 4. Initialize the databases

Initialize discovery's database. This prompts for the PostgreSQL password,
saves it in the discovery backend's `.env`, and creates/seeds its database:

```powershell
Set-Location "$ProjectRoot\shadow server\backend"
& '.\.venv\Scripts\python.exe' -m engine.configure_start --configure
Set-Location $ProjectRoot
```

Create the separate fictional CreditDB database and seed its tables.
Use your PostgreSQL administrator's username if it is not `postgres`.
Run `CREATE DATABASE` only if `creditdb` does not already exist.

```powershell
psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -c 'CREATE DATABASE creditdb;'
psql -h 127.0.0.1 -p 5432 -U postgres -d creditdb `
  -f '.\shadow server\backend\services\creditdb\init.sql'
```

The second command creates the demo tables if missing and inserts fictional rows
without replacing existing rows. Ensure `creditdb-MCP\.env` uses the credentials
for this database; it does not borrow discovery's password.

### 5. Set up the gateway's private Python environment

From the project root:

```powershell
& '.\shadow server\backend\.venv\Scripts\python.exe' `
  '.\shadow server\backend\setup\configure_gateway.py'
```

This creates `shadow server\backend\services\gateway\.venv` and installs the
gateway's private MCP dependency, keeping it separate from CreditDB's MCP version.

### 6. Set up the proxy

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File '.\shadow server\backend\setup\proxy_setup.ps1' `
  -InstallRoot "$ProjectRoot\proxy-runtime" `
  -Python "$ProjectRoot\shadow server\backend\.venv\Scripts\python.exe"
```

This creates `proxy-runtime\.venv`, installs the proxy dependencies, generates
demo authentication and certificates, prepares the fictional CSV, and records
this laptop's log path. It does not install OS-wide certificate trust or change
the Windows system proxy.

### 7. Install both frontend dependencies

```powershell
Set-Location "$ProjectRoot\shadow server\frontend"
npm.cmd ci

Set-Location "$ProjectRoot\repo server\frontend"
npm.cmd ci

Set-Location $ProjectRoot
```

### 8. Download the local model

Start the Ollama desktop application. If Ollama is not running, use
`ollama serve` in a separate PowerShell terminal and leave it open. Then run:

```powershell
ollama pull qwen2.5:1.5b
ollama list
```

Initial setup is complete. Continue with Part 2 to start the application.

## Part 2 — Commands for subsequent runs

Ensure PostgreSQL is running. Open a separate PowerShell terminal/tab for each
service below and leave it open while that service is running.

**In every new terminal, first set this variable using your actual folder:**

```powershell
$ProjectRoot = 'C:\path\Shadow AI Discovery'
```

Start Ollama, the proxy and gateway before submitting requests through the apps.
You do not need to reinstall packages, recreate databases or download the model
on every run. Restart a server after editing its `.env`.

### Terminal 1 — Ollama (11434)

If the Ollama desktop app or an existing `ollama serve` terminal is already
running, use that instance and skip this command. Starting another instance
produces a port-in-use error.

```powershell
ollama serve
```

### Terminal 2 — Proxy and inspection UI (8080 / 8081)

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$ProjectRoot\proxy-runtime\services\proxy\run_proxy.ps1" -Offline
```

`-Offline` runs the local customer-data demonstration without forwarding uploads
to the external site. The UI password and demo proxy-user passwords are `demo`.

### Terminal 3 — AI gateway (4000)

This command explicitly loads the gateway's own `.env` before starting LiteLLM:

```powershell
Set-Location "$ProjectRoot\shadow server\backend"
& '.\services\gateway\.venv\Scripts\python.exe' -c "from dotenv import load_dotenv; import os; load_dotenv('services/gateway/.env', override=True); os.environ['DEBUG']='false'; from litellm import run_server; run_server()" --config services/gateway/config.yaml --host 127.0.0.1 --port 4000
```

### Terminal 4 — Discovery backend (8000)

```powershell
Set-Location "$ProjectRoot\shadow server\backend"
& '.\.venv\Scripts\python.exe' -m engine.dev_server backend
```

### Terminal 5 — Credit Dossier (8101)

```powershell
Set-Location "$ProjectRoot\repo server\credit-dossier"
& "$ProjectRoot\shadow server\backend\.venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8101
```

### Terminal 6 — Policy Intelligence (8102)

```powershell
Set-Location "$ProjectRoot\repo server\policy-intelligence"
& "$ProjectRoot\shadow server\backend\.venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8102
```

### Terminal 7 — Loan Risk Classifier (8103)

```powershell
Set-Location "$ProjectRoot\repo server\loan-risk-classifier"
& "$ProjectRoot\shadow server\backend\.venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8103
```

### Terminal 8 — Customer Assistant (8105)

```powershell
Set-Location "$ProjectRoot\repo server\customer-assistant"
& "$ProjectRoot\shadow server\backend\.venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8105
```

### Terminal 9 — CreditDB MCP (8765)

```powershell
Set-Location "$ProjectRoot\repo server\creditdb-MCP"
& "$ProjectRoot\shadow server\backend\.venv\Scripts\python.exe" server.py
```

### Terminal 10 — Discovery frontend (5173)

```powershell
Set-Location "$ProjectRoot\shadow server\frontend"
npm.cmd run dev -- --port 5173 --strictPort
```

### Terminal 11 — Repository frontend (5174)

```powershell
Set-Location "$ProjectRoot\repo server\frontend"
npm.cmd run dev -- --port 5174 --strictPort
```

### Open the application

| Page | URL |
| --- | --- |
| Discovery dashboard | http://127.0.0.1:5173 |
| Repository hub | http://127.0.0.1:5174 |
| Customer-data upload demo | http://127.0.0.1:5174/#/demos/customer-data |
| Proxy inspection UI | http://127.0.0.1:8081 — password: `demo` |

To check backend readiness from an additional terminal:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/health'
Invoke-RestMethod 'http://127.0.0.1:4000/health/liveliness'
Invoke-RestMethod 'http://127.0.0.1:8000/demos/s3/status'
```

Stop manually launched services with **Ctrl+C in each service terminal**.
If a port is already occupied, check for an existing service terminal or desktop
Ollama instance before launching a duplicate.
