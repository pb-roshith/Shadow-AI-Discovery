$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonExe)) { $PythonExe = (Get-Command python).Source }
& $PythonExe -m engine.configure_start --configure
if ($LASTEXITCODE -ne 0) { throw 'Database configuration failed. Check backend/.env and the PostgreSQL service.' }
