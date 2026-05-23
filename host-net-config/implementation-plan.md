# Implementation plan — `host-config` repo

> Durable planning artifact. Captures the decisions, repo charter, quality bar, milestone breakdown, and issue list for the `host-config` repository. Lives in the research repo as the reference; the new repo's README links here.

## Charter

`host-config` is a public, Apache-2.0 GitHub repository under the same user account as this research repo. It holds the production-grade code, infrastructure, and deployment configuration for the **host network configuration pipeline** described in [`baremetal-network-overview.md`](baremetal-network-overview.md) and tested per [`test-strategy.md`](test-strategy.md).

**Initial scope:** Tier 1 only — Netbox model + fixtures, on-demand renderer service, nginx cache layer, OVS+QEMU test harness, cloud-init NoCloud integration, Soft-RoCE for east-west verbs validation, and a deployable lab on a DigitalOcean Droplet. **Out of initial scope:** Tier 2 hardware tests (run from this repo's CI but no provisioning code), Tier 3 LaunchPad, day-2 reconciliation, CNI / K8s overlay work (added later as a separate top-level module without restructuring).

**Operating principles:**

- **Production grade from day one.** Linting, type-checking, coverage gates, ADRs, signed commits, observability — all on the first commit, not added later.
- **Trunk-based, small reviewable changes.** Issues are scoped to be reviewable in a single sitting.
- **Horizontal layer milestones with integration gates.** Each `.5` milestone proves a vertical slice works before the next layer starts.
- **The research repo is the source of truth for design.** `host-config` references this repo for the why; it owns the how.
- **No CNI scaffolding pre-built.** When CNI work starts, it gets its own top-level module. Don't pre-design what isn't being built.

## Repo structure

```
host-config/
├── README.md                       # what this is, prereqs, quickstart
├── LICENSE                         # Apache-2.0
├── CHANGELOG.md                    # auto-generated from conventional commits
├── pyproject.toml                  # uv-managed; Python 3.12+
├── uv.lock
├── .python-version
├── .pre-commit-config.yaml
├── .gitignore
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  # lint, type-check, unit, component
│   │   ├── e2e.yml                 # full pipeline e2e on PR
│   │   └── docs.yml                # mkdocs build + deploy on main
│   ├── ISSUE_TEMPLATE/             # layer-task.md, gate-test.md, bug.md
│   └── PULL_REQUEST_TEMPLATE.md
│
├── docs/                           # mkdocs Material site source
│   ├── index.md
│   ├── architecture/
│   ├── adr/                        # 0001-..., 0002-...
│   ├── runbooks/
│   └── mkdocs.yml
│
├── infra/
│   ├── terraform/                  # DO Droplet provisioning
│   └── ansible/                    # in-host bootstrap (Netbox, OVS, nginx, renderer, qemu-host)
│
├── src/host_config/                # FastAPI renderer service (Python package)
│   ├── models/                     # Pydantic HostIntent + variants
│   ├── netbox/                     # pynetbox wrapper + loaders
│   ├── render/                     # Jinja templates + emit logic
│   ├── service/                    # FastAPI app + middleware
│   ├── observability/              # structlog + OTel + Prometheus
│   └── DESIGN.md                   # module-level design doc
│
├── tests/
│   ├── unit/
│   ├── component/                  # tests against real Netbox container
│   ├── integration/                # cross-module
│   └── e2e/                        # gate-milestone tests
│
├── fixtures/
│   ├── netbox/                     # Netbox population scripts
│   └── vms/                        # QEMU launch scripts, cloud images
│
└── scripts/                        # bootstrap-lima.sh, dev convenience
```

## Quality bar

**Code:**

- **Python 3.12+** with `uv` as the package manager (single tool for env, deps, scripts).
- **`mypy --strict`** end-to-end. CI gate.
- **`ruff`** with curated ruleset (`E`, `F`, `I`, `UP`, `B`, `S`, `RUF`, `PL`, `TID`, `SIM`); `ruff format` for code style. CI gate.
- **Tests:** `pytest` + `pytest-asyncio` + `pytest-cov`. Full pyramid (unit + component + integration) at every milestone.
- **Coverage gates:** 85% on `src/host_config`, 70% on Ansible-linted infra. CI blocks merge if coverage drops.
- **Pre-commit hooks:** `ruff`, `mypy`, `pytest -m fast`, `gitleaks` (secrets), `check-large-files`, `check-yaml`.
- **Dependency hygiene:** `uv.lock` committed, Dependabot weekly, `syft` SBOM at release, `pip-audit` in CI.

**Process:**

- **Conventional commits** enforced via `commitlint` pre-commit hook. Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `perf`, `build`.
- **GPG-signed commits** required on `main` (branch protection).
- **Trunk-based dev.** Feature branches off `main`, squash-merge back.
- **PR template** requires: linked issue, what changed, how tested, acceptance criteria check.
- **CI gates** to merge: lint + type-check + unit + component + coverage threshold + integration. e2e runs on PR but allowed to be slower.
- **CHANGELOG.md** auto-generated from conventional commits at release time.

**Docs:**

- **README.md** — what, prereqs, quickstart (`scripts/bootstrap-lima.sh && pytest -m e2e`), pointers into `docs/`.
- **`docs/architecture/`** — overview, sequence diagrams, component contracts. Renders to the mkdocs site.
- **`docs/adr/`** — Michael Nygard format. Numbered, dated, immutable once landed (supersede, don't edit).
- **Module `DESIGN.md`** — each major module (`src/host_config/`, `infra/terraform/`, `infra/ansible/`) gets one.
- **`docs/runbooks/`** — operational playbooks (deploy to DO, debug a failing render, etc.).
- **mkdocs Material theme**, published to GitHub Pages on every push to `main` via GHA.
- **Docstrings:** all public functions/classes. Google style. Rendered via `mkdocstrings`.

**Observability (in the renderer from day one):**

- **`structlog`** — JSON logs in production, console-friendly in dev.
- **OpenTelemetry** — `opentelemetry-instrumentation-fastapi`; OTLP exporter configurable, no-op default.
- **Prometheus metrics** at `/metrics` — request count, latency histograms, Netbox query duration, render duration, cache-miss rate.
- **Health endpoints** — `/healthz` (liveness), `/readyz` (Netbox reachable + cache writable).

## Workflow conventions

- **Branch naming:** `feat/<short-slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`. Issue number suffix optional.
- **Commit messages:** Conventional commit format. Body required for non-trivial changes; references linked issue.
- **PR title:** Same Conventional Commit format. Squash-merge preserves the title in `main`'s history.
- **Code review:** Self-review acceptable for trivial changes (docs typos, dependency bumps); substantive changes require linter+tests passing and a deliberate "looks good" comment before merge.
- **Issue labels:** `milestone:M0`–`milestone:M7.5`, `layer:infra`, `layer:renderer`, `layer:fixtures`, `layer:docs`, `kind:feat`, `kind:test`, `kind:bug`, `priority:p0`–`p2`.
- **Definition of done:** Acceptance criteria in the issue are checked off; tests written and passing; docstring/README/ADR updated where relevant; merged to `main`.

## Milestone plan

8 horizontal layer milestones (M0–M7) + 7 integration gate milestones (M1.5–M7.5). Open-ended dates — milestones close when their scope is shipped.

### M0 — Repo bootstrap (layer)

**Goal:** A new public repo at `gh:<user>/host-config` with all scaffolding, conventions, and CI in place. No application code yet.

**Issues (4):**

| ID | Title | Scope |
|---|---|---|
| M0-1 | Initialize repo with Apache-2.0 license and base files | LICENSE, README skeleton, `.gitignore`, `.python-version`, `pyproject.toml` with project metadata + `uv` config |
| M0-2 | Add code quality scaffolding | `ruff`, `mypy`, `pytest` config in `pyproject.toml`; `.pre-commit-config.yaml` with all hooks; `.editorconfig`; commitlint config |
| M0-3 | Add docs scaffolding | `mkdocs.yml` with Material theme; `docs/index.md`; `docs/adr/template.md` (Michael Nygard); ADR-0001 capturing the stack choices (Python 3.12, uv, FastAPI, Terraform, Ansible) |
| M0-4 | Add CI workflows and branch protection | `.github/workflows/{ci,docs}.yml` minimal — lint + type-check + docs build/deploy; Dependabot config; issue + PR templates; branch protection rules requiring signed commits + green CI on `main` |

### M1 — Netbox model + fixtures (layer)

**Goal:** Local Netbox via Docker, with custom fields for our schema, populated with one B300 host and one CPU host.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M1-1 | Ansible role: netbox-dev | Role that brings up `netbox-docker` compose stack on the target host; idempotent; exposes Netbox on a known port |
| M1-2 | Define Netbox custom fields via API | Python script using `pynetbox` to declare custom fields (`bf3_mode`, `roce_tc`, `numa_node`, `sriov_vfs`, `gpu_affinity`, `observed_mac`, `observed_firmware`); runs as a fixture-stage task |
| M1-3 | Fixture script: populate test hosts | Python script that creates one B300 host (10 NICs, 8 GPUs, full IP/VLAN/cable map) and one CPU host (2 NICs, VLANs only); deterministic MACs; idempotent |

### M1.5 — Gate: Netbox is queryable (integration)

**Goal:** Prove the fixture script produces a queryable, schema-correct host.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M1.5-1 | Component test: Netbox fixture round-trip | `tests/component/test_netbox_fixtures.py`: brings up Netbox via docker-compose, runs fixtures, queries the B300 host back, asserts 10 interfaces / correct IPs / correct VLANs / all custom fields populated |

### M2 — Renderer service (layer)

**Goal:** FastAPI service that renders Netplan + cloud-init seed for a host, given an asset tag.

**Issues (5):**

| ID | Title | Scope |
|---|---|---|
| M2-1 | Pydantic models for HostIntent | Strict-typed models: `HostIntent`, `BondMember`, `Bond`, `VlanChild`, `RoceUnderlay`, `SriovParent`; cross-field validators (exactly one default gateway; parent MTU ≥ max child MTU; etc.); jsonschema export |
| M2-2 | Netbox loader → HostIntent | `host_config.netbox.load_host(asset_tag) -> HostIntent`; wraps pynetbox; maps Netbox records onto Pydantic models; raises if intent fields missing |
| M2-3 | Jinja2 templates + emitter | Templates per role (`cpu`, `gpu-b300`) producing `meta-data`, `user-data`, `network-config`; ruamel.yaml for stable ordering; golden-file tests |
| M2-4 | FastAPI service | Routes: `/render/{asset}/meta-data`, `/render/{asset}/user-data`, `/render/{asset}/network-config`, `/healthz`, `/readyz`; dependency injection for Netbox client; error handling; OpenAPI auto-doc |
| M2-5 | Observability hooks | structlog with JSON in production; OpenTelemetry FastAPI instrumentation; Prometheus `/metrics` with request/latency/render-duration counters; no-op exporters by default |

### M2.5 — Gate: HTTP render works (integration)

**Goal:** Curl the three URLs against the live renderer and get the right content for the fixture host.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M2.5-1 | E2E component test: Netbox → Renderer → HTTP | Spin Netbox + renderer via docker-compose; populate fixtures; `curl http://localhost:8000/render/SN12345/network-config`; assert byte-equal to checked-in golden file |

### M3 — nginx proxy + cache (layer)

**Goal:** nginx in front of the renderer, with `proxy_cache_path` providing the write-through cache.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M3-1 | Ansible role: nginx-cache | Role that installs nginx, deploys our config with `proxy_cache_path`, sets up logging; idempotent; templated from variables |
| M3-2 | Cache behavior tests | Component tests: first request renders + caches; second request serves from cache without hitting renderer; 5-min TTL re-renders; Netbox-down scenario serves stale cache; manual cache-purge endpoint (`PURGE` method) |
| M3-3 | TLS/HTTPS stub for future signed-seed work | Placeholder config block + ADR documenting the future signed-seed path (HMAC headers; mTLS via smallstep); not enabled but reserved |

### M3.5 — Gate: hybrid render via nginx (integration)

**Goal:** Prove the full FastAPI + nginx cache stack behaves as designed across warm, cold, and degraded paths.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M3.5-1 | E2E test: warm/cold/Netbox-down render paths | Test scenarios end-to-end including timing assertions (warm < 50ms; cold can take longer); Netbox-down behavior validated |

### M4 — OVS + QEMU harness (layer)

**Goal:** Reproducible local lab that spins up an OVS bridge with LACP + VLAN trunk and a QEMU VM plugged into it.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M4-1 | Ansible role: ovs-harness | Installs OVS, creates bridge `br-test` with LACP partner config and VLAN trunks 100/200/300; tap interfaces pre-created for VM use |
| M4-2 | QEMU launcher (Python) | `host_config.vms.launch(asset_tag)` reads Netbox MACs, constructs the QEMU command line with mgmt NIC + nsa/nsb (and later 8 E-W NICs), supplies `ds=nocloud-net` SMBIOS; deterministic per asset tag |
| M4-3 | Cloud image preparation | Script that downloads Ubuntu 24.04 cloud image, optionally pre-installs lldpd / chrony / mlnx-ofed packages via libguestfs (so first boot is fast); image cached in `fixtures/vms/` |

### M4.5 — Gate: CPU host first-boot e2e (integration)

**Goal:** A CPU host VM boots, cloud-init fetches the rendered seed, Netplan applies, bond + 3 VLANs come up correctly.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M4.5-1 | E2E test: CPU host full first-boot | Bring up Netbox + renderer + nginx + OVS + VM; assert `bond0` in LACP-up, three VLAN children up with correct IPs/MTUs/routes; cloud-init exit status 0; test finishes in <5 min |

### M5 — 8 E-W NICs + Soft-RoCE (layer)

**Goal:** Extend the harness to the full B300-shaped 10-NIC VM with Soft-RoCE on the east-west NICs.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M5-1 | Extend QEMU launcher for 10 NICs | Adds 8 E-W virtio NICs with deterministic MACs derived from Netbox; tap interfaces auto-created; verifies host kernel supports the topology |
| M5-2 | Extend renderer for gpu-b300 role | Adds Jinja template paths for 8 RoCE underlay NIC stanzas with MTU 9000 + per-NIC IPs + `virtual-function-count: 16`; golden files added |
| M5-3 | user-data: Soft-RoCE bring-up | Cloud-init user-data block that loads `rdma_rxe`, creates `rxe_gpuN` devices on each E-W NIC, raises `memlock` limits in `/etc/security/limits.d/rdma.conf` |

### M5.5 — Gate: B300-shaped first-boot e2e (integration)

**Goal:** A 10-NIC VM boots and RDMA verbs work end-to-end via Soft-RoCE.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M5.5-1 | E2E test: B300 host full first-boot + RDMA verbs | All 10 NICs up at correct MTUs/IPs; `ibv_devinfo` lists 8 rxe devices; `rping` between gpu0 and gpu1 succeeds end-to-end |

### M6 — Terraform + Ansible for DigitalOcean (layer)

**Goal:** One-command deploy of the lab to a DigitalOcean Droplet.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M6-1 | Terraform module for DO Droplet | Provisions `s-4vcpu-8gb` Droplet, SSH key, firewall (SSH only), DO Spaces optional for cloud-image cache; outputs IPv4 + ready-to-run Ansible inventory |
| M6-2 | Ansible playbook for full lab | Single `deploy-lab.yml` that wires together netbox-dev + renderer + nginx-cache + ovs-harness roles; idempotent; one-command from a fresh Droplet to a working lab |
| M6-3 | Runbook: deploy lab to DO | `docs/runbooks/deploy-do.md` step-by-step: `terraform apply`, `ansible-playbook`, smoke test commands; expected costs and teardown procedure |

### M6.5 — Gate: lab works on DigitalOcean (integration)

**Goal:** The full M4.5 + M5.5 e2e tests pass on a real Droplet, not just on Lima.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M6.5-1 | E2E test on DO Droplet | Manual or scripted: spin Droplet, deploy lab, run e2e test suite, verify identical pass behavior, snapshot logs, teardown. Documented in the runbook as the verification step |

### M7 — GitHub Actions CI for full e2e (layer)

**Goal:** Every PR runs the entire test pyramid in <10 min.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M7-1 | `e2e.yml` workflow runs M4.5 + M5.5 on PR | KVM-enabled runners; pulls Netbox + builds renderer; runs OVS + QEMU + cloud-init e2e; reports timing; parallelization split if needed |
| M7-2 | Coverage reporting + PR comments | `pytest-cov` reports uploaded; coverage delta posted to PR; failing coverage threshold blocks merge |
| M7-3 | mkdocs site deploys to GH Pages on `main` | `docs.yml` builds the Material site, indexes ADRs and DESIGN files, deploys to `gh-pages` branch on every push to `main` |

### M7.5 — Gate: CI is the source of truth (integration)

**Goal:** Branch protection makes CI failures actually block merges; coverage drops block merges; mkdocs site stays live.

**Issues (2):**

| ID | Title | Scope |
|---|---|---|
| M7.5-1 | Branch protection finalized | Branch protection rule on `main`: required checks (lint+type-check+unit+component+integration+coverage), signed commits, 1 review on substantive PRs |
| M7.5-2 | Test failure scenarios verified | Open a deliberately broken PR (failing test); verify it cannot merge. Open a PR that drops coverage; verify it cannot merge. Open a PR with bad commit message; verify pre-commit blocks |

## Dependencies and ordering

Most milestones are strictly sequential; a few can parallelize:

- **M0 unblocks everything.**
- **M1 and M2** can start in parallel after M0, since M2's renderer can mock its Netbox calls until M1 lands. M2.5 needs both.
- **M3 depends on M2.** M3.5 depends on M3 and M2.
- **M4 depends on M0 only** (the QEMU/OVS harness is independent of the renderer). M4.5 needs M3 + M4.
- **M5 depends on M2 + M4.** M5.5 needs M5 + M3.
- **M6 depends on everything M0–M5.** It's the deployment artifact.
- **M7 depends on M6.** CI runs the same tests M6 deploys.

Critical path: M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7. Roughly linear; parallelism is bounded by review capacity, not technical dependency.

## Total issue count

~37 issues across 15 milestones (8 layer + 7 gate). Within the "larger chunks" granularity target.

## Next steps after sign-off

1. Run `gh repo create <user>/host-config --public --license apache-2.0 --description "..."` from this session (with your confirmation).
2. Create the milestones in the new repo via `gh api`.
3. Seed all ~37 issues with titles, descriptions, acceptance criteria, labels, and milestone assignments from this plan.
4. Open M0-1 as the first PR target.
5. The new repo's README links back to this plan as the durable reference; this plan becomes immutable once seeded (future changes via ADRs in the new repo).
