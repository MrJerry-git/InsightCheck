param(
    [switch]$CheckOnly,
    [ValidateSet("dashboard", "competition")][string]$Page = "dashboard"
)

$ErrorActionPreference = "Stop"
$workspaceRoot = $PSScriptRoot
$backendRoot = Join-Path $workspaceRoot "backend"
$frontendRoot = Join-Path $workspaceRoot "frontend"
$runtimeRoot = Join-Path $workspaceRoot ".runtime"
$backendPython = Join-Path $backendRoot ".venv\Scripts\python.exe"
$frontendModules = Join-Path $frontendRoot "node_modules"

function Test-ServiceUrl {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) {
    throw "Backend virtual environment not found: $backendPython. Follow README first."
}
if (-not (Test-Path -LiteralPath $frontendModules -PathType Container)) {
    throw "Frontend dependencies not found: $frontendModules. Run npm install first."
}

$npmCommand = Get-Command npm.cmd -ErrorAction Stop
$null = Get-Command node.exe -ErrorAction Stop

if ($CheckOnly) {
    Write-Host "Launcher environment check passed." -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

Push-Location $backendRoot
try {
    & $backendPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed."
    }
}
finally {
    Pop-Location
}

$backendHealthUrl = "http://127.0.0.1:8000/health"
$frontendUrl = "http://127.0.0.1:3000/$Page"
$backendDocsUrl = "http://127.0.0.1:8000/docs"

if (-not (Test-ServiceUrl -Url $backendHealthUrl)) {
    $backendProcess = Start-Process `
        -FilePath $backendPython `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $backendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtimeRoot "backend.out.log") `
        -RedirectStandardError (Join-Path $runtimeRoot "backend.err.log") `
        -PassThru
    Set-Content -LiteralPath (Join-Path $runtimeRoot "backend.pid") -Value $backendProcess.Id
}

if (-not (Test-ServiceUrl -Url $frontendUrl)) {
    $frontendProcess = Start-Process `
        -FilePath $npmCommand.Source `
        -ArgumentList @("run", "dev") `
        -WorkingDirectory $frontendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtimeRoot "frontend.out.log") `
        -RedirectStandardError (Join-Path $runtimeRoot "frontend.err.log") `
        -PassThru
    Set-Content -LiteralPath (Join-Path $runtimeRoot "frontend.pid") -Value $frontendProcess.Id
}

$deadline = (Get-Date).AddSeconds(90)
do {
    $backendReady = Test-ServiceUrl -Url $backendHealthUrl
    $frontendReady = Test-ServiceUrl -Url $frontendUrl
    if ($backendReady -and $frontendReady) {
        break
    }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

if (-not $backendReady -or -not $frontendReady) {
    throw "Services were not ready in 90 seconds. Check logs under $runtimeRoot."
}

Start-Process $frontendUrl
Start-Process $backendDocsUrl

Write-Host "Xunying services started." -ForegroundColor Green
Write-Host "Frontend: $frontendUrl"
Write-Host "Backend docs: $backendDocsUrl"
Write-Host "Runtime logs: $runtimeRoot"
