# iac-k8s — High-Level Architecture

A one-page picture of the GKE cluster factory + operator console for team brainstorming. Detail lives in [01 provisioning](01-provisioning-and-iac.md), [02 security](02-security-standard.md), [03 Day 2](03-day2-operations.md), [04 do-list](04-do-list.md), [05 console](05-operator-console.md). Design decisions **D1–D9** are tagged inline; one item (TF execution backend) is still open.

## The whole picture

```mermaid
flowchart TB
  subgraph OP["👤 AIFabrik Operator (SRE)"]
    direction LR
    UI["Operator Console<br/>React + FastAPI (D9)<br/>scans · node pools · inventory · upgrades"]
  end

  subgraph GIT["declared intent in Git (D8: PR -> plan -> approve -> apply)"]
    direction LR
    TFV["infra: clusters.yaml / tfvars"]
    POL["guardrail policy package<br/>(k8s-hardening Tier-1 + Kyverno)"]
    APP["app repos (Rafay, Mgmt Plane)"]
  end

  EXE["TF execution backend<br/>⚠ OPEN: GH Actions + self-hosted runners vs Atlantis"]

  subgraph FOUND["GCP foundation — Terraform (built once)"]
    direction LR
    ORG["org policy · folders · projects<br/>WIF (no SA keys) · KMS · VPC/NAT"]
  end

  subgraph FACTORY["🏭 Cluster Factory — Terraform"]
    direction LR
    MOD["gke-cluster module<br/>parameterized, hardened, regional HA"]
    STATE["companion stateful modules (D5)<br/>Cloud SQL / GCS · CMEK · backups"]
  end

  subgraph CLUSTERS["Hardened regional GKE clusters (D6: one FOP foreseeable)"]
    direction TB
    subgraph FOP["FOP cluster"]
      RAFAY["Rafay Controller (workload)"]
    end
    subgraph MGMT["Management Plane cluster"]
      MFN["operator-facing fns + console backend"]
    end
    subgraph NODES["node pools — Standard mode, COS default (D3)"]
      direction LR
      NP1["standard pool"]
      NP2["confidential pool (D1, AMD SEV)"]
      NP3["ubuntu pool (opt-in)"]
    end
  end

  subgraph GITOPS["in-cluster GitOps"]
    direction LR
    CS["Config Sync<br/>guardrails + drift-heal"]
    ARGO["ArgoCD<br/>app delivery"]
  end

  subgraph DAY2["Day-2 + conformance"]
    direction LR
    UPG["upgrade profiles<br/>channels + maint windows"]
    SCAN["scan pipeline<br/>kube-bench gke + kubescape"]
    POSTURE["GKE Security Posture"]
    OBS["observability / audit"]
  end

  SITES["⤵ on-prem site fleet<br/>managed by Rafay — OUT OF SCOPE (D6)"]

  UI --> GIT
  UI -->|run scan / read state| SCAN
  GIT --> EXE
  EXE --> FOUND
  EXE --> FACTORY
  FACTORY --> CLUSTERS
  FOUND --> CLUSTERS
  POL --> CS
  APP --> ARGO
  CS --> CLUSTERS
  ARGO --> CLUSTERS
  STATE -. durable state .-> RAFAY
  CLUSTERS --> DAY2
  SCAN --> UI
  POSTURE --> UI
  RAFAY ==> SITES
```

## How to read it (the four moves)

1. **Bootstrap once.** ~12 manual day-0 steps (org, billing, seed project, WIF) hand off to Terraform, which builds the GCP foundation and the factory. No downloadable keys — Workload Identity Federation.
2. **Build clusters from the factory.** The parameterized `gke-cluster` Terraform module stamps out hardened, regional (3-AZ) clusters from a values entry. Security is baked in (D2 CIS L2, D7 all GKE-native controls mandatory). Mixed node pools (D1): standard + confidential (per data class) + optional Ubuntu.
3. **Deliver config & apps via GitOps.** Config Sync continuously reconciles the guardrail policy package (reused from `k8s-hardening`) and self-heals drift; ArgoCD deploys the workloads — Rafay Controller on the FOP, operator functions on the Management Plane.
4. **Operate through the console.** Everything the operator does is **intent, not direct mutation** (D8): a console action edits declared config → opens a PR → plan → approve → apply. Scans, posture, inventory, and upgrade status flow back as reads.

## Trust & scope boundaries

- **One FOP** for the foreseeable future; it hosts **Rafay as a workload**, and **Rafay** — not this factory — manages the **multi-site on-prem k8s fleet** (D6). That fleet is out of `iac-k8s` scope; the heavy arrow to it marks the boundary.
- **No unsigned images** ever cross the admission boundary (D4) — the signing pipeline is a tier-0 dependency.
- **Control plane is a shared trust boundary** within a cluster; mixed node pools give data-in-use isolation, not blast-radius separation (D1). Hard regulatory tenancy → revisit two clusters.

## The intent loop (mutating actions)

```mermaid
sequenceDiagram
  participant Op as Operator
  participant UI as Console
  participant Git as Git (PR)
  participant Exe as TF backend (OPEN)
  participant GCP as GCP / GKE
  Op->>UI: "add confidential node pool"
  UI->>Git: open PR editing clusters.yaml
  Git->>Exe: trigger terraform plan
  Exe-->>UI: plan diff
  Op->>UI: approve
  UI->>Exe: apply
  Exe->>GCP: create node pool (confidential)
  GCP-->>UI: status + updated inventory
  Note over GCP: Config Sync keeps guardrails enforced throughout
```

## Open item for the brainstorm

- **Terraform execution backend** (the ⚠ box): **GitHub Actions + self-hosted runners** (lean — reuses CI + WIF, clean API, creds stay in-env) vs **Atlantis** (purpose-built PR server, directory locking, more to operate). HCP Terraform / TFE ≈ eliminated (external SaaS / cost / sovereignty). Decision pending — see [05](05-operator-console.md#open-thread).
