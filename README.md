# research

This repository holds the research work on various topics, organized by **area**. Each subdirectory is a research area containing one or more topic reports.

Almost all the research work and the bytes written are by LLMs, predominantly Claude and may be other models from time to time.

Reports are written in Markdown.

## Areas

| Link | Description |
|---|---|
| [ceph-multus](ceph-multus/) | Local POC: multi-VLAN Kubernetes on one Apple-silicon Mac with Rook-Ceph block (RBD) + object (RGW/S3) storage over a dedicated storage VLAN; Cilium primary CNI + Multus macvlan secondaries. Built & verified end-to-end: block + object over the storage VLAN, scaled to 3 nodes with host-level replication. |
| [gpu-infra](gpu-infra/) | GPU infrastructure: NVIDIA Blackwell reference architectures, scale-out fabrics, K8s operator stack, multi-tenant inference platforms. |
| [host-net-config](host-net-config/) | Declarative host network configuration: Netbox-driven intent rendered to Netplan + cloud-init for B300 and non-GPU hosts. |
| [hw-acceptance](hw-acceptance/) | Hardware acceptance testing — burn-in tooling and pass/fail gates for incoming AMD CPU and NVIDIA HGX B300 servers; surveys neo-cloud practice and recommends an NVIDIA-open-source-first stack + runbook. |
| [iac-k8s](iac-k8s/) | Operator console to build and run hardened GKE clusters across dev/stage/prod × FOP/MGMT: Terraform + GitHub Actions + a custom console, ArgoCD closed-loop security, Connect Gateway access. Requirements, exploration/POC, end-to-end design, and console screens. |
| [k8s-fed](k8s-fed/) | Open source Kubernetes federation technologies for a 50+ edge inference platform. |
| [k8s-hardening](k8s-hardening/) | Securing on-prem kubeadm and GKE clusters to a common posture: layered threat model, a severity-ranked manual/automation control catalog with verified CVEs, and the kube-bench/kubescape measurement workflow. |
| [mgmt-plane-setup](mgmt-plane-setup/) | Production management plane on managed K8s: AWS EKS vs GCP GKE cost and architecture comparison (multi-region HA, SOC 2, Cloudflare ingress). |
| [temporal](temporal/) | Shared self-hosted Temporal on GKE + Cloud SQL PostgreSQL as a multi-team workflow engine: instance architecture, out-of-the-box/community tooling, and the platform build list for per-team namespaces. |
