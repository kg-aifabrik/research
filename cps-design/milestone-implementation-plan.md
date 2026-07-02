# Implementation Plan - Draft

> **Status: DRAFT — awaiting approval.** On approval, milestones and chunks below
> are mirrored into **Linear**. Source plan:
> [derisking-bootstrap-plan.md](derisking-bootstrap-plan.md).

## Philosophy

- **We script and practice everything we need to automate.** Every step CPS will
  eventually perform is first executed as a script against real hardware. The
  learning — timings, failure modes, idempotency quirks, the exact Rafay API
  surfaces — is captured in runbooks and transfers directly into CPS activities.
- **Every script has a build and a teardown**, so the flow can be executed many
  times during testing without snowflaking the environment. Teardown scripts later
  become CPS's compensation activities verbatim.
- **Hand-coded inputs stand in where a dependency is itself still being built.**
  Inventory comes from a CSV (NetBox is the end-state source); network values (IP,
  VLAN, VRF, gateway) come from a hand-maintained ledger (NPS is the end-state
  source). Each stub's format mirrors the future system's fields, so the switch is
  a data-source swap, not a rewrite.

Every chunk shares one definition of done:

- create script works
- delete script restores clean state
- verification check passes
- runbook entry written (preconditions, inputs, duration, failure modes)

## Tracking model (Linear)

- One Linear **project**: *CPS Bootstrap*. Milestones below → Linear project
  milestones; chunks → issues with the acceptance criteria as checklists; labels
  `chunk` / `spike`.
- **Precondition:** Linear access from this environment (Linear MCP connector or
  API key) — not currently connected; needed before issue creation.
- Weekly comms ride on Linear state: tracker diagram + update draft generated from
  issue status (see chunk C3).

## M1 — Rafay foundation (dev)

**Demo:** Rafay console shows a managed dev site with the AiFabrik blueprint applied.

### C1 — Rafay controller org/project setup in GKE (dev)

- Depends on: —
- Acceptance criteria:
  - [ ] controller reachable
  - [ ] project/RBAC created
  - [ ] credentials in secrets manager, none hardcoded
  - [ ] runbook entry written

### C2 — Rafay head node on dev site

- Depends on: C1
- Acceptance criteria:
  - [ ] head node dials out to controller and shows healthy
  - [ ] IPMI reachability from head node verified
  - [ ] teardown: head node deregistered
  - [ ] runbook entry written

### C3 — Comms scaffolding

- Depends on: —
- Acceptance criteria:
  - [ ] `gen/build_bootstrap_tracker.py` renders the 10-step status diagram from a status file
  - [ ] weekly-update template committed (traffic lights · demoed · blocked/decisions · next week)
  - [ ] first tracker render committed

### C4 — Addons & blueprints

- Depends on: C1
- Acceptance criteria:
  - [ ] AiFabrik management blueprint applies declaratively
  - [ ] re-apply is idempotent
  - [ ] teardown: blueprint/addon removed cleanly
  - [ ] runbook entry written

**M1 integration scenario:** fresh dev site from nothing → managed in Rafay with
blueprint, then torn down to clean state, twice in a row (proves idempotency).

## M2 — Node ready

**Demo:** a bare GPU server boots into a configured OS, visible in Rafay, on the right VLAN/VRF.

### C5 — Data contracts: inventory CSV + network ledger

- Depends on: —
- Acceptance criteria:
  - [ ] inventory CSV schema mirrors NetBox fields (asset ID, serial, IPMI address, rack/leaf, GPU type/count)
  - [ ] ledger schema mirrors the future NPS response (IP, VLAN, VRF, gateway)
  - [ ] both documented with field-level comments
  - [ ] sample files validate against schema

### C6 — Inventory upload script (CSV → Rafay, incl. DHCP config)

- Depends on: C2, C5
- Acceptance criteria:
  - [ ] upload idempotent (re-run = no duplicates)
  - [ ] Rafay DHCP serves a test node
  - [ ] delete script removes assets from Rafay
  - [ ] runbook entry written

### C7 — Netplan generator + upload via Rafay provisioning hook

- Depends on: C5, C6
- Acceptance criteria:
  - [ ] netplan generated from ledger for a host
  - [ ] delivered via provisioning hook and applied on boot
  - [ ] host reachable on tenant VLAN/VRF post-boot
  - [ ] teardown: host deprovision clears config
  - [ ] runbook entry written

### C8 — BMaaS trigger with node registration

- Depends on: C6, C7
- Acceptance criteria:
  - [ ] node PXE-boots and registers
  - [ ] node shows Ready in Rafay
  - [ ] teardown: deregister + deprovision returns node to pool
  - [ ] runbook entry written

**M2 integration scenario:** CSV + ledger in → node provisioned on tenant network →
torn down → same node re-provisioned (proves the pool is actually restored).

**External dependency:** ledger values arrive from NPS's parallel derisking (manual
handoff) — interlock tracked as a standing weekly line.

## M3 — Cluster up

**Demo:** `kubectl get nodes` against a freshly minted cluster from the head-node network.

### C9 — Cluster create/delete trigger scripts

- Depends on: C8
- Acceptance criteria:
  - [ ] create returns a Ready cluster (CPU control plane + GPU workers per design)
  - [ ] create idempotent on retry
  - [ ] delete removes cluster and frees nodes
  - [ ] runbook entry written, with timings

### C10 — Blueprint control over `certSANs` / `oidc-*` flags (spike)

- Depends on: C9
- Acceptance criteria:
  - [ ] public hostname present in API-server serving cert at create time via Rafay config
  - [ ] feasibility of `oidc-*` API-server flags documented
  - [ ] finding recorded (feeds the credential end-state decision)

**M3 integration scenario:** M2 node flow feeding directly into cluster create;
delete cluster → nodes return to pool → recreate succeeds.

## M4 — Reachable & usable

**Demo:** `kubectl` from a laptop on the public internet against the tenant cluster.

### C11 — Public internet → K8s API server connectivity

- Depends on: C9, C10
- Acceptance criteria:
  - [ ] kubectl works from outside via public hostname
  - [ ] TLS verifies (no `insecure-skip-tls-verify`)
  - [ ] teardown: exposure removed, API unreachable externally
  - [ ] runbook entry written

### C12 — Public internet → workload services connectivity

- Depends on: C9
- Acceptance criteria:
  - [ ] test HTTPS workload reachable from outside
  - [ ] teardown: exposure removed
  - [ ] runbook entry written

### C13 — Bootstrap kubeconfig issuance

- Depends on: C11
- Acceptance criteria:
  - [ ] admin kubeconfig retrieved via documented route
  - [ ] marked bootstrap-only (long-lived cert) in runbook
  - [ ] revocation reality documented (CA rotation cost measured or estimated)
  - [ ] short-lived alternative demonstrated once (`kubeadm kubeconfig user` or CSR API)

### C14 — Paralus evaluation (timeboxed spike, 1 week)

- Depends on: C11
- Acceptance criteria:
  - [ ] Paralus deployed against a dev cluster
  - [ ] Okta OIDC login → kubectl works end-to-end
  - [ ] per-tenant IdP multiplexing answered yes/no with evidence
  - [ ] recommendation note committed (adopt / native OIDC / Pinniped)

**M4 integration scenario (full-path):** internet laptop → Okta/OIDC or bootstrap
kubeconfig → tenant cluster → GPU workload scheduled — the end-to-end GPUaaS
walking skeleton.

## M5 — Prod stand-up *(scope gate — see open questions)*

### C15 — Rafay controller + head node (prod)

- Depends on: M1–M4 green
- Acceptance criteria:
  - [ ] prod controller and head node standing
  - [ ] scripts remain dev-only unless explicitly decided otherwise
  - [ ] runbook delta (prod vs dev) documented

## Decision notes

Captured here for now; they graduate to formal Architecture Decision Records
(ADRs) and Technical Design Records (TDRs) in the CPS production monorepo when the
CPS build starts.

- **Scripts-first derisking with end-state-shaped stubs** — CSV/ledger mirror
  NetBox/NPS fields. Rejected: building CPS directly against unproven Rafay
  behavior; throwaway bash stubs whose learning doesn't transfer.
- **CPS owns host netplan, delivered via Rafay provisioning hook** — Rafay cannot
  generate the netplan we need. Rejected: Rafay-native host network config.
- **Every create has a symmetric delete** — teardown scripts become CPS
  compensation activities. Rejected: happy-path-only scripting.
- **Credential end-state: central OIDC; Paralus under evaluation** — Rafay ZTKA
  rejected for vendor coupling, not proxy architecture. Alternatives held: native
  OIDC flags (Dex/Keycloak), Pinniped. Decision finalizes after C14.
- **Linear for execution tracking** — issues/milestones in Linear; design contract
  stays in this repo. Rejected: GitHub Issues (team standard is Linear).

## Risks & open questions

- **Scripts repo location** — proposal: new companion repo `kg-aifabrik/cps-bootstrap`
  (mirrors the `host-config` pattern); this repo keeps the design contract. **Needs decision.**
- **Weekly update channel** — email / Slack / other; determines what the
  automation targets. **Needs decision.**
- **NPS interlock** — ledger handoff timing is the critical-path external
  dependency for M2; no committed date yet.
- **Prod scope (M5)** — what "prod" means while scripts are hand-run.
- **Rafay API unknowns** — timing, idempotency, failure modes are the point of
  the exercise; expect chunk-level surprises, absorb them into runbooks, and
  re-plan at milestone boundaries only.
