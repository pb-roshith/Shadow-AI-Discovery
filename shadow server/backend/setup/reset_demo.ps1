$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'stop.ps1')
Set-Location -LiteralPath $ProjectRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonExe)) { $PythonExe = (Get-Command python).Source }
& $PythonExe -c "from engine.bootstrap import reset_demo_results; reset_demo_results()"
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL reset failed; local files were preserved' }
& $PythonExe -m scenarios.demo reset
if ($LASTEXITCODE -ne 0) { throw 'Reset failed' }
Write-Host 'Reset PostgreSQL discovery results, seeded demo telemetry, logs and the live scratch repo. Reference edits, custom database events and baseline repos preserved.'
