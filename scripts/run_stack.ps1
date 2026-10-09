# Run the full five-layer stack as local processes (the project's only deployment path).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_stack.ps1          # start
#   powershell -ExecutionPolicy Bypass -File scripts\run_stack.ps1 -Stop    # stop
#
# Layers:
#   data        SQLite at cache/app.db          (or PostgreSQL via DATABASE_URL)
#   ingestion   prepare_data + db.seed          (one-shot, skipped if already done)
#   ml          uvicorn src.api.ml_app:app      port 8001
#   api         uvicorn src.api.app:app         port 8000  (ML_SERVICE_URL -> 8001)
#   dashboard   scripts/dashboard_server.py     port 8080  (static files + /api proxy)
#
# Set DATABASE_URL first if you want to use a real PostgreSQL instead of SQLite.
param(
    [switch]$Stop,
    [string]$Dataset = "cicids2017",
    [string]$LabelMode = "multiclass",
    [int]$ApiPort = 8000,
    [int]$MlPort = 8001,
    [int]$DashboardPort = 8080,
    [switch]$SkipSeed,
    [switch]$Open,         # open the dashboard in the default browser once the stack is up
    # Address the public API listens on. 127.0.0.1 = this machine only (default). For sensors on other
    # machines (LAN / Tailscale two-site demo) pass this machine's LAN or Tailscale IP, e.g. 100.101.102.103.
    # A non-loopback address requires GNNIDS_API_KEY to be set, so the API is never open to a network.
    [string]$BindHost = "127.0.0.1"
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
$loopback = @("127.0.0.1", "localhost", "::1")
if ($loopback -notcontains $BindHost -and -not $env:GNNIDS_API_KEY) {
    Write-Host "Refusing to expose the API on $BindHost without a key. Set one first, e.g.:"
    Write-Host '  $env:GNNIDS_API_KEY = -join ((48..57 + 97..122) | Get-Random -Count 32 | % {[char]$_})'
    Write-Host "and give the same key to each sensor (GNNIDS_API_KEY on that machine)."
    exit 1
}
$busy = Get-NetTCPConnection -State Listen -LocalPort $ApiPort -ErrorAction SilentlyContinue
if ($busy) {
    $owner = (Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Write-Host "Port $ApiPort is already in use by '$owner' (e.g. old Docker containers). Stop it first, or sensors"
    Write-Host "and the cyber range may talk to that program instead of this stack."
    exit 1
}
if (Test-Path $pidFile) {
    Write-Host "stack already running (see $pidFile); use -Stop first"
    if ($Open) { Start-Process "http://localhost:$DashboardPort/" }   # -Open still opens it
    return
}

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

# ---- api layer (forwards ML calls to the ml service)
$env:ML_SERVICE_URL = "http://127.0.0.1:$MlPort"
$api = Start-Process -FilePath $py -PassThru -WindowStyle Hidden `
    -ArgumentList "-m", "uvicorn", "src.api.app:app", "--host", "$BindHost", "--port", "$ApiPort" `
    -RedirectStandardOutput "logs\stack_api.log" -RedirectStandardError "logs\stack_api.err.log"

# ---- presentation layer: static dashboard + /api proxy to the API process
$proxy = Join-Path $root "scripts\dashboard_server.py"
$dash = Start-Process -FilePath $py -PassThru -WindowStyle Hidden `
    -ArgumentList "`"$proxy`"", "--port", "$DashboardPort", "--api", "http://$($BindHost -replace '^localhost$','127.0.0.1'):$ApiPort" `
    -RedirectStandardOutput "logs\stack_dashboard.log" -RedirectStandardError "logs\stack_dashboard.err.log"

"$($ml.Id) ml", "$($api.Id) api", "$($dash.Id) dashboard" | Set-Content -Encoding ascii $pidFile

Write-Host ""
Write-Host "dashboard : http://localhost:$DashboardPort/"
Write-Host "api docs  : http://localhost:$ApiPort/docs"
Write-Host "ml service: http://localhost:$MlPort/health"
if ($loopback -notcontains $BindHost) { Write-Host "sensors   : python sensor/agent.py --server http://${BindHost}:$ApiPort --site <name> --iface <n>  (with GNNIDS_API_KEY set)" }
Write-Host "logs      : logs\stack_*.log     stop: scripts\run_stack.ps1 -Stop"

if ($Open) {
    # the dashboard is ready immediately; the ML service finishes loading its models shortly after
    Start-Process "http://localhost:$DashboardPort/"
}
