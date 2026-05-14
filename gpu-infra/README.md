# gpu-infra

Research area for GPU infrastructure topics: hardware reference architectures, scale-out fabrics, K8s control-plane stack for accelerators, and multi-tenant inference platforms.

## Current state

- The first topic, [nvidia-b300-k8s-inference](nvidia-b300-k8s-inference.md), works through NVIDIA's **three** published reference architectures for Blackwell-generation Kubernetes deployments — Enterprise RA (Spectrum-X), DGX SuperPOD (InfiniBand), and the Inference RA (software/orchestration Northstar with Grove, Planner, NIXL, KVBM, Model Express) — and layers on the multi-tenancy concerns none of them address.
- Headline finding: both infrastructure RAs are explicitly **single-tenant**; the Inference RA is fabric-neutral and CSP-oriented but does not specify tenant isolation primitives. A multi-tenant inference platform that runs vCluster-per-tenant on a shared physical fleet must adopt NVIDIA's hardware + component model verbatim and then *diverge deliberately* at the CNI, GPU sharing, runtime catalog, and security layers. The report names each divergence.
- Second-order finding: **NVIDIA itself is split on fabric.** The Enterprise RA recommends Spectrum-X; the Inference RA and SuperPOD recommend InfiniBand. The report sides with Spectrum-X for the enterprise-on-prem multi-tenant profile and explains why.
- Fabric recommendation for the on-prem case under study: **Spectrum-X dual-plane Ethernet** over InfiniBand, on grounds of multi-tenant primitives, operator skill pool, and the Enterprise RA's framing.
- GPU-sharing recommendation: **whole-GPU passthrough** as default, MIG opt-in for cooperative tenants, **NVIDIA Confidential Computing** required for adversarial fractional sharing (driven by published research showing real cross-MIG covert/side channels). DRA is the K8s API for all sharing modes; the device-plugin model is legacy.
- Runtime stance: **support Dynamo, NIM, vLLM, and SGLang as first-class** per the Inference RA's adoption matrix. The full GenAI stack pattern (Dynamo + NIXL + KVBM + Router + Grove + KAI Scheduler + Planner) is the NVIDIA-recommended Dynamo deployment.
- OEM/neocloud comparison: Supermicro and Dell GB300 NVL72 designs; CoreWeave, Lambda, Crusoe, Nebius (none use vCluster).
- Paired self-contained HTML alongside the markdown. Primary-source PDFs preserved in `sources/`.

## Open threads

- **DPF (DOCA Platform Framework) at production scale.** Recommended as Phase 2 of the design; operational track record on 1,000+-node fleets is thin.
- **NVIDIA Confidential Computing performance at NVL72 rack scale** with NVLink encryption on. Published numbers are at HGX scale.
- **KVBM cross-tenant safety.** Need to validate per-tenant keying or design a per-tenant local-NVMe partition encryption layer.
- **DRA + ComputeDomain maturity** for MNNVL across racks. K8s 1.32+ stabilizes DRA; NVIDIA-side ComputeDomain CRD is newer.
- **NVIDIA's internal fabric inconsistency** between the Enterprise RA (Spectrum-X) and the Inference RA + SuperPOD (InfiniBand). Track which way the next revision aligns.
- **Grove + Planner + KAI interaction** at >1000-GPU scale. Each works individually; the combined live-replanning loop is newer than its components.
- **Vendor-neutral Ethernet** (Arista/Cisco + Broadcom Tomahawk) as a Spectrum-X alternative — worth a follow-up if NVIDIA lock-in becomes a blocker.
- **llm-d (CNCF)** maturity as the K8s wrapper around vLLM disaggregated serving.
- **Cost / TCO** — explicitly out of scope this round; follow-up topic comparing rack-level $/token across the recommended stack vs. neocloud rental at equivalent capacity is the obvious next piece.
