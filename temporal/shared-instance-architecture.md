# Setting up a shared self-hosted Temporal on GKE and Cloud SQL

## Executive Summary

The recommended setup: deploy Temporal with the [official Helm chart](https://github.com/temporalio/helm-charts) into its own namespace on our existing Google Kubernetes Engine (GKE) cluster, backed by a Cloud SQL for PostgreSQL instance in regional High Availability (HA) mode. Everything the chart installs is a stateless Kubernetes Deployment — **no persistent volumes anywhere in the cluster**; the only durable state lives in Cloud SQL. No Elasticsearch: PostgreSQL handles workflow search on its own at our scale, and there's a zero-downtime path to add Elasticsearch later if that ever changes. Two decisions deserve real care because they are hard or impossible to undo — the history shard count (`numHistoryShards: 512`, literally permanent) and security (Temporal ships with **no authentication at all**). A tuned PostgreSQL backend carries a few thousand workflow state transitions per second; provisioning workflows won't approach that.

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

## What actually runs in Kubernetes

Here is the exact inventory the [Helm chart](https://github.com/temporalio/helm-charts/tree/main/charts/temporal/templates) creates, because a common early question is "do I need persistent disks, StatefulSets, one pod or many?" The short answer: **everything is a plain Deployment, nothing is a StatefulSet, and no component asks for a PersistentVolumeClaim (PVC).**

| What | Kubernetes kind | Default replicas | Persistent disk? | Port |
|---|---|---|---|---|
| Frontend | Deployment | 1 | No | 7233 (gRPC) |
| History | Deployment | 1 | No | 7234 |
| Matching | Deployment | 1 | No | 7235 |
| Worker (internal) | Deployment | 1 | No | 7239 |
| Web UI | Deployment + Service | 1 | No | 8080 (HTTP) |
| Admin tools | Deployment | 1 | No | — |
| Frontend access | Service (ClusterIP) | — | — | 7233 |
| Membership discovery | Headless Service ×5 | — | — | gossip + 9090 metrics |
| Schema setup / upgrade | Job (Helm hook) | — | — | — |

A few things worth understanding rather than just reading off the table:

- **Every server service is a Deployment, and each defaults to one replica** ([template](https://raw.githubusercontent.com/temporalio/helm-charts/main/charts/temporal/templates/server-deployment.yaml)). One replica is fine for a demo and wrong for production — bump each to 2+ so a node drain or rolling update doesn't take the service down. They're Deployments, not StatefulSets, precisely because they hold no state: any pod can serve any request, and a killed pod just restarts.
- **No PVCs, because there's nothing local to persist.** The services mount only ConfigMaps. All durable data is in Cloud SQL. (This is new-ish: the pre-1.0 chart bundled Cassandra and Elasticsearch as StatefulSets *with* PVCs — those were the only stateful pieces, and [v1.0.0 removed them all](https://temporal.io/blog/an-important-milestone-for-temporals-helm-charts). The current chart creates zero StatefulSets and zero volumes.)
- **The Web UI is its own Deployment plus a Service on port 8080** — a stateless web app that talks to the frontend. Run it behind an internal load balancer with OIDC (details under security).
- **How the services find each other:** the chart creates a *headless* Service (one with no cluster IP) for each of the five services. That's what backs the gossip membership protocol (ringpop) the services use to discover peers and, for the history service, to agree on who owns which shard. You don't configure this — but it's why the pods must share one flat Kubernetes network.
- **Schema creation and upgrades are Kubernetes Jobs**, run as Helm pre-install/pre-upgrade hooks. They execute `temporal-sql-tool` against Cloud SQL to lay down and version the schema. (Under ArgoCD/Flux, disable the hook behavior — see Step 2.)

**The workers that run our workflow code are not in this table, and that's the most important point.** The chart deploys the *cluster*, never the workers. Each team packages its workflow and activity code into its own container and deploys it as an ordinary **stateless Deployment** — no PVC, replica count driven by how much work its task queues carry, scaling out with a HorizontalPodAutoscaler if needed. A worker holds nothing durable either; it crashes, restarts, re-polls, and Temporal replays its workflows from history. For safe rollouts of worker *versions*, Temporal offers the [temporal-worker-controller](https://github.com/temporalio/temporal-worker-controller) (a Kubernetes operator that runs old and new worker versions side by side) — covered in [oob-utilities-and-ecosystem.md](oob-utilities-and-ecosystem.md). Who owns and deploys these workers is the multi-team question in [multi-tenancy-gaps.md](multi-tenancy-gaps.md).

## Step 1 — where to run it

On the existing GKE cluster, in its own Kubernetes namespace. Temporal publishes [no Google-Cloud-specific guidance](https://docs.temporal.io/self-hosted-guide), and nothing about it demands a dedicated cluster — the services are ordinary stateless Deployments. A dedicated cluster would buy isolation at the cost of another cluster to operate; not worth it to start.

Two constraints to respect:

- **All the services must live in one Kubernetes cluster.** They find each other through the gossip protocol (ringpop) that needs flat pod-to-pod networking, and each member [must announce itself by IP address, not DNS name](https://github.com/temporalio/temporal/issues/2630). No stretching across clusters.
- **Workers connect through the frontend.** In-cluster workers use plain cluster DNS (`temporal-frontend.<ns>:7233`). If a team ever runs workers elsewhere, the frontend needs an internal load balancer that can carry gRPC.

GKE Autopilot works but insists on explicit resource requests everywhere; Standard mode gives more control for what is effectively a control plane. Plain VMs have no community momentum — Kubernetes is the well-trodden path.

## Step 2 — deploy with the official Helm chart

For years the official chart carried a "not for production" warning, which pushed people to community alternatives. That changed in April 2026: [chart v1.0.0](https://temporal.io/blog/an-important-milestone-for-temporals-helm-charts) is declared production-ready, with a no-breaking-changes promise across the 1.x series. The same release *removed* every bundled dependency — Cassandra, Elasticsearch, Prometheus, Grafana are gone. It now deploys the services and the Web UI and expects you to bring your own database. That matches our plan exactly.

What about the community [temporal-operator](https://github.com/alexandrevilain/temporal-operator)? It has attractive extras (declarative namespace resources, automatic certificate management), but its latest release supports Temporal server 1.28 while the server is at 1.31, and it is one person's project. Nice patterns to borrow, wrong foundation.

Chart defaults to fix before production: every service ships with **1 replica, no resource requests, and no Pod Disruption Budgets** — set all three (2 replicas per service is a fine start; give history pods the most memory). Three practical notes:

- Schema-migration Jobs run as Helm hooks. Under ArgoCD or Flux, set `schema.useHelmHooks: false` — GitOps tools can't tell an install from an upgrade.
- Feed database credentials via `existingSecret`. Better: server v1.31 added [`passwordCommand`](https://github.com/temporalio/temporal/releases/tag/v1.31.0), which fetches a fresh credential per connection — built for exactly the Cloud SQL IAM (Identity and Access Management) authentication case.
- With TLS on the frontend, Kubernetes gRPC health probes stop working; the chart falls back to TCP probes on its own.

## Step 3 — the database

Temporal wants **two logical databases**: `temporal` (the core — event histories, task queues, timers) and `temporal_visibility` (a searchable index of workflows, which powers "show me all failed workflows" queries). Both sit on one Cloud SQL instance. Temporal [tests against PostgreSQL 13–16](https://docs.temporal.io/temporal-service/persistence).

- **HA mode: regional.** Cloud SQL's regional HA replicates synchronously, which Temporal requires — it must read its own writes. Read replicas are async and [useless to Temporal](https://community.temporal.io/t/sql-replication-capability-for-temporal-postgres-db/4293/4); don't pay for them.
- **Watch the connection count.** Here's the trap: each service replica opens *two* pools (core + visibility), so total connections = `maxConns` × pods × 2. With 8 pods that blows past PostgreSQL's default `max_connections=100` easily. Raise the flag (a [community benchmark](https://piotrmucha.blog/2025/09/12/temporal-performance-tests/) used 500) and set `maxConnLifetime` so connections get recycled.
- **Two settings that measurably helped** in that same benchmark: `shared_buffers` 2 GB and `effective_cache_size` 6 GB lifted throughput from ~3.8k to ~4.5k state transitions/sec. Start around 4 vCPU / 16–32 GB.
- **Rehearse a failover.** There are reports of the history service [failing to reconnect after a managed-database failover](https://community.temporal.io/t/history-service-cant-reconnect-after-rds-db-failover/6013) until restarted. The reports are from older versions — but Cloud SQL maintenance windows force the same event, so drill it in staging before the first team onboards.

## The one number you cannot change: `numHistoryShards`

This is the setting most worth understanding, because your instinct about it is correct and the consequence is real.

**What a shard is.** Temporal splits all its bookkeeping into a fixed number of **history shards** — think of them as lanes. When a workflow starts, Temporal decides its lane by hashing the workflow's identity and taking the remainder modulo the shard count. Concretely, the server computes [`farmhash(namespaceID + "_" + workflowID) % numHistoryShards`](https://github.com/temporalio/temporal/blob/main/common/util.go) — plain modulo arithmetic. From then on, every event, timer, and state change for that workflow is handled by that one shard. Each shard is a **single-writer lane**: the history service processes its updates one at a time under a single lock, and each shard is owned by exactly one history pod at a time (the pods divide up the shards among themselves through the gossip ring, and hand them over when a pod joins or leaves). That single-writer design is how Temporal guarantees consistency without distributed locking.

**Why it's permanent — and yes, it's exactly what you suspected.** The lane assignment is `hash % shardCount`. Change the shard count and the modulo changes, so an existing workflow would now hash to a *different* lane than the one its data physically sits in. There is **no re-sharding tool** — nothing rebalances or re-indexes existing workflow data across a new lane count. Temporal staff [confirm the only remedy](https://community.temporal.io/t/numhistoryshards-modify/7585) is to stand up a brand-new cluster with the new shard count and route new workflows there while the old ones drain to completion. So the number is set once, at first startup, [for the life of the cluster](https://docs.temporal.io/temporal-service/temporal-server). Your mental model — "once data is sharded this way, there's no re-indexing if the shards change" — is precisely right; the mechanism is the modulo.

**Why not just pick a huge number, then?** Because shards aren't free in either direction:

- *Too few* and workflows queue behind each other's single-writer locks. With 4 shards (the dev default) a load test [took 28 minutes to drain 25,000 workflows](https://mikhail.io/2021/05/choose-the-number-of-shards-in-temporal-history-service/); Temporal says 4 [should never be used in production](https://community.temporal.io/t/numhistoryshards-modify/7585). A single shard tops out around 100 updates/sec at 10 ms database latency.
- *Too many* and each shard's in-memory context and task queues waste CPU and memory on the history pods and add database load. The same benchmark tried 32,768 shards and the history pod [ran out of memory and got evicted](https://mikhail.io/2021/05/choose-the-number-of-shards-in-temporal-history-service/).

**Why 512.** [Temporal recommends 512 for small production clusters](https://temporal.io/blog/scaling-temporal-the-basics) and notes even large clusters rarely exceed 4,096. A useful sizing anchor: start at roughly [one history pod per 500 shards](https://docs.temporal.io/temporal-service/temporal-server) and add pods as load grows — so 512 shards comfortably fits a cluster that starts with 1–2 history pods and has plenty of room to scale the pods up without ever touching the shard count. It's the Helm default, it fits Cloud-SQL-scale PostgreSQL, and it leaves the door open. Take 512, and load-test with [Omes](https://docs.temporal.io/self-hosted-guide/production-checklist) before go-live to confirm it against the real provisioning workload.

## Do we need Elasticsearch? Not at our scale — here's the real trade-off

Older guides insist on Elasticsearch for workflow search. That's dated: since [server v1.20 (Feb 2023)](https://github.com/temporalio/temporal/releases/tag/v1.20.0), full "advanced visibility" — custom search attributes, filtered `List`/`Count` queries, the UI's search box — [runs directly on PostgreSQL](https://docs.temporal.io/self-hosted-guide/visibility). It works by storing search attributes in indexed columns (generated from a JSON column, one indexed column per attribute), so most queries teams actually run — filter by type, status, a custom `cluster-id` — are ordinary indexed SQL. Since standard visibility was removed in v1.24, SQL is now the default non-Elasticsearch path, not a second-class one.

But it is honestly a **lesser capability than Elasticsearch, not an equal one.** Where PostgreSQL visibility is weaker:

- **Attribute caps.** PostgreSQL allows a fixed budget of custom search attributes *per namespace* — [10 Keyword, 3 each of Bool/Datetime/Double/Int/Text, 3 KeywordList](https://docs.temporal.io/search-attribute). Elasticsearch has no Temporal-imposed cap.
- **Per-namespace, not global.** SQL search attributes are scoped to one namespace; Elasticsearch attributes are global across all of them.
- **Weaker full-text.** Text fields fall back to the database's full-text index; Elasticsearch's analyzers are genuinely better at word search.
- **No horizontal scaling, and it shares the core database's I/O.** Heavy `List` query load competes with the workflow engine itself.

So Elasticsearch earns its keep at **high visibility-query load, many custom attributes, cross-namespace search, or serious full-text** — Temporal's own docs still [recommend it "for any setup that spawns more than a few Workflow Executions"](https://docs.temporal.io/self-hosted-guide/visibility) (a deliberately vague threshold; there's no published number).

For us it isn't worth it yet, for three reasons:

1. **Provisioning workflows are low-volume and low-query.** We're nowhere near the load where the core database strains under visibility queries.
2. **Operational cost is real.** Elasticsearch means a second stateful system — a StatefulSet with PVCs, Java Virtual Machine (JVM) heap tuning, shard/replica management, its own upgrades and monitoring — versus reusing the Cloud SQL we already run. That's the whole appeal of the SQL path.
3. **Adding it later is safe.** [Dual Visibility](https://docs.temporal.io/dual-visibility) lets Temporal write to two visibility stores at once. If PostgreSQL search ever becomes the bottleneck, we add Elasticsearch as a secondary store, dual-write until it's caught up, then flip reads over — no downtime, no migration event.

One licensing note if we ever do adopt it: Elasticsearch left Apache 2.0 in 2021 (SSPL / Elastic License) and [re-added an open-source AGPLv3 option in 2024](https://www.elastic.co/blog/elasticsearch-is-open-source-again) — running it internally is unrestricted under all of these. If license purity matters, Temporal also supports [OpenSearch 2+ (Apache 2.0) on server v1.30.1+](https://docs.temporal.io/self-hosted-guide/visibility), the permissive fork. Either way, not a day-one concern.

## Step 4 — lock the doors before anyone moves in

This surprises everyone: **a fresh Temporal cluster has no security whatsoever.** The default authorizer is a no-op — anyone who can open a connection to the frontend can read any team's workflow payloads, terminate anything, delete namespaces. Two layers to add, together:

1. **Mutual TLS (mTLS)** on the frontend (only holders of a client certificate can connect) and between the services. Note: since v1.20 the server's own internal calls fail authorization unless mTLS is on — so these two layers come as a pair.
2. **Authorization** — decide who can do what, per namespace.

On that second layer, there's a point worth correcting from earlier drafts: **turning on Temporal's built-in authorization is configuration, not a code change.** The server ships with a default authorizer and a default JSON Web Token (JWT) claim mapper; you enable them through the static config's `authorization` block, pointing `jwtKeyProvider` at your identity provider's public-key (JWKS) endpoint ([security guide](https://docs.temporal.io/self-hosted-guide/security)). The built-in mapper reads a `permissions` claim shaped like `["<namespace>:<role>"]` (roles: read / write / worker / admin) and enforces it. You only need to compile your own server binary if you want *custom* logic the default mapper can't express — e.g. deriving namespace access from Google Groups that don't already appear as that exact claim. That distinction (config vs. fork) and the identity-provider wiring are covered in [multi-tenancy-gaps.md](multi-tenancy-gaps.md).

Could a gateway do this instead? You can front the frontend with an API gateway (Envoy's external-authorization filter, for instance) that validates JWTs or mTLS on the gRPC connection, and Temporal's docs explicitly permit ["reverse proxies" or running unsecured inside a locked-down VPC](https://docs.temporal.io/self-hosted-guide/security). A gateway is a clean fit for *authentication* (is this caller who they say they are?). It's an awkward fit for Temporal's *authorization*, because the namespace lives inside the gRPC request body and the read/write/worker/admin distinction maps to specific gRPC methods — enforcing per-namespace RBAC at the gateway means teaching it to parse Temporal's protocol. The community standard is therefore the built-in authorizer (config for the common case, a fork for custom logic), optionally with a gateway in front for authentication and network edge. Recommendation: use the built-in authorizer; reach for a gateway only if we already run one as the standard ingress for gRPC services.

The Web UI ships in the chart and gets OIDC login via environment variables (`TEMPORAL_AUTH_ENABLED=true` + provider settings). It has no permissions of its own — it forwards the user's token to the frontend, so the server-side rules decide what each person sees. Configure one auth layer, both surfaces obey it.

## Upgrades and backup

- **Upgrades march one minor version at a time** (1.29 → 1.30 → 1.31 — [no skipping](https://docs.temporal.io/self-hosted-guide/upgrade-server)), schema migration before binaries, ~10 minutes between steps for shards to settle. Newer schema under older binaries is supported, so rolling *back* a binary is safe. One shared cluster means one org-wide maintenance train — the platform team drives it, every team rides it.
- **Backup is just database backup.** Temporal has no backup tool of its own; Cloud SQL automated backups plus Point-In-Time Recovery (PITR) are the story. Restore both logical databases to the same instant — same-instance PITR does that naturally.
- **Don't plan DR around multi-cluster replication.** It exists in OSS but is [explicitly experimental](https://docs.temporal.io/self-hosted-guide/multi-cluster-replication). Regional Cloud SQL HA plus multi-zone GKE is the honest disaster-recovery posture.

## Knowing it's healthy

The services expose Prometheus metrics (enable the chart's ServiceMonitor), and nearly every metric carries a `namespace` label — per-team visibility comes free. Three numbers tell you the cluster is happy, per [Temporal's own guide](https://temporal.io/blog/scaling-temporal-the-basics): shard lock latency under 5 ms, task poll success rate ≥ 99%, schedule-to-start latency under 150 ms. Start from the [official Grafana dashboards](https://github.com/temporalio/dashboards) and adapt.

## How much can it take? Benchmarks and sizing

Temporal measures load in **state transitions per second** — one state transition is one unit of workflow progress written durably to the database. It's the right yardstick because it normalizes across simple and complex workflows (unlike raw "workflows/sec"), and because the database is almost always the bottleneck, it maps closely to database write load. (Temporal Cloud instead meters "actions per second"; ignore that for self-hosted sizing.)

There is **no published benchmark of Temporal on GKE with Cloud SQL specifically** — a genuine gap, so the numbers below are the closest comparable public data points, with their setups so you can judge the fit:

| Source | Database & infra | numHistoryShards | Result | Bottleneck |
|---|---|---|---|---|
| [Temporal, "Scaling Temporal"](https://temporal.io/blog/scaling-temporal-the-basics) | MySQL 4 vCPU / 32 GB; 2 pods per service | 4 → 512 | **150 → 1,350 state transitions/sec** (config tuning alone) | History CPU, then polling config |
| [piotrmucha (2025)](https://piotrmucha.blog/2025/09/12/temporal-performance-tests/) | PostgreSQL 2 vCPU / 6 GB; 6 frontend / 12 history / 6 matching pods | 512 → 2,048 | **~1,000 → ~4,500 state transitions/sec** | PostgreSQL cache & disk I/O |
| [Community forum (2020)](https://community.temporal.io/t/running-temporal-postgres-benchmark/836) | PostgreSQL on AWS RDS `m5.large` → 4 vCPU/16 GB | 512 | **~16 workflows/sec, ~40–50 activities/sec** | `INSERT INTO history_node` |
| [Vymo (2025)](https://medium.com/vymo-engineering/scaling-temporal-load-testing-with-postgres-cassandra-elasticsearch-monitoring-alerting-1176b7a4968b) | PostgreSQL vs Cassandra | not stated | PostgreSQL **struggled past ~100 RPS**; moved to Cassandra (665→1,793 RPS at 8→32 cores) | PostgreSQL under bursty load |
| [PlanetScale (2022)](https://planetscale.com/blog/temporal-workflows-at-scale-sharding-in-production) | Vitess-sharded MySQL | not disclosed | **100k–180k database QPS** sustained (Black Friday / Cyber Monday) | (DB-layer metric, not directly comparable) |

Three takeaways for our sizing:

1. **A single tuned PostgreSQL instance comfortably delivers low-thousands of state transitions/sec** — the piotrmucha run hit ~4,500 on a modest instance. Provisioning workflows, which emit a handful of events over hours, generate a tiny fraction of that.
2. **The database is always the ceiling**, not the Temporal pods. Every PostgreSQL benchmark bottlenecked on database I/O, cache, connections, or shard-lock latency — never on frontend/history/matching CPU. So capacity planning is Cloud SQL sizing plus the connection-count math above.
3. **The known signals for "PostgreSQL is running out"** are sustained load approaching ~5k state transitions/sec, shard-lock latency stuck high after tuning, or Cloud SQL CPU above 80%. The 2025 Vymo report is the cautionary tale — untuned PostgreSQL fell over early under bursty load and they moved to Cassandra. Tuning (connections, `shared_buffers`) is what separates that from the ~4,500 result on similar hardware.

## When this design runs out

PostgreSQL only scales up, not out. If the signals above appear, the answer is a **second Temporal cluster** with teams pinned to one or the other (the "cell" pattern big operators use) — not a heroic single cluster. Since the shard count is immutable anyway, any rebuild is a new cluster regardless. Provisioning workflows will not get near this; a quarterly glance at the utilization dashboard is all the insurance needed.
