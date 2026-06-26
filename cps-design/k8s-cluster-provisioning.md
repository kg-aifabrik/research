# CPS — K8s Cluster Provisioning (First Capability)

Living design plan for the **Compute Provisioning Service (CPS)** first capability:
provision a Kubernetes (K8s) cluster for a tenant and (follow-up) hand back a
kubeconfig. Built up through design discussion; updated as decisions land.

> Scope of this capability: from a Tenant Management Service (TMS) request through
> a running, AiFabrik-managed K8s cluster on reserved site hardware. **Storage
> (Weka) and tenant kubeconfig delivery are deferred** (see Follow-ups).

## Executive summary

CPS is a **stateless Temporal orchestrator** exposing gRPC to its single client,
TMS. A provision request runs as one Temporal workflow (saga) that: reserves
hardware in NetBox via the Network Provisioning Service (NPS), creates a tenant
network (VRF/VLAN) via NPS→Apstra, provisions OS + builds K8s via the Rafay
Controller, and deploys the AiFabrik management/monitoring addon. NetBox is the
**System of Record (SoR)** for inventory and allocation; TMS/PGSQL owns the
business mapping tenant→cluster→assets (for billing). The call is **async**: the
API returns an operation handle and TMS polls for status.

## Actors & systems

All cloud components run in Google Cloud Platform (GCP).

| Component | Where | Role |
|-----------|-------|------|
| **TMS** (Tenant Management Service) | GCP / mgmt plane | CPS's client; owns tenant→cluster→assets mapping in PGSQL (billing). |
| **CPS** (Compute Provisioning Service) | GCP | Temporal orchestrator, gRPC API. **Stateless** beyond Temporal workflow state. Owns scheduling/selection + reservation lock. |
| **NPS** (Network Provisioning Service) | GCP | gRPC/Proto wrapper over NetBox (inventory reads + allocation writes); drives Apstra for VRF/VLAN + IPAM. |
| **NetBox** | GCP | Inventory **SoR**. Two writers, non-overlapping fields: Aravolta (physical) + CPS/NPS (allocation). |
| **Aravolta** | GCP | Physical DC infra management; feeds host/switch/router facts into NetBox. |
| **Juniper Apstra** | GCP | Underlay fabric controller; configures site switches over the VPN. |
| **Rafay Controller** | GCP (separate GKE cluster) | Bare-metal OS + K8s lifecycle + addons. **CPS↔Rafay = REST.** |
| **Rafay Head Node** | Site | Last-mile agent: IPMI discovery, PXE boot, host config. |
| **Site servers** | Site | CPU servers (control plane) + GPU servers (workers). |

**Networks at site:** PXE/provisioning rides a **separate OOB VLAN**, distinct from
the tenant data network/VRF.

**Trust boundaries:** our services (TMS/CPS/NPS/NetBox/Apstra) are all cloud-side,
one trust domain. The only VPN crossings are vendor-internal: Apstra→switches and
Rafay Controller↔Rafay Head Node (head node dials out).

## Provisioning workflow (Temporal saga)

Async: `ProvisionCluster` starts the workflow and returns an operation handle;
TMS polls `GetOperation`/`GetCluster`. Each mutating step has a compensating
action; activities are idempotent (Temporal retries them).

```mermaid
sequenceDiagram
    participant TMS
    participant CPS as CPS (Temporal)
    participant NPS
    participant NB as NetBox
    participant AP as Apstra
    participant RC as Rafay Controller
    participant RH as Rafay Head (site)

    TMS->>CPS: ProvisionCluster(idempotency_key, tenant, spec)
    CPS-->>TMS: operation handle (async)
    Note over CPS: acquire reservation lock (auto-expiry; wait if held)
    CPS->>NPS: list available servers
    NPS->>NB: query inventory
    Note over CPS: schedule/select subset (GPU match · RDMA locality · CP anti-affinity)
    CPS->>NPS: reserve nodes for tenant  [compensate: release]
    NPS->>NB: write allocation fields
    Note over CPS: release reservation lock
    CPS->>NPS: create tenant VRF/VLAN + IPAM  [compensate: delete]
    NPS->>AP: configure fabric + leaf data ports
    Note over CPS: preflight health/reachability check on reserved nodes
    CPS->>RC: provision OS on nodes  [compensate: wipe/decommission]
    RC->>RH: IPMI power + PXE over OOB VLAN
    CPS->>RC: build K8s cluster (CP + workers)  [compensate: delete cluster]
    CPS->>RC: deploy AiFabrik addon (mgmt/monitoring)
    CPS-->>TMS: SUCCEEDED (TMS records tenant→cluster→assets in PGSQL)
```

**Failure handling (D2):** when an activity exhausts retries, the workflow
transitions to `AWAITING_REVIEW` and waits on a human signal — **resume**
(retry/continue) or **cancel** (run compensations in reverse, free resources). No
automatic rollback. GPU nodes are expensive; default is to hold, not auto-release.

## Decisions

| # | Decision |
|---|----------|
| D1 | **Start small, no reservation concurrency.** A **CPS-held lock** serializes reservation requests to NPS: acquire to reserve, release after; lock has auto-expiry; callers wait if it's held. |
| D2 | **On failure: pause → human review → resume or rollback.** Temporal workflow waits on a signal; cancel runs compensations to free resources. Not auto-rollback. |
| D3 | **NetBox is the allocation SoR.** Aravolta (physical facts) and CPS/NPS (allocation facts) write **non-overlapping fields** on a NetBox object. |
| D4 | **NetBox→Rafay inventory sync is a separate periodic CPS workflow** (every few hours) — the second use case, not part of the provision path. |
| D5 | **Preflight check** on reserved nodes (health/reachability) before committing them to the tenant. |
| D6 | **PXE on a separate OOB VLAN**, distinct from the tenant data network/VRF. |
| D7 | **CPS is stateless** (only Temporal workflow state). TMS/PGSQL owns tenant→cluster→assets for billing. |
| D8 | **Scheduling/selection logic lives in CPS** (GPU type/count match, RDMA rail/leaf locality, control-plane anti-affinity). |
| D9 | **Idempotency key** on `ProvisionCluster` so TMS retries don't start a duplicate workflow. |
| D10 | **CPS↔Rafay over REST** (cross-cluster, vendor product). TMS↔CPS↔NPS over gRPC/Proto in-cloud. VPN crossings are vendor-internal (Apstra→switches, Rafay Ctrl↔Head). Rafay REST creds from a secrets manager; Rafay project/RBAC mapped 1:1 to tenants. |
| D11 | **AiFabrik management/monitoring workload** deployed via a **Rafay addon/blueprint** (declarative, re-applied). |

## Follow-ups

- **F1 — Kubeconfig delivery.** No Rafay ZTKA. Direct API-server kubeconfig — needs
  (a) network reachability from cloud/tenant to the API server in the tenant VRF at
  site, and (b) credential lifecycle (issue/rotate/revoke). Design after cluster
  build is settled.
- **F2 — Storage (Weka).** Filesystem + CSI integration; deferred.
- **F3 — Concurrency-safe reservation.** Replace the single CPS lock with an atomic
  compare-and-set reserve in NPS when we scale past serialized requests.
