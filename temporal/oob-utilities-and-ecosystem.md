# Temporal out-of-the-box utilities and ecosystem extensions

## Executive Summary

Teams on a shared Temporal instance get, for free: the **Web UI** (event-history inspection, stack-trace and pending-activity debugging, signal/reset/terminate/bulk actions), the **temporal CLI** (batch operations, live workflow tracing, resets, schedules), **seven GA SDKs** (Go, Java, TypeScript, Python, .NET, PHP, Ruby), time-skipping **test frameworks with replay testing**, **Schedules** (cron replacement), **Nexus** for governed cross-team/cross-namespace calls (GA since March 2025), and **Worker Versioning + the temporal-worker-controller** (GA March 2026) for safe rainbow deploys of workers on Kubernetes. Metrics are namespace-tagged out of the box, so per-team success/failure/runtime dashboards are a Grafana-variable exercise, not a build. The genuinely thin spots: Web UI saved views are browser-local (no shared team views), authorization is a server-side plugin you must supply, self-hosted namespace management has no official Terraform provider (community ones exist), and there is no workflow catalog/discovery tool — conventions and search attributes fill that gap.

## Requirements

- Inventory what a shared self-hosted Temporal (GKE — Google Kubernetes Engine, PostgreSQL, per-team namespaces) provides out of the box vs via community extensions.
- Focus on the utilities teams asked for: reviewing running/past workflows for debugging, and workflow metrics (success/failure, runtime).
- Code-first only — no visual workflow designers.

## Assumptions Made

- "Community supported" includes official-but-separate Temporal repos (dashboards, worker-controller, samples) plus third-party OSS (Open Source Software).
- Feature status is as of July 2026; several items (Nexus SDK coverage, worker-controller) moved fast in 2025–26 and should be re-verified at build time.

## Debugging and operations tooling

**[Web UI](https://docs.temporal.io/web-ui)** — the shared debugging surface:
- Execution lists filtered by status/type/time/custom search attributes; event history in timeline/compact/JSON views; history downloadable as JSON for local replay.
- Debug views: current **stack trace** of a blocked workflow, **pending activities** with attempt/failure drill-down, parent/child relationship tree, and a built-in **Task Failures** view surfacing workflows with 5 consecutive task failures.
- Operator actions from the UI: cancel, signal, update, **reset** (rewind to a prior event), terminate, plus **bulk terminate/cancel** driven by a visibility query. Actions can be disabled per-deployment via [UI config](https://docs.temporal.io/references/web-ui-configuration) for lockdown.
- Limitation for a shared platform: **saved views are browser-local, max 20, per user** — no centrally provisioned "team X's workflows" views. Compensate with naming conventions + custom search attributes + dashboard links.

**[temporal CLI](https://docs.temporal.io/cli)** — everything the UI does plus: `workflow trace` (live execution tree incl. children), `workflow show --follow`, batch `signal/cancel/terminate/reset` targeted by `--query` with `--rps` throttling, [schedule management](https://docs.temporal.io/cli/schedule), an embedded dev server (`temporal server start-dev`), and operator commands for namespaces/search attributes/Nexus endpoints.

**Replay debugging**: the official [VS Code debugger extension](https://github.com/temporalio/vscode-debugger-extension) replays a production event history against workflow code with breakpoints (TypeScript + Go).

## Built-in features teams get for free

- **[Schedules](https://docs.temporal.io/schedule)** (GA, replaces cron): calendar/interval specs, jitter, timezones, six overlap policies, pause/backfill, action limits.
- **Signals, Queries, and [Updates](https://temporal.io/blog/announcing-a-new-operation-workflow-update)** (Update-with-Start GA in server v1.28) — synchronous mutate-and-respond, the missing "request/reply" primitive.
- **Declarative [retry policies](https://docs.temporal.io/encyclopedia/retry-policies) + timeout model**, child workflows, continue-as-new.
- **[Nexus](https://temporal.io/blog/temporal-nexus-now-available)** — cross-namespace service calls with contract-first APIs. **This is the multi-team primitive**: team A calls team B's workflow without sharing code, queues, or namespace access. GA since 2025-03 (Go/Java, [Python GA, TypeScript/.NET preview as of Replay 2026](https://temporal.io/blog/replay-2026-product-announcements)). Self-hosted: [enabled by default from server 1.30](https://docs.temporal.io/production-deployment/self-hosted-guide/nexus), single-cluster scope, frontend HTTP port required. The Nexus endpoint registry doubles as a de-facto cross-team service catalog.
- **[Worker Versioning](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning)** — GA 2026-03-30: pinned vs auto-upgrade workflows, ramped rollout, instant rollback. Companion **[temporal-worker-controller](https://github.com/temporalio/temporal-worker-controller)** (originated at Datadog, now official; v1.8.0, needs server ≥1.29.1): a Kubernetes controller doing versioned rainbow deployments of workers with per-version autoscaling and cleanup of drained versions. This pair is the golden-path answer for "how do teams deploy workflow changes safely" — the classic [patching APIs](https://docs.temporal.io/develop/go/versioning) remain for surgical fixes.
- **SDKs**: [seven GA languages](https://docs.temporal.io/develop) — Go, Java, TypeScript, Python, .NET, PHP (needs RoadRunner), Ruby (GA Oct 2025); Rust in preview. Feature parity lags per language (e.g., Nexus in TS/.NET is preview) — pin a supported-language matrix for the platform.
- **Testing**: every major SDK ships an in-memory **time-skipping test environment** (a 30-day sleep runs in ms) and a **WorkflowReplayer** for determinism checks against recorded histories — [recommended as a CI gate](https://docs.temporal.io/develop/python/testing-suite). This matters unusually much in Temporal: non-deterministic code changes break running workflows.

## Metrics: per-team dashboards are configuration, not construction

Two complementary paths, both namespace-sliceable:

1. **Prometheus** — for rates, latencies, alerting. Server metrics carry a `namespace` tag ([`workflow_success`, `workflow_failed`, `service_latency`…](https://docs.temporal.io/references/cluster-metrics)); [SDK metrics](https://docs.temporal.io/references/sdk-metrics) add `workflow_type`/`task_queue`/`activity_type` — per-workflow-type runtime and failure breakdowns come from worker-side scraping. A Grafana dashboard with a `namespace` variable gives every team "my workflows" for free. Start from [temporalio/dashboards](https://github.com/temporalio/dashboards) (server + SDK; explicitly a baseline).
2. **Visibility API** — for lists, drill-down, exact counts: `ListWorkflowExecutions`/`CountWorkflowExecutions` with custom search attributes; works on PostgreSQL without Elasticsearch (server ≥1.20).

**Alerting recipes** ([worker health guidance](https://docs.temporal.io/production-deployment/cloud/worker-health)): `workflow_task_schedule_to_start_latency` and `activity_schedule_to_start_latency` near zero (growth = under-provisioned workers); `rate(temporal_workflow_task_execution_failed{failure_reason="NonDeterminismError"})` as a bad-deploy tripwire; per-namespace `workflow_failed`/`workflow_success` ratio; task-queue backlog (`approximate_backlog_count`).

- **Tracing**: OpenTelemetry interceptors exist for [Go](https://pkg.go.dev/go.temporal.io/sdk/contrib/opentelemetry), [Python](https://python.temporal.io/temporalio.contrib.opentelemetry.TracingInterceptor.html), [TypeScript](https://www.npmjs.com/package/@temporalio/interceptors-opentelemetry); **Java's official module is OpenTracing-only** (OTel via shim or [community module](https://github.com/Groww-OSS/temporal-opentelemetry)) — a real gap if Java is a primary language.

## Community extensions worth knowing

Index: [awesome-temporal](https://github.com/temporalio/awesome-temporal).

- **[temporal-operator](https://github.com/alexandrevilain/temporal-operator)** (alexandrevilain): `TemporalCluster` + `TemporalNamespace` CRDs, auto-mTLS. Lags server (≤1.28 vs 1.31), single maintainer — useful pattern, risky foundation.
- **Terraform**: the official [provider is Temporal Cloud-only](https://github.com/temporalio/terraform-provider-temporalcloud). For self-hosted: [platacard/terraform-provider-temporal](https://github.com/platacard/terraform-provider-temporal) (active, v0.19.0 Apr 2026 — verify resource coverage) or the operator's CRDs; fallback is `temporal operator namespace` in CI.
- **Load/sizing**: [temporalio/omes](https://github.com/temporalio/omes) (current official load generator) and [benchmark-workers](https://github.com/temporalio/benchmark-workers) (prebuilt images + Helm); maru is deprecated.
- **Payload codecs**: built-in zlib codec (Go), [encryption](https://github.com/temporalio/samples-go/tree/main/encryption)/[compression](https://github.com/temporalio/samples-go/tree/main/snappycompress) samples in every major SDK; community [Vault-backed codec server](https://github.com/zboralski/codecserver).
- **Interceptor samples** for a platform-standard stack: [logging](https://github.com/temporalio/samples-go/tree/main/logger-interceptor), [workflow-security](https://github.com/temporalio/samples-go/tree/main/workflow-security-interceptor) (whitelists which child workflow types may run — a multi-team governance hook).
- **Higher-level frameworks**: [iWF](https://github.com/indeedeng/iwf) (Indeed) layers a REST state-machine model over Temporal — only relevant if teams want to avoid the native SDK model; adds a server component. Not recommended initially.
- **Nonexistent, so plan to build or skip**: no shared-saved-views mechanism, no workflow catalog/documentation generator (closest: naming conventions + search attributes + Nexus endpoint list), no third-party alternative UI of note.

## Codec server: the one shared service to plan early

A [codec server](https://docs.temporal.io/production-deployment/data-encryption) is a small HTTP service (`/encode`, `/decode`) sharing codec logic with SDK `PayloadCodec`s. If any team encrypts or compresses payloads (they should — the platform DB stores every input/output), the shared Web UI and CLI show base64 blobs unless a codec server decodes them client-side. First-class support: per-namespace endpoint config in the UI, `--codec-endpoint` in the CLI, [samples in five languages](https://github.com/temporalio/samples-go/tree/main/codec-server). Multi-team pattern: one platform codec service routing on the `X-Namespace` header to per-team keys. The codec server sees plaintext — its authentication is the platform's job (see [multi-tenancy-gaps.md](multi-tenancy-gaps.md)).
