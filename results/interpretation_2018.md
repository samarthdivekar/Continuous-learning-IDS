**What 2018 confirms, and what it does not.**

* **Forgetting prevention replicates.** Every replay-based model keeps retention 1.0; naive retraining,
  FFNN naive and EWC-only drop to 0 (BWT −0.83 to −1.00), exactly as on CIC-IDS2017.
* **EWC alone fails in both label modes here.** On 2017 binary, EWC-only reached 0.9945; on 2018 binary it
  scores 0.539 with retention 0. The 2017 binary result does not replicate, so replay, not EWC, is the
  component that reliably prevents forgetting.
* **ADWIN pays off on this stream.** 24 drift-triggered retrains beat a periodic schedule (48 retrains,
  0.825) on both cost and quality (0.943), and the model without adaptation collapses to 0.155. On
  CIC-IDS2017 the same detector over-triggered (16 vs 8 periodic). The efficiency claim therefore holds
  on one dataset and not the other.
* **GNN vs FFNN is inconclusive on 2018.** Single-seed results tie in multiclass (0.855 vs 0.850) and favour
  the FFNN in binary (0.995 vs 0.977) with a lower false-positive rate.
* **The GNN is unstable on Infiltration.** The IP-remap experiment re-trains the identical configuration
  (same seed, same data). Its "normal" column scores **0.948** where the task-sequence run scored **0.855**.
  The whole gap is one class: the task-sequence run flagged **9,196** benign flows as Infiltration
  (FPR 0.51 %), the IP-remap run **3** (FPR 0.0014 %), with the same ~97–99 % Infiltration recall. Nothing
  differs between the runs except CUDA's non-deterministic scatter operations, so the GNN's decision
  boundary between benign traffic and the NMAP-style Infiltration traffic is fragile. Single-seed 2018
  numbers for the GNN should be read as one draw from a wide distribution.
* **Topology dependence replicates, less severely.** Randomising source hosts drops the GNN from 0.948 to
  0.754 (2017: 0.950 → 0.427) while the FFNN is unaffected; host permutation changes nothing.
