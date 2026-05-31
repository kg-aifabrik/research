# iac-k8s

Tooling to build **any** hardened, highly-available, regional GKE cluster and manage its lifecycle with mostly automation — a reusable **cluster factory**, not a fixed set of clusters. The FOP (Rafay Controller) and Management Plane are the first reference consumers; later site/tenant clusters reuse the same path.

- **Goal = reusable tooling.** A parameterized **Terraform** cluster module (built on `safer-cluster`) + a **Config Sync** guardrail policy package + a reusable **ArgoCD** app-bootstrap. A new cluster is one values entry in Git, not new code. See [01](01-provisioning-and-iac.md).
- **Day-0 manual, once per org:** ~12 steps (org, billing, seed project, WIF) via `terraform-google-bootstrap`; no downloaded SA keys — Workload Identity Federation for CI.
- **HA by default:** every factory cluster is regional (3-AZ), surviving one AZ failure (C3.2); size/mode are inputs.
- **Security baked in:** the standard = CIS GKE Benchmark (reuse [`AI-Fabrik/k8s-hardening`](https://github.com/AI-Fabrik/k8s-hardening) Tier-1 + scans) + GKE-native controls + supply-chain + WIF/OIDC, enforced on every cluster by the module + Config Sync. Tier-2 node hardening is Google's job on managed GKE. See [02](02-security-standard.md).
- **Lifecycle by profile:** reusable upgrade profiles (`conservative` = Stable/Extended, `balanced` = Regular) set release channel + maintenance windows as a parameter; security patches auto-apply, feature upgrades are deferrable. Node OS = Container-Optimized OS = near-zero OS patch burden. **Standard is the default mode, Autopilot opt-in.** See [03](03-day2-operations.md).
- **Build inventory:** heavy reuse of terraform-google-modules + k8s-hardening; net-new = the parameterized module + CI/WIF, the Config Sync policy package, GitOps bootstrap, supply-chain, upgrade profiles, and ratifying the hardening profile. See [04](04-do-list.md).

## Decisions
- **D1 — Mixed-sensitivity node pools, one cluster.** Sensitive vs non-sensitive workloads run on separate node pools (confidential vs standard) sharing a control plane, via a per-pool `confidential` flag + taints + Kyverno placement enforcement. Revisit two-cluster separation only for a hard regulatory/tenancy boundary. See [02](02-security-standard.md#decision-mixed-sensitivity-node-pools-d1).

## Open threads
- **Ratify the GKE hardening profile** — CIS L1 vs L2; which GKE-native controls are mandatory vs recommended; encode as the module's default.
- **Autopilot support depth** — how far to support Autopilot as a module mode given DaemonSet/host-access limits for observability agents.
- **Binary Authorization break-glass policy** — emergency unsigned-image admission without weakening steady state.
- **Per-consumer stateful add-ons** — generic module option (e.g. Rafay's durable Cloud SQL/GCS) vs consumer-owned; drives recovery runbooks.
- **Multi-site fleet evolution** — Config Sync chosen partly for fleet-scale; revisit when North Star multi-site lands.
