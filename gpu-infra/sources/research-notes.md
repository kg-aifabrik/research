# Research notes — NVIDIA B300 K8s inference

## NVIDIA Enterprise RA (GB300 NVL72 + Spectrum-X) — March 2026
Source: docs.nvidia.com/enterprise-reference-architectures/nvl72-ai-factory-with-gb300-nvl72-dual-plane-networking-architecture.pdf

Hardware per rack:
- 72 Blackwell Ultra GPUs + 36 Grace CPUs (18 trays, 4 GPU + 2 Grace per tray)
- 9 NVSwitch trays, 2 NVSwitch ASICs each, 130 TB/s aggregated NVLink
- 5th-gen NVLink, 1800 GB/s bi-directional per GPU (900 GB/s each direction)
- 288 GB HBM3e per GPU = 20 TB rack total; 17 TB LPDDR5X CPU memory; 37 TB fast memory total
- 1440 PFLOPS FP4, 720 PFLOPS FP8/FP6
- Power: 8 shelves × 33 kW (6× 5.5 kW PSUs/shelf), up to 142 kW/rack
- Liquid-cooled, MGX architecture
- 1 SU = 1 rack; tested up to 8 SUs (576 GPUs); 1024+ nodes needs super-spine

Per compute tray:
- 4× ConnectX-8 SuperNICs (dual-port 800 Gb/s) = 1:1 GPU:NIC ratio
- 1× BlueField-3 B3240 DPU (2×400 Gb/s ports, ~480 Gb/s aggregate)
- 1× M.2 NVMe OS; 4× E1.S NVMe local cache
- 2× Grace CPU, 72 Neoverse V2 cores total, 1 TB LPDDR5

Three physical fabrics:
1. **GPU Compute East-West** (RDMA, dual-plane, rail-optimized fat tree)
   - Each ConnectX-8 800 Gb/s port → 2× 400 Gb/s breakout
   - Each GPU has 2× 400 Gb paths (one per plane)
   - ConnectX-8 hardware does plane load balancing; NCCL handles plane failover
   - Up to 1024 × 400 Gb/s interfaces per plane (per SU)
   - SN5600 128-port 400 Gb/s switches (Spectrum-4 Ethernet)
   - Min 400 GB/s recommended, 800 GB/s recommended per GPU
2. **CPU Converged North-South** (storage, in-band mgmt, customer)
   - SN5600 switches; BlueField-3 DPU; 2× 400 Gb/s per tray; aggregate 480 Gb/s
   - RoCE v2 + tenant isolation support
3. **OOB Management** (1 Gb BMC, SN2201 48-port)
   - Spectrum-4 (SN5600D) for storage + in-band, also 2-layer to 9216 GPUs

Software stack:
- NVIDIA AI Enterprise (paid subscription, per GPU)
- NVIDIA Mission Control (recommended for ops)
- NVIDIA Dynamo (open-source inference framework)
- NVIDIA Run:ai → KAI Scheduler
- NVIDIA NetQ (network telemetry)
- K8s + Slurm supported, **non-virtualized workloads**

KEY GAP for user: NVIDIA states "ideal for multi-user, single tenant workloads" — meaning all users in one enterprise. Multi-tenant (vCluster) is explicitly NOT what this RA targets. User will need to layer on tenancy.

## NVIDIA DGX SuperPOD (GB300) RA
Source: docs.nvidia.com/pdf/dgx-spod-gb300-ra.pdf

Difference vs Enterprise RA:
- SU = 8 racks (576 GPUs) — bigger unit than Enterprise RA's 1 rack
- Compute fabric: **InfiniBand Quantum-X800** (NOT Spectrum-X Ethernet)
  - Q3400-RD 144-port switches (rail-optimized fat tree)
  - 4 NICs/tray × 800 Gbps IB
  - Adaptive routing (AR), SHARPv3 (in-network reduction), SHIELD (link healing)
- Storage + in-band fabric: Spectrum-4 SN5600D Ethernet, RoCE v2
- Storage: certified partner (HPS POSIX + User NFS)
- IB management: UFM (Unified Fabric Manager) appliance
- NVLink management: NMX-M
- Scale: 1152 → 9216 GPUs in 4 tiers (2, 4, 8, 16 SUs)
- TDP: 1.2 MW per SU (8 racks)
- Hybrid liquid + air cooling
- Datacenter: Uptime Tier 3 / TIA942-B Rated 3 / EN50600 Class 3

Storage requirements:
- High-Performance Storage (HPS): POSIX, multi-threaded, RoCE v2, partner-certified
  - 400 Gbps per tray dedicated port
- User Storage: NFS, 100 GbE, home dirs
- Storage fabric independent from compute fabric

Software:
- Mission Control (same)
- Run:ai is bundled for workload orchestration

## NVIDIA Dynamo
Source: docs.nvidia.com/dynamo + developer.nvidia.com blogs
- Disaggregated prefill/decode workers (separate pools)
- "Flash Indexer": 170M ops/s KV cache tracking across all workers
- KV-cache-aware routing (cost model for worker selection)
- KVBM (KV Block Manager) for CPU/disk offload
- Backends: SGLang, TensorRT-LLM, vLLM (Dynamo can run them as engines)
- Has Kubernetes operator + Helm charts
- Grove for multi-node tensor parallelism
- Topology-aware scheduling
- Built-in Prometheus metrics, distributed tracing
- Open-source, Apache 2.0 license

## MLPerf Inference v5.1 (GB300)
- DeepSeek-R1: 5842 t/s/GPU offline, 2907 t/s/GPU server (45% better than GB200 offline, 25% server)
- Llama 3.1 405B: 224/170/138 t/s/GPU (offline/server/interactive)
- Llama 3.1 8B: 18370/16099/15284 t/s/GPU
- vs Hopper: ~5× higher throughput per GPU on DeepSeek-R1
- TRT-LLM + Dynamo: NVFP4 weights, FP8 KV cache, expert parallelism, attention DP, disaggregation

## Hopper comparison claims
- 50× AI factory output
- 10× TPS per user (responsiveness)
- 5× TPS per MW (efficiency)
