$ErrorActionPreference = "Stop"
$taskRoot = $PSScriptRoot
foreach ($name in @("competition-web", "competition-api")) {
    $path = Join-Path $taskRoot ".runtime\$name.pid"
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $processNumber = [int](Get-Content -LiteralPath $path)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processNumber"
    if (-not $process) { continue }
    $expected = if ($name -eq "competition-web") {
        Join-Path $taskRoot "frontend\node_modules\next\dist\bin\next"
    } else { Join-Path $taskRoot "backend\.venv\Scripts\python.exe" }
    if ($process.CommandLine -notlike "*$expected*") {
        Write-Warning "PID $processNumber no longer matches the recorded project process; skipped."
        continue
    }
    # Stop this verified launcher and its descendants, never every Node/Python process.
    & taskkill.exe /PID $processNumber /T /F
}
Write-Host "Competition-owned services stopped. Shared pre-existing backend is left running."
