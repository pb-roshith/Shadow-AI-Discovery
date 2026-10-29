# Shadow AI workspace

The authenticated corporate proxy and S3 customer-upload demo are documented in
[services/proxy/README.md](shadow%20server/backend/services/proxy/README.md).
Root `setup.bat` automatically installs and initializes the proxy in `proxy-runtime`,
including its dependencies, demo authentication, certificates and fictional data.
It regenerates the deployment paths for the current laptop; no separate proxy setup is needed.
Root `start.bat` starts mitmweb in offline demo mode alongside the other services,
using the installation recorded in `services/proxy/deployment.json` (currently
`proxy-runtime` inside this workspace). Open http://127.0.0.1:8081 with password `demo`; the proxy
listens on port 8080 and writes metadata for discovery/J4. Root `stop.bat` stops
the proxy when launched by the workspace. An independently started, matching
proxy is reused and left running. For real upstream traffic, start
`services/proxy/run_proxy.ps1` without `-Offline` from the proxy installation.

For a presenter-led S3 demonstration, open
`http://127.0.0.1:5174/#/demos/customer-data` or select **Open customer data demo**
on the repository hub. With the proxy running, click **Upload fictional customer
extract** to show Priya's actual 403 response and the matching 14-count DLP
record. Click **Run discovery** to show the Network + DLP finding joined by J4,
then open the discovery dashboard for its full details. The demo uses only a
server-generated fictional extract; it accepts no customer file or destination
input. The discovery backend serves `/demos/s3/*`, proxied through the repository
frontend's `/api/demos/*` routes. Production hosting must forward those routes.

Run root `setup.bat` once, then root `start.bat`. Root `stop.bat` stops every process owned by the launcher, including both React frontends, discovery API, all four repository APIs, CreditDB MCP, LiteLLM gateway, and Ollama. Each server opens in its own named tab in one Windows Terminal window with live output. The coordinator runs hidden; startup and shutdown diagnostics are in `.runtime/launcher.log`. Stopping a server deliberately exits its tab successfully so Windows Terminal closes it without a restart prompt. Windows Terminal (wt.exe) is required. Install Ollama before starting. The launcher starts `ollama serve` on localhost:11434 in its own tab before the application services. If Ollama is already running independently, it is reused and left running by `stop.bat`. PID ownership records are in `.runtime/`. Services bind to localhost; unknown processes occupying these ports are never stopped automatically.

```text
shadow server/
  frontend/               discovery React app (5173)
  backend/                discovery FastAPI (8000), gateway (4000)
repo server/
  frontend/               ONE shared React frontend (5174)
  credit-dossier/         independent FastAPI app (8101)
  policy-intelligence/        independent FastAPI app (8102)
  loan-risk-classifier/          Loan Risk Classifier, local Ollama (8103)
  customer-assistant/            independent FastAPI app (8105)
  creditdb-MCP/               independent MCP server (8765)
```

There is no shared repository backend. Each application owns its `app.py`, requirements and `.env`, and runs as a separate Uvicorn process. CreditDB owns `server.py` and runs as a separate MCP process. The four application APIs expose `GET /api/health`, `POST /api/run` and `/docs` on their own ports; CreditDB exposes `/api/health`, `/api/tools` and `/mcp`. You can run one independently from its folder with `python -m uvicorn app:app --host 127.0.0.1 --port PORT` after installing that repo's requirements. The root launcher uses one Python environment to install dependencies but starts separate API processes.

Discovery: http://127.0.0.1:5173
Repository frontend: http://127.0.0.1:5174
API docs: http://127.0.0.1:8101/docs through http://127.0.0.1:8105/docs

The repository frontend contains six clickable cards, including CreditDB MCP with its live tool list. A workspace sends requests through a Vite proxy to that repo's own API. If one repository API is unavailable, the other cards remain available. Production hosting must configure all six proxy mappings too.

## Environment configuration

`shadow server/backend/setup/configure_env.py` and `setup.bat` create an ignored `.env` beside each server from its credential-free `.env.example`, preserving existing settings. Each repository server reads only its own file. Local values take precedence over inherited process variables; an explicitly empty key disables that provider. No server reads `repo server/.env`, a sibling server's `.env`, or the discovery backend's `.env`.

Provider keys and model names belong in `repo server/credit-dossier/.env`, `repo server/policy-intelligence/.env` and `repo server/customer-assistant/.env` independently. The classifier uses `repo server/loan-risk-classifier/.env` for `OLLAMA_MODEL`; CreditDB uses `repo server/creditdb-MCP/.env` for `CREDITDB_DSN`. The AI gateway reads `shadow server/backend/services/gateway/.env`; gateway-routed calls use its keys rather than the calling application's SDK keys. Discovery keeps its own configuration in `shadow server/backend/.env`.

For legacy installations, run `python "shadow server/backend/setup/configure_env.py" --migrate-shared` with the backend environment to copy relevant shared values into local files, verify them and remove the common file. Normal setup does not copy settings between servers. Restart a server after changing its `.env`. HOST/PORT entries document the launcher's fixed localhost ports; to change ports, update both `shadow server/backend/setup/workspace_services.py` and `repo server/frontend/src/repos.js`.

Credit Dossier accepts credit memo uploads and answers document-grounded questions through Gemini or Mistral. The frontend has a provider selector. Set `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `GEMINI_MODEL` (default `gemini-3.5-flash-lite`), `MISTRAL_API_KEY` and `MISTRAL_MODEL` (default `mistral-small-latest`) as needed. The discovery chat uses the same adapter; its provider is selected with `DOSSIER_PROVIDER` in the discovery backend `.env`. Gemini is the default.

Policy Intelligence checks company loan requests against its sample bank policy locally and optionally adds an explanation through the OpenAI, Mistral or Gemini SDK, selected in the form. Open `#/repos/policy-intelligence`; the form includes passing and violating examples and a downloadable policy. Loan Risk Classifier uses local Ollama on port 11434, with no cloud API key. Open `#/repos/loan-risk-classifier` and choose an installed local model. Customer Assistant is a multi-provider chatbot using Gemini, Mistral or OpenAI. Keys stay out of React; provider calls can incur usage charges when submitted. The gateway is a localhost development service with no master-key requirement. Credit Dossier defaults to the gateway route (`DOSSIER_ROUTE=gateway`). Set `DOSSIER_ROUTE=sdk` only for direct SDK requests; those do not produce gateway evidence.

## Validation

From the root: `"shadow server/backend/.venv/Scripts/python.exe" -m unittest discover -s "repo server/tests" -v`.

From `shadow server/backend`: `.venv/Scripts/python.exe -m unittest tests.test_scenarios tests.test_api tests.test_correlation tests.test_dev_server -v`.

Run `npm.cmd run build` from either frontend folder. The discovery scanner reads the application repositories from `repo server`; isolated test scenarios retain temporary local fixtures.



## Live Scenario 1

Run discovery defaults to `hybrid`: Scenario 1 reads actual repository code plus live metadata from `shadow server/backend/logs/gateway.jsonl` and, when available, `proxy.jsonl`. S1 seeded database/replay runtime events are excluded, while other scenarios retain their demo telemetry. Results are saved to PostgreSQL. The UI labels the mixed source explicitly; an offline replay mode remains available for fixture testing.

Credit Dossier defaults to LiteLLM's OpenAI-compatible completion endpoint on port 4000, with its application ID and a fresh request ID. Gemini and Mistral SDK routes remain available with DOSSIER_ROUTE=sdk. Gateway provider keys belong in `shadow server/backend/services/gateway/.env`. The API app must be restarted after configuration changes.

The [LiteLLM custom callback](https://docs.litellm.ai/docs/observability/custom_callback) records pending/success/failure metadata without prompts, responses or keys. Discovery deduplicates callbacks using the request ID, so one invocation counts once and rerunning discovery does not inflate it. Pending and failed requests establish that the app invoked the gateway; they are never described as successful responses. Code-only recurrence is zero; actual invocation counts drive runtime recurrence.

Gateway evidence identifies the application/provider/model. A separate Network clue requires a real proxy log; gateway callbacks never synthesize proxy traffic. The internet proxy is not started by the workspace launcher. If no correctly configured proxy captures traffic, a Code + Gateway candidate is expected.

Confidence grows from executable code to observed runtime. Risk grows with observed exposure, bypass/approval state, credentials and sensitive-data evidence, rather than call count alone. AI tool approvals apply globally across every repository. An application is Approved only when all detected tools are globally Approved. Missing approvals produce Unknown; Restricted or Revoked tools block application approval. Legacy application/host entries are migrated to tool approvals, preserving the stricter status if entries conflict.

Live smoke verification: Google code-only confidence/risk 40/15; one successful Gemini gateway request produced 80/50 with one Gateway event; another discovery run still counted one. No seeded S1 Network clues remained. `tests.test_live_s1` covers absence of fabricated runtime, callback deduplication, score changes, repeated discovery and real-proxy-only Network evidence.

## Scenario 6: Customer Assistant

The former readme-only repository is now customer-assistant, a conversation chatbot
using Gemini, Mistral or OpenAI SDKs. Open http://127.0.0.1:5174/#/repos/customer-assistant.
Gemini reads its key/model from credit-dossier/.env; keys are never copied into code.
Configure MISTRAL_API_KEY or OPENAI_API_KEY in customer-assistant/.env
to use those providers. Conversation history is held in the browser for the current chat.

Discovery scans all three SDK integrations. Actual SDK attempts are recorded in
backend/logs/sdk_calls.jsonl with request ID, provider, model, timestamp and outcome.
These are application SDK invocation records, not captured network packets; they
contain no prompts, replies or credentials. Discovery deduplicates by request ID
and keeps the chatbot separate from other apps using its own service identity.

The Customer Assistant README includes a clearly labeled, nonfunctional OpenAI demo
credential for secret scanning. The app never reads it; discovery stores its fingerprint
and masked preview, never the complete dummy value.


Scenarios 1 and 6 always use actual application code and live invocation metadata in every discovery mode. Use credit-dossier or customer-assistant to make requests, then run discovery to update scores. No request means no runtime signal; code evidence may still appear. S1 gateway callbacks and direct SDK calls, and S6 SDK calls, record request IDs and outcomes without prompts, responses or keys. Failed attempts are recorded as failed, not successful usage. Recurrence counts recorded attempts, deduplicated by request ID; code files do not add invocations. Demo setup preserves live logs and does not generate S1/S6 runtime evidence. Other scenarios retain demo fixtures.


## Loan Risk Classifier in Shadow AI

S7 now represents the actual Loan Risk Classifier using local Ollama, not the former simulated Anthropic scenario. Discovery reads current Ollama code under the canonical loan-risk-classifier application name and reads only real app invocation metadata from logs/ollama_calls.jsonl. Request IDs deduplicate attempts, success/failure counts remain separate, and metadata-only evidence snapshots support candidate audit verification. Local calls appear under Endpoint and add no external-exposure points. Old AI Risk Classifier log entries are retained as history but are not attributed to the current loan application. The former S7 simulation endpoint is retired.

The clue map always shows all scenarios, including connected live applications, code-only integrations, and retained demo scenarios. Imports alone do not prove an invocation. Signal labels match the global evidence list. S4 endpoint demo evidence is separate from S7 application activity. Existing historical runs and issue evidence packs are preserved.


## Scenario 2: Policy Intelligence

The former loan-ops-helper is now policy-intelligence (port 8102). Submit the company loan form to evaluate 13 clauses from `repo server/policy-intelligence/bank_policy.json`. Each result includes the clause text, submitted or calculated value, pass/violation status, and overall policy compliance. Checks work without credentials. Optional OpenAI, Mistral or Gemini explanations send the company form and policy to the selected provider and record metadata-only SDK attempts. Discovery uses actual S2 SDK evidence and preserves historical Git secret evidence; seeded S2 network calls are retired. Existing historical discovery runs remain unchanged. See `repo server/policy-intelligence/README.md`.


## Dynamic candidate list and clue map

Decision rules use first-match order R0, R1, R3, R4, R2, R5. Exposed credentials raise an issue under R0 regardless of approval or confidence. R1 classifies confidence below 40 as False positive. At confidence 40 or above, risk 70 or above raises an issue for unapproved tools under R3 and approved tools under R4. Approved tools with confidence at least 70 and risk below 70 are Genuine under R2; all remaining findings are Monitor under R5. Thresholds remain configurable. Exposed credentials increase data and control risk; write/destructive MCP capability increases autonomy and control risk even when the tool is approved. Capability evidence does not establish that a destructive action succeeded. Restart the backend after updating to migrate stored rule descriptions, then run discovery to refresh current decisions.

Shadow AI defaults to live application discovery. The clue map shows all detected integrations, including SDK imports and dependencies labeled as code-only evidence. Recorded SDK/gateway/local inference activity and detected credentials remain distinct clues. The candidate list initially shows recorded activity or detected credentials; its checkbox also includes code-only integrations. Demo proxy, DLP, endpoint and MCP fixtures are excluded from live mode; legacy replay modes remain available through the API for isolated demonstrations and tests. Historical issues and audit records are retained.

While Shadow AI is open, the frontend checks for changed repository files, Git metadata and invocation logs every 10 seconds. `POST /discovery/refresh` reruns discovery only when those inputs change. An unchanged refresh keeps the same run and counts. Manual Run discovery remains available. Credentials are visible as findings without being counted as AI invocations.

Scenarios, candidates, signals and the latest run load together from `/discovery/state` under the discovery lock. Scenario decisions and scores come from current candidates; catalogue expectations never substitute for missing evidence. A scenario without a current candidate shows “No current evidence.” Multi-provider scenarios list each candidate's decision and use the highest-priority issue, then highest risk, for the summary. Rule, scoring and reference file changes also invalidate the discovery input revision.

## CreditDB MCP (Scenario 5)

CreditDB now lives in `repo server/creditdb`. Root `start.bat` starts it in its own named tab and waits for `/api/health`; `stop.bat` stops its owned process. Its MCP endpoint remains http://127.0.0.1:8765/mcp. Open http://127.0.0.1:5174/#/repos/creditdb-MCP to view the current tools, read/write permissions, descriptions and inputs. Listing tools needs no database connection. Executing tools requires the existing local fictional PostgreSQL `creditdb` and `loans` table. Configure `CREDITDB_DSN` in `creditdb-MCP/.env`; CreditDB does not read the discovery backend `.env`. Audit logs remain in the discovery backend for Scenario 5 correlation. See `repo server/creditdb-MCP/README.md`.

Scenario 5 now uses the repository identity `creditdb-MCP` in the scenario card, candidates and clue map. Its MCP configuration and live tools/list are collected directly from the independent server; actual audit calls retain their caller identity separately. Installed discovery excludes replay CreditDB runtime events. Restart the services after this rename and run discovery to refresh current candidates.

## Gateway MCP dependency isolation

LiteLLM 1.106.4 requires the MCP 2 `CacheableResult` API; discovery and CreditDB use MCP 1. `setup.bat` runs `shadow server/backend/setup/configure_gateway.py` to create `shadow server/backend/services/gateway/.venv` with a private MCP 2.3.0 install. Its remaining dependencies come from the workspace backend environment through a site-packages link. Machine-wide and user Python packages are excluded. The launcher runs only the gateway with this private interpreter; discovery and CreditDB keep the shared MCP 1 environment. After moving the workspace, rerun setup to refresh the link.


## Analytics dashboard

Open **Dashboard ? Analytics** in discovery, or `http://127.0.0.1:5173/?page=analytics`.
The six current scenarios have request counts for today, this calendar week (Monday onward),
and this calendar month in India Standard Time. Choose a reporting period and application
to inspect daily activity, input/output model tokens, average request duration,
successful and failed request counts, and request outcomes. The page refreshes every 10 seconds.

`GET /discovery/analytics?period=week&application=all` aggregates actual SDK, gateway,
Ollama, browser proxy and MCP audit metadata. Lifecycle records are deduplicated per
application and request ID; DLP records do not add a second browser request. Failed and
blocked attempts count, and unknown historical outcomes remain unknown. Replay fixtures
are excluded. Token counts come from provider responses and duration from measured calls;
historical missing measurements display as unavailable. Browser uploads and MCP tools
do not have model token usage. No prompt, document, response body or credential is added
to the telemetry. Restart the affected application services after upgrading measurement
code; the installed proxy must also use the updated metadata logger.

The Analytics page ends with **AI call audit traces**, filtered by the selected
period and application, with 25 calls per page. Each trace includes the model,
provider, outcome, input/output/total tokens, duration and an eye icon that opens model input
and output in a popup. New SDK, gateway and Ollama calls capture their messages and model
output in `shadow server/backend/logs/model_traces.jsonl`, separately from the
metadata-only discovery evidence. The earlier metadata-only description applies
to the discovery logs; audit content is now retained locally for this view.
Historical content cannot be recovered and displays **Not recorded**. Browser
uploads and MCP tools retain available metadata without invented model content
or token counts. Restart the application APIs, gateway and discovery backend
after upgrading to activate audit capture. The audit API is
`GET /discovery/analytics/traces?period=week&application=all&page=1&page_size=25`.
