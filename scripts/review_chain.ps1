# The experiments the external review asked for, run one after another on the GPU (detached: survives a closed
# session, not a reboot). Each step's start/end and exit code go to logs/chain_review.steps.log; output to
# logs/chain_review.log. Re-running skips steps whose marker file already exists.
#
#   powershell -ExecutionPolicy Bypass -File scripts\review_chain.ps1
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$steps = "logs\chain_review.steps.log"
$out = "logs\chain_review.log"
$env:PYTHONIOENCODING = "utf-8"

$CTX = "ffnn_ctx_ewc_replay ffnn_ctx_joint xgboost_replay xgboost_joint xgboost_ctx_replay"
$DROP = "features.drop=[dst_port,protocol,fwd_init_win_bytes,bwd_init_win_bytes]"
$T = "split.strategy=temporal_attack"

$plan = @(
  # 1 does the graph help, or does window context? (review point 3) -- interleaved, then temporal
  @{ id = "ctx17";      done = "results\cicids2017\multiclass\continual\seed44\final_predictions_xgboost_ctx_replay.parquet";
     args = "-m experiments.run_continual --dataset cicids2017 --label-mode multiclass --seeds 42 43 44 --no-checkpoints --models $CTX" },
  @{ id = "ctx17t";     done = "results\cicids2017\multiclass\continual_temporal\seed46\final_predictions_xgboost_ctx_replay.parquet";
     args = "-m experiments.run_continual --dataset cicids2017 --label-mode multiclass --set $T --seeds 42 43 44 45 46 --out-name continual_temporal --no-checkpoints --models $CTX" },
  # unseen attacks: can window context alone catch an attack it never saw?
  @{ id = "loao18_42";  done = "results\csecicids2018\binary\loao_ctx\loao.csv";
     args = "-m experiments.run_loao --dataset csecicids2018 --label-mode binary --seed 42 --out-name loao_ctx --models ffnn_ctx_naive xgboost_ctx_static" },
  @{ id = "loao18_43";  done = "results\csecicids2018\binary\loao_ctx_seed43\loao.csv";
     args = "-m experiments.run_loao --dataset csecicids2018 --label-mode binary --seed 43 --out-name loao_ctx_seed43 --models ffnn_ctx_naive xgboost_ctx_static" },
  @{ id = "loao18_44";  done = "results\csecicids2018\binary\loao_ctx_seed44\loao.csv";
     args = "-m experiments.run_loao --dataset csecicids2018 --label-mode binary --seed 44 --out-name loao_ctx_seed44 --models ffnn_ctx_naive xgboost_ctx_static" },
  @{ id = "loao17_42";  done = "results\cicids2017\binary\loao_ctx\loao.csv";
     args = "-m experiments.run_loao --dataset cicids2017 --label-mode binary --seed 42 --out-name loao_ctx --models ffnn_ctx_naive xgboost_ctx_static" },
  @{ id = "loao17_43";  done = "results\cicids2017\binary\loao_ctx_seed43\loao.csv";
     args = "-m experiments.run_loao --dataset cicids2017 --label-mode binary --seed 43 --out-name loao_ctx_seed43 --models ffnn_ctx_naive xgboost_ctx_static" },
  @{ id = "loao17_44";  done = "results\cicids2017\binary\loao_ctx_seed44\loao.csv";
     args = "-m experiments.run_loao --dataset cicids2017 --label-mode binary --seed 44 --out-name loao_ctx_seed44 --models ffnn_ctx_naive xgboost_ctx_static" },
  # does the context baseline also collapse when attacker topology is randomised?
  @{ id = "ip17_42";    done = "results\cicids2017\multiclass\ip_remap_ctx\summary.csv";
     args = "-m experiments.run_ip_remap --dataset cicids2017 --label-mode multiclass --seed 42 --out-name ip_remap_ctx --models ffnn_ctx_ewc_replay" },
  @{ id = "ip17_43";    done = "results\cicids2017\multiclass\ip_remap_ctx_seed43\summary.csv";
     args = "-m experiments.run_ip_remap --dataset cicids2017 --label-mode multiclass --seed 43 --out-name ip_remap_ctx_seed43 --models ffnn_ctx_ewc_replay" },
  @{ id = "ip17_44";    done = "results\cicids2017\multiclass\ip_remap_ctx_seed44\summary.csv";
     args = "-m experiments.run_ip_remap --dataset cicids2017 --label-mode multiclass --seed 44 --out-name ip_remap_ctx_seed44 --models ffnn_ctx_ewc_replay" },
  # 2 shortcut features removed (review point 5): dst_port, protocol, init window bytes
  @{ id = "drop17t";    done = "results\cicids2017\multiclass\continual_temporal_noshortcut\seed46\final_predictions_ffnn_ctx_ewc_replay.parquet";
     args = "-m experiments.run_continual --dataset cicids2017 --label-mode multiclass --set $T $DROP --seeds 42 43 44 45 46 --out-name continual_temporal_noshortcut --no-checkpoints --models gnn_ewc_replay ffnn_ewc_replay ffnn_ctx_ewc_replay" },
  @{ id = "drop_loao18"; done = "results\csecicids2018\binary\loao_noshortcut\loao.csv";
     args = "-m experiments.run_loao --dataset csecicids2018 --label-mode binary --seed 42 --set $DROP --out-name loao_noshortcut --models gnn_naive ffnn_naive ffnn_ctx_naive" },
  # 3 more seeds where the claims rest (review point 4): 5 seeds for the interleaved headline
  @{ id = "seeds17";    done = "results\cicids2017\multiclass\continual\seed46\final_predictions_gnn_ewc_replay.parquet";
     args = "-m experiments.run_continual --dataset cicids2017 --label-mode multiclass --seeds 45 46 --no-checkpoints" },
  @{ id = "ctx17_more"; done = "results\cicids2017\multiclass\continual\seed46\final_predictions_xgboost_ctx_replay.parquet";
     args = "-m experiments.run_continual --dataset cicids2017 --label-mode multiclass --seeds 45 46 --no-checkpoints --models $CTX" },
  # 2018: the context baseline beside the GNN
  @{ id = "ctx18";      done = "results\csecicids2018\multiclass\continual\seed44\final_predictions_xgboost_ctx_replay.parquet";
     args = "-m experiments.run_continual --dataset csecicids2018 --label-mode multiclass --seeds 42 43 44 --no-checkpoints --models $CTX" }
)

"[$(Get-Date -Format HH:mm:ss)] REVIEW CHAIN START ($($plan.Count) steps)" | Add-Content $steps
$i = 0
foreach ($s in $plan) {
  $i++
  if (Test-Path $s.done) { "[$(Get-Date -Format HH:mm:ss)] STEP $i/$($plan.Count) $($s.id) SKIP (done)" | Add-Content $steps; continue }
  "[$(Get-Date -Format HH:mm:ss)] STEP $i/$($plan.Count) $($s.id) START $($s.args)" | Add-Content $steps
  $p = Start-Process -FilePath $py -ArgumentList $s.args -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput "logs\chain_review_$($s.id).out.log" -RedirectStandardError "logs\chain_review_$($s.id).err.log"
  "[$(Get-Date -Format HH:mm:ss)] STEP $i/$($plan.Count) $($s.id) END rc=$($p.ExitCode)" | Add-Content $steps
}
"[$(Get-Date -Format HH:mm:ss)] ALL DONE" | Add-Content $steps
