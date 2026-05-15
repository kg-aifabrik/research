# AWS EKS vs GCP GKE — Production Management Plane

## Table of Contents
- [Executive Summary](#executive-summary)
- [Requirements](#requirements)
- [Assumptions Made](#assumptions-made)
- [Architecture](#architecture)
- [Kubernetes Layer](#kubernetes-layer)
- [PostgreSQL](#postgresql)
- [Networking](#networking)
- [Security & Compliance](#security--compliance)
- [Observability](#observability)
- [Disaster Recovery](#disaster-recovery)
- [Cost Breakdown](#cost-breakdown)

---

## Executive Summary

| Dimension | AWS — Amazon EKS | GCP — Google GKE Standard |
|:---|:---|:---|
| Managed Kubernetes (K8s) | Amazon EKS | Google GKE Standard |
| PostgreSQL (PG) | RDS for PostgreSQL Multi-AZ | Cloud SQL for PostgreSQL HA |
| Load balancer | Application LB — regional | Cloud HTTPS LB — global anycast |
| Pod IAM | IRSA / EKS Pod Identity (addon) | Workload Identity (native) |
| K8s threat detection | GuardDuty EKS Runtime (+cost) | GKE Security Posture (free) |
| Binary Authorization | Kyverno / ECR signing (manual setup) | Binary Authorization (native, free) |
| NAT topology | Per-AZ — 3 NAT GWs per region | Per-region — 1 Cloud NAT per region |
| Monthly cost — on-demand | **~$7,990** | **~$7,750** |
| Monthly cost — 1-year committed | **~$5,470** | **~$5,280** |

**Prefer GCP (GKE Standard)** over AWS (EKS) because: (1) GCP is ~$240/mo cheaper on-demand and ~$190/mo cheaper at 1-year commitments — driven entirely by networking: regional Cloud NAT saves $133/mo and the global HTTPS LB saves $98/mo; (2) GKE ships stronger K8s security defaults at no extra cost — Binary Authorization, Workload Identity, and GKE Security Posture are free and cover the key SOC 2 Type II supply-chain and threat-detection controls that on EKS require paid services (GuardDuty EKS Runtime) or manual integration (Kyverno); (3) GCP's global HTTPS LB uses a single anycast virtual IP (VIP), making multi-region active/passive failover a backend swap rather than a DNS record change. AWS has the advantage of a larger ops-talent pool, broader third-party tooling, and more mature SOC 2 audit evidence libraries — if your team is already AWS-fluent, the talent argument may outweigh the cost and security-defaults edge.

---

## Requirements

- Management plane governing 50+ remote sites; deployed in a single cloud (this report compares AWS vs GCP to support the choice)
- Managed K8s: Amazon EKS or GKE Standard on a private cluster (no public API endpoint)
- Application workloads: 50 vCPU / 200 GB RAM per region
- Managed PostgreSQL (PG) HA: RDS for PG Multi-AZ or Cloud SQL for PG HA
- Multi-region active/passive disaster recovery (DR): warm standby, **RPO ≤ 5 min, RTO ≤ 30 min**
- Mixed exposure: public services (customer REST APIs + web console) fronted by Cloudflare; internal-only services accessible only from corporate network
- Cloudflare fronts all public ingress: Web Application Firewall (WAF), Transport Layer Security (TLS), DDoS, CDN
- Internal network access via site-to-site Internet Protocol Security (IPsec) VPN
- Compliance: SOC 2 Type II — encryption at rest and in transit, audit logging, access controls
- Staff Single Sign-On (SSO) via Okta: kubectl OIDC, Grafana, web console
- Observability: self-hosted Prometheus + Grafana + Loki in-cluster
- Site telemetry: ~50 sites × ~50 GB/mo ≈ 2.5 TB/mo log ingestion
- Production only; costs quoted at US list price, on-demand and 1-year committed

---

## Assumptions Made

| # | Assumption | Confirmed? |
|:--|:---|:---:|
| 1 | Platform add-ons (Prometheus, Loki, Grafana, ArgoCD, cert-manager, External Secrets Operator, Ingress) consume ~9 vCPU / 30 GB; combined cluster requirement ~59 vCPU / 230 GB per region | ✓ |
| 2 | 5 × m6i.4xlarge (16 vCPU, 64 GB) on AWS / 5 × n2-standard-16 on GCP per region provides ~68 vCPU / 272 GB effective after K8s system overhead (~10–15%) | ✓ |
| 3 | PostgreSQL sized at 8 vCPU / 32 GB / 500 GB SSD — management-plane metadata only; no per-site bulk data | ⚠️ size not confirmed |
| 4 | Log retention: Loki 30 days in object store; metrics 90 days via Thanos to S3/GCS | ⚠️ not confirmed |
| 5 | Regions: AWS = `us-east-1` (primary) + `us-west-2` (standby); GCP = `us-central1` (primary) + `us-west1` (standby) | ⚠️ not confirmed |
| 6 | Standby cluster runs full-size warm (5 nodes, workloads at `minReplicas: 1`); meets RTO ≤ 30 min | ✓ |
| 7 | Async cross-region PG replication; WAL lag < 30 s under normal load satisfies RPO ≤ 5 min | ⚠️ sync replication eliminates risk but adds cross-region write latency (~50–80 ms RTT) |
| 8 | Cloudflare Tunnel (cloudflared daemon-set in-cluster) — cloud load balancer (LB) is not publicly reachable | ✓ |
| 9 | CI/CD: GitHub Actions builds container images → ECR / Artifact Registry; ArgoCD GitOps deploys to clusters | ⚠️ not confirmed |
| 10 | ~200 GB/mo outbound origin egress from cluster to Cloudflare; ~20 GB/mo cross-region PG WAL | ⚠️ estimate |
| 11 | All prices US list price, May 2026; Savings Plans / Committed Use Discounts (CUDs) shown separately | ✓ |

---

## Architecture

```
Internet
    │
    ▼
Cloudflare  (WAF · DDoS · CDN · TLS termination)
    │  Cloudflare Tunnel  ─  cloudflared DaemonSet in-cluster
    ▼
External LB  ──  public subnet, port 443
    │  (AWS ALB / GCP HTTPS LB)
    ▼
Ingress Controller  (NGINX / GKE Gateway API)
    ├── /api/*   →  API microservices (K8s pods)
    └── /*       →  Web console (K8s pods)

Corporate network  ──  IPsec VPN  ──  VPN Gateway
                                          │
                                          ▼
                              Internal LB  (private subnet)
                                          │
                                          ▼
                                  Internal microservices (K8s pods)

K8s pods  ──  private endpoint  ──  RDS / Cloud SQL (VPC-private)
K8s pods  ──  VPC endpoint      ──  Secrets Manager / Secret Manager
K8s pods  ──  Private Access    ──  S3 / GCS  (Loki chunks, Thanos, backups)
```

**Multi-region layout:**

```
Primary  (us-east-1 / us-central1)         Standby  (us-west-2 / us-west1)
┌──────────────────────────────────────┐    ┌──────────────────────────────────────┐
│  EKS / GKE Standard  ·  3 AZs       │    │  EKS / GKE Standard  ·  3 AZs (warm)│
│  5 nodes  ·  full replicas           │    │  5 nodes  ·  minReplicas: 1          │
│  RDS Multi-AZ / Cloud SQL HA         │───▶│  RDS Read Replica / SQL Read Replica │
│  External LB + Internal LB           │    │  External LB + Internal LB           │
│  NAT · VPN Gateway · ArgoCD          │    │  NAT · VPN Gateway · ArgoCD          │
└──────────────────────────────────────┘    └──────────────────────────────────────┘
            │  Cloudflare DNS / LB Pool
     Primary healthy  →  all traffic to primary
     Primary failing  →  promote DB replica  →  update Cloudflare pool  →  standby live
```

ArgoCD in both regions watches the same Git repo. Standby workloads stay applied at minimum replicas to keep nodes warm. Failover scales them up in minutes via a runbook or automated Cloudflare health-check trigger.

---

## Kubernetes Layer

| Feature | AWS EKS | GCP GKE Standard |
|:---|:---|:---|
| Private cluster | EKS private endpoint only | GKE private cluster (VPC-native) |
| Node autoscaling | [Karpenter](https://karpenter.sh/) (open-source) | Node Auto-Provisioning (built-in) |
| Pod identity / IAM | IRSA or EKS Pod Identity (managed addon) | Workload Identity (native binding) |
| Container Network Interface (CNI) | VPC CNI + Security Groups for Pods | GKE Dataplane V2 (eBPF, Cilium-based) |
| Container registry | ECR — $0.10/GB storage | Artifact Registry — $0.10/GB storage |
| Binary Authorization | Kyverno or OPA Gatekeeper + ECR signing | [Binary Authorization](https://cloud.google.com/binary-authorization) — native, free |
| K8s threat detection | [GuardDuty EKS Runtime](https://aws.amazon.com/guardduty/) (+cost, ~$0.35/vCPU/mo) | [GKE Security Posture](https://cloud.google.com/kubernetes-engine/docs/concepts/security-posture-dashboard) — free in Standard |
| kubectl auth (Okta) | EKS OIDC IdP → Okta app → K8s RBAC | OIDC kubeconfig → Okta app → K8s RBAC |
| GitOps (assumed) | ArgoCD (self-installed) | ArgoCD (self-installed) |

**On GuardDuty EKS cost:** Runtime Monitoring is priced per EC2 instance-hour in the cluster. For 10 nodes across both regions, expect ~$50–80/mo additional — not included in the cost table below but relevant if threat detection is a SOC 2 audit requirement. GKE Security Posture covers equivalent findings for free.

---

## PostgreSQL

| Dimension | AWS — RDS Multi-AZ | GCP — Cloud SQL HA (n1) |
|:---|:---|:---|
| Instance type | db.m6g.2xlarge (8 vCPU, 32 GB) | Custom 8 vCPU / 32 GB (n1 tier) |
| In-region HA | Sync standby in second AZ; auto-failover < 60 s | Sync failover replica; auto-failover < 60 s |
| Cross-region DR | Async read replica (us-west-2) | Async read replica (us-west1) |
| Primary HA instance cost | $1.272/hr × 730 = **$929/mo** | $1.109/hr × 730 = **$810/mo** |
| Primary storage (500 GB) | $0.230/GB-mo = **$115/mo** | $0.340/GB-mo = **$170/mo** |
| DR replica instance cost | $0.636/hr × 730 = **$464/mo** | $0.554/hr × 730 = **$405/mo** |
| DR replica storage (500 GB) | $0.115/GB-mo = **$58/mo** | $0.170/GB-mo = **$85/mo** |
| Misc (backups, I/O) | $9/mo | $9/mo |
| **Total PostgreSQL/mo** | **~$1,575** | **~$1,479** |
| Point-in-time recovery (PITR) | Yes — 5-min granularity | Yes — 1-min granularity |
| Logical replication | Yes | Yes |

Cloud SQL's per-GB storage is 48% more expensive than RDS in Multi-AZ mode, but the instance hourly rate is ~13% lower; Cloud SQL saves ~$96/mo overall. GCP Cloud SQL HA pricing is exactly 2× the base instance rate (primary + sync standby).

---

## Networking

| Component | AWS | GCP |
|:---|:---|:---|
| Public LB | ALB — regional, $0.0225/hr + LCUs | Cloud HTTPS LB — global anycast, $0.025/hr/region |
| Internal LB | Internal ALB (private subnet) | Internal HTTPS LB (private subnet) |
| LB total cost (2 regions) | ~$136/mo | ~$38/mo |
| NAT topology | 3 NAT GWs/region (one per AZ) | 1 Cloud NAT/region |
| NAT total cost (2 regions) | ~$206/mo | ~$73/mo |
| VPN | Site-to-Site VPN — $0.05/hr/connection | Cloud VPN — $0.05/hr/tunnel |
| VPN cost (2 connections) | $73/mo | $73/mo |
| PG private access | RDS in VPC (no endpoint charge) | Cloud SQL Private IP (no extra charge) |
| Secrets private access | VPC Endpoint — $0.01/hr/AZ | Private Service Connect (included) |

**Global LB vs regional ALB:** With GCP's global HTTPS LB, both regions share one anycast VIP. Cloudflare routes to the nearest healthy backend service; switching traffic to the standby region during DR is a backend group update (seconds, no TTL). With AWS ALBs, each region has its own VIP; DR requires a Cloudflare DNS record change or load-balancer pool swap — still fast given Cloudflare is the authoritative DNS, but architecturally more steps.

**NAT Gateway cost note:** AWS NAT Gateways are Availability Zone (AZ)-scoped; for HA you provision one per AZ. Three AZs × 2 regions = 6 gateways at $0.045/hr each ($197/mo fixed). GCP Cloud NAT is region-scoped; 1 gateway per region = $0.044/hr ($64/mo fixed). The $133/mo delta is entirely due to this topological difference.

---

## Security & Compliance (SOC 2 Type II)

| Control | AWS | GCP |
|:---|:---|:---|
| Encryption at rest | KMS CMK → EBS, RDS, S3 | Cloud KMS CMK → PD, Cloud SQL, GCS |
| Encryption in transit | TLS 1.3; enforced via SCP/policy | TLS 1.3; enforced by default |
| Secret management | Secrets Manager + External Secrets Operator | Secret Manager + External Secrets Operator |
| K8s audit logs | EKS audit → CloudWatch Logs | GKE audit → Cloud Logging |
| API/infra audit logs | [CloudTrail](https://aws.amazon.com/cloudtrail/) | [Cloud Audit Logs](https://cloud.google.com/logging/docs/audit) |
| Network visibility | VPC Flow Logs → CloudWatch / S3 | VPC Flow Logs → Cloud Logging |
| Audit log retention | 1 yr CloudWatch → S3 Glacier | 1 yr Cloud Logging → GCS |
| Image supply-chain | ECR image scanning + Kyverno admission | [Binary Authorization](https://cloud.google.com/binary-authorization) + Artifact Analysis |
| Runtime threat detection | GuardDuty EKS Runtime (+cost) | GKE Security Posture (free) |
| Secrets cost | $21/mo (50 secrets) | $4/mo (50 secrets) |
| KMS cost | $6/mo | $1/mo |

**Okta → kubectl setup (both clouds):**
1. Create an Okta OIDC app; capture issuer URL + client ID.
2. **AWS:** Register Okta as an EKS OIDC Identity Provider. Map Okta group claims to K8s `ClusterRoleBinding`. Okta users get `kubeconfig` entries that fetch short-lived tokens via `kubectl oidc-login` (kubelogin plugin).
3. **GCP:** Add `--oidc-issuer-url` and `--oidc-username-claim` to the kube-apiserver flags via GKE's OIDC config, or use Anthos Identity Service for a managed flow. Okta users similarly use kubelogin.

The Okta integration complexity is equivalent on both clouds.

---

## Observability

No cost differential between clouds for this layer — all components run in-cluster.

| Component | Configuration |
|:---|:---|
| Prometheus | 2 replicas/region, 200 GB PVC (14-day hot TSDB); [Thanos](https://thanos.io/) sidecar ships to S3/GCS for 90-day retention |
| Grafana | 2 replicas; Okta SAML SSO; dashboards managed via ArgoCD ConfigMaps |
| Loki | Distributed mode (ingester + querier + compactor); chunks to S3/GCS; BoltDB index on local PVC; 30-day retention |
| Alertmanager | Clustered, peered via mesh; routes to PagerDuty / Slack |
| Site telemetry ingest | Sites push logs via [Grafana Agent](https://grafana.com/docs/agent/latest/) or Vector over HTTPS through Cloudflare Tunnel → Loki; metrics via Prometheus remote-write → Prometheus |

Loki receives ~2.5 TB/mo raw logs; ~5:1 compression yields ~500 GB stored in object storage at steady state. S3 cost: ~$12/mo; GCS cost: ~$10/mo.

---

## Disaster Recovery

| Step | Action | Time |
|:---|:---|:---|
| 1. Detect | Cloudflare health monitor or external synthetic check fails on primary LB | < 1 min |
| 2. Promote DB | Promote cross-region read replica to standalone primary (RDS `promote-read-replica` / Cloud SQL promote replica) | ~2–5 min |
| 3. Scale workloads | Trigger ArgoCD sync with `replicas: N` or run `kubectl scale` in standby cluster | ~5–10 min |
| 4. Cut traffic | Update Cloudflare Load Balancing pool origins (or DNS A record) to standby LB VIP | ~1–2 min |
| 5. Validate | Automated smoke tests against standby API endpoint | ~5 min |
| **Total RTO** | | **~15–25 min ✓** |

**RPO detail:** Async WAL replication typically lags < 30 seconds under steady-state write load. Alert at `replica_lag > 3 min` to preserve the 5-min RPO buffer. Under a write spike (bulk import, migration), lag can exceed 5 min — schedule maintenance windows accordingly. Synchronous replication (Multi-AZ in the standby region itself, not cross-region) is not supported by either RDS or Cloud SQL cross-region; true RPO = 0 requires a distributed database (CockroachDB, AlloyDB Omni, Aurora Global with write-forwarding).

**Runbook automation:** Both AWS (Lambda + EventBridge) and GCP (Cloud Functions + Cloud Monitoring alerts) support automated DR runbook execution. Consider a dead-man's-switch approach: auto-promote only on confirmed primary unreachability, with human approval gate for the traffic cut to prevent split-brain.

---

## Cost Breakdown

All prices USD, US regions, May 2026 list price. Instance sizes: 5 × m6i.4xlarge (AWS) / 5 × n2-standard-16 (GCP) per region; PG: db.m6g.2xlarge / Cloud SQL n1 8 vCPU 32 GB.

### On-Demand Monthly

| Line item | AWS | GCP |
|:---|---:|---:|
| K8s nodes — primary (5 nodes) | $2,803 | $2,836 |
| K8s nodes — standby (5 nodes) | $2,803 | $2,836 |
| K8s control planes (×2 clusters) | $146 | $146 |
| Block storage — EBS gp3 / pd-balanced (root + PVCs) | $168 | $210 |
| Object storage — S3 / GCS (Loki, Thanos, backups) | $21 | $19 |
| PostgreSQL HA (primary) + cross-region replica | $1,575 | $1,479 |
| Load balancers ×4 (external + internal, both regions) | $136 | $38 |
| NAT gateway (6 AWS / 2 GCP, both regions) | $206 | $73 |
| VPN ×2 connections | $73 | $73 |
| KMS | $6 | $1 |
| Secrets Manager / Secret Manager (50 secrets) | $21 | $4 |
| Audit logging + VPC Flow Logs | $15 | $5 |
| Data egress (origin + cross-region replication) | $18 | $26 |
| **Total — on-demand** | **$7,991** | **$7,746** |

### 1-Year Committed

| | AWS | GCP |
|:---|---:|---:|
| Compute Savings Plan / CUD (~36–37% off nodes) | −$2,018 | −$2,099 |
| RDS Reserved / Cloud SQL CUD (~32–25% off PG) | −$504 | −$370 |
| **Total — 1-year committed** | **~$5,469** | **~$5,277** |

**Notes:**
- Cloudflare, Okta, and GitHub Actions costs are excluded — identical regardless of cloud choice. Expect ~$200–500/mo additional depending on plan tier and seat count.
- GuardDuty EKS Runtime Monitoring would add ~$50–80/mo to the AWS total if enabled (recommended for SOC 2); GKE Security Posture covers equivalent functionality for free.
- AWS Compute Savings Plans are flexible (any instance family in the region); RDS Reserved Instances are class-specific — lock in only after the instance size is stable.
- GCP CUDs are resource-based (vCPU + memory commitments), applied automatically to any matching VM in the region. Cloud SQL CUDs follow the same mechanic.
