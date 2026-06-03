# iac-k8s — Requirements

*Status: draft for review. Earlier working documents are in [`archive/`](archive/).*

## What we are building, in one paragraph

A small web console that lets our operations team create and run **Google Kubernetes Engine (GKE)** clusters — Google's managed Kubernetes service — on **Google Cloud Platform (GCP)**. The operator picks two things — an **environment** (dev, stage, or prod) and a **purpose** (Fleet Operations Plane or Management Plane) — and the console builds a security-hardened cluster for them. The same console handles day-to-day cluster administration and a daily security check. Under the hood, every change is written as code, reviewed, and applied automatically, so the setup is repeatable and auditable.

Immediate scope is **at most 6 clusters**: three environments × two purposes. Start simple; grow later.

## Requirements

Each requirement says *what* we need and *why*.

- **R1 — Operator console.** A web user interface (UI) for our Site Reliability Engineering (SRE) operators to build and manage clusters. *It is an internal tool for operators, not a self-service portal for application teams.*
- **R2 — Two-dimensional choice.** The operator selects an **environment** (dev/stage/prod) and a **purpose** (Fleet Operations Plane = the plane that operates our fleet; Management Plane = the end-user-facing product surface). One selection produces one cluster. *Why: these are the only two axes we vary today.*
- **R3 — One-time manual setup.** A written runbook covers the handful of things that must be done by hand once in Google Cloud (organization, projects, identity, billing). Everything after that is automated. *Why: some bootstrap steps cannot be automated because they create the very accounts the automation uses.*
- **R4 — One project per environment.** Each environment is its own Google Cloud **project** (an isolated container for resources). All dev clusters live in the dev project, stage in stage, prod in prod. *Why: a project is the natural isolation boundary — a mistake in dev cannot touch prod.*
- **R5 — Hardened by default.** Every cluster is built to a defined security standard with no extra steps: the **Center for Internet Security (CIS)** GKE benchmark as the floor, plus the controls Google's "safer-cluster" template does not turn on for us (e.g. our own admission policies). *Why: security must be built in, not bolted on per cluster.*
- **R6 — Daily security audit.** The console runs a daily check on every cluster, produces a report, and flags anomalies — meaning **configuration drift** (the live cluster no longer matches what we declared) and **security regressions** (a control went missing or a benchmark score dropped). *We start with security and can widen the scope later.*
- **R7 — Day-2 operations in the console.** The everyday cluster-administration tasks are available as console features (full list below): add/remove node pools, add pools of different machine types, resize, upgrade, drain a node, and so on. *Why: operators should not need the command line for routine work.*
- **R8 — Code is the source of truth.** Every change is expressed as code in **Git** (our version-control system), reviewed as a **pull request (PR)** (a proposed change others can review), and applied by automation after approval. *Why: this gives us a complete, reviewable history and prevents undocumented manual changes.*
- **R9 — Extensible to new resource types.** The console is the single place operators work, and we can add new kinds of cloud resources behind it later — for example a **PostgreSQL** database (an open-source relational database, via Google Cloud SQL) or an object-storage bucket. *Why: avoid a new tool for every resource type.*
- **R10 — Highly available.** Each cluster is **regional** — its control plane and nodes are spread across multiple **availability zones (AZs)** (independent data-center failure domains) — so it survives the loss of one zone.
- **R11 — Cost-aware defaults.** Use small, inexpensive defaults; only add costly features (such as confidential, memory-encrypting nodes) on the specific clusters that need them.
- **R12 — Per-cluster cost tracking.** We can see cost broken down by individual cluster (and by environment and purpose). *Why: budgeting and chargeback. How: label every resource with environment/purpose/cluster, and turn on **GKE Cost Allocation** so the billing export in **BigQuery (BQ)** — Google's data warehouse for billing data — and the Cloud Billing reports can group per cluster. This works even with several clusters in one project; the only nuance is splitting truly shared resources (e.g. a shared network gateway), which we avoid by giving each cluster its own networking.*

## How we will build it, and why (the engine decision)

We will use **Infrastructure as Code (IaC)** — defining cloud resources in text files rather than clicking in a console — with three pieces:

1. **Terraform** (an IaC tool) describes the clusters and other resources.
2. **GitHub Actions** (an automation service that runs jobs when code changes) runs Terraform to make the changes — it shows a preview ("plan"), waits for approval, then applies.
3. **A custom console** (a small web app) gives operators the friendly UI on top, opening the pull requests and showing status.

**Why this and not a "control-plane" tool like Crossplane or Config Connector?** Those tools model cloud resources as live Kubernetes objects and continuously correct any drift, which is powerful. We considered them seriously and chose not to, for now, because:

- **Security.** Terraform-via-automation uses short-lived credentials (about one hour per run). A control-plane tool needs an always-on, highly privileged service holding credentials to everything — a bigger, permanent target.
- **Control.** Terraform shows an exact preview of what will change before we approve it. That explicit gate matters for production.
- **Simplicity and skills.** Terraform is widely known and lets us reuse Google's existing hardened modules. The control-plane tools are a specialized, fast-moving skill.

**The trade-off we accept:** Terraform does not *continuously* watch for drift. We cover this by running a scheduled check (daily, per R6) instead of instant correction. We can revisit a control-plane tool later only if we need continuous reconciliation across many resource types, or open the console to self-service — **not** merely to add a database or bucket, which Terraform already does.

## Assumptions and scope decisions

- **Managed Kubernetes on Google Cloud only.** We are not comparing clouds and not running these clusters elsewhere. On-premises/edge clusters are handled by a separate system (Rafay) and are out of scope here.
- **GKE Standard mode, not Autopilot.** Standard lets us control the nodes (needed for confidential, memory-encrypting node pools and host-level agents). Nodes use **Container-Optimized OS (COS)** — Google's hardened, auto-patched node operating system — so node maintenance is near-zero.
- **Operators only.** No self-service for application teams (this keeps the console simple).
- **Security-first audit.** The daily audit starts with security checks; cost, capacity, and other checks can come later.
- **Confidential nodes by environment.** **Stage and prod clusters use memory-encrypting (Confidential) nodes; dev does not.** This keeps dev cheap while protecting the environments that hold real data. *(Open: whether the entire stage/prod cluster is Confidential or just a dedicated pool — see open question 2.)*
- **Git is the source of truth**, even though a friendly console sits in front; the console writes to Git, it does not bypass it.

## Out of scope (for now)

- On-premises / per-site clusters (a separate system owns these).
- Multiple clouds.
- Self-service for application developers.
- Database *operations* beyond provisioning (schema migrations, point-in-time restore, failover drills).

## Day-2 operations the console must support (R7 detail)

- **Node pools:** add or remove a pool; add a pool of a different machine type (e.g. GPU, or confidential/memory-encrypting); resize a pool (min/max); change machine type.
- **Versions:** upgrade the cluster and node pools; choose the update cadence ("release channel"); set maintenance windows.
- **Nodes:** drain or replace a node; trigger node repair; view node and capacity status.
- **Security:** rotate the encryption key; manage access (RBAC = role-based access control); install/update guardrail policies.
- **Lifecycle:** create or delete a cluster; back up and restore.
- **Audit:** run an on-demand security scan; view daily reports; acknowledge flagged anomalies.
- **Future resources (R9):** provision and attach a Cloud SQL database, an object-storage bucket, etc.

## Open questions for your review

1. **Project layout** (also affects cost tracking, R12): confirm **one project per environment** (3 projects; per-cluster cost works via labels + GKE Cost Allocation). Alternatives: **one project per environment × purpose** (6 projects, one cluster each — cost attribution is trivial, but more projects to manage), or split only prod.
2. **Confidential scope** (decided: stage + prod use Confidential nodes): make the **whole** stage/prod cluster Confidential (every node memory-encrypting), or a **dedicated Confidential pool** alongside normal pools? *Lean: whole-cluster, for simplicity and a clear security story.*
3. **Approval gates** (these gate **infrastructure changes** — building/modifying clusters, the Terraform apply): confirm **dev automatic, stage + prod require a reviewer**. Also: do you want the **in-cluster hardening config** changes gated the same way, or only the infrastructure layer?
4. **Reaching the clusters:** use **GKE Connect Gateway** so the console/audits reach the locked-down clusters via Google's fleet service (IAM-controlled, no IP allow-listing, no VPN). *Explained; confirm OK to adopt.*
5. **Code repository:** start a fresh `iac-gke` repository for this, or keep building in the existing proof-of-concept repository?
