$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OllamaExe = Join-Path $ProjectRoot 'endpoint\bin\ollama.exe'
if (-not (Test-Path -LiteralPath $OllamaExe)) { throw 'Place the Windows Ollama portable distribution in endpoint/bin first. See README.md.' }
$env:OLLAMA_MODELS = Join-Path $ProjectRoot 'endpoint\models'
$env:OLLAMA_HOST = '127.0.0.1:11434'
$Child = Start-Process -FilePath $OllamaExe -ArgumentList 'serve' -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
$Registry = Join-Path $ProjectRoot '.runtime\ollama.json'
@{id=$Child.Id; executable=$OllamaExe} | ConvertTo-Json | Set-Content -LiteralPath $Registry
Start-Sleep -Seconds 3
& $OllamaExe run qwen2.5:0.5b 'Say hello to the fictional demo bank.'
