# Run the full five-layer stack WITHOUT Docker, as local processes.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_stack.ps1          # start
#   powershell -ExecutionPolicy Bypass -File scripts\run_stack.ps1 -Stop    # stop
#
# Layers (same code as docker-compose, different packaging):
#   data        SQLite at cache/app.db          (Postgres/TimescaleDB in compose)
#   ingestion   prepare_data + db.seed          (one-shot, skipped if already done)
#   ml          uvicorn src.api.ml_app:app      port 8001
#   api         uvicorn src.api.app:app         port 8000  (ML_SERVICE_URL -> 8001)
#   dashboard   python -m http.server           port 8080  (nginx in compose)
#
# Set DATABASE_URL first if you want to use a real PostgreSQL instead of SQLite.
param(
    [switch]$Stop,
    [string]$Dataset = "cicids2017",
    [string]$LabelMode = "multiclass",
    [int]$ApiPort = 8000,
    [int]$MlPort = 8001,
    [int]$DashboardPort = 8080,
    [switch]$SkipSeed
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$pidFile = Join-Path $root "cache\stack.pids"
New-Item -ItemType Directory -Force (Join-Path $root "logs"), (Join-Path $root "cache") | Out-Null

function Stop-Stack {
    if (Test-Path $pidFile) {
        foreach ($line in Get-Content $pidFile) {
            $id = [int]($line -split '\s+')[0]
            $p = Get-Process -Id $id -ErrorAction SilentlyContinue
            if ($p) { Write-Host "stopping $($line)"; Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
        }
        Remove-Item $pidFile -Force
    }
    Write-Host "stack stopped"
}

if ($Stop) { Stop-Stack; return }
if (Test-Path $pidFile) { Write-Host "stack already running (see $pidFile); use -Stop first"; return }

$env:DATASET = $Dataset
$env:LABEL_MODE = $LabelMode
$env:PYTHONIOENCODING = "utf-8"

# ---- ingestion layer (one-shot; prepare_data is a no-op when the cache exists)
& $py -m experiments.prepare_data --dataset $Dataset
if (-not $SkipSeed) { & $py -m src.db.seed --dataset $Dataset --label-mode $LabelMode }

# ---- ml service layer
$ml = Start-Process -FilePath $py -PassThru -WindowStyle Hidden `
    -ArgumentList "-m", "uvicorn", "src.api.ml_app:app", "--host", "127.0.0.1", "--port", "$MlPort" `
    -RedirectStandardOutput "logs\stack_ml.log" -RedirectStandardError "logs\stack_ml.err.log"

# ---- api layer (forwards ML calls to the ml service, exactly like compose)
$env:ML_SERVICE_URL = "http://127.0.0.1:$MlPort"
$api = Start-Process -FilePath $py -PassThru -WindowStyle Hidden `
    -ArgumentList "-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1", "--port", "$ApiPort" `
    -RedirectStandardOutput "logs\stack_api.log" -RedirectStandardError "logs\stack_api.err.log"

# ---- presentation layer: static dashboard + /api proxy to the API process
$proxy = Join-Path $root "scripts\dashboard_server.py"
$dash = Start-Process -FilePath $py -PassThru -WindowStyle Hidden `
    -ArgumentList $proxy, "--port", "$DashboardPort", "--api", "http://127.0.0.1:$ApiPort" `
    -RedirectStandardOutput "logs\stack_dashboard.log" -RedirectStandardError "logs\stack_dashboard.err.log"

"$($ml.Id) ml", "$($api.Id) api", "$($dash.Id) dashboard" | Set-Content -Encoding ascii $pidFile

Write-Host ""
Write-Host "dashboard : http://localhost:$DashboardPort/"
Write-Host "api docs  : http://localhost:$ApiPort/docs"
Write-Host "ml service: http://localhost:$MlPort/health"
Write-Host "logs      : logs\stack_*.log     stop: scripts\run_stack.ps1 -Stop"
