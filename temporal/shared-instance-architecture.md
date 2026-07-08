# Setting up a shared self-hosted Temporal on GKE and Cloud SQL

A build guide for standing up one Temporal cluster on Google Kubernetes Engine (GKE), backed by Cloud SQL for PostgreSQL, to be shared by multiple engineering teams through per-team namespaces. It is written to be followed top to bottom: each layer builds on the one before it — database first, then the server, then the settings that are hard to change later, then visibility and security.

## Executive Summary

Build the stack in five layers:

1. **Database (Cloud SQL for PostgreSQL)** — the foundation and the capacity ceiling. Regional High Availability (HA), two databases on one instance, tuned connection and memory settings.
2. **Temporal server (official Helm chart, server v1.31.1)** — four stateless Deployments plus the Web UI; no persistent volumes. Feed database credentials with `passwordCommand` so nothing static is stored.
3. **`numHistoryShards` = 512** — set at first startup, permanent for the life of the cluster.
4. **Visibility on PostgreSQL** — no Elasticsearch; add it later only if query load demands it.
5. **Security** — mutual TLS plus Temporal's built-in role-based access control (RBAC), which is configuration, not a code change.

A single tuned PostgreSQL instance carries a few thousand workflow state transitions per second — far more than provisioning-style workflows generate.

## Requirements

- Self-hosted Temporal Open Source Software (OSS) as a shared workflow engine for long-running, cross-system orchestration (bare-metal → OS install via Rafay → Kubernetes cluster build).
- One Temporal cluster, one namespace per team.
- Runs on Google Cloud, on the existing GKE cluster.
- PostgreSQL as the database backend.
- Teams work independently; a platform team owns the cluster.

## Assumptions Made

- Cloud SQL, not AlloyDB (see footnote at the database layer).
- Modest scale: provisioning workflows run for hours but emit few events per second.
- Worker ownership and multi-team concerns are handled in [multi-tenancy-gaps.md](multi-tenancy-gaps.md).

## How the pieces fit

A Temporal cluster is **four stateless services plus one database**:

| Service | Job |
|---|---|
| Frontend | The API door. Every client and worker talks to it (gRPC, port 7233). |
| History | Holds each workflow's event history and drives its state forward. The heavyweight. |
| Matching | Runs the task queues — hands tasks to workers when they poll for work. |
| Worker (internal) | Runs Temporal's own housekeeping workflows, not application workflows. |

All durable state lives in the database. The four services hold nothing persistent — any pod can be killed and restarted without data loss. This is why capacity planning for Temporal is mostly database planning, and why the services themselves are easy to run on Kubernetes.

Application workflow code does not run in any of these. It runs in **workers** — separate processes each team deploys — that poll the cluster for tasks. The cluster is the bookkeeper; workers do the work. The Helm chart deploys the cluster, never the workers.

The whole cluster must live in one Kubernetes cluster: the services discover each other over a gossip protocol (ringpop) that needs flat pod-to-pod networking, and each member [announces itself by IP address, not DNS name](https://github.com/temporalio/temporal/issues/2630). Run it in its own Kubernetes namespace on the existing GKE Standard cluster.[^compute]

---

## Layer 1 — the database (Cloud SQL for PostgreSQL)

The database is the foundation and, in every published benchmark, the bottleneck. Provision it first and provision it well.

### Instance

- **Edition/tier:** Cloud SQL Enterprise.
  - **Development:** 4 vCPU, 8 GB RAM.
  - **Production:** 8 vCPU, 16 GB RAM to start. Scale vertically from here — the database saturates before the Temporal pods do.
- **Availability:** **Regional (HA).** Cloud SQL regional HA replicates synchronously, which Temporal requires because it must read its own writes. Do not add read replicas — they are asynchronous and [Temporal cannot use them](https://community.temporal.io/t/sql-replication-capability-for-temporal-postgres-db/4293/4) for correctness.
- **PostgreSQL version:** 16 (Temporal [tests against 13–16](https://docs.temporal.io/temporal-service/persistence)).
- **Connectivity:** private IP, reachable from the GKE cluster over VPC. (Alternatively the Cloud SQL Auth Proxy as a sidecar.)
- **Backups:** enable automated backups and Point-In-Time Recovery (PITR). This is the entire backup strategy — Temporal has no backup tool of its own.

### Two databases on the instance

Create both before installing Temporal:

- `temporal` — core: event histories, task queues, timers, mutable state.
- `temporal_visibility` — the searchable index that powers workflow list/filter queries.

The Helm chart's schema Jobs populate both (see Layer 2).

### PostgreSQL flags to set

Set these as Cloud SQL database flags. The values are drawn from the community benchmark below and scaled to a 16 GB production instance:

- **`max_connections = 500`** — the default of 100 is exhausted quickly (see connection math). This is the single most common cause of a stalled cluster.
- **`shared_buffers ≈ 25% of RAM`** — 4 GB on a 16 GB instance.
- **`effective_cache_size ≈ 75% of RAM`** — 12 GB on a 16 GB instance. Pairing this with `shared_buffers` is what lifted throughput most in the benchmark.
- **`work_mem = 32 MB`** — per-sort working memory for visibility queries.
- **`maintenance_work_mem = 512 MB – 1 GB`** — faster index maintenance and vacuuming as the `history_node` table grows.

Scale `shared_buffers` and `effective_cache_size` with RAM whenever the instance is resized; leave the rest.

### Temporal-side connection pool

These are set in the Temporal datastore configuration (Helm values), not in Cloud SQL:

- **`maxConns`** — connections per pool per service instance. Keep it modest and do the math below.
- **`maxIdleConns`** — usually equal to `maxConns`.
- **`maxConnLifetime = 1h`** — recycles connections so stale ones don't survive a Cloud SQL maintenance restart or HA failover. Setting this is what prevents the "history service won't reconnect after failover" failure mode seen on managed databases.

**Connection math — the part that bites:** each server pod opens **two** pools (one for `temporal`, one for `temporal_visibility`). Total connections ≈ `maxConns × (number of server pods) × 2`. With ~8 server pods and `maxConns = 25`, that is ~400 connections against the 500 ceiling. Size `maxConns` down, or `max_connections` up, so the product stays comfortably under the ceiling.

### Where these numbers come from

A [September 2025 community benchmark](https://piotrmucha.blog/2025/09/12/temporal-performance-tests/) ([deployment detail](https://piotrmucha.blog/2025/09/12/temporal-deployment/)) tuned exactly these settings on a PostgreSQL instance and reached **~4,500 workflow state transitions per second**. Its tuning: `max_connections` 100→500, `shared_buffers` 2 GB, `effective_cache_size` 6 GB, `work_mem` 32 MB, `maintenance_work_mem` 512 MB. It identified the database's cache and disk I/O as the ceiling — adding Temporal pods past that point changed nothing. An 8 vCPU / 16 GB production instance gives headroom above that result.

> **Other options (passed on):** AlloyDB[^alloydb], Cassandra[^cassandra].

---

## Layer 2 — deploy the Temporal server (Helm chart, v1.31.1)

With the database ready, deploy the server with the [official Helm chart](https://github.com/temporalio/helm-charts). As of the v1.0.0 chart line (April 2026) it is production-ready with a no-breaking-changes commitment across the 1.x series, and it installs **only** server components — no bundled databases. Deploy chart 1.x, which pins **Temporal server v1.31.1** (the current stable release).[^operator]

### Feed database credentials with `passwordCommand`

Server v1.31 added [`passwordCommand`](https://github.com/temporalio/temporal/releases/tag/v1.31.0) for SQL datastores: instead of a static password, Temporal runs a command to fetch a fresh credential for each new connection. This is the right fit for Cloud SQL — enable **Cloud SQL IAM database authentication**, run Temporal's Kubernetes service account as a workload-identity-bound IAM principal, and have `passwordCommand` mint a short-lived access token per connection. No database password is stored in a Secret, and credentials rotate automatically. Use this rather than a static `existingSecret` password.

### What the chart creates

Every component is a stateless Deployment. There are **no StatefulSets and no PersistentVolumeClaims** — all durable state is in Cloud SQL.

| Component | Kubernetes kind | Default replicas | Persistent disk? | Port |
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

The headless Services back the ringpop gossip membership; the schema Jobs run `temporal-sql-tool` against Cloud SQL as Helm pre-install/pre-upgrade hooks. The application workers that run team workflow code are not created by the chart — each team deploys its own stateless worker Deployment that dials the frontend on 7233.

### Settings to change from the defaults

- **Replicas:** raise every service from 1 to **2 or more** so a node drain or rolling update never takes a service down. History pods carry the most load — give them the most CPU and memory.
- **Pod Disruption Budgets:** the chart exposes them per service but leaves them empty; set them (requires replicas > 1).
- **Resources:** the chart sets no requests/limits; set them. A reasonable start: frontend 1.5–2 vCPU / 4 GiB, history 2–4 vCPU / 8 GiB, matching 1 vCPU / 2 GiB, worker 0.5–1 vCPU / 1 GiB.
- **GitOps:** set `schema.useHelmHooks: false` under ArgoCD or Flux — those tools cannot distinguish an install from an upgrade, which breaks the hook Jobs.
- **TLS probes:** with mutual TLS on the frontend, gRPC health probes stop working; the chart falls back to TCP probes automatically.

---

## Layer 3 — set `numHistoryShards` to 512 (permanent)

`numHistoryShards` is fixed at first startup and cannot be changed for the life of the cluster. Set it to **512** and understand why it is permanent before deploying, because the only way to change it later is to build a new cluster.

**What a shard is.** Temporal splits all of its bookkeeping into a fixed number of history shards — parallel lanes. When a workflow starts, its lane is chosen by [`farmhash(namespaceID + "_" + workflowID) % numHistoryShards`](https://github.com/temporalio/temporal/blob/main/common/util.go) — plain modulo arithmetic. Every event, timer, and state change for that workflow is then handled by that one shard. Each shard is a single-writer lane processed under one lock and owned by exactly one history pod at a time; the pods divide the shards among themselves through the gossip ring and hand them over as pods join or leave. This single-writer design is how Temporal keeps state consistent without distributed locking.

**Why it is permanent.** The lane assignment is `hash % shardCount`. Change the count and the modulo changes, so an existing workflow now hashes to a different lane than the one its data physically occupies. No tool re-shards or re-indexes existing data across a new lane count. Temporal staff [confirm](https://community.temporal.io/t/numhistoryshards-modify/7585) the only remedy is a new cluster with the new count, routing new workflows there while old ones drain.

**Why 512.** Too few shards serialize workflows behind each other's locks — 4 shards (the development default) [must never be used in production](https://community.temporal.io/t/numhistoryshards-modify/7585). Too many waste CPU and memory per shard on the history pods and add database load — a benchmark that tried 32,768 shards [ran the history pod out of memory](https://mikhail.io/2021/05/choose-the-number-of-shards-in-temporal-history-service/). [Temporal recommends 512 for small production clusters](https://temporal.io/blog/scaling-temporal-the-basics); even large clusters rarely exceed 4,096. Starting from roughly [one history pod per 500 shards](https://docs.temporal.io/temporal-service/temporal-server), 512 fits a cluster that begins with 1–2 history pods and has room to scale the pods up without ever touching the shard count. Load-test with [Omes](https://docs.temporal.io/self-hosted-guide/production-checklist) against the real workload before go-live to confirm.

---

## Layer 4 — visibility on PostgreSQL (skip Elasticsearch)

"Visibility" is the searchable index of workflow executions — the UI's search box, and every `List`/`Count` query with custom search attributes. Since [server v1.20](https://github.com/temporalio/temporal/releases/tag/v1.20.0) this runs directly on PostgreSQL (search attributes stored in indexed columns), so no Elasticsearch is needed. Run visibility on the `temporal_visibility` database created in Layer 1.

PostgreSQL visibility is a genuinely smaller capability than Elasticsearch, and that is an acceptable trade at this scale:

- **Attribute caps:** PostgreSQL allows a fixed budget of custom search attributes per namespace — [10 Keyword, 3 each of Bool/Datetime/Double/Int/Text, 3 KeywordList](https://docs.temporal.io/search-attribute). Elasticsearch has no such cap.
- **Per-namespace scope:** SQL search attributes belong to one namespace; Elasticsearch's are global.
- **Weaker full-text**, and visibility queries share the core database's I/O.

Elasticsearch earns its operational cost — a second stateful system with its own volumes, Java heap tuning, and upgrades — only at [high query load or large attribute needs](https://docs.temporal.io/self-hosted-guide/visibility). It is not warranted for provisioning-scale workloads. If it ever becomes necessary, [Dual Visibility](https://docs.temporal.io/dual-visibility) adds it with no downtime: write to both stores, let the new one catch up, then switch reads over.[^elasticsearch]

---

## Layer 5 — security (mutual TLS + built-in RBAC)

A fresh Temporal cluster has **no authentication**: anyone who can reach the frontend can read any team's payloads, terminate workflows, or delete namespaces. Add two layers, together:

**1. Mutual TLS (mTLS).** Enable it on the frontend (only holders of a client certificate connect) and between the services. Since v1.20, the server's own internal calls fail authorization unless mTLS is on, so these are enabled as a pair.

**2. Authorization — configuration, not a code change.** The server ships with a default authorizer and default JSON Web Token (JWT) claim mapper. Enable them in the static config's `authorization` block: set `authorizer: "default"`, `claimMapper: "default"`, and point `jwtKeyProvider.keySourceURIs` at the identity provider's public-key (JWKS) endpoint. The built-in authorizer enforces read/write/worker/admin roles per API call, per namespace, with no custom code. A server rebuild is required only for *custom* claim logic — when the identity provider cannot emit the expected `permissions` claim of `["<namespace>:<role>"]` strings. Wiring the identity provider and per-namespace RBAC is covered in [multi-tenancy-gaps.md](multi-tenancy-gaps.md).[^gateway]

**Web UI.** The chart includes the UI; enable OpenID Connect (OIDC) login with `TEMPORAL_AUTH_ENABLED=true` plus provider settings. The UI has no permissions of its own — it forwards the user's token to the frontend, so the server-side rules decide what each person sees. Configure authorization once; both the API and the UI obey it.

---

## Operating the cluster

- **Upgrades** move one minor version at a time (1.30 → 1.31 → 1.32 — [no skipping](https://docs.temporal.io/self-hosted-guide/upgrade-server)), schema migration before binaries, ~10 minutes between steps for shards to settle. Newer schema under older binaries is supported, so a binary rollback is safe. One shared cluster means one org-wide upgrade train the platform team drives.
- **Backup** is Cloud SQL automated backups plus PITR (Layer 1). Restore both databases to the same instant — same-instance PITR does this naturally.
- **Disaster recovery** rests on regional Cloud SQL HA plus multi-zone GKE. Multi-cluster replication exists in OSS but is [explicitly experimental](https://docs.temporal.io/self-hosted-guide/multi-cluster-replication) — do not depend on it.
- **Health.** The services expose Prometheus metrics (enable the chart's ServiceMonitor); nearly every metric carries a `namespace` label, giving per-team visibility for free. The three signals that say the cluster is healthy, per [Temporal's guide](https://temporal.io/blog/scaling-temporal-the-basics): shard lock latency under 5 ms, poll success rate ≥ 99%, schedule-to-start latency under 150 ms. Start from the [official Grafana dashboards](https://github.com/temporalio/dashboards).

## Capacity and benchmarks

Temporal measures load in **state transitions per second** — one unit of workflow progress written durably to the database. It normalizes across simple and complex workflows and maps closely to database write load, which is the ceiling in every case.

No benchmark of Temporal on GKE with Cloud SQL is published, so the closest comparable public data points are below with their setups:

| Source | Database & infra | Shards | Result | Bottleneck |
|---|---|---|---|---|
| [Temporal, "Scaling Temporal"](https://temporal.io/blog/scaling-temporal-the-basics) | MySQL 4 vCPU / 32 GB; 2 pods per service | 4 → 512 | **150 → 1,350** transitions/sec (config tuning alone) | History CPU, then polling config |
| [piotrmucha (2025)](https://piotrmucha.blog/2025/09/12/temporal-performance-tests/) | PostgreSQL 2 vCPU / 6 GB; 6 frontend / 12 history / 6 matching | 512 → 2,048 | **~1,000 → ~4,500** transitions/sec | PostgreSQL cache & disk I/O |
| [Community forum (2020)](https://community.temporal.io/t/running-temporal-postgres-benchmark/836) | PostgreSQL on AWS RDS `m5.large` → 4 vCPU/16 GB | 512 | **~16 workflows/sec, ~40–50 activities/sec** | `INSERT INTO history_node` |
| [Vymo (2025)](https://medium.com/vymo-engineering/scaling-temporal-load-testing-with-postgres-cassandra-elasticsearch-monitoring-alerting-1176b7a4968b) | PostgreSQL vs Cassandra | n/s | PostgreSQL **struggled past ~100 RPS**; Cassandra scaled 665→1,793 RPS | Untuned PostgreSQL under bursty load |

Takeaways: a single tuned PostgreSQL instance comfortably delivers low-thousands of state transitions/sec; the database is always the ceiling, not the Temporal pods; and the signals that PostgreSQL is running out are sustained load nearing ~5k transitions/sec, shard-lock latency stuck high after tuning, or Cloud SQL CPU above 80%. The Vymo result is the cautionary tale — untuned PostgreSQL fell over early, so apply the Layer 1 tuning and load-test before go-live.

## Scaling out

PostgreSQL scales up, not out. When the signals above appear, the path is a **second Temporal cluster** with teams pinned to one or the other (the "cell" pattern) — not a heroic single cluster. Because the shard count is immutable anyway, any expansion is a new cluster regardless. Provisioning workflows will not reach this; a quarterly review of the utilization dashboard is sufficient insurance.

---

[^compute]: **GKE Autopilot** — works, but requires explicit resource requests on every pod and gives less control over node pools for a control-plane workload; Standard is the better fit. **Plain VMs / GCE** — no community momentum; Kubernetes is the documented path.

[^alloydb]: **AlloyDB** — PostgreSQL-wire-compatible but not on Temporal's [tested-database list](https://docs.temporal.io/temporal-service/persistence); the one [community attempt](https://community.temporal.io/t/alloydb-integration-with-temporal/16977) was unresolved. Its columnar analytics engine does not help Temporal's write-heavy OLTP pattern. Cloud SQL is the proven choice.

[^cassandra]: **Cassandra** — the horizontal-scale backend for very high throughput (Temporal supports it), but it adds a distributed database to operate and is unnecessary below several thousand state transitions/sec. It becomes relevant only if a single large PostgreSQL instance saturates.

[^operator]: **temporal-operator** (community Kubernetes operator) — offers declarative namespace and certificate management, but its latest release supports server 1.28 while the server is at 1.31, and it is a single-maintainer project; good patterns to borrow, wrong foundation. **Community Terraform modules / chart forks** — predate the chart's v1.0.0 stabilization; no advantage over the official chart now.

[^elasticsearch]: If Elasticsearch is ever adopted: it left Apache 2.0 in 2021 (SSPL / Elastic License) and [re-added an open-source AGPLv3 option in 2024](https://www.elastic.co/blog/elasticsearch-is-open-source-again); running it internally is unrestricted under all of these. For a permissive alternative, Temporal supports [OpenSearch 2+ (Apache 2.0) on server v1.30.1+](https://docs.temporal.io/self-hosted-guide/visibility).

[^gateway]: **API gateway in front** — a gateway (e.g. Envoy) can validate JWTs or mTLS for authentication, and Temporal permits [reverse proxies](https://docs.temporal.io/self-hosted-guide/security). It is a poor fit for *authorization*: the namespace lives inside the gRPC request body and roles map to specific gRPC methods, so per-namespace RBAC at the gateway means deserializing Temporal's protocol and re-implementing its permission map. Use the built-in authorizer; add a gateway only for the network edge.
