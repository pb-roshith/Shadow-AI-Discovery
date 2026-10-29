param([switch]$Services)
$ErrorActionPreference = 'Stop'
$WorkspaceRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
& (Join-Path $WorkspaceRoot 'setup.bat')
exit $LASTEXITCODE
