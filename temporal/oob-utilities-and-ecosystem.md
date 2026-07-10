# What teams get out of the box (and what the community adds)

## Executive Summary

More than expected. A team landing on the shared instance gets, without the platform building anything: official SDKs (Software Development Kits) in seven languages, test frameworks that fast-forward time, a Web UI that answers "where is my workflow stuck and why", a CLI (command-line interface) for bulk operations, cron-style Schedules, **Nexus** for calling another team's workflows without touching their code, and **Worker Versioning** for deploying workflow changes without breaking runs already in flight. Metrics are labelled by namespace out of the box, so "my team's dashboard" is Grafana templating, not engineering. The honest gaps: the UI's saved views can't be shared across a team, there is no workflow catalog tool anywhere in the ecosystem, and authorization has to be turned on deliberately — mostly configuration rather than a build (covered in [multi-tenancy-setup.md](multi-tenancy-setup.md)).

## Requirements

- Inventory what our shared self-hosted Temporal (GKE — Google Kubernetes Engine, PostgreSQL, per-team namespaces) gives teams out of the box vs via community extensions.
- Cover the utilities named in the ask: reviewing running/past workflows for debugging, and workflow metrics (success/failure, runtime).
- Code-first only — no visual designers.

## Assumptions Made

- "Community supported" includes Temporal's own side repos (dashboards, samples, the worker-controller) plus third-party open source.
- Statuses are as of July 2026. Nexus and Worker Versioning moved fast through 2025–26 — re-verify at build time.

This report follows a team through the life of a workflow: write it, test it, deploy it, watch it, debug it — then what exists between teams, and what doesn't exist at all.

![Temporal ecosystem landscape: what ships out-of-the-box (server, Web UI, CLI, schema tools, SDKs, Schedules/Nexus), what the community/official add-ons provide (Helm chart, Grafana dashboards, OTel exporters, Cloud SQL Auth Proxy), and what you build (gRPC API frontend, authn/authz glue, CI/CD, alerting, namespace provisioning)](diagrams/oob-utilities-and-ecosystem.png)

## Writing: seven languages, one caveat

[Seven GA SDKs](https://docs.temporal.io/develop): Go, Java, TypeScript, Python, .NET, PHP, Ruby (Rust in preview). The caveat is that **new features arrive language by language** — Nexus, for example, is GA in Go/Java/Python but still preview in TypeScript and .NET. The platform should publish a small supported-language matrix rather than promising "any SDK, any feature."

Day-to-day essentials are uniform everywhere: declarative [retry policies](https://docs.temporal.io/encyclopedia/retry-policies) and timeouts (an activity that calls a flaky API gets retries by configuration, not by code), signals and queries, and [Updates](https://temporal.io/blog/announcing-a-new-operation-workflow-update) — a synchronous "change this running workflow and give me an answer back", the request/reply primitive workflows long lacked.

## Testing: the part that's genuinely better than it sounds

Two built-in capabilities matter for our use case:

- **Time-skipping test environments.** Every major SDK ships an in-memory test server that fast-forwards timers — a provisioning workflow that waits 30 days for a follow-up runs in milliseconds. Long-running workflows become unit-testable.
- **Replay testing.** Temporal reconstructs a workflow's state by re-running its code against recorded history — which means *changed* code can silently corrupt *running* workflows. The [WorkflowReplayer](https://docs.temporal.io/develop/python/testing-suite) catches this: feed it production histories in CI and it fails the build if new code diverges. For workflows that run for days, this check is not optional hygiene — it is the safety net.

## Deploying: versioning is a solved problem now

The historical Temporal headache — "how do I deploy new workflow code while old workflows are mid-flight?" — got a proper answer recently. [Worker Versioning](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning) (GA March 2026) pins each workflow to the worker version that started it; new versions take new work, old versions drain, rollback is instant. Its companion, the [temporal-worker-controller](https://github.com/temporalio/temporal-worker-controller) (built at Datadog, now an official project; needs server ≥ 1.29.1), automates the whole dance on Kubernetes — running old and new worker versions side by side and cleaning up drained ones. Together they are the ready-made answer to "how do teams ship workflow changes safely."

## Watching: per-team dashboards are configuration, not construction

Everything is already labelled. Server metrics carry `namespace` ([`workflow_success`, `workflow_failed`, latencies…](https://docs.temporal.io/references/cluster-metrics)); [SDK metrics from workers](https://docs.temporal.io/references/sdk-metrics) add `workflow_type` and `task_queue`. So the exact utilities in the original ask — success/failure rates and runtimes per team, per workflow type — fall out of a Grafana dashboard with a namespace variable. Start from [temporalio/dashboards](https://github.com/temporalio/dashboards) and adapt.

Three alerts worth copying from day one:

1. **Schedule-to-start latency creeping up** — tasks are waiting for workers; the team is under-provisioned.
2. **Workflow task failures where `failure_reason="NonDeterminismError"`** — someone shipped code that breaks running workflows. The bad-deploy tripwire.
3. **Per-namespace failed/success ratio** — the basic health signal per team.

For lists rather than rates ("show me every failed provisioning run this week"), the **Visibility API** does filtered queries over custom search attributes — on PostgreSQL, no Elasticsearch needed. One flag: Java's official tracing module is OpenTracing-only; OpenTelemetry needs a shim or a [community module](https://github.com/Groww-OSS/temporal-opentelemetry). Go, Python, and TypeScript have first-class OpenTelemetry interceptors.

## Debugging: the Web UI earns its keep

The [Web UI](https://docs.temporal.io/web-ui) is the main reason teams won't need to file tickets with the platform:

- Every workflow's **full event history** — each step, input, output, and failure, browsable as a timeline and downloadable as JSON.
- "**Where is it stuck?**" answered directly: a stack-trace view of the exact line a workflow is blocked on, and a pending-activities view showing retry counts and the last error.
- **Fixes from the browser**: signal, cancel, terminate, and — most useful in practice — **reset**, which rewinds a workflow to an earlier step and lets it re-run from there. A provisioning run that failed halfway doesn't restart from zero.
- **Bulk operations** driven by a search query ("terminate everything of type X started before noon").

Two limits to know. Actions can be disabled per deployment via [UI config](https://docs.temporal.io/references/web-ui-configuration) — but fine-grained "who may reset what" comes from the server-side authorizer, i.e. platform work. And **saved views are stored in the browser, per person** — a team cannot share a curated "our workflows" view; naming conventions and dashboard links have to fill that gap.

The [CLI](https://docs.temporal.io/cli) covers the same ground scriptably, plus batch operations with rate limiting and `workflow trace` (a live tree of a workflow and its children). For deep debugging, the [VS Code extension](https://github.com/temporalio/vscode-debugger-extension) replays a downloaded history against local code with breakpoints — stepping through what production actually did.

## Scheduling: cron, minus the sharp edges

[Schedules](https://docs.temporal.io/schedule) (GA) replace cron triggers: calendar and interval specs, timezones, jitter, pause/resume, backfill, and — the part cron never had — explicit **overlap policies** declaring what happens when a run is due while the previous one is still going (skip, buffer, cancel it, run anyway). Managed via CLI and visible in the UI.

## Between teams: Nexus

The cross-team primitive, and worth introducing properly. Without it, team A calling team B's workflow means importing B's code or B exposing a bespoke API. [Nexus](https://temporal.io/blog/temporal-nexus-now-available) (GA since March 2025) lets a team publish named operations at an **endpoint**; callers invoke them across namespaces with Temporal handling retries and long-running completion. Teams share a contract, not code, queues, or namespace access.

For our provisioning case this is the natural shape for platform-owned building blocks — a "provision bare-metal via Rafay" operation published once, called by any team's workflow. Self-hosted notes: [on by default since server 1.30](https://docs.temporal.io/production-deployment/self-hosted-guide/nexus), single-cluster scope, needs the frontend's HTTP port exposed. A pleasant side effect: the endpoint registry doubles as a de-facto catalog of what teams offer each other.

## Community extensions worth knowing

(Index: [awesome-temporal](https://github.com/temporalio/awesome-temporal).)

- **[temporal-operator](https://github.com/alexandrevilain/temporal-operator)** — declarative cluster + namespace resources, auto-mTLS. Supports server ≤ 1.28 (current: 1.31), single maintainer. Borrow the patterns, don't build on it.
- **Terraform** — the official provider is [Temporal Cloud-only](https://github.com/temporalio/terraform-provider-temporalcloud). For self-hosted namespace management: [platacard/terraform-provider-temporal](https://github.com/platacard/terraform-provider-temporal) (active; verify resource coverage) or plain `temporal operator namespace` in CI.
- **Load testing** — [omes](https://github.com/temporalio/omes), Temporal's own generator, plus [benchmark-workers](https://github.com/temporalio/benchmark-workers) for cluster sizing.
- **Payload codecs** — encryption/compression samples in every major SDK, and a [Vault-backed codec server](https://github.com/zboralski/codecserver). (Why codecs matter for a shared instance: next section.)
- **Interceptors** — [logging](https://github.com/temporalio/samples-go/tree/main/logger-interceptor) and [workflow-security](https://github.com/temporalio/samples-go/tree/main/workflow-security-interceptor) (restricts which child workflow types may run) samples; raw material for a platform-standard worker stack.
- **[iWF](https://github.com/indeedeng/iwf)** — Indeed's higher-level framework on top of Temporal. Adds its own server and model; skip unless teams reject the native SDKs.

And what **doesn't** exist, so nobody goes looking: no shared saved views, no workflow catalog or docs generator (conventions + search attributes + the Nexus endpoint list are the substitute), and no serious alternative UI — the official one is the standard.

## One shared service to plan early: the codec server

Everything a workflow touches — inputs, outputs, errors — is stored in the shared database and displayed in the shared UI. Teams handling sensitive data (machine credentials, for us) should encrypt payloads with an SDK codec. But then the UI shows base64 noise — unless a [**codec server**](https://docs.temporal.io/production-deployment/data-encryption) is running: a small HTTP service the UI and CLI call to decode payloads *in the viewer's browser session*. Data stays encrypted in the database; authorized humans still get readable debugging. Support is first-class (per-namespace endpoint config in the UI, `--codec-endpoint` in the CLI, [samples in five languages](https://github.com/temporalio/samples-go/tree/main/codec-server)). The multi-team pattern — one platform codec service routing on the namespace header to per-team keys — is platform work, detailed in [multi-tenancy-setup.md](multi-tenancy-setup.md).
