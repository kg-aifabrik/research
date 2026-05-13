# gpu-infra

Research area for GPU infrastructure topics: hardware reference architectures, scale-out fabrics, K8s control-plane stack for accelerators, and multi-tenant inference platforms.

## Current state

- The first topic, [nvidia-b300-k8s-inference](nvidia-b300-k8s-inference.md), works through NVIDIA's two published reference architectures for Blackwell-generation Kubernetes deployments (Enterprise RA with Spectrum-X, DGX SuperPOD with InfiniBand) and layers on the multi-tenancy concerns NVIDIA's RA does not address.
- Headline finding: both NVIDIA reference architectures are explicitly **single-tenant**. A multi-tenant inference platform that runs vCluster-per-tenant on a shared physical fleet must adopt NVIDIA's hardware + fabric design verbatim and then *diverge deliberately* at the CNI, GPU sharing, runtime, and security layers. The report names each divergence.
- Fabric recommendation for the on-prem case under study: **Spectrum-X dual-plane Ethernet** over InfiniBand, on grounds of multi-tenant primitives, operator skill pool, and NVIDIA's own Enterprise RA bet.
- GPU-sharing recommendation: **whole-GPU passthrough** as the default, MIG opt-in for cooperative tenants, **NVIDIA Confidential Computing** required for distrustful tenants who want fractional sharing — driven by published research showing real cross-MIG covert/side channels.
- Runtime stance: **support Dynamo, NIM, vLLM, and SGLang as first-class** — BYO inference runtime per tenant. NVIDIA's stack has real advantages (Flash Indexer, KV-cache-aware routing, pre-compiled engines) and real drawbacks (license, container size, slower upstream of new architectures).
- OEM/neocloud comparison covered: Supermicro and Dell GB300 NVL72 designs side by side; CoreWeave, Lambda, Crusoe, Nebius compared on where they follow NVIDIA's RA and where they diverge (none of the four use vCluster).
- Paired self-contained HTML alongside the markdown.

## Open threads

- **DPF (DOCA Platform Framework) at production scale.** Recommended as Phase 2 of the design, but the operational track record of running a per-DPU second K8s control plane on 1,000+-node fleets is thin.
- **NVIDIA Confidential Computing performance at NVL72 rack scale** with NVLink encryption fully on. Published numbers are at HGX scale; rack-scale CC data is sparse.
- **KVBM (Dynamo KV Block Manager) cross-tenant safety.** Need to validate per-tenant keying or design a per-tenant local-NVMe partition encryption layer.
- **Vendor-neutral Ethernet (Arista/Cisco + Broadcom Tomahawk)** as a Spectrum-X alternative. Worth a follow-up topic if NVIDIA lock-in at the switching tier becomes a blocker.
- **llm-d maturity** as the CNCF K8s wrapper around vLLM disaggregated serving — if it catches Dynamo on operator ergonomics, the runtime recommendation matrix changes.
- **Cost / TCO** was explicitly out of scope this round. A follow-up topic comparing rack-level $/token across the recommended stack vs. neocloud rental at equivalent capacity would be useful before procurement.
