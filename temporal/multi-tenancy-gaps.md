# Making one Temporal serve many teams: what we have to build

## Executive Summary

Temporal's namespaces separate teams' *names and configuration* — workflows, task queues, retention — but not their *machines*: every namespace shares the same four services and the same PostgreSQL instance, and Open Source Software (OSS) Temporal ships with no authentication, no self-service, and no per-team billing. Closing that gap is the platform team's actual job. The build list, in dependency order: (1) authentication and per-namespace authorization — the largest single build; (2) an automated team-onboarding pipeline; (3) a worker "chassis" and CI (Continuous Integration) template; (4) a shared codec server; (5) dashboard templating; (6) cost showback, only if demanded.

On the open worker-pool question: **per-team workers from day one, and it's not close.** A Temporal worker serves exactly one namespace by design, so with per-team namespaces a "common pool" would mean one deployment carrying every team's code — and no published platform does that. The genuinely irreversible choice is elsewhere: **namespace layout.** Workflows cannot move between namespaces, ever. Design namespace granularity carefully; everything else can be refactored later.

## Requirements

- Determine what must be *built*, vs merely *configured*, vs free, for multiple teams to share one self-hosted Temporal (GKE — Google Kubernetes Engine, Cloud SQL PostgreSQL, per-team namespaces) independently.
- Resolve the open item: start with a common worker pool, or per-team workers? Does committing early matter?

## Assumptions Made

- 5–20 teams, not thousands of tenants — comfortably inside the per-team-namespace pattern.
- Teams own their workflow code and workers; the platform owns cluster, database, auth, and shared services.
- An OpenID Connect (OIDC) identity provider that can mint custom claims is available (Google Workspace / Identity Platform).

## First, the right mental model: what a namespace is and isn't

A namespace is a **logical boundary**: its own workflow IDs, task queues, retention policy, and — once auth exists — its own access-control scope. When team A's worker misbehaves, it can only touch team A's workflows. That's real, useful isolation, and per-team namespaces are the pattern [Temporal's own guidance](https://docs.temporal.io/best-practices/managing-namespace) points to at our scale.

What a namespace is **not**: a resource boundary. All namespaces flow through the same frontend, the same history service, the same database. A Temporal staffer [confirms the consequence plainly](https://community.temporal.io/t/noisy-neighbor-namespace/18728): one namespace under heavy load can degrade all the others. Nothing prevents it by default — the platform has to set limits (below).

Keep this split in mind throughout: **namespaces isolate names; only quotas and worker separation isolate resources.**

## The worker question, answered

The request was to start with a common worker pool shared by all teams, moving to per-team workers later if needed. Three findings say to start per-team instead:

**1. Temporal's design already decided.** A worker connects to exactly one namespace. This is deliberate — Temporal's co-founder [explains](https://community.temporal.io/t/sharing-activity-workers-across-namespaces/9921) that a multi-namespace worker would let one namespace starve another of capacity, exactly what namespaces exist to prevent. So with per-team namespaces, a "common pool" can't be a pool at all; it degenerates into one deployment running a separate worker per namespace, with **every team's code compiled into one artifact**. One team's memory leak evicts everyone's pollers; one team's dependency upgrade forces everyone's redeploy; shipping anything means shipping everything.

**2. Nobody runs it that way.** [Netflix's Temporal platform](https://community.temporal.io/t/automating-temporal-a-full-view-of-the-netflix-temporal-platform/13624) (namespace automation, mTLS, per-language init libraries — built by ~1.5 engineers in a quarter) and [Datadog's](https://opensource.datadoghq.com/projects/temporal/) (they wrote the worker-controller) both converge on the same shape: **teams run their own workers on a platform-paved road.**

**3. The asymmetry of regret is the clincher.** Suppose we start shared and it hurts — how bad is the switch? For workers: painless. Task-queue names aren't validated on replay, so [moving work to new queues and workers needs no versioning](https://community.temporal.io/t/clarity-on-task-queue-and-worker-segregation-patterns/4429). For namespaces: brutal. A running workflow [cannot change namespace](https://community.temporal.io/t/switch-workflow-execution-to-another-namespace-task-queue/5627), and there is [no supported way to migrate histories](https://community.temporal.io/t/migrate-a-namespace-between-servers-and-namespace/18497) — fixing a wrong split means draining months-long provisioning workflows to completion. **Spend the design meeting on namespace granularity** (per team? per team per environment? — per-environment namespaces like `team-prod` / `team-staging` are the documented pattern), not on worker topology.

The "shared" idea survives in better form: share the **chassis**, not the process. A base image plus a thin per-language init library that pre-wires mTLS, metrics, tracing, encryption, and standard interceptors — Netflix's exact pattern — so a team's first worker is an afternoon, not a sprint. And when something genuinely common is needed (one blessed "provision bare-metal via Rafay" implementation), publish it as a **Nexus endpoint** from a platform-owned namespace; teams call it without hosting it.

## Build 1 — authentication and authorization (do this before sharing anything)

Out of the box, anyone with network reach can read every team's payloads, terminate any workflow, delete namespaces. The [security model](https://docs.temporal.io/self-hosted-guide/security) is two pluggable hooks: a **claim mapper** (turns a JWT — JSON Web Token — into "this caller has these roles in these namespaces") and an **authorizer** (allows or denies each API call against those roles).

The built-in mapper expects a `permissions: ["<namespace>:<role>"]` claim (roles: read / write / worker / admin). Google-issued tokens don't carry it, leaving two options:

- **Mint the claim in the identity provider** — map groups to namespace roles at token issuance. No Temporal code changes; do this if the IdP cooperates.
- **Write a custom claim mapper** — here's the catch: custom mappers are [compiled into the server binary](https://community.temporal.io/t/custom-claim-mapper/12706). That means maintaining our own server build and rebuilding on every upgrade. Worked examples exist ([Bitovi](https://www.bitovi.com/blog/implementing-role-based-authentication-for-self-hosted-temporal), [Keycloak walkthrough](https://piotrmucha.blog/2025/12/26/implementing-authorization-in-temporal-server/)), but budget it as a real project.

The Web UI needs no separate work — it forwards the user's token, so a team member sees exactly their namespaces. Workers get their own credentials (mTLS certificates or `<namespace>:worker`-scoped JWTs), issued per team at onboarding. Since v1.31 the server stamps a tamper-proof [`Principal`](https://github.com/temporalio/temporal/releases/tag/v1.31.0) on history events — who-terminated-this audit for free.

## Build 2 — the onboarding pipeline (and the quota trap inside it)

There is no self-service anything in OSS Temporal, and the official Terraform provider is [Cloud-only](https://github.com/temporalio/terraform-provider-temporalcloud). Onboarding a team touches six things — script it once, run it per team:

1. Create the namespace(s) (retention, `<team>-<env>` naming — remember: permanent).
2. Add the team's quota block to the dynamic-config file.
3. Map the team's IdP group to namespace roles.
4. Issue worker credentials.
5. Stamp out the team's Grafana folder and alerts.
6. Register the team's key with the codec server (Build 4).

Step 2 is where the noisy-neighbor protection actually lives, via per-namespace [dynamic-config](https://docs.temporal.io/references/dynamic-configuration) overrides: `frontend.namespaceRPS` caps a team's request rate (requests per second), `*.persistenceNamespaceMaxQPS` caps their database pressure — the one that really protects Cloud SQL — and `limit.blobSize.*` / `limit.historySize.*` / `limit.historyCount.*` stop oversized payloads and runaway histories before they hurt the shared database.

Two traps: overrides [can't be wildcarded](https://github.com/temporalio/temporal/issues/6237) — every namespace must be listed explicitly, hence the templating; and key names drift between releases — verify against [constants.go](https://github.com/temporalio/temporal/blob/main/common/dynamicconfig/constants.go) for the deployed version. (The newer [Task Queue Priority & Fairness](https://docs.temporal.io/develop/task-queue-priority-fairness) feature, GA May 2026, sounds relevant but operates *within* one task queue — useful to a team prioritizing its own work, e.g. urgent re-provisions over bulk builds; not a cross-team isolation tool.)

## Build 3 — the paved road for workers

Assembly, not invention:

- **The chassis** (from the worker discussion): base image + init library with mTLS, metrics, tracing, encryption codec, standard interceptors pre-wired. Optionally the [workflow-security interceptor](https://github.com/temporalio/samples-go/tree/main/workflow-security-interceptor) to restrict which child workflow types run.
- **A CI template with a replay gate** — the highest-value guardrail on the list. Replay production histories against the new build; fail on non-determinism ([safe deployments guide](https://docs.temporal.io/develop/safe-deployments)). This catches broken-running-workflow bugs *before* deploy, which matters enormously when workflows run for days.
- **Deployment via the [temporal-worker-controller](https://github.com/temporalio/temporal-worker-controller)** with Worker Versioning in pinned mode — old and new worker versions run side by side, old workflows finish on the code that started them.
- **SDK governance**: a supported language/version matrix (feature parity varies — see [oob-utilities-and-ecosystem.md](oob-utilities-and-ecosystem.md)). Local dev is solved: `temporal server start-dev` is a single binary.

## Build 4 — the codec server

Teams encrypting payloads (they should — the shared database stores every workflow input/output, including machine credentials) need a [codec server](https://docs.temporal.io/production-deployment/data-encryption) so the shared UI can decode payloads for authorized viewers. One platform service, routing on the namespace header the UI sends to per-team keys — Netflix runs [exactly this centralized shape](https://community.temporal.io/t/automating-temporal-a-full-view-of-the-netflix-temporal-platform/13624). It sees plaintext, so it authenticates callers as strictly as the cluster itself.

## Builds 5 & 6 — dashboards and showback

Mostly templating. Metrics are namespace-labelled, so per-team Grafana folders with the three standard alerts (worker starvation, non-determinism tripwire, failure ratio) stamp out per team. For cost attribution, per-namespace request and state-transition rates approximate what [Temporal Cloud bills on](https://temporal.io/blog/improved-cost-transparency-with-usage-based-billing); start with a monthly usage report and build real chargeback only if someone demands it.

## Running it: what actually breaks

- **PostgreSQL connection exhaustion** — the [best-documented failure mode](https://community.temporal.io/t/postgres-connection-churn/9612) (stuck workflows, UI errors). Budget `maxConns` × replicas × 2 against the Cloud SQL limit; alert on connection count.
- **Hot shards** — one workflow taking a very high event rate serializes on its shard, whose ceiling is [database latency](https://planetscale.com/blog/temporal-workflows-at-scale-sharding-in-production). The history-length guardrails and a word in code review ("split that loop into child workflows") prevent it.
- **The upgrade train** — sequential minors, schema-first, one org-wide window. Platform coordinates; teams' workers just need SDK compatibility.
- **On-call split** follows ownership: platform pages on cluster/database/auth; teams page on their own workflow failures and worker starvation. The namespace label routes alerts correctly by construction.

If the org someday outgrows one cluster (Cloud SQL can't shard — [Datadog runs dozens of clusters](https://temporal.io/resources/on-demand/surviving-the-challenges-of-self-hosting-temporal-at-datadog)), the answer is more clusters with teams pinned to each. Provisioning-scale load won't get there — which is itself a design input: keep the platform layer thin enough that a second cluster is an instance of it, not a rewrite.
