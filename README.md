# research

This repository holds the research work on various topics, organized by **area**. Each subdirectory is a research area containing one or more topic reports.

Almost all the research work and the bytes written are by LLMs, predominantly Claude and may be other models from time to time.

Reports are written in Markdown.

## Areas

| Link | Description |
|---|---|
| [gpu-infra](gpu-infra/) | GPU infrastructure: NVIDIA Blackwell reference architectures, scale-out fabrics, K8s operator stack, multi-tenant inference platforms. |
| [host-net-config](host-net-config/) | Declarative host network configuration: Netbox-driven intent rendered to Netplan + cloud-init for B300 and non-GPU hosts. |
| [iac-k8s](iac-k8s/) | Reusable cluster factory: Terraform + Config Sync + ArgoCD tooling to build any hardened HA GKE cluster (FOP/Rafay, Mgmt Plane as reference consumers), the GKE security standard (aligned to k8s-hardening), and automated Day-2 version/OS lifecycle. |
| [k8s-fed](k8s-fed/) | Open source Kubernetes federation technologies for a 50+ edge inference platform. |
| [mgmt-plane-setup](mgmt-plane-setup/) | Production management plane on managed K8s: AWS EKS vs GCP GKE cost and architecture comparison (multi-region HA, SOC 2, Cloudflare ingress). |
