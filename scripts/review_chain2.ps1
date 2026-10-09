# Second batch of review experiments (starts after scripts/review_chain.ps1 finishes), run one after another on the GPU (detached: survives a closed
# session, not a reboot). Each step's start/end and exit code go to logs/chain_review.steps.log; output to
# logs/chain_review.log. Re-running skips steps whose marker file already exists.
#
#   powershell -ExecutionPolicy Bypass -File scripts\review_chain.ps1
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$steps = "logs\chain_review2.steps.log"
$out = "logs\chain_review2.log"
$env:PYTHONIOENCODING = "utf-8"

$CTX = "ffnn_ctx_ewc_replay ffnn_ctx_joint xgboost_replay xgboost_joint xgboost_ctx_replay"
$DROP = "features.drop=[dst_port,protocol,fwd_init_win_bytes,bwd_init_win_bytes]"
$T = "split.strategy=temporal_attack"

$plan = @(
  # standard continual-learning baselines on the same graph network (review point 3)
  @{ id = "cl17";   done = "results\cicids2017\multiclass\continual\seed44\final_predictions_gnn_derpp.parquet";
     args = "-m experiments.run_continual --dataset cicids2017 --label-mode multiclass --seeds 42 43 44 --no-checkpoints --models gnn_lwf gnn_derpp" },
  @{ id = "cl17t";  done = "results\cicids2017\multiclass\continual_temporal\seed46\final_predictions_gnn_derpp.parquet";
     args = "-m experiments.run_continual --dataset cicids2017 --label-mode multiclass --set $T --seeds 42 43 44 45 46 --out-name continual_temporal --no-checkpoints --models gnn_lwf gnn_derpp" },
  # does it generalise to another network? train on CIC-IDS2017, test on CSE-CIC-IDS2018 (review point 6)
  @{ id = "x17to18"; done = "results\cross_dataset\cicids2017_to_csecicids2018\summary.csv";
     args = "-m experiments.run_cross_dataset --train cicids2017 --test csecicids2018 --seeds 42 43 44" },
  # the graph without the degree node feature it is handed directly (review point 2)
  @{ id = "nodeg17t"; done = "results\cicids2017\multiclass\continual_temporal_nodegree\seed46\final_predictions_gnn_ewc_replay.parquet";
     args = "-m experiments.run_continual --dataset cicids2017 --label-mode multiclass --set $T graph.node_features=constant --seeds 42 43 44 45 46 --out-name continual_temporal_nodegree --no-checkpoints --models gnn_ewc_replay" }
)

while (-not (Select-String -Path "logs\chain_review.steps.log" -Pattern "ALL DONE" -Quiet)) { Start-Sleep 60 }
"[$(Get-Date -Format HH:mm:ss)] REVIEW CHAIN 2 START ($($plan.Count) steps)" | Add-Content $steps
$i = 0
foreach ($s in $plan) {
  $i++
  if (Test-Path $s.done) { "[$(Get-Date -Format HH:mm:ss)] STEP $i/$($plan.Count) $($s.id) SKIP (done)" | Add-Content $steps; continue }
  "[$(Get-Date -Format HH:mm:ss)] STEP $i/$($plan.Count) $($s.id) START $($s.args)" | Add-Content $steps
  $p = Start-Process -FilePath $py -ArgumentList $s.args -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput "logs\chain_review2_$($s.id).out.log" -RedirectStandardError "logs\chain_review2_$($s.id).err.log"
  "[$(Get-Date -Format HH:mm:ss)] STEP $i/$($plan.Count) $($s.id) END rc=$($p.ExitCode)" | Add-Content $steps
}
"[$(Get-Date -Format HH:mm:ss)] ALL DONE" | Add-Content $steps

