# AIFabrik GKE Security Standard

The FOP Hardening Standard, profiled for **managed GKE**. Requirements & Assumptions are canonical in [01](01-provisioning-and-iac.md#requirements) (this report delivers **R4**).

## Executive Summary

The standard is **baked into the reusable cluster module**, so every cluster the factory produces is hardened identically — not hand-secured per cluster. On managed GKE it is **three layers**: (1) the **CIS GKE Benchmark** workload controls — exactly the [`AI-Fabrik/k8s-hardening`](https://github.com/AI-Fabrik/k8s-hardening) **Tier-1** manifests + Kyverno policies, reused verbatim; (2) a defined set of **GKE-native controls** the k8s-hardening repo already lists as "beyond CIS" (Workload Identity, Binary Authorization, Shielded/Confidential nodes, private cluster, Dataplane V2, Cloud KMS secrets encryption, audit logs); (3) **org/identity controls** (WIF-only, OIDC for human kubectl, org policy constraints). **Tier-2 (control-plane/etcd/kubelet node hardening) is Google's responsibility** under the shared-responsibility model and is *not* ours to implement — this is the single biggest difference from the self-managed clusters k8s-hardening was built for.

Because the controls live in the module + Config Sync policy package, **conformance is a property of the factory, not a per-cluster checklist**. It is proven continuously by **kube-bench `gke-1.6.0`** + **kubescape** (reused from k8s-hardening) + the free **GKE Security Posture** dashboard, gated in CI and drift-enforced by Config Sync on every cluster.

**What we must evolve (the standards to ratify):**

| # | Standard to ratify | Seed |
|---|---|---|
| S1 | **GKE profile of the FOP Hardening Standard** = CIS GKE L2 + the named GKE-native control set below | k8s-hardening + this table |
| S2 | **Node OS standard** for the GKE node image | Container-Optimized OS default; OS Hardening Standard only if Ubuntu image is forced |
| S3 | **Supply-chain standard** — Binary Authorization policy + cosign signing + attestations for FOP/Mgmt images | k8s-hardening Tier-3 image-signing stub |
| S4 | **Identity standard** — WIF-only (no SA keys), Workload Identity for pods, OIDC IdP for human access | k8s-hardening Tier-3 OIDC stub |
| S5 | **Conformance & drift gate** — kube-bench gke + kubescape + Security Posture, enforced in CI + Config Sync | k8s-hardening scan pipeline |

## Shared-responsibility split on managed GKE

| k8s-hardening tier | Self-managed (kubeadm) | Managed GKE | Our action |
|---|---|---|---|
| **Tier 1** — workload posture (PSS, NetworkPolicy, Kyverno, RBAC, SA automount) | Ours | **Ours** | **Reuse verbatim** via Config Sync |
| **Tier 2** — API server / KCM / scheduler / etcd / kubelet flags | Ours (Ansible+SSH) | **Google's** | N/A — no SSH; Google applies CIS 1.x–4.x baseline |
| **Tier 3** — cert rotation, secret re-encryption, OIDC, image signing | Manual | Mixed | Cert rotation = Google; **OIDC, image signing, KMS re-encrypt = ours** |
| **GKE-native** (beyond CIS) | n/a | **Ours** | **New** — express as Terraform flags + org policy |

This is exactly what the repo's [`SETUP-HYPERSCALER.md`](https://github.com/AI-Fabrik/k8s-hardening/blob/main/docs/SETUP-HYPERSCALER.md) states: on GKE, run `./harden.py all --skip-tier2`; Tier 1 + scans are the workload-posture evidence, the rest is provider-native.

## The control set (S1)

| Domain | Control | Mechanism | Source |
|---|---|---|---|
| **Identity** | Workload Identity (no node-SA cloud roles) | Terraform `workload_pool` | GKE-native [new] |
| | OIDC IdP for human kubectl | Connect Gateway / IdP | k8s-hardening Tier-3 [adapt] |
| | No downloadable SA keys | Org policy `iam.disableServiceAccountKeyCreation` | [new] |
| **Network** | Private nodes + private endpoint | Terraform `enable_private_nodes` | GKE-native [new] |
| | Master authorized networks | Terraform | GKE-native [new] |
| | Default-deny NetworkPolicy + Dataplane V2 | Config Sync (Tier-1 `01-default-deny-netpol.yaml`) + cluster flag | k8s-hardening [reuse] |
| **Workload** | PSS labels, Kyverno (no-privileged, no-hostPath, runAsNonRoot, drop-caps, no-priv-esc, ro-rootfs, seccomp, limits) | Config Sync (Tier-1 manifests + `kyverno-policies/`) | k8s-hardening [reuse] |
| | Default SA automount off | Config Sync (`02-disable-default-sa-automount.yaml`) | k8s-hardening [reuse] |
| **Nodes** | Shielded GKE Nodes (Secure Boot + vTPM + integrity monitoring) | Terraform | GKE-native [new] |
| | Confidential GKE Nodes (AMD SEV / Intel TDX) — **per node pool** | Terraform per-pool `confidential` flag | GKE-native [new] |
| | Container-Optimized OS node image | Terraform `image_type=COS_CONTAINERD` | [new] |
| **Secrets** | Application-layer secrets encryption (Cloud KMS CMEK) + re-encrypt existing | Terraform `database_encryption` + Tier-3 re-encrypt | GKE-native + k8s-hardening Tier-3 [new] |
| **Supply chain** | Binary Authorization (signed-image admission) | Terraform `binary_authorization` + policy | GKE-native [new] |
| | cosign image signing + attestations in CI | CI pipeline + Kyverno `verifyImages` | k8s-hardening Tier-3 stub [new] |
| **Audit** | Cloud Audit Logs (Admin + Data Access) | Terraform / org policy | GKE-native [new] |
| | API-server audit policy | Google-managed on GKE | N/A |
| **Conformance** | kube-bench `gke-1.6.0`, kubescape `cis-v1.10.0`, GKE Security Posture | CI job + dashboard | k8s-hardening [reuse + adapt benchmark] |

## Autopilot note

GKE **Autopilot enforces much of this by default** — Workload Identity on, metadata server restricted, privileged containers + hostPath blocked, COS-only, Google-hardened nodes ([Autopilot overview](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview)). It effectively bakes in the Tier-1 workload controls. The tradeoff (no DaemonSets-with-host-access, no custom node image, no SSH) is analyzed for cluster-mode choice in [03](03-day2-operations.md). Either way, the *standard* is the same; Autopilot just pre-satisfies more of it.

## Conformance gate (S5)

Run the k8s-hardening pipeline against every factory-built cluster in CI, with the GKE benchmark override:

- `scan/kube-bench-job.yaml` → `--benchmark gke-1.6.0`
- `harden.py all --skip-tier2` → baseline + Tier-1 apply + validate, emitting `delta.md` as audit evidence
- Add **GKE Security Posture** (free) for managed vuln + misconfig findings
- **Config Sync** enforces drift back to the Git baseline continuously — a config that drifts off-standard self-heals

## Decision: no unsigned images, no break-glass (D4)

**Decided** — Binary Authorization is **enforce-only with no break-glass exception**. Every image admitted to any factory cluster must carry a valid cosign signature/attestation; unsigned images are rejected, period — including in incidents.

- **Operational implication:** the "emergency" path is **sign-and-ship or roll back to a previously-signed image**, never "admit unsigned." This makes the CI signing pipeline a tier-0 dependency — it must be highly available, and a known-good signed image must always be re-deployable.
- **No `ALWAYS_ALLOW` admission rule, no per-namespace exemptions** for unsigned content. (Narrow allowlists for *signed* third-party base images are fine; the bar is "signed by a trusted attestor," not "unsigned but exempt.")
- Implemented via GKE-native Binary Authorization enforce mode + Kyverno `verifyImages` as defense-in-depth.

## Decision: CIS GKE L2 as the default floor (D2)

**Decided** — the module bakes in **CIS GKE Benchmark Level 2** as the hardening floor for every cluster. No looser-baseline consumer is known; all current consumers (FOP, Mgmt Plane) are security-sensitive infrastructure planes that can absorb L2 strictness. Per-workload exceptions are handled via explicit, audited Kyverno policy exceptions — not by lowering the cluster floor. If a future consumer genuinely needs L1, add it as an opt-down flag then.

## Decision: GKE-native controls all mandatory except Confidential nodes (D7)

**Decided** — within the CIS L2 floor (D2), the module makes **all GKE-native controls mandatory defaults**, with one exception:

| Control | Default |
|---|---|
| Private cluster (private nodes + private endpoint) + master authorized networks | **Mandatory** |
| Workload Identity (no node-SA cloud roles) | **Mandatory** |
| Shielded GKE Nodes (Secure Boot + vTPM + integrity monitoring) | **Mandatory** |
| Dataplane V2 + default-deny NetworkPolicy | **Mandatory** |
| Cloud KMS application-layer secrets encryption (CMEK) | **Mandatory** |
| Binary Authorization enforce (no break-glass, per [D4](#decision-no-unsigned-images-no-break-glass-d4)) | **Mandatory** |
| Cloud Audit Logs (Admin + Data Access) | **Mandatory** |
| Confidential GKE Nodes | **Per node pool by data class** (per [D1](#decision-mixed-sensitivity-node-pools-d1)) — the only non-blanket control |
| OIDC IdP for human kubectl access | **Mandatory** |
| No downloadable SA keys (org policy) | **Mandatory** |

The mandatory controls are not parameters a consumer can switch off; they are baked into the module. Confidential nodes are the sole per-pool toggle because they carry cost/perf overhead and are only warranted for sensitive data classes.

## Decision: mixed-sensitivity node pools (D1)

**Decided** — handle sensitive vs non-sensitive workloads with **mixed node pools in one cluster**, not separate clusters, for current needs. Revisit per-cluster separation only if a hard regulatory/tenancy boundary emerges.

- **Confidential GKE Nodes are enabled per node pool** (GA "mixed node pool" support): a confidential pool (AMD SEV / Intel TDX, memory encrypted in-use) + a standard pool share one control plane ([docs](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/confidential-gke-nodes), [GA announcement](https://cloud.google.com/blog/products/identity-security/announcing-general-availability-of-confidential-gke-nodes)).
- **Module shape:** a `node_pools` list where each pool carries `confidential: true|false` + taints/labels + machine type, replacing any cluster-wide confidential toggle.
- **Placement enforcement:** taint the confidential pool + matching toleration/nodeSelector on sensitive workloads; **Kyverno** policy rejects `data-class=sensitive` pods that don't target it (reuse k8s-hardening). Separate namespaces + NetworkPolicy + distinct Workload Identity SAs per class.
- **Accepted limit:** the **control plane is a shared trust boundary** — mixed pools give strong data-in-use isolation and lower ops overhead, but not the blast-radius/RBAC/upgrade separation of two clusters. Sufficient for now.

Sources: [AI-Fabrik/k8s-hardening](https://github.com/AI-Fabrik/k8s-hardening), [SETUP-HYPERSCALER.md](https://github.com/AI-Fabrik/k8s-hardening/blob/main/docs/SETUP-HYPERSCALER.md), [Autopilot overview](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview), [safer-cluster module](https://github.com/terraform-google-modules/terraform-google-kubernetes-engine/blob/main/modules/safer-cluster/README.md).
