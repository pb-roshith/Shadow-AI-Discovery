param([switch]$InstallCurrentUserCA, [switch]$Remove)
$ErrorActionPreference = 'Stop'
$DemoRoot = Split-Path -Parent $PSScriptRoot
$BrowserRoot = [IO.Path]::GetFullPath((Join-Path $DemoRoot 'browser'))
$ProfilePath = [IO.Path]::GetFullPath((Join-Path $BrowserRoot 'priya'))
$ReceiptPath = Join-Path $BrowserRoot 'priya-cert.json'
if ($Remove) {
    if (Test-Path -LiteralPath $ReceiptPath) {
        $Receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
        if ($Receipt.InstalledByDemo -and $Receipt.Thumbprint -match '^[A-Fa-f0-9]{40}$') {
            & certutil.exe -user -delstore Root $Receipt.Thumbprint
            if ($LASTEXITCODE -ne 0) { throw 'Could not remove demo CA' }
        }
        Remove-Item -LiteralPath $ReceiptPath -Force
    }
    if (Test-Path -LiteralPath $ProfilePath) {
        $ResolvedProfile = (Resolve-Path -LiteralPath $ProfilePath).Path
        if ($ResolvedProfile -ne (Join-Path $BrowserRoot 'priya') -or
            -not $ResolvedProfile.StartsWith($BrowserRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Unsafe browser profile removal target'
        }
        $Links = Get-ChildItem -LiteralPath $ResolvedProfile -Recurse -Force |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
        if ($Links -or ((Get-Item -LiteralPath $ResolvedProfile).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Profile contains reparse points; review and remove it manually'
        }
        Remove-Item -LiteralPath $ResolvedProfile -Recurse -Force
    }
    Write-Host 'Removed demo-owned CurrentUser CA trust and the Priya profile. Restart Edge to clear cached trust.'
    exit
}
if (-not $InstallCurrentUserCA) {
    throw 'Windows CurrentUser Root trust applies to ALL apps for this user, beyond the Priya profile. Use -InstallCurrentUserCA only in a disposable demo Windows account, or use the S3 Python script for scoped trust.'
}
$CertPath = Join-Path $DemoRoot 'services\proxy\certs\mitmproxy-ca-cert.cer'
if (-not (Test-Path -LiteralPath $CertPath)) { throw 'Run setup\proxy_setup.ps1 first' }
$Certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CertPath)
New-Item -ItemType Directory -Path $BrowserRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $ReceiptPath)) {
    $AlreadyTrusted = Test-Path -LiteralPath "Cert:\CurrentUser\Root\$($Certificate.Thumbprint)"
    @{ Thumbprint = $Certificate.Thumbprint; InstalledByDemo = (-not $AlreadyTrusted) } |
        ConvertTo-Json | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
}
Write-Host 'CA trust will apply to every application in this Windows account until removed.'
& certutil.exe -user -addstore Root $CertPath
if ($LASTEXITCODE -ne 0) { throw 'Could not add CurrentUser CA' }
$EdgeCandidates = @((Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
                    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'))
$Edge = $EdgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Edge) { throw 'Microsoft Edge was not found' }
Start-Process -FilePath $Edge -WindowStyle Normal -ArgumentList @("--user-data-dir=`"$ProfilePath`"", '--proxy-server=http://127.0.0.1:8080', 'https://chatgpt.com')
Write-Host 'Enter proxy credentials priya / demo. Paste ACC-0000123456 into ChatGPT and press send.'
Write-Host 'Expect the message to fail and dlp.jsonl to gain a line. Use online mode for the browser UI.'
Write-Host 'If uploads use another host, inspect mitmweb, add it to extra_ai_hosts, then restart.'
Write-Host 'After the demo close the dedicated Edge window and run this script with -Remove.'
