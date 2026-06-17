# hw-acceptance

Research area for hardware acceptance testing: validating servers between DC arrival and production entry — burn-in, incoming inspection, firmware baselining, and the pass/fail gates that decide what ships into the fleet.

## Current state

- First topic, [burnin](burnin.md), covers burn-in tooling for an incoming batch of **40 NVIDIA HGX B300** (Blackwell Ultra, 8-GPU) nodes on a **RoCEv2/Juniper** fabric plus **AMD EPYC** CPU servers. Bare-metal Linux, 24–72 h soak, NVIDIA-open-source-first.
- **Headline:** the neo-clouds have converged on one open-source stack — adopt it, don't invent one. NVIDIA **DCGM** diag + **nccl-tests** + **nvbandwidth** + **gpu-burn**/**GPU Fryer** for GPU/fabric; **StressAppTest** + **FIRESTARTER** + AOCL **HPL** + **fio** + **rasdaemon** for the CPU/mem/storage layers NVIDIA doesn't cover; **Slurm + LBNL NHC** + **DCGM-Exporter→Prometheus→Grafana** to orchestrate and gate. Only the RMA arbiter (**Field Diagnostics**) is closed.
- **Why this shape:** GPUs + HBM cause ~58% of real-world interruptions ([Llama 3](https://arxiv.org/abs/2407.21783)), so the stack weights HBM/ECC stress, sustained thermal soak, and SDC detection. Survey covers CoreWeave, Crusoe, Nebius, Together AI, imbue, Oracle OCI, and SemiAnalysis ClusterMAX.
- **Gating philosophy:** stress with escalating load, gate against **golden-node baselines** (NVIDIA publishes no hard Blackwell `busbw` figure), and **auto-drain** on any XID/ECC/throttle/busbw deviation. NCCL `busbw` ≥ ~92% of NIC line rate is the published anchor.
- Topic includes a phased **burn-in runbook** (Phase 0 incoming → Phase 5 acceptance/RMA) with durations and pass/fail gates for both CPU and B300 tracks.

## Open threads

- B300/NVLink5 reference `busbw` numbers must be derived from golden nodes — none published.
- Juniper Apstra RoCE-specific telemetry probes (ECN/PFC/queue depth) likely need custom build.
- DeepOps maintenance currency for Blackwell; may need to lift patterns into fresh Ansible.
- Whether to add a dedicated silent-data-corruption test (TinyMeg2 / numerical-regression) beyond stress tools.
- Future topics: incoming-inspection checklist, firmware/BIOS baselining policy, decommissioning/secure-erase.
