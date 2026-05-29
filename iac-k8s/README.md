# iac-k8s

IaC for taking GCP from nothing to **two hardened, HA, regional GKE clusters** — one hosting the Fleet Operations Plane (FOP / Rafay Controller), one the Management Plane — managed by declared intent in Git, plus Day-2 lifecycle.

- **Provisioning:** ~12 day-0 manual steps (org, billing, seed project, WIF), then everything is **Terraform** (`safer-cluster` module) + **Config Sync** for guardrails + **ArgoCD** for apps. No downloaded SA keys — Workload Identity Federation for CI. See [01](01-provisioning-and-iac.md).
- **Topology:** separate clusters for FOP and Mgmt Plane; regional (3-AZ) to survive one AZ failure (C3.2).
- **Security standard:** = CIS GKE Benchmark (reuse [`AI-Fabrik/k8s-hardening`](https://github.com/AI-Fabrik/k8s-hardening) Tier-1 + scans, GKE benchmark) + GKE-native controls + supply-chain + WIF/OIDC. **Tier-2 node hardening is Google's job** on managed GKE. See [02](02-security-standard.md).
- **Day 2:** security patches auto-apply via release channel (FOP=Stable/Extended, Mgmt=Regular) inside maintenance windows; node OS = Container-Optimized OS = near-zero OS patch burden. **Standard over Autopilot** (Rafay needs node control). See [03](03-day2-operations.md).
- **Build inventory:** heavy reuse of terraform-google-modules + k8s-hardening; net-new = layered Terraform+CI, GKE-native config, GitOps bootstrap, supply-chain, Day-2 policy, and ratifying the hardening profile. See [04](04-do-list.md).

## Open threads
- **Ratify the GKE FOP Hardening Standard profile** — CIS L1 vs L2; which GKE-native controls are mandatory vs recommended.
- **Confidential GKE Nodes for the Management Plane?** It handles end-user data — decide if AMD SEV is required.
- **Can the Management Plane run on Autopilot?** Depends on whether it needs any host-level / DaemonSet access (observability agents).
- **Binary Authorization break-glass policy** — how to admit emergency unsigned images without weakening steady state.
- **Rafay Controller durable-state choice** — Cloud SQL vs GCS vs in-cluster; drives the `60-data` Terraform layer and recovery runbook.
- **Multi-site fleet evolution** — Config Sync chosen partly for fleet-scale; revisit when North Star multi-site lands.
