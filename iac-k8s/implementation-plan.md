# iac-k8s — POC Implementation Plan (high level)

A small, cheap, ephemeral proof-of-concept that validates the two foundational pieces of the factory before we invest in the full build. **Status: draft for review.**

## POC goal & milestones

| Milestone | What it proves |
|---|---|
| **M1 — Smallest hardened multi-AZ cluster** | The factory (Terraform module + GitHub Actions, D11) can build, on a PR-merge, the cheapest GKE cluster that still meets our needs — **regional/multi-AZ, ≥2 node pools, hardened baseline** — and tear it down idempotently. |
| **M2 — UI drives the build** | A minimal **FastAPI + React** console (D9) can, after the manual steps are done, drive M1 end-to-end via the GitHub Actions API (D8/D11): create cluster → render plan → approve → cluster up → run scan → view report → add a node pool → teardown — **no CLI**. |

**Out of scope for the POC:** Rafay Controller, Management Plane apps, Confidential nodes (optional toggle test only), multi-region, full operator RBAC, observability stack, Binary Authorization *enforcement* (run in dry-run/audit), Day-2 upgrade automation. These are noted so the POC stays small.

## Decisions baked in

Built on the design decisions in the area README: **D1** mixed node pools · **D2** CIS L2 floor · **D3** Standard + COS · **D4** signed images · **D5** companion stateful modules · **D6** one FOP · **D7** GKE-native controls mandatory · **D8** PR-based mutation · **D9** FastAPI+React console · **D10** ArgoCD single GitOps engine · **D11** GitHub Actions backend.

---

## Phase 0 — Manual prerequisites (before any automation)

Do once, by hand; everything after is automated. (This is R1 scoped to the POC.)

| # | Step | Tool |
|---|---|---|
| 1 | Have/confirm a GCP **Organization + Billing Account** (or use an existing sandbox project) | Cloud Console |
| 2 | Create a **POC project** `aifabrik-iac-poc` and link billing | `gcloud` / [`terraform-google-bootstrap`](https://github.com/terraform-google-modules/terraform-google-bootstrap) |
| 3 | Create a **GCS bucket** for Terraform state (versioning on) | `gcloud storage` |
| 4 | Configure **Workload Identity Federation**: pool + provider for GitHub OIDC, a CI service account, and IAM bindings (no keys) | `gcloud iam` |
| 5 | Enable APIs: `container`, `compute`, `iam`, `cloudkms`, `cloudresourcemanager` | `gcloud services enable` |
| 6 | Create **GitHub repos**: `iac-gke` (Terraform + workflows + guardrail manifests) and `iac-console` (FastAPI+React) | `gh repo create` |
| 7 | Set a **budget alert** on the project (cost guardrail) | Cloud Console / `gcloud billing budgets` |
| 8 | Install local tooling for the operator: `gcloud`, `terraform`, `kubectl`, `gh` | local |

**Exit:** WIF works (a hello-world GitHub Action authenticates to GCP), state bucket exists, repos exist. Handoff line reached.

---

## Phase 1 — M1: smallest hardened multi-AZ cluster

### Cost-minimizing configuration (the "smallest meeting our needs")

| Lever | POC choice | Why |
|---|---|---|
| Region | single, `us-central1` | cheap; regional = multi-AZ control plane (meets "multiple AZs") |
| Cluster type | **Regional** GKE Standard | multi-AZ requirement; COS nodes (D3) |
| Node pools | **2** (`system`, `general`) | proves "node pools"; general spread across 3 zones |
| Machine type | `e2-small` (or `e2-medium`) | smallest viable |
| Nodes | autoscale **min 1 / zone**, total kept low; **Spot VMs** | ~60–90% cheaper |
| Hardening | full D2/D7 controls (private cluster, WI, Shielded, Dataplane V2, KMS) | the point of the POC; near-zero added cost |
| Confidential pool | **off** by default; optional 1-node toggle test | n2d machines cost more — keep optional |
| Lifecycle | **ephemeral** — build, test, destroy | cluster mgmt fee (~$0.10/hr) only billed while up |

### Build steps (automated)

1. **Repo scaffold** (`iac-gke`): `foundation/` (minimal VPC + 1 KMS key), `modules/gke-cluster/` (thin wrapper over [`safer-cluster`](https://github.com/terraform-google-modules/terraform-google-kubernetes-engine/blob/main/modules/safer-cluster/README.md) exposing a `node_pools` list with per-pool `confidential`/`image_type`), `envs/poc/poc.tfvars`.
2. **GitHub Actions workflows**:
   - `plan.yml` — on PR: `terraform plan`, post diff as PR comment + upload plan artifact.
   - `apply.yml` — on merge to `main`, gated by an **Environment with required reviewer**: `terraform apply`.
   - `destroy.yml` — `workflow_dispatch`: `terraform destroy` (teardown test).
   - All auth via **WIF** (no keys).
3. **ArgoCD bootstrap (D10)**: Terraform/Helm installs ArgoCD; an App-of-Apps syncs the **guardrail App** (k8s-hardening Tier-1 + Kyverno, sync wave 0, self-heal).

### Validation (automated tests)

| Check | Tool |
|---|---|
| Cluster is regional, nodes span **3 zones** | `kubectl get nodes -o wide` / `gcloud container clusters describe` |
| **2 node pools** present | `gcloud container node-pools list` |
| Hardening conformance (Tier-1 + GKE benchmark) | reuse [`AI-Fabrik/k8s-hardening`](https://github.com/AI-Fabrik/k8s-hardening) `harden.py all --skip-tier2`, kube-bench `gke-1.6.0`, kubescape |
| Drift self-heal | delete a Kyverno policy, confirm ArgoCD restores it |
| **Idempotent** | re-run `apply` → no changes; `destroy` → clean |

**M1 done when:** a merged PR builds the cluster, all checks pass, and `destroy` cleans up with no orphaned resources.

---

## Phase 2 — M2: UI drives the build

### Minimal console (`iac-console`)

- **Backend (FastAPI):**
  - `POST /clusters` / `POST /clusters/{id}/nodepools` → edits `poc.tfvars`, opens a **PR** via the GitHub API.
  - `GET /runs/{id}` → polls the Actions run, returns plan diff (from the plan artifact) + status.
  - `POST /runs/{id}/approve` → approves the Environment / merges the PR to trigger apply.
  - `POST /scans` + `GET /scans/{id}` → triggers the scan workflow, returns the rendered `delta.md`/`scores.json`.
  - `GET /inventory` → live reads from the GKE API + Terraform state.
  - Auth: single-operator OIDC login for the POC (full RBAC is future).
- **Frontend (React):** create-cluster / add-node-pool forms, plan-diff viewer with **Approve** button, run-status view, scan-report view, inventory list.

### Integration

GitHub **Actions API** (`workflow_dispatch`, runs, artifacts) + **PR API** + **GKE API**. The UI never calls `gcloud`/`kubectl` to mutate — it only opens PRs and reads status (D8).

**M2 done when:** an operator, starting from a completed Phase 0, drives the entire M1 lifecycle from the browser — create → approve → cluster up → scan → add node pool → teardown — without touching a terminal.

---

## Tooling summary

| Tool | Purpose | Phase |
|---|---|---|
| `gcloud`, `terraform-google-bootstrap` | day-0 project/state/WIF | 0 |
| Terraform + `safer-cluster` module | provision GCP + GKE | 1 |
| GitHub Actions + WIF (D11) | plan/apply/destroy execution | 1, 2 |
| ArgoCD (D10) | guardrail + (later) app delivery | 1 |
| `AI-Fabrik/k8s-hardening` (harden.py, kube-bench, kubescape) | conformance scans | 1, 2 |
| FastAPI + React (D9) | operator console | 2 |
| GKE Security Posture | managed posture findings | 1, 2 |

## Cost controls

Spot VMs · `e2-small` · single region · ephemeral (destroy after each test) · budget alert. Expect **single-digit dollars per test run** dominated by the ~$0.10/hr cluster management fee while the cluster is up.

## Rough sequencing

`Phase 0 (manual)` → `M1 cluster + workflows` → `M1 ArgoCD + validation` → `M2 backend` → `M2 frontend` → `M2 end-to-end demo`. M1 should be demoable before M2 work starts.

## Open questions for review

1. POC GCP project — new sandbox, or an existing one?
2. GitHub-hosted runners for the POC (simplest), or stand up self-hosted runners now?
3. Include the Confidential-pool toggle test in the POC, or defer it?
4. How strict on supply-chain (Binary Authorization) in the POC — audit-only, or skip?
