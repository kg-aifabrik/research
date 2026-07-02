# CPS — Derisking Bootstrap Plan (Scripts → CPS)

Before building the **Compute Provisioning Service (CPS)**, every provisioning step
is first proven manually with scripts against Rafay. Each script is a stand-in for a
CPS capability; the mapping below is the transition contract. Companion design:
[k8s-cluster-provisioning.md](k8s-cluster-provisioning.md).

## Executive summary

Scripts-first derisking: prove the Rafay integration (timing, failure modes,
idempotency) with cheap scripts before CPS code exists. Three rules make the
learning transfer:

1. **Every create has a delete.** Teardown scripts are written alongside create
   scripts — they become CPS's compensation activities verbatim, and they keep the
   dev site from snowflaking.
2. **Stubs are shaped like the end state.** Input files (inventory CSV, network
   ledger) mirror the fields NetBox/NPS will later provide, so the CPS transition is
   a source swap, not a rewrite.
3. **Every run produces a runbook entry.** Preconditions, inputs, verification
   check, duration, observed failure modes — this is the spec for the Temporal
   workflows.

## Requirements

- Prove end-to-end provisioning through Rafay: controller in GKE (dev, prod), head
  node on site (dev, prod), addons/blueprints, inventory, host network config,
  cluster creation, Bare Metal as a Service (BMaaS) node registration, and public
  connectivity to both the Kubernetes (K8s) API server and workload services.
- Scripts are idempotent, parameterized units in CPS's implementation language, so
  CPS wraps rather than rewrites them.
- Symmetric teardown for every create.

## Assumptions made

All confirmed in discussion:

- **Inventory stub:** server inventory lives in a CSV; a script loads it into Rafay
  (including Rafay DHCP configuration). End state: **NetBox is the System of Record
  (SoR)**; CPS syncs NetBox→Rafay. The CSV schema mirrors the NetBox fields and
  doubles as the NetBox seed import.
- **Network-values stub:** IP, VLAN, Virtual Routing and Forwarding (VRF), and
  gateway are allocated manually and recorded in a ledger file the scripts read.
  End state: the **Network Provisioning Service (NPS)** allocates and records them
  in NetBox, returning them to CPS over gRPC. The ledger format mirrors the future
  NPS response.
- **Fabric is NPS scope:** NPS runs its own parallel derisking plan to configure
  the Juniper fabric and hands the resulting values to us — manually now, via API
  under CPS.
- **CPS owns host netplan** (constraint discovered: Rafay cannot generate the
  netplan configuration we need). The script generates it and uploads it via
  **Rafay's provisioning hook**; that hook is CPS's contract with the host. ADR
  candidate when CPS implementation starts.

## Step mapping

| # | Step (derisking script) | Teardown pair | CPS end state |
|---|------------------------|---------------|---------------|
| 1 | Rafay controller in GKE (dev, prod) | n/a — standing infra | unchanged |
| 2 | Rafay head node on site (dev, prod) | n/a — standing infra | unchanged |
| 3 | Set up addons & blueprints in Rafay (manual) | remove addon/blueprint | CPS applies the AiFabrik blueprint declaratively |
| 4 | Upload inventory CSV to Rafay, incl. DHCP config | remove assets from Rafay | periodic CPS workflow syncs NetBox→Rafay |
| 5 | Generate host netplan from ledger (IP, VLAN, VRF, gateway); upload via Rafay provisioning hook | host deprovision clears it | CPS generates netplan from NPS-provided values |
| 6 | Trigger BMaaS with node registration | deregister + deprovision node | activity inside the CPS provisioning workflow |
| 7 | Trigger cluster creation via Rafay | delete cluster | CPS `CreateCluster` provisioning workflow |
| 8 | Configure public internet → K8s API server connectivity | remove exposure | CPS orchestrates with Platform Connectivity |
| 9 | Configure public internet → workload services connectivity | remove exposure | CPS orchestrates with Platform Connectivity |

Steps 6/7 order per Rafay's flow; the runbook records the actual dependency graph
(inventory → network values → netplan → BMaaS → cluster → connectivity) with wait
conditions and durations — the encoding Temporal needs.

## Open items

Not covered by the scripts phase; each needs a pass before or during CPS build:

- **Kubeconfig & credential issuance** — steps 8/9 give a network path, not
  credentials (issue/rotate/revoke).
- **Preflight health checks** before committing nodes to a tenant.
- **Per-step verification** — the manual analog of `GetOperation`: define the check
  that proves each step succeeded, and record it in the runbook.
- **Weka storage** — separate design pass.
- **"Prod" scope during the manual phase** — hand-run scripts stay dev-only until
  CPS wraps them, unless explicitly decided otherwise.
