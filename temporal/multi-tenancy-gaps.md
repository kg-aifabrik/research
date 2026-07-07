# What the platform team must build for multi-team Temporal

## Executive Summary

Namespaces give logical isolation only — task queues, workflow IDs, retention, rate-limit boundaries, access-control scope — while all teams share the same frontend/history/matching services and the same PostgreSQL instance. Everything that makes the shared instance *safe* and *self-service* is platform work:

| Capability | Status in OSS | Platform work |
|---|---|---|
| Namespace provisioning | CLI/gRPC only; no official Terraform | **Build**: onboarding automation (namespace + quotas + dashboards + auth) |
| Per-team quotas / noisy-neighbor limits | Dynamic-config keys exist, per-namespace, no wildcards | **Configure + template** per team |
| Authentication / authorization | Pluggable, default = wide open | **Build**: OIDC + claim mapping; custom mapper means recompiling the server |
| Worker deploy golden path | Worker Versioning + worker-controller GA | **Assemble**: chassis library + CI template + replay gate |
| Payload encryption / codec server | Samples only | **Build**: central codec service, per-namespace keys |
| Cost attribution | Namespace-tagged metrics | **Build** (thin): showback dashboard |
| Cross-team calls | Nexus (GA) | **Govern**: endpoint registry conventions |

On the open worker-topology question: **commit to per-team workers now.** Temporal's design binds one worker to one namespace ([deliberately, to prevent cross-namespace starvation](https://community.temporal.io/t/sharing-activity-workers-across-namespaces/9921)), so a "common worker pool" across per-team namespaces would mean one deployment running every team's code — coupled deploys, shared blast radius — and no published platform (Netflix, Datadog) does it. The good news: worker/task-queue layout is cheap to change later; **namespace layout is not** (no supported migration of running workflows between namespaces). Spend the design care on namespace granularity, and give teams a platform-provided worker chassis instead of a shared pool.

## Requirements

- Identify what must be built (vs configured vs free) for multiple teams to use one self-hosted Temporal cluster (GKE — Google Kubernetes Engine, Cloud SQL PostgreSQL, per-team namespaces) independently.
- Resolve the open item: common worker pool first vs per-team workers — and whether committing early matters.

## Assumptions Made

- O(5–20) teams, not thousands of namespaces — the per-team-namespace model is well inside Temporal's guidance at this scale.
- Teams own their workflow code and worker deployments; the platform team owns cluster, database, auth, and shared services.
- An OIDC (OpenID Connect) Identity Provider with custom-claim support is available (Google Workspace/Identity Platform).

## Worker topology: the open item, resolved

Facts that settle it:

- **One worker instance serves exactly one namespace.** Maxim Fateev (Temporal co-founder): workers can't span namespaces because "one namespace could get starved for workers by another" ([forum](https://community.temporal.io/t/sharing-activity-workers-across-namespaces/9921)). With per-team namespaces, a shared pool degenerates to one process hosting N per-namespace workers containing all teams' code — dependency conflicts, one team's OOM kills everyone's pollers, every deploy is everyone's deploy.
- **No published multi-team platform shares worker processes across teams.** [Netflix](https://community.temporal.io/t/automating-temporal-a-full-view-of-the-netflix-temporal-platform/13624) (namespace operator, mTLS, SDK shims — teams run their own workers) and [Datadog](https://opensource.datadoghq.com/projects/temporal/) (built the [temporal-worker-controller](https://github.com/temporalio/temporal-worker-controller), which models per-service worker deployments) both converge on per-team workers on a paved road.
- **Switching worker layout later is cheap; switching namespace layout is not.** Moving activities/workflows to different task queues [needs no versioning](https://community.temporal.io/t/clarity-on-task-queue-and-worker-segregation-patterns/4429) — queue names aren't replay-validated. But running workflows [cannot move between namespaces](https://community.temporal.io/t/switch-workflow-execution-to-another-namespace-task-queue/5627) and there's [no supported history migration](https://community.temporal.io/t/migrate-a-namespace-between-servers-and-namespace/18497) — a wrong namespace split means drain-and-restart.

**Recommendation:** per-team worker deployments from day one, built on a **platform chassis**: a base image + small init library per language (Netflix's "SDK shim" pattern) that wires mTLS, metrics, tracing, the encryption data converter, and standard interceptors; deployed via a CI template using the worker-controller. The "shared" part of the vision lives in the chassis and golden path, not in shared processes. Where a genuinely common capability is needed (e.g., a platform-owned "provision bare-metal via Rafay" service), expose it as a **Nexus endpoint** from a platform namespace rather than putting platform code in team workers.

## Noisy neighbors: quotas to set per team

One loaded namespace [can degrade others](https://community.temporal.io/t/noisy-neighbor-namespace/18728) — the shared surfaces are frontend RPS (requests per second), persistence QPS (queries per second), and history shards. OSS mitigations are [dynamic-config keys](https://docs.temporal.io/references/dynamic-configuration), settable per namespace via `constraints` blocks:

- `frontend.namespaceRPS` (default 2400/instance), `frontend.globalNamespaceRPS`; poller cap `frontend.namespaceCount` (default 1200).
- `frontend/history/matching.persistenceNamespaceMaxQPS` — the knob that actually protects Cloud SQL.
- Size guardrails: `limit.blobSize.*` (512 KB warn / 2 MB error), `limit.historySize.*` (10/50 MB), `limit.historyCount.*` (10k/51k events).

Two catches: per-namespace overrides [must enumerate namespaces explicitly — no wildcards](https://github.com/temporalio/temporal/issues/6237), so onboarding must template the dynamic-config file; and exact key names drift between 1.2x/1.3x releases — verify against [constants.go](https://github.com/temporalio/temporal/blob/main/common/dynamicconfig/constants.go) for the deployed version.

[Task Queue Priority & Fairness](https://docs.temporal.io/develop/task-queue-priority-fairness) (GA [May 2026](https://temporal.io/changelog/priority-fairness-generally-available)) adds priorities (1–5) and weighted fairness keys — but *within one task queue*, so with per-team namespaces it's a within-team tool (e.g., prioritizing urgent re-provisions over bulk builds), not the cross-team isolation mechanism.

## AuthN/AuthZ: the largest single build

- OSS default is **no auth**: anyone with network access can read histories, terminate workflows, delete namespaces. The [pluggable model](https://docs.temporal.io/self-hosted-guide/security) is `ClaimMapper` (JWT — JSON Web Token → claims) + `Authorizer` (per-API allow/deny).
- The built-in JWT mapper expects `permissions: ["<namespace>:<role>"]` (read/write/worker/admin). Google's tokens don't carry it → either mint custom claims in the IdP (group-to-namespace mapping) or write a custom claim mapper — which requires [compiling your own server binary](https://community.temporal.io/t/custom-claim-mapper/12706). Budget for the custom-binary path; the default mapper also has [known `sub`-handling quirks](https://github.com/temporalio/temporal/issues/8218). Worked examples: [Bitovi RBAC](https://www.bitovi.com/blog/implementing-role-based-authentication-for-self-hosted-temporal), [Keycloak walkthrough](https://piotrmucha.blog/2025/12/26/implementing-authorization-in-temporal-server/).
- Web UI has no roles of its own — it forwards the user's token; enforcement is server-side. Per-team UI visibility falls out of the authorizer.
- Server v1.31 adds a non-spoofable [`Principal` field on history events](https://github.com/temporalio/temporal/releases/tag/v1.31.0) — use it for audit.
- Workers authenticate with mTLS certs or JWTs scoped `<namespace>:worker` — issue per-team credentials at onboarding.

## Namespace lifecycle: build the onboarding pipeline

No official self-hosted IaC (Infrastructure as Code) exists (the [Terraform provider is Cloud-only](https://github.com/temporalio/terraform-provider-temporalcloud)). Onboarding a team touches ~6 systems, so script it once: create namespace (retention, naming `<team>-<domain>-<env>` per [best practices](https://docs.temporal.io/best-practices/managing-namespace)) → append dynamic-config quota block → IdP group/claim mapping → worker credentials → Grafana folder with namespace-scoped dashboards/alerts → codec-server key registration. Options for the namespace step: [community Terraform provider](https://github.com/platacard/terraform-provider-temporal), `temporal operator namespace` in CI, or the temporal-operator's CRD (version-lagged). Per-env = per-namespace (`team-prod`, `team-staging`); names are effectively permanent (no migration), so gate naming at onboarding.

## Golden path and guardrails

- **Replay gate in CI** (highest-value guardrail): run the SDK WorkflowReplayer against sampled production histories on every worker build; fail on non-determinism ([safe deployments](https://docs.temporal.io/develop/safe-deployments)). Pair with Worker Versioning pinned mode + [worker-controller](https://github.com/temporalio/temporal-worker-controller) progressive rollout.
- **Chassis interceptor stack**: metrics, tracing, logging, encryption codec, optionally the [workflow-security interceptor](https://github.com/temporalio/samples-go/tree/main/workflow-security-interceptor) to whitelist child-workflow types.
- **SDK governance**: pin a supported language/SDK-version matrix; feature parity differs by language (see [oob-utilities-and-ecosystem.md](oob-utilities-and-ecosystem.md)).
- **Local dev**: `temporal server start-dev` covers laptops; staging namespaces on the shared cluster cover integration.

## Cost attribution and ops

- **Showback**: all server metrics are namespace-tagged — a thin dashboard over `service_requests`/state-transition rates and per-namespace storage approximates [Temporal Cloud's actions-based billing](https://temporal.io/blog/improved-cost-transparency-with-usage-based-billing). Build only if chargeback is actually demanded; start with a usage report.
- **What breaks in practice**: Postgres connection exhaustion ([documented failure mode](https://community.temporal.io/t/postgres-connection-churn/9612) — stuck workflows, UI 500s), hot shards from high-event-rate single workflows ([per-shard throughput is DB-latency-bound](https://planetscale.com/blog/temporal-workflows-at-scale-sharding-in-production)), and upgrade-train coordination (sequential minors, schema-first). On-call: platform owns cluster/DB/auth; teams own their workers and workflow failures — per-namespace alerts route accordingly.
- **Scale ceiling**: Cloud SQL can't shard, so the scale-out path is a second cluster (cells) with namespaces pinned to cells — [Datadog runs dozens of clusters](https://temporal.io/resources/on-demand/surviving-the-challenges-of-self-hosting-temporal-at-datadog); irrelevant at provisioning-workflow scale but it caps how much to invest in the one-cluster design.

## Suggested build order

1. mTLS + OIDC auth + claim mapping (nothing else is safe to share without it).
2. Namespace onboarding automation (namespace + quotas + credentials + dashboards).
3. Worker chassis + CI template with replay gate and worker-controller.
4. Codec server with per-namespace keys.
5. Per-team Grafana dashboards/alerts (mostly templating).
6. Showback, Nexus endpoint conventions — as demand appears.
