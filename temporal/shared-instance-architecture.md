# Shared self-hosted Temporal: architecture and setup on GKE + Cloud SQL

## Executive Summary

Deploy Temporal Open Source Software (OSS) with the [official Helm chart](https://github.com/temporalio/helm-charts) — production-ready and breaking-change-stable since [chart v1.0.0, April 2026](https://temporal.io/blog/an-important-milestone-for-temporals-helm-charts) — into its own namespace on the existing Google Kubernetes Engine (GKE) cluster, backed by Cloud SQL for PostgreSQL (regional High Availability, HA). No Elasticsearch needed at the start: advanced visibility runs on PostgreSQL 12+ since server v1.20, with [Dual Visibility](https://docs.temporal.io/self-hosted-guide/visibility) as a zero-downtime escape hatch if List/query load outgrows it. Keep the Helm default `numHistoryShards: 512` — it is **immutable for the life of the cluster** and 512 is the accepted value for small production clusters. Expect a tuned Cloud SQL PostgreSQL backend to carry **low thousands of state transitions/sec** ([~4.5k in a 2025 community benchmark](https://piotrmucha.blog/2025/09/12/temporal-performance-tests/)); past that the path is a second cluster or Cassandra, not a bigger Postgres. Security is opt-in: the server ships with a no-op authorizer, so mutual TLS (mTLS) + JSON Web Token (JWT) claim-mapper authorization must be configured deliberately (details in [multi-tenancy-gaps.md](multi-tenancy-gaps.md)).

## Requirements

- Self-hosted Temporal OSS as a shared workflow engine for long-running, cross-system orchestration (e.g., bare-metal → OS provisioning via Rafay → Kubernetes cluster build).
- One Temporal cluster with per-team namespaces.
- Runs in Google Cloud on an existing GKE cluster; evaluate better options if any.
- PostgreSQL database backend, optimized for.
- Multiple teams deploy workflows independently; platform team owns the cluster.

## Assumptions Made

- Cloud SQL (not AlloyDB) is the PostgreSQL flavor — AlloyDB is not on Temporal's [tested-database list](https://docs.temporal.io/temporal-service/persistence) and the one [community attempt](https://community.temporal.io/t/alloydb-integration-with-temporal/16977) is unresolved.
- Initial scale is modest (tens of workflow types, not >5k sustained state transitions/sec) — provisioning-style workflows are long-running but low-throughput.
- Worker topology is an open item (covered in [multi-tenancy-gaps.md](multi-tenancy-gaps.md)).

## Deployment: Helm chart on the existing GKE cluster

**Use the official Helm chart.** It was historically "not for production", but [v1.0.0 (2026-04-08) changed that](https://temporal.io/blog/an-important-milestone-for-temporals-helm-charts): Temporal now commits to no breaking changes within the 1.x series, and the chart deploys **server components only** — all bundled databases (Cassandra, Elasticsearch, Prometheus, Grafana) were removed. You bring external persistence, which is exactly the Cloud SQL setup here. Latest: chart 1.5.0 pinning server v1.31.1 (June 2026).

The community [temporal-operator](https://github.com/alexandrevilain/temporal-operator) offers nice extras (declarative `TemporalNamespace` CRDs — Custom Resource Definitions, automatic mTLS via cert-manager) but its latest release supports server ≤1.28 while the server is at 1.31, and it is a single-maintainer project. Not recommended as the foundation; revisit for namespace CRDs only if it catches up.

**Where to run it.** Temporal publishes [no GCP-specific reference architecture](https://docs.temporal.io/self-hosted-guide); a Kubernetes namespace on the existing GKE Standard cluster is the community-default pattern and nothing about Temporal forces a dedicated cluster. All four services must share one Kubernetes cluster (the ringpop membership gossip needs flat pod networking, and `broadcastAddress` [must be an IP, not DNS](https://github.com/temporalio/temporal/issues/2630)). GKE Autopilot works but requires explicit resource requests on every service; Standard gives more control for a control-plane-like workload. Workers reach the frontend in-cluster via `temporal-frontend.<ns>:7233`; workers elsewhere need an internal passthrough Network Load Balancer or gRPC-capable ingress.

**Topology.** Four independently scalable services: frontend (API entry), history (event histories + shard locks — the heavy one), matching (task-queue dispatch), internal worker. Chart defaults are 1 replica each with no resources or Pod Disruption Budgets (PDBs) set — set all three. Starting point per [Temporal's scaling guide](https://temporal.io/blog/scaling-temporal-the-basics): 2+ replicas per service, history at 2 CPU / 8 GB per pod. A [community load test](https://piotrmucha.blog/2025/09/12/temporal-performance-tests/) reached ~4.5k transitions/sec at 6 frontend / 12 history / 6 matching — far above provisioning-workflow needs; 2/2/2/1 is a sane start.

**`numHistoryShards` — decide once.** The shard count is [set once and forever](https://docs.temporal.io/self-hosted-guide/production-checklist); changing it means a new cluster and migration. Too few → history lock contention; too many → memory overhead and database pressure. [512 is right for small production clusters](https://temporal.io/blog/scaling-temporal-the-basics) and matches both the Helm default and Cloud SQL-scale PostgreSQL. Load-test with [Omes](https://docs.temporal.io/self-hosted-guide/production-checklist) before go-live.

**GitOps gotchas:** schema jobs run as Helm hooks — set `useHelmHooks: false` under ArgoCD/Flux. Database credentials via `existingSecret` (External Secrets Operator); server v1.31+ adds [`passwordCommand`](https://github.com/temporalio/temporal/releases/tag/v1.31.0) enabling Cloud SQL IAM (Identity and Access Management) database authentication with short-lived credentials. gRPC health probes are incompatible with TLS on the frontend; the chart falls back to TCP probes.

## Persistence: Cloud SQL for PostgreSQL

Two databases on one instance: `temporal` (core) and `temporal_visibility`, plugin `postgres12`. Temporal [pre-release-tests PostgreSQL 13–16](https://docs.temporal.io/temporal-service/persistence).

- **Instance:** regional HA (synchronous replication — Temporal requires strong consistency; [async read replicas are useless to it](https://community.temporal.io/t/sql-replication-capability-for-temporal-postgres-db/4293/4)). Start ~4 vCPU / 16–32 GB.
- **Connections:** each service replica opens **two** pools (persistence + visibility); total = `maxConns` × pods × 2. Benchmarks routinely saturated Postgres' default `max_connections=100` — raise the Cloud SQL flag (500 in the [reference benchmark](https://piotrmucha.blog/2025/09/12/temporal-performance-tests/)) and set `maxConnLifetime` to bound stale connections.
- **Tuning that measurably mattered:** `shared_buffers` 2 GB + `effective_cache_size` 6 GB lifted throughput ~3.8k→4.5k transitions/sec; watch `history_node` table growth — throughput degrades as the working set outgrows cache.
- **Failover drill required:** the history service has been observed [not reconnecting cleanly after managed-database failover](https://community.temporal.io/t/history-service-cant-reconnect-after-rds-db-failover/6013) (RDS reports; same mechanism applies to Cloud SQL HA failover and maintenance windows). Reports are from older server versions — verify on 1.31 in staging.

**Visibility: PostgreSQL first, Elasticsearch later if needed.** Advanced visibility (custom search attributes, List filters) is GA on PostgreSQL 12+ since server v1.20. Docs [still recommend Elasticsearch for heavy production query load](https://docs.temporal.io/self-hosted-guide/visibility), and one team [hit PG visibility limits under load](https://medium.com/vymo-engineering/scaling-temporal-load-testing-with-postgres-cassandra-elasticsearch-monitoring-alerting-1176b7a4968b) — but for provisioning-scale workloads PG suffices, and **Dual Visibility** lets you add Elasticsearch as a secondary store later without downtime. Don't run Elasticsearch on day one.

## Security baseline

- **Default is wide open**: `noopAuthorizer` allows every request from anyone with network reach. Enable frontend mTLS (`requireClientAuth` + client CA) and internode mTLS per the [security guide](https://docs.temporal.io/self-hosted-guide/security). Since v1.20, internal calls fail the default claim mapper **unless mTLS is on** — enable both together.
- **AuthN/AuthZ**: OpenID Connect (OIDC) JWTs validated by the built-in claim mapper, which expects a `permissions: ["<namespace>:<role>"]` claim (roles: read/write/worker/admin). Google-issued tokens don't carry that claim → configure custom claims in the Identity Provider (IdP) or build a custom claim mapper (requires recompiling the server binary). Full treatment in [multi-tenancy-gaps.md](multi-tenancy-gaps.md).
- **Web UI**: bundled in the chart; OIDC login via `TEMPORAL_AUTH_ENABLED=true` + provider env vars. The UI forwards the user's token to the frontend, so per-namespace enforcement happens server-side.

## Upgrades, backup, DR

- **Sequential minor versions only** (v1.n → v1.n+1), schema before binary via `temporal-sql-tool`, ~10 min between steps for shard rebalancing ([upgrade guide](https://docs.temporal.io/self-hosted-guide/upgrade-server)). Older binaries on newer schema are supported → binary rollback is safe. One shared cluster = one org-wide maintenance train the platform team owns.
- **Backup = database backup.** No Temporal-native tool: Cloud SQL automated backups + Point-In-Time Recovery (PITR). Restore both databases to the same instant (same-instance PITR handles this); visibility is derived data but there is no official rebuild tool.
- **Multi-cluster replication is [explicitly experimental](https://docs.temporal.io/self-hosted-guide/multi-cluster-replication) in OSS** — do not bet DR on it. Rely on regional Cloud SQL HA + multi-zone GKE.

## Observability

Server emits Prometheus metrics (chart default port 9090; enable the ServiceMonitor). Key series — all tagged `namespace`, giving per-team slicing for free: `service_requests/errors/latency`, `persistence_*`, `workflow_success/failed/timeout/terminate`. [Health targets](https://temporal.io/blog/scaling-temporal-the-basics): shard lock latency <5 ms, poll sync rate ≥99%, schedule-to-start <150 ms. Start from the [official Grafana dashboards](https://github.com/temporalio/dashboards) (explicitly a baseline, not production-final). SDK-side metrics and per-team dashboards are covered in [oob-utilities-and-ecosystem.md](oob-utilities-and-ecosystem.md).

## When this architecture runs out

PostgreSQL scales vertically only. Signals to plan for a split: sustained >~5k state transitions/sec, shard-lock latency stuck high after tuning, Cloud SQL CPU >80%. The escape paths — in order of preference — are a second Temporal cluster (cell model, namespaces pinned to cells) or a Cassandra-backed rebuild (shards are immutable anyway, so it's a new cluster either way). Provisioning workflows are unlikely to get there; a metrics-driven review at ~50% of the benchmark ceiling is the cheap insurance.
