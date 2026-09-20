param([switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$taskRoot = $PSScriptRoot
$backend = Join-Path $taskRoot "backend"
$frontend = Join-Path $taskRoot "frontend"
$runtime = Join-Path $taskRoot ".runtime"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$next = Join-Path $frontend "node_modules\next\dist\bin\next"
$node = (Get-Command node.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Force $runtime | Out-Null
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $next)) {
    throw "Install backend and frontend dependencies as described in README first."
}
function Ready([string]$Url) {
    try { return (Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 }
    catch { return $false }
}
Push-Location $backend
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Migration failed." }
} finally { Pop-Location }
if (-not (Ready "http://127.0.0.1:8000/health")) {
    $backendProcess = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $backend -WindowStyle Hidden -RedirectStandardOutput "$runtime\competition-api.out.log" -RedirectStandardError "$runtime\competition-api.err.log" -PassThru
    Set-Content "$runtime\competition-api.pid" $backendProcess.Id
}
$deadline = (Get-Date).AddSeconds(30)
while (-not (Ready "http://127.0.0.1:8000/api/v1/prevention/reports")) {
    if ((Get-Date) -gt $deadline) { throw "Competition API unavailable. Restart the project's old backend and try again." }
    Start-Sleep -Seconds 1
}
# The competition server has a separate port; other team development stays on 3000.
$url = "http://127.0.0.1:3030/competition"
if (-not (Ready $url)) {
    Push-Location $frontend
    try {
        & $node $next build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } finally { Pop-Location }
    $frontendProcess = Start-Process -FilePath $node -ArgumentList @("`"$next`"", "start", "--hostname", "127.0.0.1", "--port", "3030") -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput "$runtime\competition-web.out.log" -RedirectStandardError "$runtime\competition-web.err.log" -PassThru
    Set-Content "$runtime\competition-web.pid" $frontendProcess.Id
}
$deadline = (Get-Date).AddSeconds(45)
while (-not (Ready $url)) {
    if ((Get-Date) -gt $deadline) { throw "Frontend unavailable. See .runtime/competition-web.err.log" }
    Start-Sleep -Seconds 1
}
if (-not (Ready "http://127.0.0.1:3030/api/prevention/reports")) {
    throw "Frontend API proxy failed. Check INSIGHTCHECK_BACKEND_URL and rebuild."
}
if (-not $NoBrowser) { Start-Process $url }
Write-Host "Competition edition ready: $url"
Write-Host "Closing the browser does not stop the service. Use stop-competition.cmd."
