param([string]$InstallRoot, [string]$Python = 'python', [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$SourceRoot = Split-Path -Parent $PSScriptRoot
$DemoRoot = $SourceRoot
if ($InstallRoot) {
    $DemoRoot = [IO.Path]::GetFullPath($InstallRoot)
    if ($DemoRoot -ne $SourceRoot) {
        foreach ($Relative in @('services\proxy', 'scenarios\data', 'reference')) {
            $Destination = Join-Path $DemoRoot $Relative
            New-Item -ItemType Directory -Path $Destination -Force | Out-Null
            Get-ChildItem -LiteralPath (Join-Path $SourceRoot $Relative) -File |
                Where-Object { $_.Name -ne 'htpasswd' } |
                Copy-Item -Destination $Destination -Force
        }
        foreach ($Relative in @('setup\proxy_setup.ps1', 'scenarios\s3_pii_upload.py', 'scenarios\s3_browser_profile.ps1', 'reset_demo.ps1')) {
            $Destination = Join-Path $DemoRoot $Relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $SourceRoot $Relative) -Destination $Destination -Force
        }
        New-Item -ItemType Directory -Path (Join-Path $DemoRoot 'tests') -Force | Out-Null
        foreach ($Name in @('proxy_harness.py', 'test_dlp_rules.py', 'test_proxy_integration.py', 'test_proxy_privacy.py')) {
            Copy-Item -LiteralPath (Join-Path $SourceRoot "tests\$Name") -Destination (Join-Path $DemoRoot "tests\$Name") -Force
        }
        Set-Content -LiteralPath (Join-Path $DemoRoot 'tests\__init__.py') -Value '' -Encoding UTF8
    }
}
$VenvPython = Join-Path $DemoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $Python -m venv (Join-Path $DemoRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment' }
}
if (-not $SkipInstall) {
    $Minor = & $VenvPython -c 'import sys; print(sys.version_info.minor if sys.version_info.major == 3 else 0)'
    if ([int]$Minor -lt 11) { throw 'Python 3.11 or newer is required' }
    $MitmRequirement = if ([int]$Minor -eq 11) { 'mitmproxy>=11,<12' } else { 'mitmproxy' }
    Write-Host "Installing $MitmRequirement. Current stable mitmproxy requires Python 3.12+."
    & $VenvPython -m pip install --upgrade $MitmRequirement requests pyyaml bcrypt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
Push-Location -LiteralPath $DemoRoot
try {
    & $VenvPython -m services.proxy.setup_proxy --config (Join-Path $DemoRoot 'services\proxy\proxy_config.yaml')
    if ($LASTEXITCODE -ne 0) { throw 'Proxy initialization failed' }
} finally { Pop-Location }
$DeploymentFile = Join-Path $SourceRoot 'services\proxy\deployment.json'
@{ logs_dir = (Join-Path $DemoRoot 'logs') } | ConvertTo-Json |
    Set-Content -LiteralPath $DeploymentFile -Encoding UTF8
Write-Host "Next: & '$DemoRoot\services\proxy\run_proxy.ps1' -Offline"
Write-Host "Then: & '$VenvPython' '$DemoRoot\scenarios\s3_pii_upload.py'"
Write-Host 'Run discovery after S3. No Windows proxy or certificate trust settings were changed.'
