# iac-k8s — Requirements

*Status: draft for review. Earlier working documents are in [`archive/`](archive/).*

## What we are building, in one paragraph

A small web console that makes operating **Google Kubernetes Engine (GKE)** clusters — Google's managed Kubernetes service — easier for our operations team, on **Google Cloud Platform (GCP)**. The operator picks two things — an **environment** (dev, stage, or prod) and a **purpose** (Fleet Operations Plane or Management Plane) — and the console builds a security-hardened cluster, then handles day-to-day administration and a daily security check. Every change is written as code, reviewed, approved, and applied automatically, so the setup is repeatable and auditable. Immediate scope is **at most 6 clusters** (three environments × two purposes). Start simple; grow later.

## Guiding principles

Four principles drive every decision below; each requirement notes the principle(s) it serves.

- **Simplicity.** Favor the simplest design that works. Fewer moving parts means fewer chances for costly mistakes as we scale.
- **Audit ready.** Every change to the infrastructure traces back to a **Git** commit (Git is our version-control system) and was approved by an authorized approver before it took effect. Nothing changes by hand.
- **Secure by design.** Every cluster follows the same security standard, and security is enforced as a **closed loop** — the live cluster is continuously reconciled against a committed specification, so drift is corrected automatically rather than caught later.
- **Cost transparency.** Every cost can be traced to a specific cluster and project.

## Requirements

Each requirement states *what* we need, *why*, and the principle(s) it serves.

- **R1 — Operator console.** A web user interface (UI) whose purpose is to **make operating clusters easier** for our Site Reliability Engineering (SRE) operators — build, manage, and audit clusters from one place. It is an internal operator tool, not a self-service portal for application teams. *(Simplicity)*
- **R2 — Two-dimensional choice.** The operator selects an **environment** (dev/stage/prod) and a **purpose** (Fleet Operations Plane = the plane that operates our fleet; Management Plane = the end-user-facing product surface). One selection produces one cluster. *(Simplicity)*
- **R3 — One-time manual setup.** A written runbook covers the few things done by hand once in Google Cloud (organization, projects, identity, billing); everything after is automated. *Why: some bootstrap steps create the very accounts the automation later uses. (Simplicity, Audit ready)*
- **R4 — One project per environment.** Each environment is its own Google Cloud **project** (an isolated container for resources): all dev clusters in the dev project, stage in stage, prod in prod. *Why: a project is the natural isolation boundary and a clean cost boundary. (Simplicity, Cost transparency)*
- **R5 — Hardened by default, enforced as a closed loop.** Every cluster is built to the same security standard — the **Center for Internet Security (CIS)** GKE benchmark plus the extra controls Google's "safer-cluster" template does not enable for us. Security is then **continuously enforced** through the **GitOps** path proven in our proof-of-concept: **ArgoCD** — a tool that keeps a cluster matching a Git-committed specification — syncs the guardrail policies and **self-heals** any drift. (GitOps = operating infrastructure by committing the desired state to Git and letting a tool reconcile reality to it.) *(Secure by design)*
- **R6 — Daily audit as evidence.** Because security is a closed loop (R5), the daily audit's job is to **gather and archive artifacts** that prove the committed spec holds — and flag anything that doesn't — rather than to do the enforcing. The same mechanism gives us a reusable framework to automate any recurring infrastructure task later. *(Audit ready)*
- **R7 — Day-2 operations, with the console as the source of truth for cluster shape.** Everyday administration (full list below) is available in the console. **Most importantly: what each cluster is sized and configured to** — node pools, machine types, and options like Confidential nodes — **is recorded in Git through the console, making Git the authoritative record of every cluster's shape.** *(Audit ready, Simplicity)*
- **R8 — Every change is approved and traceable. No exceptions.** All changes — infrastructure *and* in-cluster hardening config, across all projects, all clusters, and all other resources — are expressed as code in Git, reviewed as a **pull request (PR)** (a proposed change others review), and **require approval by an authorized approver** before automation applies them. *(Audit ready)*
- **R9 — Extensible to new resource types.** The console is the single place operators work, and we can add new kinds of cloud resources behind it later — e.g. a **PostgreSQL** database (an open-source relational database, via Google Cloud SQL) or an object-storage bucket. *(Simplicity)*
- **R10 — Highly available.** Each cluster is **regional** — control plane and nodes spread across multiple **availability zones (AZs)** (independent data-center failure domains) — so it survives the loss of one zone. *(Secure by design)*
- **R11 — Cost-aware, with Confidential nodes as an operator choice.** Small, inexpensive defaults. **Confidential (memory-encrypting) nodes are an option the operator selects per cluster**, not a fixed environment policy — protect what needs it without paying for it everywhere. *(Cost transparency, Simplicity)*
- **R12 — Per-cluster cost tracking.** Cost is visible broken down by individual cluster (and by environment and purpose). *How: label every resource with environment/purpose/cluster and enable **GKE Cost Allocation**, so the billing export in **BigQuery (BQ)** — Google's billing data warehouse — and the Cloud Billing reports group per cluster; this works even with several clusters in one project. (Cost transparency)*

## Assumptions and scope decisions

- **Managed Kubernetes on Google Cloud only.** No cloud comparison; on-premises/edge clusters are handled by a separate system (Rafay) and are out of scope.
- **GKE Standard mode** (not Autopilot), so we control nodes; nodes run **Container-Optimized OS (COS)** — Google's hardened, auto-patched node operating system. *(Simplicity, Secure by design)*
- **Operators only** — no self-service for application teams. *(Simplicity)*
- **Confidential nodes are an operator choice per cluster**, not fixed by environment.
- **All changes require approval** (R8) — there is no auto-apply environment, including dev. *(Audit ready)*
- **Git is the source of truth**; the console writes to Git, never bypasses it. *(Audit ready)*
- **Cluster access via GKE Connect Gateway** — the console and audits reach the locked-down clusters through Google's fleet service, controlled by **Identity and Access Management (IAM)**, with no public endpoints, Internet Protocol (IP) allow-lists, or Virtual Private Network (VPN). *(Secure by design, Simplicity)*

## Out of scope (for now)

- On-premises / per-site clusters (a separate system owns these).
- Multiple clouds.
- Self-service for application developers.
- Database *operations* beyond provisioning (schema migrations, point-in-time restore, failover drills).

## Day-2 operations the console must support (R7 detail)

- **Node pools:** add or remove a pool; add a pool of a different machine type (e.g. graphics processing unit (GPU), or Confidential/memory-encrypting); resize a pool (min/max); change machine type.
- **Versions:** upgrade the cluster and node pools; choose the update cadence ("release channel"); set maintenance windows.
- **Nodes:** drain or replace a node; trigger node repair; view node and capacity status.
- **Security:** rotate the encryption key; manage access (**role-based access control (RBAC)**); install/update guardrail policies.
- **Lifecycle:** create or delete a cluster; back up and restore.
- **Audit:** run an on-demand security scan; view daily reports; acknowledge flagged anomalies.
- **Future resources (R9):** provision and attach a Cloud SQL database, an object-storage bucket, etc.
