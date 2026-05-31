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
- **D2 — CIS GKE L2 is the default floor.** Module bakes in CIS Level 2 for all clusters; no looser baseline known. Workload exceptions via audited Kyverno exceptions, not a lower floor. See [02](02-security-standard.md#decision-cis-gke-l2-as-the-default-floor-d2).
- **D3 — Standard mode, COS default, Ubuntu opt-in per pool.** Factory builds Standard (not Autopilot) clusters with Container-Optimized OS on every pool by default; `image_type` is a per-pool input so an Ubuntu pool can sit alongside COS when a workload needs it (that pool owns its OS patching). See [03](03-day2-operations.md#decision-standard-mode-cos-default-ubuntu-opt-in-per-pool-d3).
- **D4 — No unsigned images, no break-glass.** Binary Authorization enforce-only; every image needs a valid cosign signature/attestation, no exceptions even in incidents. Emergency path = re-deploy a previously-signed image, never admit unsigned. Makes the signing pipeline a tier-0 dependency. See [02](02-security-standard.md#decision-no-unsigned-images-no-break-glass-d4).
- **D5 — Stateful add-ons as separate companion modules.** Consumer state (e.g. Rafay's durable Cloud SQL/GCS) lives in separate optional modules composed alongside the cluster, not in the `gke-cluster` module — independent lifecycle so data outlives cluster rebuilds; cluster module stays single-purpose. See [01](01-provisioning-and-iac.md#decision-stateful-add-ons-as-separate-companion-modules-d5).

## Open threads
- **Which GKE-native controls are mandatory vs recommended** within the L2 (D2) floor — finalize and encode as the module's defaults.
- **Multi-site fleet evolution** — Config Sync chosen partly for fleet-scale; revisit when North Star multi-site lands.
