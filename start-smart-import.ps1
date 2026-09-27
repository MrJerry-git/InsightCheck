param([string]$Model = "qwen3-vl:4b-instruct", [switch]$Install)
$ErrorActionPreference = "Stop"
$taskRuntime = Join-Path $PSScriptRoot ".runtime\ollama"
New-Item -ItemType Directory -Force $taskRuntime | Out-Null
$localExe = Join-Path $taskRuntime "ollama.exe"
$existing = Get-Command ollama.exe -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $localExe) { $exe = $localExe }
elseif ($existing) { $exe = $existing.Source }
elseif ($Install) {
    $zip = Join-Path $taskRuntime "ollama.zip"
    Invoke-WebRequest "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip" -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $taskRuntime -Force
    $exe = $localExe
} else { throw "First run: powershell -ExecutionPolicy Bypass -File start-smart-import.ps1 -Install" }
$env:OLLAMA_HOST = "127.0.0.1:11434"
$env:OLLAMA_MODELS = Join-Path $taskRuntime "models"
$ready = $false
try { $null = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3; $ready = $true } catch {}
if (-not $ready) {
    $process = Start-Process $exe -ArgumentList "serve" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$taskRuntime\server.log" -RedirectStandardError "$taskRuntime\server.err.log"
    Set-Content "$taskRuntime\server.pid" $process.Id
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Seconds 1
        try { $null = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 2; $ready = $true } catch {}
    } until ($ready -or (Get-Date) -gt $deadline)
    if (-not $ready) { throw "Ollama failed to start. Check .runtime/ollama/server.err.log" }
}
$tags = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
if ($Model -notin @($tags.models.name)) {
    & $exe pull $Model
    if ($LASTEXITCODE -ne 0) { throw "Model download failed; run this script again to resume." }
}
Write-Host "Local model ready: $Model. Start/restart the competition backend next."
Write-Host "Default backend model is qwen3-vl:4b-instruct. For other models set IMPORT_MODEL in .env."
