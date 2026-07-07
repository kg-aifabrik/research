# temporal

Shared self-hosted Temporal as a multi-team workflow engine for long-running, cross-system orchestration (first use case: bare-metal → OS provisioning via Rafay → Kubernetes cluster build), on GKE with Cloud SQL PostgreSQL.

- **Architecture settled** ([shared-instance-architecture.md](shared-instance-architecture.md)): official Helm chart (production-ready since v1.0.0, April 2026) into the existing GKE cluster; Cloud SQL PostgreSQL regional HA; `numHistoryShards: 512` (immutable — decide once); no Elasticsearch initially — PostgreSQL advanced visibility suffices, Dual Visibility is the later escape hatch. Tuned ceiling ≈ low-thousands state transitions/sec, far above provisioning-workflow needs.
- **Teams get a lot for free** ([oob-utilities-and-ecosystem.md](oob-utilities-and-ecosystem.md)): Web UI debugging (stack traces, pending activities, reset/bulk ops), CLI, 7 GA SDKs, time-skipping test frameworks + replay testing, Schedules, Nexus (GA) for cross-team calls, Worker Versioning + temporal-worker-controller (GA 2026) for safe worker deploys. Per-team metrics dashboards are configuration, not construction — everything is namespace-tagged.
- **Platform build list** ([multi-tenancy-gaps.md](multi-tenancy-gaps.md)), in order: (1) mTLS + OIDC auth/claim mapping — OSS default is wide open, custom claim mapper means recompiling the server; (2) namespace onboarding automation (quotas via dynamic config have no wildcards — template per team); (3) worker chassis + CI template with replay gate; (4) codec server with per-namespace keys; (5) dashboard templating; (6) showback.
- **Worker topology decision (was an open item): per-team workers from day one.** One worker binds to one namespace by design; no published platform (Netflix, Datadog) shares worker processes across teams. Worker/task-queue layout is cheap to change later; **namespace layout is not** — that's where early design care goes. Shared capabilities are delivered as a chassis library and Nexus endpoints, not shared processes.
- No visual workflow designer needed (code-first confirmed); no workflow catalog tool exists — naming conventions + search attributes + Nexus endpoint registry fill the gap.

## Open threads

- Cloud SQL failover reconnect behavior on server 1.31 needs a staging drill (older versions had history-service reconnect failures).
- Exact dynamic-config key names for per-namespace visibility RPS drift between releases — verify against `constants.go` at deploy time.
- Load test with Omes before go-live to validate 512 shards + Cloud SQL sizing against the real provisioning workload.
- Java OpenTelemetry tracing has no official module (OpenTracing shim or community) — matters if Java becomes a primary SDK.
- Namespace granularity per team (one vs per-env vs per-domain) deserves a short design pass before onboarding the first team — it's the irreversible choice.
