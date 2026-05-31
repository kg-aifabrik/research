# GKE Day 2: Version Lifecycle & Host OS Management

Delivers **R6** (version lifecycle) and **R7** (host OS), and resolves the **Standard-vs-Autopilot** comparison (A5). Requirements & Assumptions canonical in [01](01-provisioning-and-iac.md#requirements).

## Executive Summary

Lifecycle is managed by **reusable upgrade profiles** — a parameter on the cluster module, not a per-cluster decision. Two profiles cover the current needs; new clusters pick one:

| Profile | Release channel | Cluster mode | Node image | Upgrade control | Example consumer |
|---|---|---|---|---|---|
| **`conservative`** | **Stable** (or Extended for tighter change control) | **Standard** | Container-Optimized OS (COS) | Maintenance window + exclusions; surge upgrade | FOP / Rafay Controller |
| **`balanced`** | **Regular** | **Standard** (Autopilot viable) | COS | Same | Management Plane |

**Mandatory security patching is automatic** via the release channel — GKE auto-upgrades the control plane (always) and node pools (auto-upgrade on, default in channels) to patched versions; you *cannot* opt out of security patches on a regional cluster, only *schedule* them. **Feature/minor-version upgrades are channel-gated** and deferrable: the **Extended channel** gives up to ~24 months on a minor version, auto-applying only same-minor patches ([release channels](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/release-channels)). **Host-OS management is near-zero** — COS is a Google-maintained, auto-patched, read-only-rootfs immutable image; you only inherit OS-patching burden if you force the **Ubuntu** node image or run standalone **GCE VMs** (then VM Manager + the OS Hardening Standard apply).

**Standard vs Autopilot verdict — the factory defaults to Standard, exposes Autopilot as a mode parameter, because:** (1) any consumer needing tenant isolation or host-access debugging (e.g. Rafay) requires node-level control Autopilot forbids (no SSH, no host-path DaemonSets); (2) Shielded/Confidential node-pool choices and custom node config are explicit under Standard; (3) it matches `mgmt-plane-setup`'s costing. Autopilot is *defensible for consumers that need nothing host-level* (less Day-2 node work, security-hardened by default), but its DaemonSet/host-access constraints can bite observability agents — so Standard is the default profile and Autopilot is opt-in per consumer.

## Release channels

| Channel | Lag after upstream | Auto-upgrades | Use for |
|---|---|---|---|
| Rapid | ~4–8 wks | minor + patch | never (prod) |
| Regular | ~8–12 wks | minor + patch | `balanced` profile |
| Stable | ~12–16 wks | minor + patch (high-priority) | `conservative` profile |
| Extended | older minors, ~24mo total support | **patch-only within minor** | `conservative` when minor-version churn must be frozen |

GKE gives ~24 months total support per minor (≈14mo standard + ≈10mo extended); after that, forced upgrade ([versioning & support](https://docs.cloud.google.com/kubernetes-engine/versioning)). **Version skew:** control plane upgrades first; node pools must stay within the supported skew of the control plane — GKE enforces and will not let nodes lag indefinitely.

## Controlling *when* upgrades land

- **Maintenance windows** — confine auto-upgrades to a weekly low-traffic window (Terraform `maintenance_policy`).
- **Maintenance exclusions** — freeze upgrades during change-freeze periods (launches, audits); three exclusion scopes (no upgrades / no minor / no minor-or-node). Cannot indefinitely block security patches.
- **Surge upgrades** — `max_surge` / `max_unavailable` per node pool; pair with **PodDisruptionBudgets** so Rafay/etcd-style workloads keep quorum.
- **Blue-green node upgrades** — for risk-sensitive pools, GKE can stand up the new pool, drain, and roll back fast on failure.
- **Rollout sequencing** — upgrade FOP and Mgmt clusters on staggered windows so a bad version is caught on one before the other.

## Mandatory vs optional — operational rule

- **Mandatory (security):** patch versions and end-of-support minor bumps. Strategy = let the channel auto-apply inside a maintenance window; never disable node auto-upgrade.
- **Optional (features):** moving to a newer minor early. Strategy = pin via channel choice; test in a non-prod cluster on Regular/Rapid before promoting FOP.

## Host OS management (R7)

| Surface | OS | Day-2 burden | Standard to apply |
|---|---|---|---|
| **GKE nodes (recommended)** | Container-Optimized OS | **Minimal** — Google auto-patches; immutable, read-only rootfs, locked-down | None beyond Shielded Nodes (S2) |
| GKE nodes (if forced) | Ubuntu node image | **You patch** — auto-upgrade rotates the image, but custom packages are your problem | OS Hardening Standard + node auto-upgrade |
| Standalone GCE VMs (bastion, tooling) | Ubuntu/COS | **You patch** | **VM Manager** OS patch management (scheduled patch deployments, patch compliance reporting) + OS Hardening Standard |

**Recommendation:** keep all GKE node pools on **COS** — it removes the OS patch treadmill and satisfies most of the OS hardening intent out of the box. Reserve the OS Hardening Standard + VM Manager for the few GCE VMs (if any) the FOP needs. This aligns the GKE-node OS story with the bare-metal OS Hardening Standard work without duplicating it.

## Day-2 recovery & scaling (cross-ref)

The objectives doc's *Remediation & recovery playbooks* (P1) for FOP components (Rafay Controller, head node, NetBox) build on this: maintenance windows + Config Sync drift-heal + Terraform re-apply give the idempotent recovery primitive; runbooks wrap them. Out of scope for this report — flagged in the [do-list](04-do-list.md).

Sources: [GKE release channels](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/release-channels), [GKE versioning & support](https://docs.cloud.google.com/kubernetes-engine/versioning), [choose cluster mode](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/choose-cluster-mode), [Autopilot overview](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview).
