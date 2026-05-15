# mgmt-plane-setup

Research on deploying a production-grade management plane that governs 50+ remote sites, covering managed Kubernetes, PostgreSQL HA, multi-region DR, security, and cost.

- **GCP (GKE Standard) is the recommended choice** over AWS (EKS) at this workload size — ~$240/mo cheaper on-demand ($7,750 vs $7,990) and ~$190/mo cheaper at 1-year committed pricing (~$5,280 vs ~$5,470), driven by GCP's regional Cloud NAT (saves $133/mo vs per-AZ AWS NAT Gateways) and cheaper global HTTPS LB ($38 vs $136/mo).
- **Security defaults favour GCP**: Binary Authorization, Workload Identity, and GKE Security Posture are free in GKE Standard; equivalent controls on EKS require paid add-ons (GuardDuty EKS Runtime ~$50–80/mo) or manual integration.
- **PostgreSQL costs are similar**: Cloud SQL HA (n1, 8 vCPU / 32 GB) is ~$96/mo cheaper than RDS Multi-AZ at this size despite higher per-GB storage pricing, because the hourly instance rate is lower.
- **Multi-region active/passive DR** (RPO ≤ 5 min, RTO ≤ 30 min) is achievable on both clouds via async cross-region read replica + warm standby cluster; async WAL lag is the main RPO risk and should be monitored with a 3-min alert threshold.
- **AWS advantage**: larger ops-talent pool, broader third-party tooling ecosystem, and more mature SOC 2 audit evidence libraries — relevant if the team is already AWS-fluent.

## Open threads

- Confirm PostgreSQL sizing (8 vCPU / 32 GB / 500 GB) against actual metadata volume from 50 sites.
- Confirm target regions (us-east-1/us-west-2 vs us-central1/us-west1) and any data-residency constraints.
- Confirm log/metrics retention windows (30d logs, 90d metrics assumed).
- Confirm CI/CD toolchain (GitHub Actions + ArgoCD assumed).
- Evaluate whether ~50 GB/site/month telemetry estimate is accurate — this is the largest swing factor on Loki storage cost.
- Decide whether async RPO ≤ 5 min is acceptable or whether synchronous cross-region replication is required (would change DB recommendation to Aurora Global or AlloyDB).
