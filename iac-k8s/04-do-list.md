# iac-k8s Do-List: Tasks, Reuse vs New

Delivers **R8**. The concrete build inventory across buckets, each task tagged **[REUSE]** (existing automation we adopt) or **[NEW]** (we build). Requirements & Assumptions canonical in [01](01-provisioning-and-iac.md#requirements).

**Legend:** [REUSE] = existing tool/module/repo we wire in · [NEW] = net-new for AIFabrik · [ADAPT] = existing artifact, modified.

## Bucket 0 — Day-0 manual (one-time, per [01](01-provisioning-and-iac.md#day-0-the-irreducible-manual-bootstrap))

| Task | Tag | Notes |
|---|---|---|
| Create/claim GCP Org + verify domain | [NEW] manual | bound to Cloud Identity/Workspace |
| Create billing account + payment method | [NEW] manual | |
| Create Cloud Identity admin/SRE groups | [NEW] manual | RBAC identity source |
| Seed project + state bucket + WIF + bootstrap APIs | [REUSE] | [`terraform-google-bootstrap`](https://github.com/terraform-google-modules/terraform-google-bootstrap) module scripts steps 4–8 |
| Grant first human bootstrap admin org roles | [NEW] manual | |

## Bucket 1 — IaC provisioning (Terraform, in Git)

| Task | Tag | Notes |
|---|---|---|
| `00-org` org policies + folders | [NEW] | constraints: disable SA keys, require Shielded VM, restrict public IP |
| `10-projects` per-plane projects + API enablement | [REUSE] | `terraform-google-modules/project-factory` |
| `20-network` VPC, subnets w/ secondary ranges, **regional Cloud NAT**, firewall | [REUSE] | `terraform-google-modules/network` |
| `30-kms` key rings/keys (secrets, state) | [REUSE] | `terraform-google-modules/kms` |
| **`gke-cluster` parameterized module** (the core deliverable — builds *any* hardened HA cluster from a values entry) | [NEW] wraps [REUSE] | thin wrapper over [`safer-cluster`](https://github.com/terraform-google-modules/terraform-google-kubernetes-engine/blob/main/modules/safer-cluster/README.md) (pins CIS + GKE hardening guide) exposing a values contract + upgrade profile |
| Reference instantiations (FOP, Mgmt Plane) as `clusters.yaml`/tfvars entries | [NEW] | proves the factory; each new cluster = one entry, no new code |
| `fleet` register clusters, enable Config Sync + Policy Controller (per cluster) | [REUSE] | `google_gke_hub_feature` ([guide](https://cloud.google.com/blog/topics/anthos/using-terraform-to-enable-config-sync-on-a-gke-cluster)) |
| Optional per-consumer stateful add-on (e.g. Rafay durable Cloud SQL/GCS) | [NEW] | module option; survives controller reinstall (objectives R) |
| CI: GitHub Actions + WIF, per-layer plan/apply, `prevent_destroy` on stateful | [NEW] | keyless; idempotent build/teardown; same pipeline for every cluster |

## Bucket 2 — Security standard (per [02](02-security-standard.md))

| Task | Tag | Notes |
|---|---|---|
| GKE-native controls (WI, private cluster, Shielded, Dataplane V2, KMS secrets, Binary Authz, audit logs) | [NEW] | Terraform flags on `safer-cluster`; mostly defaults of the module |
| Tier-1 workload manifests + Kyverno policies via Config Sync | [REUSE] | [`k8s-hardening/tier1-manifests`](https://github.com/AI-Fabrik/k8s-hardening/tree/main/tier1-manifests) synced as-is |
| OIDC IdP for human kubectl (Connect Gateway) | [ADAPT] | k8s-hardening Tier-3 OIDC stub |
| cosign signing + Binary Authz attestation in CI; Kyverno `verifyImages` | [ADAPT] | k8s-hardening Tier-3 image-signing stub |
| KMS secrets re-encrypt (existing secrets) | [REUSE] | k8s-hardening Tier-3 procedure |
| Conformance gate: `harden.py all --skip-tier2`, kube-bench `gke-1.6.0`, kubescape | [ADAPT] | k8s-hardening pipeline, GKE benchmark override |
| GKE Security Posture dashboard | [REUSE] | free, enable per project |
| **Ratify** the GKE FOP Hardening Standard profile (L1 vs L2; Confidential Nodes for Mgmt?) | [NEW] | governance artifact, security sign-off |

## Bucket 3 — App delivery (per [01](01-provisioning-and-iac.md#app-delivery-from-empty-cluster-to-rafay--mgmt-plane))

| Task | Tag | Notes |
|---|---|---|
| Config Sync root-sync **policy package** (hardening baseline) applied to all factory clusters | [NEW] | structure repo; sources k8s-hardening manifests; authored once |
| Reusable `app-bootstrap` (ArgoCD install via Config Sync) | [REUSE] | OSS; identical per cluster |
| Per-consumer ArgoCD App-of-Apps (e.g. Rafay Controller, Mgmt Plane) | [NEW] | consumer points at own app repo; Rafay as isolated tenant |

## Bucket 4 — Day 2 (per [03](03-day2-operations.md))

| Task | Tag | Notes |
|---|---|---|
| Reusable upgrade **profiles** (`conservative`/`balanced`): release channel + maintenance window/exclusion | [NEW] | Terraform `maintenance_policy` as a module input, not per-cluster config |
| Surge-upgrade + PDBs for Rafay/stateful | [NEW] | quorum-safe node upgrades |
| Node OS = COS everywhere (no OS patch treadmill) | [NEW] | Terraform `image_type` |
| VM Manager OS patch mgmt for any standalone GCE VMs | [NEW] | only if GCE VMs exist |
| Staggered upgrade rollout across clusters (canary one before the rest) | [NEW] | runbook |
| Remediation/recovery + scale runbooks (Rafay, NetBox, head node) | [NEW] | objectives P1; builds on drift-heal + TF re-apply |

## Net-new vs reuse at a glance

- **Heaviest reuse:** the entire workload-posture layer (k8s-hardening Tier-1 + scan pipeline) and the GCP/GKE substrate (terraform-google-modules). These are mature; we wire, not write.
- **Net-new build, in priority order:** (1) layered Terraform root + CI/WIF; (2) GKE-native control config; (3) Config Sync + ArgoCD bootstrap and the Rafay/Mgmt app stacks; (4) supply-chain (cosign + Binary Authz); (5) Day-2 channel/window policy; (6) governance: ratify the GKE hardening profile.
- **Biggest unknowns to close:** Confidential Nodes requirement for the Mgmt Plane (end-user data), Binary Authz break-glass policy, and whether the Mgmt Plane can run on Autopilot.
