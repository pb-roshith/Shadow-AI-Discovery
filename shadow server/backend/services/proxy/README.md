# Corporate proxy and S3 demo

This component uses mitmproxy's built-in htpasswd authentication for five demo
identities, buffers uploads in memory, blocks matching AI uploads before opening
an upstream connection, and appends allowlisted metadata to proxy/DLP JSONL files.
It changes neither the Windows system proxy nor OS certificate trust during setup.

## Setup and run

Run the workspace-root `setup.bat` for automatic proxy setup in `proxy-runtime`.
It creates the proxy environment, installs dependencies, generates authentication
and certificates, prepares the fictional CSV and records this laptop's log path.
Then use root `start.bat` to launch the application and proxy together.
The commands below are for standalone proxy setup or repair.

From `shadow server/backend` in PowerShell:

```powershell
# Install in place, using the existing backend environment if present.
.\setup\proxy_setup.ps1
# Or deploy this component and its reference catalog/tests to the requested root:
.\setup\proxy_setup.ps1 -InstallRoot '..\..\proxy-runtime' -Python python

# In the installed root, first terminal:
.\services\proxy\run_proxy.ps1 -Offline
# Second terminal:
.\.venv\Scripts\python.exe .\scenarios\s3_pii_upload.py
```

`-Headless` selects mitmdump; otherwise mitmweb listens on localhost:8081 and the
proxy on localhost:8080. Open the UI at `http://127.0.0.1:8081` with password
`demo` (configured as a randomized Argon2 hash). Remove `-Offline` for real upstream traffic.
The five proxy users have password `demo`. Setup generates randomized bcrypt
hashes and checks every identity against the installed mitmproxy validator.
`-SkipInstall` on setup is for an environment whose dependencies already exist.

Setup creates the CA using mitmproxy's `CertStore.from_store`, the same initializer
used by mitmdump, instead of starting a temporary listening proxy. Public CA
exports go in `services/proxy/certs`; the private CA stays in
`%USERPROFILE%\.mitmproxy`. Scenario requests explicitly pass that public PEM as
`verify=`. TLS verification remains enabled. No global trust is installed.

The deterministic fictional CSV has exactly 14 accounts, a disclaimer, and
2,400,000 bytes (2.4 decimal MB). Regenerate with
`python scenarios/data/make_dummy_extract.py`. S3 supports `--user`, `--file`, and
isolated-test overrides `--proxy-port` and `--ca`. Success requires both HTTP 403
and `X-ShadowAI-DLP: blocked`, and exits 0. Other outcomes exit 1 with a diagnosis.

## Version and observed behavior

Validated locally with Python 3.14.7 and mitmproxy 12.3.1. The pure detection code
also targets Python 3.11. Current stable mitmproxy requires Python >=3.12, so
"Python 3.11 + latest stable mitmproxy" cannot both be satisfied in one interpreter.
Setup installs the latest available mitmproxy on Python >=3.12 and selects the
compatible `mitmproxy>=11,<12` line on Python 3.11. The 3.11/11.x combination has
not been exercised on this machine. See [mitmproxy package metadata](https://pypi.org/project/mitmproxy/)
and [installation documentation](https://docs.mitmproxy.org/stable/overview/installation/).

The installed built-in proxyauth carries `(username, password)` from CONNECT to
each HTTPS flow's metadata. Both add-ons read only the username; the logger never
serializes credentials. The header fallback extracts only a username, and does
not authorize access: the DLP add-on requires validated proxyauth metadata and an
allowlisted user. CONNECT itself is not logged. Rejected plain HTTP requests are
logged as 407; failed CONNECT requests have no tunneled HTTP flow to log.

The `response` hook fires for responses created in `request`, including DLP 403s.
It produces one proxy record without a special DLP logging fallback. An `error`
hook produces status 0 and a fixed `UpstreamError` class; raw exception messages
are never written. Per-flow metadata prevents duplicate completion records.
Timestamps use request start time with the machine's local UTC offset.

Launchers set `connection_strategy=lazy` **and** `upstream_cert=false`, preventing
certificate sniffing from opening an origin connection before inspection. The
test origin sees zero TCP connections and zero HTTP requests for blocked uploads.
Clean HTTPS uploads use verified upstream TLS and reach the same origin.
See [mitmproxy options](https://docs.mitmproxy.org/stable/concepts/options/).

Startup checks that both audit files are writable before opening the listener.
The DLP decision sets the block response before attempting an audit write, so
a later disk failure cannot turn a sensitive-data block into a forwarded upload.
The regression suite explicitly checks this failure case. A sandboxed launch in
the external installation directory requires write access to its logs; otherwise
startup now fails with a permission error.

## Privacy and inspection boundaries

Only the specified JSON fields are written to disk; no flow dumps or HAR files
are enabled. Startup disables configured automatic flow/HAR saving and streaming.
Console flow summaries are disabled. mitmweb retains flows transiently in memory
for the requested demo inspection; do not manually export flows or HAR files.
The UI flow comment shows `proxy_user=priya` (or the authenticated identity).
Request bodies must exist transiently
in memory for inspection and forwarding; these add-ons never persist them.

The JSONL writer serializes writes with one process-wide thread lock and flushes
each line. Run one proxy process per log directory. It does not coordinate multiple
independent proxy processes. `path_class` is upload/api/web, never a saved URL.

Only POST/PUT/PATCH bodies to exact AI hosts or their DNS subdomains are scanned.
Raw multipart and JSON text are supported. Rules decode UTF-8 with ignored errors
and scan only the first configured 10 MB. Compressed/archive payloads, escaped
representations, sensitive data beyond that prefix and unlisted hosts are outside
this demo's detection scope. Bodies are fully buffered; the inspection prefix is
not a total memory limit. Use only the fictional demo data.

Multiple matching labels produce one DLP record per label; account and PAN counts
are combined as Customer PII. Responses use the prescribed generic policy text
for every label, including when Customer PII and Confidential both match. In
`log_only`, `blocked` and `dlp_blocked` are false and clean online forwarding
continues. Offline mode responds locally after inspection: AI=401, non-AI=200,
policy block=403. Offline traffic never connects to origins.

## Discovery and reset

In-place proxy logs already share the discovery backend's `logs` directory. If
deploying with `-InstallRoot`, setup records the installed logs directory in the
source backend's ignored `services/proxy/deployment.json`. Discovery and its input
revision check read that pointer automatically. `SHADOWAI_PROXY_LOGS_DIR` remains
an explicit process-environment override. Both local and hybrid
collectors accept the schema. Hybrid reads live `flow_id` records in every mode,
deduplicating by flow (and label for DLP), and marks them as live evidence. Network
and DLP replay fixtures for a user/host are superseded once live records exist.
Network and DLP from the same user/host within two minutes join through existing rule J4.
Provider matching accepts AI subdomains and the OpenAI file-upload host.

Stop the proxy before `./reset_demo.ps1`, which clears only proxy.jsonl and
dlp.jsonl. The existing `setup/reset_demo.ps1` remains the full application reset.

## Optional Edge demo

Windows CurrentUser Root trust applies to every application in that Windows
account. A dedicated Edge profile **does not isolate CA trust**. Therefore the
browser variant requires an explicit opt-in and should use a disposable demo
Windows account:

```powershell
.\scenarios\s3_browser_profile.ps1 -InstallCurrentUserCA
# Enter priya / demo when prompted; paste ACC-0000123456 and send.
# After closing the dedicated Edge window:
.\scenarios\s3_browser_profile.ps1 -Remove
```

The script records whether it installed the certificate so cleanup preserves
preexisting trust. It removes only its dedicated Priya profile, checking the
absolute removal path and refusing reparse points. The S3 Python script is the
default path when profile-scoped certificate trust is required. ChatGPT's live
site may require sign-in or use additional upload hosts; add observed upload hosts
to `extra_ai_hosts` and restart. Offline mode does not provide a working ChatGPT UI.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_dlp_rules tests.test_proxy_integration tests.test_proxy_privacy -v
# In the source backend, also validate discovery/J4:
.\.venv\Scripts\python.exe -m unittest tests.test_proxy_discovery -v
```

Tests generate temporary bcrypt credentials, a proxy CA, logs and a trusted local
HTTPS origin; no external websites or global certificate trust are needed. They
exercise auth/CONNECT identity, the 14-match block, zero origin connections,
clean forwarding, all five identities, non-AI traffic, offline responses,
multiple labels, log-only behavior, upstream errors, CLI narration and log privacy.
