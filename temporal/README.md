# temporal

Shared self-hosted Temporal as a multi-team workflow engine for long-running, cross-system orchestration (first use case: bare-metal → OS provisioning via Rafay → Kubernetes cluster build), on GKE with Cloud SQL PostgreSQL.

- **Architecture is settled** ([shared-instance-architecture.md](shared-instance-architecture.md)): official Helm chart (production-ready since April 2026) into the existing GKE cluster, Cloud SQL PostgreSQL in regional HA, no Elasticsearch. The chart installs only stateless Deployments — no StatefulSets, no persistent volumes; all durable state is in Cloud SQL, and teams deploy their own workers (also stateless Deployments), not the chart. Two decisions need care because they're hard to undo: the history shard count (512 — permanent because workflows map to shards by `hash % shardCount` and there's no re-sharding tool) and security (Temporal ships with no authentication at all). A tuned single PostgreSQL delivers low-thousands of state transitions/sec; no GCP-specific benchmark is published, so load-test before go-live.
- **Teams get more for free than expected** ([oob-utilities-and-ecosystem.md](oob-utilities-and-ecosystem.md)): seven SDK languages, time-skipping test frameworks, replay testing (the safety net for changing long-running workflows), a Web UI that answers "where is my workflow stuck", Schedules, Nexus for cross-team calls, and Worker Versioning + worker-controller for safe deploys. Per-team metrics dashboards are Grafana templating, not engineering — everything is namespace-labelled.
- **The platform build list** ([multi-tenancy-gaps.md](multi-tenancy-gaps.md)), in dependency order: auth (turning on the built-in per-namespace RBAC is *configuration*, not a rebuild — a server fork is only needed if the identity provider can't emit the expected `namespace:role` claim), an onboarding pipeline (namespace + quotas + credentials + dashboards; quota config can't be wildcarded, so it's templated per team), a worker chassis + CI replay gate, a shared codec server, then dashboards and showback.
- **The worker-pool question is resolved: per-team workers from day one.** A worker serves exactly one namespace by design, so a common pool would mean every team's code in one deployment — no published platform (Netflix, Datadog) does that. Worker layout is cheap to change later; **namespace layout is permanent** (workflows can never move between namespaces) — that's where the design care goes. Shared capability = shared chassis + Nexus endpoints, not shared processes.
- Code-first confirmed; no workflow-designer UX needed. No workflow catalog tool exists in the ecosystem — naming conventions, search attributes, and the Nexus endpoint registry fill that role.

## Open threads

- Cloud SQL failover reconnect on server 1.31 needs a staging drill (older versions had history-service reconnect failures).
- Dynamic-config key names drift between releases — verify per-namespace quota keys against `constants.go` at deploy time.
- Load-test with Omes before go-live to validate 512 shards + Cloud SQL sizing against the real provisioning workload.
- Java has no official OpenTelemetry tracing module (shim or community only) — matters if Java becomes a primary SDK.
- Namespace granularity (per team vs per team-per-environment) deserves a short design pass before onboarding the first team — it's the irreversible choice.
