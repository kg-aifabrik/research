# Setting up a shared self-hosted Temporal on GKE and Cloud SQL

## Executive Summary

The recommended setup: deploy Temporal with the [official Helm chart](https://github.com/temporalio/helm-charts) into its own namespace on our existing Google Kubernetes Engine (GKE) cluster, backed by a Cloud SQL for PostgreSQL instance running in regional High Availability (HA) mode. No Elasticsearch — PostgreSQL handles workflow search on its own at our scale. Two decisions deserve real care because they are hard or impossible to undo: the history shard count (`numHistoryShards: 512` — literally permanent), and the security setup (Temporal ships with **no authentication at all**; anyone who can reach it can do anything). A tuned Cloud SQL backend carries a few thousand workflow state transitions per second — orders of magnitude more than provisioning workflows will ever generate.

## Requirements

- Self-hosted Temporal Open Source Software (OSS) as a shared workflow engine for long-running, cross-system orchestration (bare-metal → OS install via Rafay → Kubernetes cluster build).
- One Temporal cluster, one namespace per team.
- Runs on Google Cloud, preferably the existing GKE cluster; flag better options if they exist.
- PostgreSQL as the database backend.
- Teams work independently; a platform team owns the cluster.

## Assumptions Made

- Cloud SQL, not AlloyDB. AlloyDB speaks the PostgreSQL protocol but is not on Temporal's [tested-database list](https://docs.temporal.io/temporal-service/persistence), and the one [community attempt](https://community.temporal.io/t/alloydb-integration-with-temporal/16977) ended unresolved. Cloud SQL is the boring, proven choice.
- Modest scale: provisioning workflows run for hours but generate few events per second. We are nowhere near Temporal's limits.
- Worker topology is handled separately in [multi-tenancy-gaps.md](multi-tenancy-gaps.md).

## What a Temporal cluster actually is

Before the setup steps, it helps to know what we are deploying. A Temporal cluster is **four stateless services plus one database**:

| Service | Job |
|---|---|
| Frontend | The API door. Every client and worker talks to it (gRPC, port 7233). |
| History | Keeps each workflow's event history and drives its state forward. The heavyweight. |
| Matching | Runs the task queues — hands tasks to workers when they ask for work. |
| Worker (internal) | Runs Temporal's own housekeeping workflows. Not our workers. |

The key fact: **all state lives in the database.** The four services hold nothing durable — kill any pod and nothing is lost. This is why almost every capacity question about Temporal is really a question about the database, and why the services themselves are easy to run on Kubernetes.

Our workflow code never runs inside any of this. It runs in **workers** — plain processes each team deploys — which poll the cluster for tasks. The cluster is the bookkeeper; workers do the work.

## Step 1 — where to run it

On the existing GKE cluster, in its own Kubernetes namespace. Temporal publishes [no Google-Cloud-specific guidance](https://docs.temporal.io/self-hosted-guide), and nothing about it demands a dedicated cluster — the four services are ordinary stateless deployments. A dedicated cluster would buy isolation at the cost of another cluster to operate; not worth it to start.

Two constraints to respect:

- **All four services must live in one Kubernetes cluster.** They find each other through a gossip protocol (ringpop) that needs flat pod-to-pod networking, and each member [must announce itself by IP address, not DNS name](https://github.com/temporalio/temporal/issues/2630). No stretching across clusters.
- **Workers connect through the frontend.** In-cluster workers use plain cluster DNS (`temporal-frontend.<ns>:7233`). If a team ever runs workers elsewhere, the frontend needs an internal load balancer that can carry gRPC.

GKE Autopilot works but insists on explicit resource requests everywhere; Standard mode gives more control for what is effectively a control plane. Plain VMs have no community momentum — Kubernetes is the well-trodden path.

## Step 2 — deploy with the official Helm chart

For years the official chart carried a "not for production" warning, which pushed people to community alternatives. That changed in April 2026: [chart v1.0.0](https://temporal.io/blog/an-important-milestone-for-temporals-helm-charts) is declared production-ready, with a no-breaking-changes promise across the 1.x series. The same release *removed* every bundled dependency — Cassandra, Elasticsearch, Prometheus, Grafana are gone from the chart. It now deploys the four services and the Web UI, and expects you to bring your own database. That matches our plan exactly.

What about the community [temporal-operator](https://github.com/alexandrevilain/temporal-operator)? It has attractive extras (declarative namespace resources, automatic certificate management), but its latest release supports Temporal server 1.28 while the server is at 1.31, and it is one person's project. Nice patterns to borrow, wrong foundation.

Chart defaults to fix before production: every service ships with **1 replica, no resource requests, and no Pod Disruption Budgets** — set all three (2 replicas per service is a fine start; give history pods the most memory). Three practical notes:

- Schema-migration jobs run as Helm hooks. Under ArgoCD or Flux, set `useHelmHooks: false` — GitOps tools can't tell an install from an upgrade.
- Feed database credentials via `existingSecret`. Better: server v1.31 added [`passwordCommand`](https://github.com/temporalio/temporal/releases/tag/v1.31.0), which fetches a fresh credential per connection — built for exactly the Cloud SQL IAM (Identity and Access Management) authentication case.
- With TLS on the frontend, Kubernetes gRPC health probes stop working; the chart falls back to TCP probes on its own.

## Step 3 — the database

Temporal wants **two logical databases**: `temporal` (the core — event histories, task queues, timers) and `temporal_visibility` (a searchable index of workflows, which powers "show me all failed workflows" queries). Both sit on one Cloud SQL instance. Temporal [tests against PostgreSQL 13–16](https://docs.temporal.io/temporal-service/persistence).

- **HA mode: regional.** Cloud SQL's regional HA replicates synchronously, which Temporal requires — it must read its own writes. Read replicas are async and [useless to Temporal](https://community.temporal.io/t/sql-replication-capability-for-temporal-postgres-db/4293/4); don't pay for them.
- **Watch the connection count.** Here's the trap: each service replica opens *two* pools (core + visibility), so total connections = `maxConns` × pods × 2. With 8 pods that blows past PostgreSQL's default `max_connections=100` easily. Raise the flag (a [community benchmark](https://piotrmucha.blog/2025/09/12/temporal-performance-tests/) used 500) and set `maxConnLifetime` so connections get recycled.
- **Two settings that measurably helped** in that same benchmark: `shared_buffers` 2 GB and `effective_cache_size` 6 GB lifted throughput from ~3.8k to ~4.5k state transitions/sec. Start around 4 vCPU / 16–32 GB.
- **Rehearse a failover.** There are reports of the history service [failing to reconnect after a managed-database failover](https://community.temporal.io/t/history-service-cant-reconnect-after-rds-db-failover/6013) until restarted. The reports are from older versions — but Cloud SQL maintenance windows force the same event, so drill it in staging before the first team onboards.

## The one number you cannot change: `numHistoryShards`

Temporal splits its workflow bookkeeping across a fixed number of **history shards**, set on first startup and [never changeable again](https://docs.temporal.io/self-hosted-guide/production-checklist) — not without standing up a brand-new cluster and migrating. Too few shards and workflows queue up behind each other's locks; too many and each one wastes memory and database capacity.

There's no need to agonize: [512 is the accepted value for small production clusters](https://temporal.io/blog/scaling-temporal-the-basics), it's the Helm default, and it matches Cloud-SQL-scale PostgreSQL (clusters rarely justify more than 4,096 even at large scale). Take 512, and load-test with [Omes](https://docs.temporal.io/self-hosted-guide/production-checklist) (Temporal's load generator) before go-live to confirm.

## Do we need Elasticsearch? No — and here's the escape hatch

Older guides insist on Elasticsearch for workflow search. That's dated: since server v1.20, full search — custom attributes, filtered listing — [runs on PostgreSQL 12+](https://docs.temporal.io/self-hosted-guide/visibility). The docs still nudge heavy users toward Elasticsearch, and one team [did outgrow PostgreSQL search under load](https://medium.com/vymo-engineering/scaling-temporal-load-testing-with-postgres-cassandra-elasticsearch-monitoring-alerting-1176b7a4968b) — but that was at throughput we won't approach.

The reason to be relaxed about it: **Dual Visibility**. Temporal can write the search index to two stores at once, so if PostgreSQL search ever becomes the bottleneck, we add Elasticsearch as a secondary store, let it catch up, and promote it — no downtime, no migration event. Skipping Elasticsearch on day one is not a bet we can lose.

## Step 4 — lock the doors before anyone moves in

This surprises everyone: **a fresh Temporal cluster has no security whatsoever.** The default authorizer is a no-op — anyone who can open a connection to the frontend can read any team's workflow payloads, terminate anything, delete namespaces. Two layers to add, together:

1. **Mutual TLS (mTLS)** on the frontend (only holders of a client certificate can connect) and between the services. Note: since v1.20 the server's own internal calls fail authorization unless mTLS is on — so these two layers come as a pair, not à la carte.
2. **Authorization** — OpenID Connect (OIDC) tokens checked by a claim mapper. The built-in one expects a `permissions: ["<namespace>:<role>"]` claim that Google tokens don't naturally carry. Solving that is platform work, covered in [multi-tenancy-gaps.md](multi-tenancy-gaps.md).

The Web UI ships in the chart and gets OIDC login via environment variables (`TEMPORAL_AUTH_ENABLED=true` + provider settings). It has no permissions of its own — it forwards the user's token to the frontend, so the server-side rules decide what each person sees. Configure one auth layer, both surfaces obey it.

## Upgrades and backup

- **Upgrades march one minor version at a time** (1.29 → 1.30 → 1.31 — [no skipping](https://docs.temporal.io/self-hosted-guide/upgrade-server)), schema migration before binaries, ~10 minutes between steps for shards to settle. Newer schema under older binaries is supported, so rolling *back* a binary is safe. One shared cluster means one org-wide maintenance train — the platform team drives it, every team rides it.
- **Backup is just database backup.** Temporal has no backup tool of its own; Cloud SQL automated backups plus Point-In-Time Recovery (PITR) are the story. Restore both logical databases to the same instant — same-instance PITR does that naturally.
- **Don't plan DR around multi-cluster replication.** It exists in OSS but is [explicitly experimental](https://docs.temporal.io/self-hosted-guide/multi-cluster-replication). Regional Cloud SQL HA plus multi-zone GKE is the honest disaster-recovery posture.

## Knowing it's healthy

The services expose Prometheus metrics (enable the chart's ServiceMonitor), and nearly every metric carries a `namespace` label — per-team visibility comes free. Three numbers tell you the cluster is happy, per [Temporal's own guide](https://temporal.io/blog/scaling-temporal-the-basics): shard lock latency under 5 ms, task poll success rate ≥ 99%, schedule-to-start latency under 150 ms. Start from the [official Grafana dashboards](https://github.com/temporalio/dashboards) and adapt.

## When this design runs out

PostgreSQL only scales up, not out. If sustained load approaches ~5k state transitions/sec, or shard-lock latency stays high after tuning, or Cloud SQL CPU lives above 80%, the answer is a **second Temporal cluster** with teams pinned to one or the other (the "cell" pattern big operators use) — not a heroic single cluster. Since the shard count is immutable anyway, any rebuild is a new cluster regardless. Provisioning workflows will not get near this; a quarterly glance at the utilization dashboard is all the insurance needed.
