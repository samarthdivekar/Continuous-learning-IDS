| Comparison | Question | Metric | Seeds | Ours | Other | Mean diff | Bootstrap 95 % CI | Wilcoxon p (2-sided / 1-sided) | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 2017 · interleaved | does the graph help? | macro-F1 | 3 | 0.964 | 0.928 (ffnn_ewc_replay) | +0.036 | [+0.011, +0.069] | 0.250 / 0.125 | ours better (indicative, n=3) |
| 2017 · interleaved | does the graph help? | false-positive rate | 3 | 0.066 % | 0.043 % (ffnn_ewc_replay) | +0.023 pp | [+0.016 pp, +0.031 pp] | 0.250 / 1.000 | ffnn_ewc_replay better (indicative, n=3) |
| 2017 · temporal | does the graph help? | macro-F1 | 5 | 0.915 | 0.870 (ffnn_ewc_replay) | +0.044 | [+0.019, +0.058] | 0.125 / 0.062 | ours better (indicative, n=5) |
| 2017 · temporal | does the graph help? | false-positive rate | 5 | 0.042 % | 0.041 % (ffnn_ewc_replay) | +0.001 pp | [-0.032 pp, +0.035 pp] | 0.812 / 0.688 | no detectable difference |
| 2017 · interleaved | does EWC add anything to replay? | macro-F1 | 3 | 0.964 | 0.948 (gnn_replay) | +0.015 | [-0.016, +0.045] | 0.500 / 0.250 | no detectable difference |
| 2017 · interleaved | does EWC add anything to replay? | false-positive rate | 3 | 0.066 % | 0.116 % (gnn_replay) | -0.050 pp | [-0.087 pp, +0.004 pp] | 0.500 / 0.250 | no detectable difference |
| 2017 · temporal | does EWC add anything to replay? | macro-F1 | 5 | 0.915 | 0.848 (gnn_replay) | +0.067 | [+0.003, +0.145] | 0.188 / 0.094 | ours better (indicative, n=5) |
| 2017 · temporal | does EWC add anything to replay? | false-positive rate | 5 | 0.042 % | 0.075 % (gnn_replay) | -0.033 pp | [-0.069 pp, +0.000 pp] | 0.312 / 0.156 | no detectable difference |
| 2018 · interleaved | does the graph help? | macro-F1 | 3 | 0.881 | 0.836 (ffnn_ewc_replay) | +0.045 | [+0.004, +0.123] | 0.250 / 0.125 | ours better (indicative, n=3) |
| 2018 · interleaved | does the graph help? | false-positive rate | 3 | 0.346 % | 0.124 % (ffnn_ewc_replay) | +0.222 pp | [-0.234 pp, +0.455 pp] | 0.500 / 0.875 | no detectable difference |
