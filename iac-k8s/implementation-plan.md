# iac-k8s — POC Implementation Plan (high level)

A small, cheap, ephemeral proof-of-concept that validates the foundational pieces of the factory before we invest in the full build. **Status: draft for review.**

## POC goal & milestones

| Milestone | What it proves |
|---|---|
| **M1 — GKE cluster only** | The factory (Terraform module + GitHub Actions, D11) builds, on a PR-merge, a GKE cluster meeting our requirements — **regional/multi-AZ, COS nodes (D3), multiple node pools incl. a Confidential pool (D1/D7), private + hardened cluster config** — and tears it down idempotently. |
| **M2 — Deploy hardening + report** | **ArgoCD (D10)** deploys the workload-hardening guardrails (k8s-hardening Tier-1 + Kyverno) onto the M1 cluster, and the scan pipeline produces a **before/after conformance test report**. |
| **M3 — Drive M1 + M2 from the Operator Console** | A minimal **FastAPI + React** console (D9) drives both milestones via the GitHub Actions API (D8/D11): create cluster → render plan → approve → cluster up → deploy hardening → run scan → view report → teardown — **no CLI**. |

**POC parameters (decided):** new **sandbox GCP project**; **GitHub-hosted runners**; **Confidential-pool toggle test included**.

**Out of scope for the POC:** Rafay Controller, Management Plane apps, multi-region, full operator RBAC, observability stack, Day-2 upgrade automation. **Binary Authorization runs audit-only** (enabled + logging violations, not blocking) — avoids standing up the signing pipeline; flips to Enforce (D4) once that pipeline exists.

## Decisions baked in

Built on the design decisions in the area README: **D1** mixed node pools · **D2** CIS L2 floor · **D3** Standard + COS · **D4** signed images · **D5** companion stateful modules · **D6** one FOP · **D7** GKE-native controls mandatory · **D8** PR-based mutation · **D9** FastAPI+React console · **D10** ArgoCD single GitOps engine · **D11** GitHub Actions backend.

---

## Phase 0 — Manual prerequisites (before any automation)

Do once, by hand; everything after is automated. (R1 scoped to the POC.) **Copy-paste runbook + handoff checklist:** [phase0-runbook.md](phase0-runbook.md).

| # | Step | Tool |
|---|---|---|
| 1 | Create a **new sandbox project** `aifabrik-iac-poc` and link billing | Cloud Console / `gcloud` |
| 2 | Create a **GCS bucket** for Terraform state (versioning on) | `gcloud storage` |
| 3 | Configure **Workload Identity Federation**: pool + provider for GitHub OIDC, a CI service account, IAM bindings (no keys) | `gcloud iam` |
| 4 | Enable APIs: `container`, `compute`, `iam`, `cloudkms`, `cloudresourcemanager` | `gcloud services enable` |
| 5 | Create **GitHub repos**: `iac-gke` (Terraform + workflows + guardrail manifests) and `iac-console` (FastAPI+React) | `gh repo create` |
| 6 | Set a **budget alert** on the project | Cloud Console / `gcloud billing budgets` |
| 7 | Install local tooling: `gcloud`, `terraform`, `kubectl`, `gh` | local |

**Exit:** a hello-world GitHub Action authenticates to GCP via WIF; state bucket and repos exist. Handoff line reached.

---

## Phase 1 — M1: GKE cluster only

### Configuration (smallest meeting our requirements)

| Lever | POC choice | Why |
|---|---|---|
| Region | single, `us-central1` | cheap; regional = multi-AZ control plane |
| Cluster type | **Regional** GKE Standard, **private nodes** | multi-AZ + hardened (D2/D7) |
| Node image | **Container-Optimized OS** (D3) | requirement; auto-patched |
| Node pools | **`system`** (e2-small, spot) · **`general`** (e2-small, spot, 3 zones) · **`confidential`** (n2d-standard-2, AMD SEV, 1 node) | proves node pools + Confidential toggle (D1/D7) |
| GKE-native controls | private cluster, Workload Identity, Shielded nodes, Dataplane V2, KMS secrets encryption | D7 mandatory; near-zero added cost |
| Lifecycle | **ephemeral** — build, test, destroy | mgmt fee billed only while up |

> Confidential GKE Nodes require an AMD SEV-capable machine (`n2d-standard-2` is the smallest), so that pool is pricier than the e2-small pools — it's brought up briefly for the toggle test, then torn down.

### Build steps (automated)

1. **Repo scaffold** (`iac-gke`): `foundation/` (minimal VPC + 1 KMS key), `modules/gke-cluster/` (thin wrapper over [`safer-cluster`](https://github.com/terraform-google-modules/terraform-google-kubernetes-engine/blob/main/modules/safer-cluster/README.md) exposing a `node_pools` list with per-pool `confidential` / `image_type` / `machine_type`), `envs/poc/poc.tfvars`.
2. **GitHub Actions workflows** (GitHub-hosted runners, WIF auth, no keys):
   - `plan.yml` — on PR: `terraform plan`, post diff to PR + upload plan artifact.
   - `apply.yml` — on merge to `main`, gated by an **Environment with required reviewer**: `terraform apply`.
   - `destroy.yml` — `workflow_dispatch`: `terraform destroy`.

### Validation

| Check | Tool |
|---|---|
| Regional cluster; nodes span **3 zones** | `kubectl get nodes -o wide` / `gcloud container clusters describe` |
| **3 node pools**, one **Confidential** | `gcloud container node-pools list` (+ confidential flag) |
| Node image is **COS** | `gcloud container node-pools describe` |
| **Idempotent** | re-run `apply` → no changes; `destroy` → clean |

**M1 done when:** a merged PR builds the cluster (incl. the Confidential pool), all checks pass, and `destroy` leaves no orphaned resources.

---

## Phase 2 — M2: Deploy hardening + generate report

**Detailed runbook:** [m2-runbook.md](m2-runbook.md).

### Steps (automated)

1. **ArgoCD bootstrap (D10):** Terraform/Helm installs ArgoCD on the M1 cluster; an App-of-Apps points at the guardrail repo.
2. **Guardrail App (sync wave 0, self-heal):** ArgoCD syncs the [`AI-Fabrik/k8s-hardening`](https://github.com/AI-Fabrik/k8s-hardening) **Tier-1 manifests + Kyverno policies** verbatim (PSS, default-deny NetworkPolicy, RBAC, SA-automount-off).
3. **Conformance report:** run the k8s-hardening **scan pipeline** — `kube-bench` (`gke-1.6.0`), `kubescape` — capturing a **baseline** (pre-sync) and **validate** (post-sync) scan, emitting `delta.md` + `scores.json` **committed to the `iac-gke` code repo's `reports/` folder** (store of record for the POC; no GCS). Overlay **GKE Security Posture** findings.

### Validation

| Check | Tool |
|---|---|
| Tier-1 guardrails present and **enforcing** (a privileged pod is rejected) | `kubectl apply` test pod → Kyverno deny |
| Drift **self-heals** (delete a policy → ArgoCD restores) | ArgoCD |
| **Report generated** showing baseline→post delta | k8s-hardening `delta.md`, kube-bench, kubescape |

**M2 done when:** guardrails are live and enforcing on the M1 cluster, and a readable conformance report is produced and stored.

---

## Phase 3 — M3: Drive M1 + M2 from the Operator Console

### Minimal console (`iac-console`)

- **Backend (FastAPI):**
  - `POST /clusters`, `POST /clusters/{id}/nodepools` (incl. `confidential: true`) → edit `poc.tfvars`, open a **PR** via the GitHub API.
  - `GET /runs/{id}` → poll the Actions run; return plan diff (from artifact) + status. `POST /runs/{id}/approve` → approve the Environment / merge to apply.
  - `POST /hardening` → trigger the M2 ArgoCD sync + scan; `GET /reports/{id}` → fetch the rendered `delta.md`/`scores.json` from the `iac-gke` repo `reports/` folder via the GitHub API.
  - `GET /inventory` → live reads from the GKE API + Terraform state.
  - Auth: single-operator OIDC login (full RBAC is future).
- **Frontend (React):** create-cluster / add-node-pool (Confidential checkbox) forms, plan-diff viewer with **Approve**, run-status, **deploy-hardening** action, scan-report viewer, inventory list.

### Integration

GitHub **Actions API** (`workflow_dispatch`, runs, artifacts) + **PR API** + **GKE API** + ArgoCD API. The UI never calls `gcloud`/`kubectl` to mutate — it only opens PRs and reads status (D8).

**M3 done when:** an operator, starting from a completed Phase 0, drives the full M1+M2 lifecycle from the browser — create cluster (with Confidential pool) → approve → cluster up → deploy hardening → view report → teardown — without a terminal.

---

## Tooling summary

| Tool | Purpose | Phase |
|---|---|---|
| `gcloud`, `terraform-google-bootstrap` | day-0 project/state/WIF | 0 |
| Terraform + `safer-cluster` module | provision GCP + GKE | 1 |
| GitHub Actions + WIF (D11), GitHub-hosted runners | plan/apply/destroy execution | 1, 3 |
| ArgoCD (D10) | deploy guardrails (+ later apps) | 2 |
| `AI-Fabrik/k8s-hardening` (harden.py, kube-bench, kubescape) | hardening manifests + conformance scans | 2, 3 |
| FastAPI + React (D9) | operator console | 3 |
| GKE Security Posture | managed posture findings | 2, 3 |

## Cost controls

**All node pools on Spot** (incl. the Confidential `n2d-standard-2` pool, which supports Spot) · `e2-small` for system/general pools · **`us-central1`** (GCP's lowest-cost US region — us-west1 ≈ +5%, us-east4 ≈ +8%; no cheaper option, and the management fee + Cloud NAT are region-flat) · ephemeral (destroy after each test) · budget alert. The Confidential pool adds cost while up — bring it up only for the toggle test.

### Approx cost per hour (while running)

| Component | Config | ~$ / hour |
|---|---|---|
| GKE control plane (cluster management fee) | 1 regional Standard cluster | 0.10 |
| `system` pool | 1× e2-small (Spot) | 0.005 |
| `general` pool | up to 3× e2-small (Spot) | 0.015 |
| `confidential` pool | 1× n2d-standard-2 (Spot) | 0.025 |
| Node boot disks | ~5× 50 GB pd-balanced | 0.03 |
| Cloud NAT (egress for private nodes) | 1 regional gateway | 0.05 |
| KMS + logging/monitoring | minimal | 0.01 |
| **Total — all pools incl. Confidential (Spot)** | | **≈ $0.24 / hr** |
| Total — same on **on-demand** (no Spot) | | ≈ $0.40 / hr |
| Total — **without** Confidential pool (M1 base / M2 steady, Spot) | | ≈ $0.20 / hr |

Caveats: us-central1, approximate list prices, **excludes** network egress / NAT data-processing and Cloud Logging/Monitoring ingestion beyond free tiers; the ~$0.10/hr management fee is the floor regardless of node count. Spot nodes can be **preempted** (acceptable for a POC; not for production planes). With **ephemeral teardown**, a full build → test → destroy cycle lands in **low single-digit dollars**.

## Rough sequencing

`Phase 0 (manual)` → `M1 cluster + workflows + validation` → `M2 ArgoCD + hardening + report` → `M3 console backend` → `M3 frontend` → `M3 end-to-end demo`. Each milestone is demoable before the next begins.

## Progress log

- **Phase 0** — complete & verified (project `k8s-iac-poc`, WIF, state bucket, CI SA, repos, `poc-apply` env). One WIF repo-name typo found & fixed during handoff.
- **Phase 1 / M1** — ✅ **built & validated.** [`kg-aifabrik/iac-gke-poc`](https://github.com/kg-aifabrik/iac-gke-poc): regional cluster, COS, 3 pools (incl. Confidential AMD SEV), D7 hardening (private nodes, WI, Shielded, Dataplane V2, KMS, BinAuthz audit-only), via GitHub Actions + WIF. Bumped `system`/`general` to `e2-standard-2` for M2 headroom; Confidential pool switched Spot→on-demand (Spot preemption left it with no node).
- **Phase 2 / M2** — ✅ **complete.** ArgoCD + Kyverno installed; `guardrails` Application **Synced/Healthy** delivering k8s-hardening Tier-1 (PSS + 10 Kyverno policies). **Behavioral proof:** privileged pod rejected; deleted policy **self-healed** by ArgoCD. Conformance report committed to `iac-gke-poc/reports/`. kubescape 85→82 (measurement artifact — post scan includes the unhardened ArgoCD/Kyverno tooling; see report).
- **POC learnings:** (1) two `push`-to-main applies raced on the TF **state lock** → added `concurrency: terraform-state` to apply/destroy. (2) **Spot** `n2d` Confidential capacity is unreliable → on-demand for stable confidential nodes. (3) Phase-0 runbook was missing BinAuthz/ServiceUsage APIs + `serviceAccountAdmin`/`projectIamAdmin`/`binaryauthorization.policyEditor` CI-SA roles (now fixed). (4) Whole-cluster kubescape aggregate is a noisy before/after; scan a fixed workload namespace instead.
- **Phase 3 / M3** — **mocked console built** in [`kg-aifabrik/iac-console-poc`](https://github.com/kg-aifabrik/iac-console-poc): FastAPI + React/Bootstrap (D9), GCP/Actions/ArgoCD calls mocked with a run state machine (D8 plan→approve→apply). Drives create-cluster → confidential node pool → deploy hardening → conformance report with no live cloud. Run: `cd backend && pip install -r requirements.txt && uvicorn main:app --port 8000`. **Real-cloud M3 still needs GKE Connect Gateway** to reach the IP-restricted endpoint; the mock backend handlers are the seam to replace.

## Resolved POC parameters

- **Single sandbox project** for all three milestones (incl. console resources) — isolation deferred.
- **Report committed to the `iac-gke` code repo** (`reports/` folder) as store of record; console reads via the GitHub API.
- **Binary Authorization audit-only** for the POC (enabled, logging, not blocking); enforce later (D4).

All open questions resolved — plan is ready to expand into execution detail (repo scaffolds, workflow skeletons, task breakdown) on your go.
