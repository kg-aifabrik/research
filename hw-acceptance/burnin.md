# Burn-In Tooling for AMD CPU and NVIDIA HGX B300 Servers

How to stress-test and acceptance-gate newly-arrived AMD CPU servers and NVIDIA HGX B300 (Blackwell Ultra, 8-GPU) GPU servers before they enter production. Surveys what the neo-clouds actually run, compares the tools, recommends a layered stack, and gives a burn-in runbook.

## Table of contents

- [Executive Summary](#executive-summary)
- [Requirements](#requirements)
- [Assumptions Made](#assumptions-made)
- [Why burn-in: the failure data](#why-burn-in-the-failure-data)
- [What the neo-clouds run](#what-the-neo-clouds-run)
- [Tool comparison by layer](#tool-comparison-by-layer)
- [Recommendation and reasoning](#recommendation-and-reasoning)
- [Burn-in runbook](#burn-in-runbook)
- [Open threads](#open-threads)

## Executive Summary

The industry has converged on one open-source burn-in stack; adopt it rather than inventing one. Every serious GPU operator runs the same primitives — NVIDIA [DCGM](https://github.com/NVIDIA/DCGM) diagnostics, [nccl-tests](https://github.com/NVIDIA/nccl-tests), [nvbandwidth](https://github.com/NVIDIA/nvbandwidth), `gpu-burn`/[GPU Fryer](https://github.com/huggingface/gpu-fryer) — and gate against per-node baselines, draining anything that deviates. NVIDIA open-source covers the entire GPU and fabric path; only the CPU/memory/storage layers (which have no NVIDIA equivalent) use best-of-breed OSS; only the RMA arbiter is closed.

**Recommended stack:**

| Burn-in layer | Recommended tool(s) | License | Main alternative rejected | Hard gate signal |
|---|---|---|---|---|
| GPU single-node stress | `dcgmi diag -r 4` + **gpu-burn** (long thermal soak) | Apache-2.0 / BSD-2 | DCGM alone (caps at ~2.25 h) | XID 48/94/95/64/79; ECC; thermal throttle |
| GPU compute uniformity | **GPU Fryer** | Apache-2.0 | manual TFLOPS diff | slowest-GPU / throttle outlier |
| Intra-node NVLink | **nvbandwidth** + `nccl-tests -g 8` | Apache-2.0 / BSD | CUDA p2p samples | busbw < golden baseline |
| Inter-node fabric (RoCEv2) | **nccl-tests** (MPI, multi-node) + **perftest** `ib_write_bw -R` | BSD / BSD-GPLv2 | iperf3 only (no RDMA path) | busbw < ~92% NIC line rate; link flaps |
| CPU + memory stress | **StressAppTest** + **FIRESTARTER** + AOCL **HPL** + **stress-ng** | Apache-2.0 / GPL | Prime95/y-cruncher (closed) | SAT/HPL miscompare; UE > 0 |
| Pre-OS DRAM | **Memtest86+** | GPL-2.0 | MemTest86 (PassMark, paid) | any memory error |
| Storage | **fio** (`verify=crc32c`) + **nvme-cli**/**smartctl** | GPL-2.0 | vendor-only tools | media errors; SMART critical warning |
| RAS gate (CPU/mem) | **rasdaemon** (EDAC/AMD-SMCA) | GPL-2.0 | mcelog (legacy on AMD) | UE > 0; CE concentrated on one DIMM |
| RMA arbiter (GPU) | **NVIDIA Field Diagnostics** | closed, vendor-gated | — (authoritative; no sub) | row-remap-failure flag set |
| Orchestration + telemetry | **Slurm + LBNL NHC** (DeepOps-style) + **DCGM-Exporter→Prometheus→Grafana** | GPL / Apache-2.0 | bespoke scripts | auto-drain on any gate |

**Prefer this stack because (1) it is what graded operators run** — SemiAnalysis's [ClusterMAX](https://newsletter.semianalysis.com/p/the-gpu-cloud-clustermax-rating-system-how-to-rent-gpus), [Together AI](https://www.together.ai/blog/a-practitioners-guide-to-testing-and-running-large-gpu-clusters-for-training-generative-ai-models), [Crusoe](https://www.crusoe.ai/resources/blog/how-crusoe-burn-in-tests-every-node-before-it-reaches-you), [Nebius](https://nebius.com/blog/posts/how-we-build-reliable-clusters) and [imbue](https://imbue.com/research/70b-infrastructure/) independently describe the same primitives, so it is battle-tested at fleet scale; **(2) it maximizes NVIDIA open-source** (DCGM, nccl-tests, nvbandwidth, dcgm-exporter, DeepOps are all Apache-2.0/BSD), with closed code confined to the one job — RMA arbitration — where NVIDIA states no substitute exists; **(3) it gates on the failures that actually dominate** — GPUs and HBM cause ~58% of real interruptions ([Llama 3](https://arxiv.org/abs/2407.21783)), so the stack weights HBM/ECC stress, sustained thermal soak, and silent-data-corruption detection over quick smoke tests.

## Requirements

- Survey burn-in / incoming-acceptance tooling neo-clouds and NVIDIA/OEMs actually use.
- Cover both arriving server types: AMD CPU servers (CPU, DRAM, NVMe, power/thermal) and NVIDIA HGX B300 nodes (GPU compute, HBM3e, intra-node NVLink/NVSwitch, inter-node RoCEv2 fabric, plus the host's CPU/DRAM/NVMe).
- Compare tools across subsystem coverage, single- vs multi-node, stress vs diagnostic, error/telemetry detection, licensing, RMA-grade evidence, and automation fit; tables grouped by layer.
- Recommend a layered stack with explicit reasoning.
- Provide a burn-in runbook: phased procedure, durations, workloads, and pass/fail thresholds for CPU and B300 nodes.
- Cite primary sources inline; keep tight.

## Assumptions Made

All confirmed with the requester (2026-06-17):

- Burn-in runs at DC receiving/staging on bare-metal Linux; goal is infant-mortality screening + acceptance gating.
- B300 = **HGX B300 8-GPU baseboard** systems (NVLink domain = 8 GPUs/node via on-board NVSwitch), **not** GB300 NVL72 rack-scale. Individual systems uplinked to Juniper switches.
- Inter-node GPU fabric = **RoCEv2 over Ethernet** (NVIDIA ConnectX-class NICs → Juniper switches). Not NVIDIA Spectrum-X proper (which requires Spectrum switches) — but identical at the RDMA layer that burn-in exercises.
- Cooling (direct-liquid) is live at test time.
- Initial batch = **40 GPU nodes** (≈320 GPUs); multi-node fabric burn-in matters.
- Soak window: **24–72 h** per node.
- Prefer **NVIDIA open-source** tooling wherever it covers the job.
- Orchestration via bare-metal scripts / Ansible / Slurm; Kubernetes not required for burn-in.

## Why burn-in: the failure data

Burn-in screens the front of the bathtub curve — infant-mortality defects that survive factory test but die in the first hours/days under sustained heat and power. The failure distribution dictates where to spend test time:

- **GPUs and HBM dominate.** Meta's [Llama 3](https://arxiv.org/abs/2407.21783) 16,384×H100 run logged 466 interruptions over 54 days (419 unexpected, ~78% hardware). Root causes: **faulty GPU 30.1%, GPU HBM3 memory 17.2%**, software 12.9%, network switch/cable 8.4%, GPU SRAM 4.5%, GPU system processor 4.1%, NIC 1.7%, **silent data corruption 1.4%**. GPU-related ≈ 58%. → Burn-in must hammer HBM/ECC and tensor-core compute, and detect SDC, not just confirm a GPU is present.
- **Infant mortality is real and fast.** imbue saw **~10% of machines fail to boot** at bring-up and **~3%/week** break thereafter; their InfiniBand fabric threw **~1,800 link-error/flap alerts** with ~10% of ports needing replacement. SemiAnalysis recommends **3–4 weeks** of cluster-wide high-temperature burn-in to flush infant mortality.
- **Reliability collapses with scale.** Crusoe cites MTBF falling from ~47 days at 8 GPUs to **~8 h at 1,024 GPUs**; a weak or thermally-marginal node that passes a smoke test will still sink a multi-node job. Hence reference-baseline gating, not just pass/fail.

## What the neo-clouds run

| Operator | GPU stress / diag | Fabric | CPU/mem/storage | Duration & gate |
|---|---|---|---|---|
| **CoreWeave** (ClusterMAX Platinum) | proprietary + chip-level deep diag; GPU burn; FP8/16/BF16 numerical-regression check; all-SM thermal | NCCL + `ib_write_bw` vs reference | firmware (GPU/retimer/BMC/BIOS) | ~24 h Day-1 burn-in; hourly 20–30 min idle re-checks |
| **Crusoe** | DCGM L1–4; gpu-p2p NVLink | `ib_write_bw` + RDMA; iperf3 | sysbench; block-storage sweep | "fails don't ship"; re-run after repair |
| **Nebius** (NVIDIA Exemplar) | `dcgmi diag -r 4` + EUD (8–12 h); GPU Fryer; SuperBench | NCCL collectives; ClusterKit; UFM topology = **0 discrepancies** | HPL on 8/16/32-node groups, **< 1% variance** | 3-stage (factory→node→cluster); all must pass |
| **Together AI** | `dcgmi diag --run 3 --fail-early`; gpu-burn; nvbandwidth (~388 GB/s) | NCCL `all_reduce_perf` **≥ ~92%** (~370/400 GB/s); `ib_*_bw`; iperf3 | fio | FSDP Llama-3 8B to 16 nodes as real-load gate |
| **imbue** | GPU count/ECC/NVLink; Xid/SXid dmesg scan; throttle events | `ib_write_bw --use_cuda` ~15 min; multinode NCCL stall test **12–24 h** | disk util; PCIe width | open-sourced [cluster-health](https://github.com/imbue-ai/cluster-health) |
| **Oracle OCI** (Blackwell) | DCGM diag; GPU Fryer; (RVS/RCCL for AMD) | NCCL/RCCL tests | host checks | 5 active checks on 24 h cycle, pass/fail node labels |

**ClusterMAX two-tier model** (the framing to adopt): *passive* continuous monitoring (XID/SXID, ECC rates, PCIe faults, link flaps, thermals) plus *active* scheduled tests (full DCGM diag, NCCL, `ib_write_bw`, GPU Burn, SDC detection). Any deviation auto-drains the node before it reaches production.

## Tool comparison by layer

**GPU + fabric (NVIDIA-centric):**

| Dimension | DCGM `dcgmi diag` | nccl-tests | nvbandwidth | gpu-burn | GPU Fryer | Field Diag |
|---|---|---|---|---|---|---|
| Tests | ECC/Memtest, PCIe/NVLink, SM/targeted stress, targeted power, EDPp pulse | collective bw+correctness | H2D/D2H/D2D, NVLink, PCIe | cuBLAS GEMM soak + verify | FP8/BF16 matmul, HBM, throttle | authoritative HW qual |
| Node scope | single | **single + multi (MPI)** | single (+multi via IMEX, NVLink only) | single | single | single, offline |
| Covers RoCE fabric? | no | **yes** | no (NVLink only) | no | no | no |
| License | Apache-2.0 | BSD | Apache-2.0 | BSD-2 | Apache-2.0 | closed/gated |
| Role | primary GPU diag/stress | **end-to-end fabric gate** | link-bw baseline | long thermal soak | uniformity/outlier | RMA arbiter |

`dcgmi diag` run levels: **r1** <2.5 s (deploy check) · **r2** <10.5 min/8-GPU (adds SM/targeted stress+power, NVBandwidth, NCCL) · **r3** <35 min/8-GPU (adds Memtest) · **r4** <2.25 h/8-GPU (adds EDPp pulse). NVIDIA explicitly lists "replace the field diagnosis tools" as [beyond DCGM's scope](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/dcgm-diagnostics.html) — so DCGM screens, Field Diagnostics arbitrates RMA. `busbw` (not `algbw`) is the metric to gate on; it normalizes for rank count and compares to hardware peak.

**CPU / memory / storage (no NVIDIA equivalent — best-of-breed OSS):**

| Tool | Subsystem | Role | License | Gate signal |
|---|---|---|---|---|
| **StressAppTest** | DRAM (+CPU/IO) | error **detector** | Apache-2.0 | miscompare = fail; caught 20% of DIMM failures no other test found |
| **stress-ng** | CPU/cache/VM/IO | broad **load** driver | GPL-2.0 | (not a detector — gate via RAS) |
| **FIRESTARTER** | CPU+uncore+mem | peak **power/thermal** | GPL-3.0 | confirms cooling/VRM hold at max draw |
| **HPL** (AMD AOCL/AOCC) | FP + mem bw | sustained load + self-check | BSD / AMD | residual FAILED or GFLOP/s variance |
| **Memtest86+** | DRAM (pre-OS) | detector | GPL-2.0 | any error |
| **fio** | NVMe/SSD | load + integrity | GPL-2.0 | `verify` mismatch; perf below spec |
| **rasdaemon** | EDAC/AMD-SMCA | **gate layer** | GPL-2.0 | **UE > 0**; CE concentrated on a DIMM |

Load generators (stress-ng, FIRESTARTER, HPL) drive heat/power; **error detectors** (StressAppTest, Memtest86+, fio-verify) find faults; but the authoritative CPU/mem verdict is the **RAS layer** — [rasdaemon](https://github.com/mchehab/rasdaemon) decoding AMD Scalable-MCA: corrected-error (CE) trend + uncorrected-error (UE) count. Prime95/y-cruncher are excellent torture tests but **closed-source**, so secondary under the OSS preference.

**Orchestration:** [LBNL NHC](https://github.com/mej/nhc) is the de-facto HPC node-health gate (wires into Slurm `HealthCheckProgram`; failed check → node DRAIN). [NVIDIA DeepOps](https://github.com/NVIDIA/deepops) extends NHC with GPU checks (driver, PCIe width, retired/row-remap pages) and ships NCCL/HPL/DCGM/gpu-burn playbooks — the closest NVIDIA-blessed fleet harness (note: lightly maintained; validate for B300). Telemetry: [DCGM-Exporter](https://github.com/NVIDIA/dcgm-exporter) → Prometheus → Grafana surfaces ECC/XID/throttle that `nvidia-smi` misses across a 24–72 h soak.

## Recommendation and reasoning

A burn-in run is a **pipeline of escalating stress with a continuous RAS/telemetry gate**, orchestrated by Slurm+NHC and drained automatically on any failure.

- **GPU: DCGM diag + gpu-burn, not DCGM alone.** `dcgmi diag -r 4` is the NVIDIA-native one-shot (memory/Memtest, targeted stress+power, EDPp) but caps at ~2.25 h/8-GPU — too short to flush thermal infant mortality. Layer **gpu-burn** (BSD, hours-long cuBLAS soak with result verification) and **GPU Fryer** (catches the slowest-GPU/throttle outlier that bottlenecks a whole job). All open-source, satisfying the NVIDIA-first preference.
- **Fabric: nccl-tests is the gate, perftest localizes.** Multi-node `all_reduce_perf` over the 40-node RoCEv2 fabric is the one end-to-end correctness+performance test; gate `busbw` at **≈92% of NIC line rate** (Together's published anchor: ~370/400 GB/s). When it underperforms, `ib_write_bw -R -x <gid>` pairwise isolates the bad NIC/leaf/spine, and you revisit RoCE lossless config (PFC/ECN/DCQCN). `nvbandwidth` validates intra-node NVLink only — don't mistake it for a fabric test.
- **CPU/mem: detector + load + RAS gate.** Memtest86+ pre-OS, then StressAppTest (the detector — `-W`, near-full RAM) under FIRESTARTER+HPL heat, with **rasdaemon as the verdict** (UE=0). This mirrors AMD's own [Instinct acceptance](https://instinct.docs.amd.com/projects/system-acceptance/en/latest/) philosophy (sustained load + telemetry + zero uncorrected errors), transferred to EPYC hosts.
- **RMA path: Field Diagnostics only as arbiter.** It's closed and vendor-gated, but NVIDIA makes it the authoritative RMA tool — it validates the **row-remap-failure flag**. Confine closed code to this one escalation step; everything upstream stays open-source.
- **Set thresholds from a golden node.** NVIDIA does not publish a hard Blackwell/NVLink5 `busbw` acceptance number; establish per-node baselines on a known-good B300 and gate on deviation, exactly as CoreWeave/Nebius do with reference numbers.

## Burn-in runbook

Two tracks (CPU nodes, B300 nodes) sharing a RAS/telemetry gate. Orchestrate with Slurm + NHC; stream DCGM-Exporter + rasdaemon to Prometheus/Grafana throughout. Auto-drain on any hard-gate hit; suspect GPUs escalate to Field Diagnostics.

**Phase 0 — Incoming (per node, ~1–3 h):** firmware/BIOS/BMC + GPU VBIOS + NIC/retimer baselined to a pinned version; `dcgmi diag -r 1` (deploy gate); Memtest86+ ≥ 1 full pass (pre-OS DRAM); confirm ECC enabled, PCIe link width/speed, GPUDirect RDMA, RoCE lossless config (PFC/ECN) present.

**Phase 1 — Single-node stress (per node, in parallel):**

| Track | Workload | Duration | Pass gate |
|---|---|---|---|
| CPU node | StressAppTest (`-W`, ~90% RAM) + FIRESTARTER + AOCL HPL (N≈80–90% RAM) + stress-ng `--cpu-method all --tz` | 24 h | UE=0; no SAT/HPL miscompare; all HPL residuals PASS; no thermal throttle; power in spec; CE not DIMM-concentrated |
| B300 node | `dcgmi diag -r 4`, then gpu-burn `-tc` + GPU Fryer | r4 once, then ≥ 6–12 h soak | no XID 48/63/64/79/94/95; ECC UE=0; no row-remap-failure; no throttle; GPU Fryer no slow/outlier GPU |
| Storage (both) | fio precondition → sustained `randrw` with `verify=crc32c`; SMART before/after | ≥ 2–4 h | zero verify mismatch; Δmedia_errors=0; no SMART critical warning; spare stable |

**Phase 2 — Intra-node interconnect (B300, ~30 min):** nvbandwidth (H2D/D2H/D2D + NVLink) and single-node `nccl-tests all_reduce_perf -g 8`; gate busbw ≥ golden-node baseline.

**Phase 3 — Multi-node fabric (across the 40 nodes):** `ib_write_bw -R` pairwise sweep (every NIC pair hits RoCEv2 line rate), then MPI `all_reduce_perf` ramped pairwise → leaf → full cluster. Gate `busbw ≥ ~92%` of NIC line rate; localize any shortfall to node/leaf/spine; watch Juniper switch FEC/CRC + NIC `ethtool -S` PFC counters for flaps.

**Phase 4 — Soak (whole batch, 24–72 h):** full-cluster multi-node NCCL + GPU/CPU stress held under live cooling. Multi-node NCCL must run ≥ 12–24 h (imbue's window for random-stall faults to surface). Continuous gate: zero new uncorrectable XID/ECC, no throttle, busbw stable, rasdaemon UE=0.

**Phase 5 — Acceptance & escalation:** node passes only if every phase is clean for the full window. Failures → triage → repair/replace → **re-run the full suite** (or a fix-scoped subset). GPUs flagged for uncorrectable ECC, row-remap-failure (XID 64), or "fallen off the bus" (XID 79) → **NVIDIA Field Diagnostics**; row-remap-failure flag set (≥8 remaps/bank, a re-remap, or 512 total per the [RMA policy](https://docs.nvidia.com/deploy/a100-gpu-mem-error-mgmt/rma-policy-thresholds-for-row-remapping.html)) confirms RMA.

**Fatal GPU XIDs to drain on:** 48 (double-bit ECC), 63/64 (row-remap pending/failure), 79 (GPU off bus), 92 (high SBE rate), 94/95 (contained/uncontained ECC). Read via dmesg + `nvidia-smi -q -d ECC,ROW_REMAPPER` + DCGM.

## Open threads

- **B300/NVLink5 reference numbers.** NVIDIA publishes no hard `busbw` or per-test acceptance figure for Blackwell Ultra — derive golden-node baselines on first good units before gating the batch.
- **Juniper-side validation.** [Juniper Apstra](https://www.juniper.net/documentation/us/en/software/jvd/jvd-ai-dc-apstra-nvidia-weka/index.html) Intent-Based Analytics catches lossless-config drift, but a RoCE-specific probe (ECN marks, PFC pauses, queue depth) is likely a custom build — confirm against the Apstra guide.
- **DeepOps currency for B300.** DeepOps is lightly maintained; validate its NHC/DCGM playbooks on Blackwell or lift the patterns into fresh Ansible.
- **SDC detection.** ClusterMAX-grade operators add silent-data-corruption tests (TinyMeg2 / numerical-regression kernels) beyond stress; evaluate adding one — SDC is low-frequency but invisible to ECC.
- **DCGM "fully open" vs open-core.** DCGM is Apache-2.0; confirm the bundled NVVS diagnostic plugins carry the same license if that matters for your supply-chain policy.
- **AMD CPU RAS depth.** Validate EPYC post-package-repair (PPR) behavior and SMCA bank coverage on the specific SKU's BIOS before relying on CE-trend gating.
