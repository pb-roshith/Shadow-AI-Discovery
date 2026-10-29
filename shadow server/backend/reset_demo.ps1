param([string]$DemoRoot = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$ResolvedRoot = (Resolve-Path -LiteralPath $DemoRoot).Path
foreach ($Name in @('proxy.jsonl', 'dlp.jsonl')) {
    $LogPath = [IO.Path]::GetFullPath((Join-Path $ResolvedRoot "logs\$Name"))
    if (-not $LogPath.StartsWith($ResolvedRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe log path' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $LogPath) -Force | Out-Null
    [IO.File]::WriteAllText($LogPath, '')
}
Write-Host 'Cleared proxy and DLP logs. Stop the proxy before reset.'
