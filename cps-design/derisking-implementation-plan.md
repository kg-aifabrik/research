# CPS Derisking Bootstrap — Implementation Plan (DRAFT for review)

> **Status: DRAFT — awaiting approval.** On approval: ADRs are written to
> `docs/adr/`, and milestones/chunks are mirrored into **Linear** (not GitHub).
> Source plan: [derisking-bootstrap-plan.md](derisking-bootstrap-plan.md).

Executes the 10-step scripts-first plan as independently testable **chunks**
grouped into demoable **milestones**. Every chunk shares one definition of done:
**create script works · delete script restores clean state · verification check
passes · runbook entry written** (preconditions, inputs, duration, failure modes).

## Tracking model (Linear)

- One Linear **project**: *CPS Bootstrap*. Milestones below → Linear project
  milestones; chunks → issues with the acceptance criteria as checklists; labels
  `chunk` / `spike`.
- **Precondition:** Linear access from this environment (Linear MCP connector or
  API key) — not currently connected; needed before issue creation.
- Weekly comms ride on Linear state: tracker diagram + update draft generated from
  issue status (see chunk C3).

## Milestones → chunks

### M1 — Rafay foundation (dev)

**Demo:** Rafay console shows a managed dev site with the AiFabrik blueprint applied.

| # | Chunk | Depends on | Acceptance criteria |
|---|-------|-----------|---------------------|
| C1 | Rafay controller org/project setup in GKE (dev) | — | ☐ controller reachable; ☐ project/RBAC created; ☐ credentials in secrets manager, none hardcoded; ☐ runbook entry |
| C2 | Rafay head node on dev site | C1 | ☐ head node dials out to controller and shows healthy; ☐ IPMI reachability from head node verified; ☐ teardown: head node deregistered; ☐ runbook entry |
| C3 | Comms scaffolding | — | ☐ `gen/build_bootstrap_tracker.py` renders 10-step status diagram from a status file; ☐ weekly-update template committed (traffic lights · demoed · blocked/decisions · next week); ☐ first tracker render committed |
| C4 | Addons & blueprints | C1 | ☐ AiFabrik management blueprint applies declaratively; ☐ re-apply is idempotent; ☐ teardown: blueprint/addon removed cleanly; ☐ runbook entry |

**Integration scenario:** fresh dev site from nothing → managed in Rafay with
blueprint, then torn down to clean state, twice in a row (proves idempotency).

### M2 — Node ready

**Demo:** a bare GPU server boots into a configured OS, visible in Rafay, on the right VLAN/VRF.

| # | Chunk | Depends on | Acceptance criteria |
|---|-------|-----------|---------------------|
| C5 | Data contracts: inventory CSV + network ledger | — | ☐ inventory CSV schema mirrors NetBox fields (asset ID, serial, IPMI addr, rack/leaf, GPU type/count); ☐ ledger schema mirrors future NPS response (IP, VLAN, VRF, gateway); ☐ both documented with field-level comments; ☐ sample files validate against schema |
| C6 | Inventory upload script (CSV → Rafay, incl. DHCP config) | C2, C5 | ☐ upload idempotent (re-run = no dupes); ☐ Rafay DHCP serves a test node; ☐ delete script removes assets from Rafay; ☐ runbook entry |
| C7 | Netplan generator + upload via Rafay provisioning hook | C5, C6 | ☐ netplan generated from ledger for a host; ☐ delivered via provisioning hook and applied on boot; ☐ host reachable on tenant VLAN/VRF post-boot; ☐ teardown: host deprovision clears config; ☐ runbook entry |
| C8 | BMaaS trigger with node registration | C6, C7 | ☐ node PXE-boots and registers; ☐ node shows Ready in Rafay; ☐ teardown: deregister + deprovision returns node to pool; ☐ runbook entry |

**Integration scenario:** CSV + ledger in → node provisioned on tenant network →
torn down → same node re-provisioned (proves the pool is actually restored).
**External dependency:** ledger values arrive from NPS's parallel derisking (manual
handoff) — interlock tracked as a standing weekly line.

### M3 — Cluster up

**Demo:** `kubectl get nodes` against a freshly minted cluster from the head-node network.

| # | Chunk | Depends on | Acceptance criteria |
|---|-------|-----------|---------------------|
| C9 | Cluster create/delete trigger scripts | C8 | ☐ create returns a Ready cluster (CPU control plane + GPU workers per design); ☐ create idempotent on retry; ☐ delete removes cluster and frees nodes; ☐ runbook entry with timings |
| C10 | Blueprint control over `certSANs` / `oidc-*` flags (spike) | C9 | ☐ public hostname present in API-server serving cert at create time via Rafay config; ☐ feasibility of `oidc-*` API-server flags documented; ☐ finding recorded (feeds credential end-state decision) |

**Integration scenario:** M2 node flow feeding directly into cluster create; delete
cluster → nodes return to pool → recreate succeeds.

### M4 — Reachable & usable

**Demo:** `kubectl` from a laptop on the public internet against the tenant cluster.

| # | Chunk | Depends on | Acceptance criteria |
|---|-------|-----------|---------------------|
| C11 | Public internet → K8s API server connectivity | C9, C10 | ☐ kubectl works from outside via public hostname; ☐ TLS verifies (no `insecure-skip-tls-verify`); ☐ teardown: exposure removed, API unreachable externally; ☐ runbook entry |
| C12 | Public internet → workload services connectivity | C9 | ☐ test HTTPS workload reachable from outside; ☐ teardown: exposure removed; ☐ runbook entry |
| C13 | Bootstrap kubeconfig issuance | C11 | ☐ admin kubeconfig retrieved via documented route; ☐ marked bootstrap-only (long-lived cert) in runbook; ☐ revocation reality documented (CA rotation cost measured or estimated); ☐ short-lived alternative demonstrated once (`kubeadm kubeconfig user` or CSR API) |
| C14 | Paralus evaluation (timeboxed spike, 1 week) | C11 | ☐ Paralus deployed against a dev cluster; ☐ Okta OIDC login → kubectl works end-to-end; ☐ per-tenant IdP multiplexing answered yes/no with evidence; ☐ recommendation note committed (adopt / native OIDC / Pinniped) |

**Integration scenario (full-path):** internet laptop → Okta/OIDC or bootstrap
kubeconfig → tenant cluster → GPU workload scheduled — the end-to-end GPUaaS
walking skeleton.

### M5 — Prod stand-up *(scope gate — see open questions)*

| # | Chunk | Depends on | Acceptance criteria |
|---|-------|-----------|---------------------|
| C15 | Rafay controller + head node (prod) | M1–M4 green | ☐ prod controller and head node standing; ☐ scripts remain dev-only unless explicitly decided otherwise; ☐ runbook delta (prod vs dev) documented |

## Decisions to record as ADRs (on approval)

1. **Scripts-first derisking with end-state-shaped stubs** — CSV/ledger mirror
   NetBox/NPS fields. Rejected: building CPS directly against unproven Rafay
   behavior; throwaway bash stubs whose learning doesn't transfer.
2. **CPS owns host netplan, delivered via Rafay provisioning hook** — Rafay cannot
   generate the netplan we need. Rejected: Rafay-native host network config.
3. **Every create has a symmetric delete** — teardown scripts become CPS
   compensation activities. Rejected: happy-path-only scripting.
4. **Credential end-state: central OIDC; Paralus under evaluation** — Rafay ZTKA
   rejected for vendor coupling, not proxy architecture. Alternatives held: native
   OIDC flags (Dex/Keycloak), Pinniped. Decision finalizes after C14.
5. **Linear for execution tracking** — issues/milestones in Linear; design contract
   stays in this repo. Rejected: GitHub Issues (team standard is Linear).

## TDR outline (on approval)

`docs/design/` — *CPS bootstrap scripts*: repo layout; script conventions
(idempotent, parameterized, CPS implementation language); data contracts (inventory
CSV, network ledger, status file for the tracker); runbook format; Rafay API
surfaces used per script (= CPS dependency contracts); teardown symmetry rule.

## Risks & open questions

1. **Scripts repo location** — proposal: new companion repo `kg-aifabrik/cps-bootstrap`
   (mirrors the `host-config` pattern); this repo keeps the design contract. **Needs decision.**
2. **Weekly update channel** — email / Slack / other; determines what the
   automation targets. **Needs decision.**
3. **NPS interlock** — ledger handoff timing is the critical-path external
   dependency for M2; no committed date yet.
4. **Prod scope (M5)** — what "prod" means while scripts are hand-run.
5. **Rafay API unknowns** — timing, idempotency, failure modes are the point of
   the exercise; expect chunk-level surprises, absorb them into runbooks, and
   re-plan at milestone boundaries only.
