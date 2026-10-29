param([switch]$Headless, [switch]$Offline, [string]$Python, [string]$Config)
$ErrorActionPreference = 'Stop'
$DemoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Python) { $Python = Join-Path $DemoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python environment missing. Run setup\proxy_setup.ps1 first or supply -Python.' }
if (-not $Config) { $Config = Join-Path $PSScriptRoot 'proxy_config.yaml' }
$PreviousConfig = $env:SHADOWAI_PROXY_CONFIG
$PreviousOffline = $env:SHADOWAI_PROXY_OFFLINE
try {
    $env:SHADOWAI_PROXY_CONFIG = (Resolve-Path -LiteralPath $Config).Path
    $env:SHADOWAI_PROXY_OFFLINE = if ($Offline) { '1' } else { '0' }
    Push-Location -LiteralPath $DemoRoot
    try {
        & $Python -m services.proxy.launch_proxy $(if ($Headless) { '--headless' })
        if ($LASTEXITCODE -ne 0) { throw "Proxy exited with code $LASTEXITCODE" }
    } finally { Pop-Location }
} finally {
    $env:SHADOWAI_PROXY_CONFIG = $PreviousConfig
    $env:SHADOWAI_PROXY_OFFLINE = $PreviousOffline
}
