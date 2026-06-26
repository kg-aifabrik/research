# CPS — K8s Cluster Provisioning (First Capability)

Design snapshot for the **Compute Provisioning Service (CPS)** first capability:
provisioning a Kubernetes (K8s) cluster for a tenant on site hardware.

This describes the system as built. It covers the path from a Tenant Management
Service (TMS) request to a running, AiFabrik-managed K8s cluster. Storage (Weka),
kubeconfig delivery, and client connectivity belong to the same capability and are
still to be built — see [To be included](#to-be-included).

## Executive summary

CPS is a **stateless Temporal orchestrator** exposing gRPC to its single client,
TMS. A provision request runs as one Temporal workflow (a saga): it reserves
hardware in NetBox through the Network Provisioning Service (NPS), creates a tenant
network (VRF/VLAN + IP addressing) through NPS→Apstra, provisions the operating
system (OS) and builds K8s through the Rafay Controller, and deploys the AiFabrik
management/monitoring addon. NetBox is the **System of Record (SoR)** for inventory
and allocation; TMS — backed by PostgreSQL (PGSQL) — owns the business mapping
tenant→cluster→assets used for billing. The API is **async**: a call returns an
operation handle and TMS polls for status.

## Actors & systems

All cloud components run in Google Cloud Platform (GCP).

| Component | Where | Role |
|-----------|-------|------|
| **TMS** (Tenant Management Service) | GCP / mgmt plane | CPS's client; owns tenant→cluster→assets mapping in PGSQL (billing). |
| **CPS** (Compute Provisioning Service) | GCP | Temporal orchestrator, gRPC API. **Stateless** beyond Temporal workflow state. Owns scheduling/selection + the reservation lock. |
| **NPS** (Network Provisioning Service) | GCP | gRPC/Proto wrapper over NetBox (inventory reads + allocation writes); drives Apstra for VRF/VLAN + IP addressing (IPAM). |
| **NetBox** | GCP | Inventory **SoR**. Two writers, non-overlapping fields: Aravolta (physical) + CPS/NPS (allocation). |
| **Aravolta** | GCP | Physical data-center infra management; feeds host/switch/router facts into NetBox. |
| **Juniper Apstra** | GCP | Underlay fabric controller; configures site switches over the VPN. |
| **Rafay Controller** | GCP (separate GKE cluster) | Bare-metal OS + K8s lifecycle + addons. CPS↔Rafay is REST. |
| **Rafay Head Node** | Site | Last-mile agent: IPMI discovery, PXE boot, host config. |
| **Site servers** | Site | CPU servers (control plane) + GPU servers (workers). |

## Provisioning workflow (Temporal saga)

The API is async: `ProvisionCluster` starts the workflow and returns an operation
handle; TMS polls `GetOperation`/`GetCluster`. Every mutating step has a
compensating action, and activities are idempotent so Temporal can safely retry
them. `ProvisionCluster` takes a client-supplied idempotency key, so a TMS retry
does not start a duplicate workflow.

![CPS K8s cluster-provisioning workflow — Temporal saga](diagrams/cps_provision_flow.png)

> Diagram source: [`gen/build_provision_flow.py`](gen/build_provision_flow.py) →
> `diagrams/cps_provision_flow.{excalidraw,svg,png}`. Regenerate with
> `python3 gen/build_provision_flow.py`.

**Failure handling.** When an activity exhausts its retries, the workflow
transitions to `AWAITING_REVIEW` and waits on a human signal — **resume**
(retry/continue) or **cancel** (run compensations in reverse to free resources).
There is no automatic rollback: GPU nodes are expensive, so the default is to hold
resources rather than release them.

## State & systems of record

- CPS holds no durable state of its own beyond Temporal workflow state — it can be
  wiped and rebuilt.
- **NetBox is the SoR for inventory and allocation.** It has two writers on
  non-overlapping fields: Aravolta writes physical facts; CPS/NPS write allocation
  facts. After a CPS wipe, NetBox still reflects which assets belong to which tenant.
- **TMS/PGSQL owns the tenant→cluster→assets mapping** (consumed by billing).
- NetBox→Rafay node inventory is kept current by a **separate periodic CPS
  workflow** (every few hours), not by the provisioning path.

## Scheduling & reservation

- **Node selection lives in CPS.** It matches the request against GPU type/count,
  keeps GPU workers rail/leaf-local for backend Remote Direct Memory Access (RDMA),
  and spreads control-plane nodes for high availability (HA).
- **Reservation is serialized by a CPS-held lock**: acquire before reserving,
  release after; the lock auto-expires, and callers wait to acquire it. (Single
  site, low volume — a concurrency-safe reserve is [to be included](#to-be-included).)
- **Reserved nodes pass a preflight** health/reachability check before being
  committed to the tenant.

## Networking

- Per-tenant isolation is a **tenant VRF/VLAN with IP addressing (IPAM)**, created
  through NPS→Apstra before OS install.
- **PXE/IPMI provisioning rides a separate out-of-band (OOB) VLAN**, distinct from
  the tenant data network, so attaching nodes to the tenant VRF never strands the
  boot.

## Interfaces & security

- **TMS↔CPS↔NPS** speak gRPC with Protocol Buffers (Proto); NPS presents NetBox and
  Apstra behind that same gRPC surface.
- **CPS↔Rafay is REST** (Rafay is a vendor product in a separate GKE cluster). Rafay
  credentials come from a secrets manager, never hardcoded.
- All our services run cloud-side in one trust domain. The only VPN crossings are
  vendor-internal: Apstra→switches and Rafay Controller↔Rafay Head Node (the head
  node dials out). Rafay's project/RBAC model maps 1:1 to tenants to bound blast
  radius.
- The AiFabrik management/monitoring workload deploys as a **Rafay addon/blueprint**
  (declarative, re-applied).

## To be included

The capability is not complete without these; each gets its own design pass.

- **Storage (Weka).** Per-tenant filesystem plus the K8s Container Storage Interface
  (CSI) integration.
- **Kubeconfig & client connectivity.** Tenants get a **direct API-server
  kubeconfig** (no Rafay zero-trust kubectl access, "ZTKA"). Two problems: a network
  path from cloud/tenant to the API server inside the tenant VRF at the site, and
  credential lifecycle (issue/rotate/revoke).
- **Concurrency-safe reservation.** Replace the single CPS lock with an atomic
  compare-and-set reserve in NPS once request volume outgrows serialized access.
