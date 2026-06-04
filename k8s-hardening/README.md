# k8s-hardening

Securing two Kubernetes worlds — self-managed on-prem `kubeadm` and managed Google Kubernetes Engine (GKE) — to a common, verifiable posture.

- **[REPORT.md](REPORT.md)** is the threat model and operator's narrative: four layers (empty clusters → GKE-vs-on-prem defaults → tenants/network/storage → workloads/runtime), each ending with exact check commands. It explains the *why* and surfaces the open bake-offs (admission engine, supply chain, runtime detection, L7 egress, node OS).
- **[controls-catalog.md](controls-catalog.md)** is the consolidated, severity-ranked control catalog: **Manual** vs **Automation** controls, each tagged Common / GKE-only / on-prem-only, with the exposure it closes and a verified CVE + CVSS score where one maps. It also documents the kube-bench + kubescape measurement tooling and the provision → baseline → manual → delta → automation → hardened workflow.
- **Shared-responsibility split:** on GKE, Google owns the control plane / node OS / kubelet baseline (we *verify* via scans); we own the workload-policy layer, identity, supply chain and audit destination. On-prem we own everything, applied via `harden.py` tier-2 Ansible. The workload-policy layer (Pod Security, NetworkPolicy, Kyverno, RBAC) is identical in both worlds.
- **Implementation** lives in the companion repo [`kg-aifabrik/k8s-hardening`](https://github.com/kg-aifabrik/k8s-hardening) (orchestrator `harden.py`, tier-1 manifests, tier-2 Ansible, scanners, workload harness); GKE provisioning in [`iac-gke-poc`](https://github.com/kg-aifabrik/iac-gke-poc) and the factory design in [`../iac-k8s/`](../iac-k8s/). The highest-severity exposures map to real CVEs — unauthenticated control plane ([CVE-2018-1002105](https://nvd.nist.gov/vuln/detail/CVE-2018-1002105), 9.8) and ingress RCE ([CVE-2025-1974](https://nvd.nist.gov/vuln/detail/CVE-2025-1974), 9.8).
- **Reality check:** the CIS benchmark score (kube-bench 46.9→58.5%, kubescape 39.7→49.2% on a 3-node test cluster) is a regression signal, not a safety proof — several top exposures barely move it. Read deltas with the checklist, not instead of it.

**Open threads / next session:**

- The measurement flow is two-point (baseline → hardened); the catalog's workflow calls for a **third post-manual measurement** and an operator-facing manual-controls checklist derived into `k8s-hardening/docs/` — captured in a pending implementation plan.
- Bake-offs still unresolved: admission engine (Kyverno vs GKE Policy Controller vs OPA Gatekeeper), supply-chain enforcement (Binary Authorization vs Kyverno `verifyImages`), runtime detection (Falco vs Tetragon), on-prem node OS (Talos/Flatcar vs conventional), CNI/L7 egress (Cilium vs Calico + mesh), on-prem KMS v2 provider, and encrypted storage (Rook-Ceph vs Longhorn).
- Scope is **GKE + on-prem `kubeadm` only**.
