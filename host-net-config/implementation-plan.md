# Implementation plan — `host-config` repo

> Durable planning artifact for the `host-config` GitHub repository. Captures the engineering philosophy, repo charter, code and quality conventions, testing strategy, observability strategy, milestone plan, and decision-log seed for the implementation of the Tier 1 host network configuration pipeline.
>
> This document is **immutable once seeded into the new repo**. Future changes happen via ADRs in `host-config`, not by editing this plan.

---

## 1. Charter

`host-config` is a **public, Apache-2.0** GitHub repository under the same user account as this research repo. It holds the production-grade code, infrastructure, and deployment configuration for the host network configuration pipeline described in [`baremetal-network-overview.md`](baremetal-network-overview.md) and tested per [`test-strategy.md`](test-strategy.md).

**Initial scope (this plan):** Tier 1 only — Netbox model + fixtures, on-demand renderer service, nginx cache layer, OVS+QEMU test harness, cloud-init NoCloud integration, Soft-RoCE for east-west verbs validation, and a deployable lab on a DigitalOcean Droplet.

**Explicitly out of initial scope:** Tier 2 hardware-test orchestration code, Tier 3 LaunchPad workflows, day-2 reconciliation agent, CNI / K8s overlay work (added later as a separate top-level module without restructuring), production-grade seed signing / mTLS, multi-host scenarios.

---

## 2. Engineering principles (the durability mindset)

These are the load-bearing values. Every other decision in this plan derives from them.

1. **Code is read 10× more than it's written.** Optimize for the reader. If a clever one-liner would take two minutes to understand, the four-line obvious version wins.
2. **Public contracts are forever; implementations are disposable.** Anything that crosses a module boundary (Pydantic models, REST routes, CLI invocations, library APIs, config-file shapes) is a contract. Treat its design with the seriousness of a versioned, semver-bound API.
3. **Documentation is the artifact that outlives turnover.** A team's understanding evaporates over years. The text that explains *why* is what survives. Code comments, docstrings, ADRs, and DESIGN files are the durable medium.
4. **Tests are the executable specification.** Tests describe what the system promises. A new contributor should learn what a function does by reading its tests, not by guessing from its name.
5. **Logs are the post-mortem evidence.** When a 3am incident happens and the engineer on call has no context, the structured logs are the substrate they reconstruct reality from. Logs are debugging affordances, not afterthoughts.
6. **Failure modes are first-class design subjects.** What does this function do when its dependency is down? When its inputs are malformed? When it's called concurrently? When the disk is full? These are designed for, not discovered.
7. **Reproducibility is a feature.** Identical inputs produce identical outputs, regardless of time, machine, or network. Time, randomness, and external state are injected dependencies, not implicit globals.
8. **Boring technology wins.** Choose the technology that will still be supported, hireable-for, and patched in ten years. Resist novelty unless the alternative materially fails the durability test.
9. **One way to do common things.** Every common operation (run tests, format code, build docs, deploy) has exactly one entry point. Multiple competing ways are technical debt the day they ship.
10. **Quality is preserved, not retrofit.** Linting, type-checking, coverage gates, ADR-on-design-change discipline — all enforced from the first commit. Retrofitting them onto an established codebase is several engineer-years of work.
11. **Leave no trace.** Every operation that provisions a resource is paired with the operation that destroys it. Every run starts with nothing and ends with nothing — no orphaned containers, no leftover Droplets, no `/tmp` debris. Cleanup runs on failure as reliably as on success.

---

## 3. Stack choices

| Choice | Selection | Rationale |
|---|---|---|
| Language | **Python 3.12** | Mature, stable, broad ecosystem for both web service and infrastructure scripting. 3.13's free-threaded mode is interesting but ecosystem support is partial. Pin to 3.12 for ecosystem maturity. ADR-0001 |
| Package manager | **uv** | Single tool covering env, deps, lockfile, run, project. Replaces pip+venv+pip-tools+poetry+pipx with one fast, well-engineered binary. Maintained by Astral (also `ruff` makers). ADR-0002 |
| Web framework | **FastAPI** | Pydantic-native, async, generates OpenAPI from types automatically. The "obvious choice" for production Python HTTP services in 2026. ADR-0003 |
| Validation / models | **Pydantic v2** | The de-facto Python schema framework. Already pervasive; integrates with FastAPI. Strict mode + custom validators give us strong invariants. ADR-0003 |
| Templating | **Jinja2** | Boring, ubiquitous, mature. ADR-0003 |
| Linter + formatter | **ruff** | Replaces flake8 + isort + pyupgrade + black with one fast tool. Astral-maintained, actively developed. ADR-0004 |
| Type checker | **mypy --strict** | More mature, broader ecosystem support, fewer edge cases than pyright. Slower CI but acceptable. ADR-0004 |
| Test runner | **pytest** | The Python test standard. ADR-0005 |
| Property-based testing | **Hypothesis** | For invariant-based testing of models and renderer. ADR-0005 |
| Test containers | **testcontainers-python** | For component tests against real Netbox / nginx containers. |
| Provisioning + configuration | **Ansible** (with `community.digitalocean` for cloud provisioning) | Single tool covering both DO Droplet provisioning and in-host configuration. One mental model, one tool to install, one config style. ADR-0006 |
| Container runtime (dev) | **Docker** | Broadest ecosystem; testcontainers integration is best. Could revisit Podman later. |
| Secret management (dev) | Gitignored **`.env`** file; `.env.example` committed; `just` targets source the file explicitly | Plain shell-sourced env file; no external tool dependency. README documents which variables are required and how to obtain each value. |
| Task runner | **just** | Cleaner than Make for non-build tasks; cross-platform; single-file. ADR-0007 |
| Documentation | **GitHub-rendered Markdown** in `docs/`; SVG diagrams in `docs/diagrams/` (Excalidraw sources + exported SVG) | No build step, no hosting dependency, no separate doc framework to maintain. GH renders Markdown natively and the SVGs embed inline. Simpler is more durable. ADR-0008 |
| Observability — logs | **structlog** | Structured logging is non-negotiable for production. structlog gives clean Python ergonomics. ADR-0009 |
| Observability — metrics | **prometheus-client** | Plain Prometheus text format at `/metrics`; standard, no agent dependency. ADR-0009 |
| CI | **GitHub Actions** | Same platform as the repo; KVM available on hosted runners; free tier sufficient. ADR-0010 |

**Deferred — future enhancements** (captured here so they're not lost):

- **Distributed tracing via OpenTelemetry.** Add when a second service exists (e.g., the CNI module on top of host-config). For Tier 1, `structlog` correlation IDs already let us trace a single request through the one service we have.
- **Mutation testing via `mutmut`.** Add when the code surface stabilizes (after M7.5). Until then, coverage + integration tests for user-facing scenarios are the quality bar.

---

## 4. Repo structure

```
host-config/
├── README.md                       # what this is, prereqs, quickstart, links
├── LICENSE                         # Apache-2.0
├── CHANGELOG.md                    # auto-generated from conventional commits
├── CODE_OF_CONDUCT.md              # Contributor Covenant 2.1
├── CONTRIBUTING.md                 # how to contribute, dev setup, PR flow
├── CODE_CONVENTIONS.md             # the living rulebook (§5 of this plan)
├── SECURITY.md                     # how to report vulnerabilities
├── justfile                        # one-line entry points for every common task
├── pyproject.toml                  # uv-managed; Python 3.12; tool configs
├── uv.lock                         # committed
├── .python-version
├── .pre-commit-config.yaml
├── .env.example                    # template; real .env is gitignored
├── .gitignore
├── .gitattributes                  # consistent line endings, binary marks
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  # lint, type-check, unit, component
│   │   ├── e2e.yml                 # full pipeline e2e on PR
│   │   ├── docs-links.yml          # broken-link + missing-SVG checker
│   │   └── deps.yml                # dependabot + uv lock refresh
│   ├── ISSUE_TEMPLATE/             # layer-task.md, gate-test.md, bug.md, design-discussion.md
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
│
├── docs/                           # GitHub-rendered Markdown
│   ├── index.md                    # entry point (also linked from README)
│   ├── architecture/               # systems overview, sequence flows, component contracts
│   │   └── systems-overview.md     # the living architecture doc (mirrors ADR-0011)
│   ├── adr/                        # 0001-..., 0002-..., immutable once landed
│   │   └── template.md             # Michael Nygard format
│   ├── runbooks/                   # operational playbooks
│   └── diagrams/                   # SVG diagrams + Excalidraw sources
│       └── README.md               # how to author and export diagrams
│
├── infra/
│   └── ansible/                    # provisioning (DO Droplet) + in-host bootstrap
│       ├── playbooks/
│       │   ├── provision.yml       # creates the Droplet via community.digitalocean
│       │   └── deploy-lab.yml      # configures the Droplet (composes roles below)
│       ├── roles/
│       │   ├── netbox-dev/
│       │   ├── renderer/
│       │   ├── nginx-cache/
│       │   ├── ovs-harness/
│       │   └── qemu-host/
│       ├── inventory/
│       │   └── digitalocean.yml
│       └── README.md
│
├── src/host_config/                # the renderer service (Python package)
│   ├── __init__.py                 # version, package-level __all__
│   ├── errors.py                   # custom exception hierarchy
│   ├── logging_config.py           # structlog setup, single source of truth
│   ├── observability/
│   │   ├── __init__.py
│   │   └── metrics.py              # Prometheus collectors
│   ├── models/
│   │   ├── __init__.py
│   │   ├── intent.py               # HostIntent + role-specific variants
│   │   ├── interface.py            # PhysIface, Bond, VlanChild, RoceUnderlay, SriovParent
│   │   └── validators.py           # cross-field validators
│   ├── netbox/
│   │   ├── __init__.py
│   │   ├── client.py               # pynetbox wrapper (typed)
│   │   ├── loaders.py              # Netbox record → HostIntent
│   │   └── schema.py               # custom field definitions
│   ├── render/
│   │   ├── __init__.py
│   │   ├── templates/              # Jinja2 templates per role
│   │   │   ├── cpu/
│   │   │   └── gpu-b300/
│   │   ├── emitter.py              # template → text bytes
│   │   └── golden/                 # checked-in expected outputs for fixtures
│   └── service/
│       ├── __init__.py
│       ├── app.py                  # FastAPI app construction
│       ├── routes.py               # route handlers
│       ├── middleware.py           # request_id, logging, metrics
│       └── dependencies.py         # FastAPI DI providers
│
├── tests/
│   ├── conftest.py                 # shared fixtures, container management
│   ├── unit/
│   │   ├── models/
│   │   ├── netbox/
│   │   ├── render/
│   │   └── service/
│   ├── component/                  # against real Netbox container
│   │   ├── netbox/
│   │   ├── render/
│   │   └── service/
│   ├── integration/                # cross-module
│   └── e2e/                        # full pipeline (gate-milestone tests)
│
├── fixtures/
│   ├── netbox/
│   │   ├── populate.py             # idempotent fixture loader
│   │   └── data/                   # YAML descriptions of fixture hosts
│   └── vms/
│       ├── launch.py               # QEMU launcher
│       └── images/                 # downloaded cloud images (gitignored)
│
└── scripts/                        # one-shot dev convenience
    ├── bootstrap-lima.sh
    ├── bootstrap-mac.sh
    └── ...
```

**Why this shape:**

- **Source under `src/host_config/`** (not flat) — prevents accidental "tests/imports from project root work because they run from the repo dir" foot-gun. Forces installed-package semantics.
- **Module-per-domain** (`models/`, `netbox/`, `render/`, `service/`, `observability/`) — each module has one reason to change.
- **`errors.py` per package** — custom exceptions colocated with the code that raises them.
- **`golden/` for renderer outputs** — checked-in expected bytes; every change to renderer requires updating goldens, which forces a review of output drift.
- **Module-level design rationale lives in code** — module docstrings, function docstrings, and ADRs are the durable record. No separate `DESIGN.md` per module; the systems-overview doc (ADR-0011) and per-decision ADRs carry cross-module rationale.
- **`docs/adr/`** — numbered, dated, immutable; this is the load-bearing "why we did it that way" record.
- **`docs/diagrams/`** — SVG files (committed) alongside their Excalidraw sources, so anyone can edit and re-export. Referenced from MD via `![alt](../diagrams/foo.svg)`. See §8.4.
- **`fixtures/` separated from `tests/`** — fixtures are reusable data; tests are the assertions.

---

## 5. Code conventions

These are concrete rules — what `CODE_CONVENTIONS.md` in the new repo will say.

### 5.1 File organization

- **Every file declares its scope in a module-level docstring** at the top. Two sentences minimum: what this module is responsible for, and what it explicitly is not.
- **File length budget: ~400 lines (soft cap).** Exceeding this is a smell. Either the file has too much responsibility or a function is over-budget.
- **One primary class per file** when classes are involved. Tightly coupled helper classes can share a file.
- **Standard intra-file ordering:**
  1. Module docstring
  2. `from __future__ import annotations`
  3. Standard library imports
  4. Third-party imports
  5. First-party imports
  6. Module-level constants
  7. Type aliases
  8. Public functions/classes (in order of importance)
  9. Private functions (prefixed `_`)
  10. `__all__` declaration at the bottom listing public API

### 5.2 Function conventions

- **Single responsibility.** A function does one thing. The one thing might be "orchestrate three other functions" — that's fine — but it's still one thing.
- **Function length budget: ~50 lines (soft cap).** If a function exceeds this, factor.
- **Cyclomatic complexity ≤ 10** (enforced by `ruff` rule `C901`).
- **Pure functions preferred.** When a function has side effects (I/O, mutation, time), name and document them explicitly.
- **Dependency injection.** External state (clock, random, network client, file system) is passed in, not imported globally. This makes functions testable without monkeypatching.

### 5.3 Docstring style

Google style, extended with `Approach` and `Scenarios`. Every public function has a full docstring. Private helpers have at least a one-line summary.

```python
def render_network_config(
    intent: HostIntent,
    templates_dir: Path,
    *,
    now: Callable[[], datetime] = datetime.utcnow,
) -> bytes:
    """Render the cloud-init network-config YAML for a host.

    Approach:
        Selects the Jinja2 template directory for the host's role,
        constructs a deterministic Jinja environment (autoescape off
        for YAML, undefined raises), and renders the template against
        the intent. The output is post-processed via ruamel.yaml to
        produce stable key ordering, ensuring byte-deterministic
        output across runs given identical input.

    Args:
        intent: A validated `HostIntent` for the target host. Must
            already have passed all cross-field invariants (e.g.,
            exactly one default gateway).
        templates_dir: Root of the templates tree. Expected to contain
            a subdirectory matching `intent.role`.
        now: Callable returning the current UTC datetime. Injected
            for testability. Default: `datetime.utcnow`.

    Returns:
        UTF-8 encoded bytes of the rendered YAML, suitable for direct
        delivery as a cloud-init `network-config` file.

    Raises:
        TemplateNotFoundError: No template directory exists for
            `intent.role`.
        RenderError: The Jinja template raised a `UndefinedError` or
            similar — usually indicates the intent lacks a field the
            template expected.

    Scenarios:
        - Happy path: cpu role intent → produces parseable YAML with
            bond0 + three VLAN children.
        - Happy path: gpu-b300 role intent → produces YAML with all
            10 NICs configured.
        - Missing role template → raises TemplateNotFoundError with
            the offending role name.
        - Intent missing a required field → raises RenderError with
            the field name in the message.
        - Same intent rendered twice → byte-identical output (tested
            via golden-file comparison).
        - now() returning a fixed timestamp → embedded timestamp in
            output matches (tests determinism).

    Example:
        >>> intent = HostIntent(role="cpu", ...)
        >>> output = render_network_config(intent, Path("templates"))
        >>> assert b"bond0.100" in output
    """
```

**The `Scenarios:` block is load-bearing.** It is the spec the test file implements. A reviewer reading the docstring knows what tests must exist; a contributor writing tests has a checklist.

### 5.4 Inline comments

- **Prefer "why" over "what."** The code already says what; comments explain the rationale.
- **Use prefixed tags** for searchability:
  - `# WHY: ...` — explains a non-obvious decision
  - `# NOTE: ...` — caller-relevant context (e.g., "this assumes input is sorted")
  - `# SAFETY: ...` — invariant that must hold; explains why something is safe
  - `# TODO(#issue): ...` — must reference an open issue; ungrounded TODOs blocked by pre-commit
  - `# HACK: ...` — known workaround; should link to the issue tracking proper fix
- **Reference ADRs, RFCs, issue numbers** where context lives elsewhere.
- **Document non-obvious trade-offs at the decision site.** A reader two years from now should not have to do archaeology to understand why we chose `layer3+4` hash policy over `layer2+3`.

Example:

```python
# WHY: We hash on layer3+4 (not the bonding default of layer2)
# because both bond members face the same logical LACP partner
# (the ESI-LAG pair). Layer2 hashing collapses all traffic to
# one slave; layer3+4 spreads flows by 5-tuple. See ADR-0014.
parameters: dict[str, Any] = {
    "mode": "802.3ad",
    "transmit-hash-policy": "layer3+4",
}
```

### 5.5 Naming

- **Modules:** `snake_case`, descriptive. No `utils.py`, `helpers.py`, `common.py`, `misc.py`. Every module name is a noun describing what lives there.
- **Public functions:** `verb_noun` form. `render_network_config`, `load_host_from_netbox`, `build_intent`.
- **Private functions:** `_prefix` (single underscore).
- **Constants:** `SCREAMING_SNAKE_CASE`, module-level only.
- **Types:** `PascalCase`. `HostIntent`, `BondMember`, `RenderError`.
- **Type aliases:** `PascalCase` followed by `Type` only when ambiguous. Prefer `AssetTag = NewType("AssetTag", str)` over `AssetTagType = ...`.

### 5.6 Error handling

- **Specific exception classes per failure scenario.** No bare `Exception` raises. Defined in `errors.py` per package.
- **Errors carry context.** Exception messages include the operation being attempted and the relevant identifiers (asset tag, host name, etc.).
- **No bare `except:`.** Specific catches only. Re-raise unless explicitly handled.
- **Retry policies are configurable, not implicit.** Use `tenacity` for retry logic; configure timeouts, max attempts, and backoff explicitly.
- **Errors at module boundaries are typed.** A function that calls Netbox should not let `requests.exceptions.HTTPError` leak out; wrap into `NetboxQueryError`.

```python
# src/host_config/netbox/errors.py
class NetboxError(Exception):
    """Base class for all Netbox-related errors."""

class NetboxQueryError(NetboxError):
    """Netbox query failed (timeout, 5xx, etc.)."""
    def __init__(self, asset_tag: str, operation: str, cause: Exception) -> None:
        super().__init__(
            f"Netbox query failed for asset_tag={asset_tag} "
            f"during operation={operation!r}: {cause}"
        )
        self.asset_tag = asset_tag
        self.operation = operation
        self.cause = cause
```

### 5.7 Concurrency and side effects

- **Async is opt-in, not pervasive.** FastAPI routes are `async def`; downstream blocking I/O (pynetbox) runs in a thread pool via `asyncio.to_thread`. Don't make pure logic async.
- **No global mutable state.** Configuration is passed in at startup; runtime state lives in well-defined objects.
- **Time, randomness, and external state are injected.** Functions take `now: Callable[[], datetime]` arguments where time matters; tests substitute fixed values.

---

## 6. Testing strategy

### 6.1 Pyramid composition

Each milestone produces tests at every applicable level. The pyramid is the shape, not just the goal.

| Level | % of suite (rough) | Scope | Speed | Network/Container |
|---|---|---|---|---|
| Unit | ~60% | Single function or tightly coupled function group | <50 ms each | None |
| Component | ~25% | One module against real downstream container (Netbox, nginx) | <2 s each | testcontainers |
| Integration | ~10% | Multiple modules wired together; mocks at the system edge | <10 s each | testcontainers |
| E2E | ~5% | Full pipeline; gate-milestone tests | <5 min each | Full lab via OVS+QEMU |

### 6.2 Test conventions

- **File structure mirrors source.** `src/host_config/render/emitter.py` → `tests/unit/render/test_emitter.py`. Searchability matters.
- **Test names: `test_<scenario>_<expected>`.** Examples: `test_missing_mac_raises_clear_error`, `test_idempotent_render_produces_same_bytes`. A reader scanning failed tests should know what broke from the name alone.
- **Each function's docstring `Scenarios:` block enumerates required tests.** A new test must correspond to a scenario in the docstring; a new scenario must produce a test.
- **Parametrize liberally.** Don't write 8 nearly-identical test functions; parametrize one.
- **One assertion per test (soft rule).** Multi-assertion tests are OK when they describe one logical observation, but prefer splitting.

### 6.3 Property-based testing (Hypothesis)

For functions with non-trivial invariants — model validators, renderers, anything that should hold for "any valid input."

- Generate arbitrary `HostIntent` objects; assert no IP duplications, MTU monotonicity (parent ≥ child), exactly one default gateway.
- Generate arbitrary VLAN sub-interface configurations; assert renderer never emits invalid Netplan YAML (re-parseable by Netplan).
- Generate arbitrary asset tags; assert the renderer never panics, only raises the documented exception types.

### 6.4 Mutation testing — deferred

Mutation testing (e.g., `mutmut`) is a meaningful test-quality signal but adds noise on early-stage code. **Add after M7.5**, once the code surface stabilizes. The quality bar until then is: coverage on key functions and flows + mandatory integration tests for user-facing scenarios (§6.8). Captured as a deferred enhancement so it isn't lost.

### 6.5 Test infrastructure

- **`testcontainers-python`** for Netbox / nginx in component and integration tests. Containers are reused across tests in a module via session-scoped fixtures where state isolation allows.
- **`pytest-xdist`** for parallel execution across CPU cores.
- **`pytest-timeout`** with global 30s cap (overrideable per test) to catch hangs.
- **Fixtures live in `conftest.py` at the lowest common ancestor.** Don't duplicate.
- **Markers:** `@pytest.mark.fast` (unit only; runs in pre-commit), `@pytest.mark.slow` (component+), `@pytest.mark.e2e` (full pipeline), `@pytest.mark.requires_kvm` (skipped on non-KVM CI).

### 6.6 What we deliberately don't test

- **Trivial getters/setters.** No.
- **Pydantic's own serialization.** Pydantic has its own tests.
- **Third-party library contracts.** Trust the contract; test our usage of it.
- **Implementation details that aren't part of the contract.** Tests should survive refactors that don't change behavior.

### 6.7 Coverage stance

**Principle:** test the things that matter. Don't game the coverage number.

- **Unit tests cover key functions and key flows.** "Key" is judgment-driven: anything with non-trivial logic, branching, error handling, or cross-module contracts. Trivial getters, Pydantic-emitted boilerplate, and pure delegation methods don't require dedicated unit tests.
- **Every user-facing scenario has an integration test.** (See §6.8 below — this is the load-bearing rule.)
- **Line coverage is reported, not gated at a single number.** We track it (target ~75% on `src/host_config/`; ~60% on Ansible-linted infra) but won't add filler tests just to hit a number. A PR-level *drop* of >2% is reviewed but not auto-blocked.
- **Reviewers may require tests for code that lacks them**, regardless of coverage number, if the code is non-trivial.
- **Mutation testing** (`mutmut`) is a deferred quality enhancement (see §6.4) and will complement coverage once added.

### 6.8 User-facing scenarios — integration tests mandatory

Every scenario in this list **must** have at least one integration test. New user-facing scenarios get new integration tests as part of the same PR — no "we'll add the test later."

User-facing surfaces:

1. **HTTP renderer endpoints.** Each route × happy path × representative error paths.
   - `GET /render/<asset>/meta-data` for `cpu` role → 200 with valid YAML.
   - `GET /render/<asset>/user-data` for `gpu-b300` role → 200 with valid cloud-config.
   - `GET /render/<asset>/network-config` for both roles → 200 with byte-equal-to-golden output.
   - `GET /render/<unknown>/*` → 404 with structured error JSON.
   - `GET /render/<asset>/*` with Netbox down → appropriate 5xx + error JSON; logs preserve context.
   - `GET /healthz` → 200 while running.
   - `GET /readyz` → 200 when Netbox reachable, 503 with reason when not.
   - `GET /metrics` → 200 with valid Prometheus exposition format.
2. **nginx cache behavior** for each endpoint.
   - Cold path: first request renders.
   - Warm path: second request within TTL serves from cache, renderer not invoked.
   - Expiry: request after TTL re-renders.
   - Netbox-down + cache hit → still serves successfully from cache.
   - Manual cache purge endpoint → next request re-renders.
3. **Cloud-init NoCloud first-boot** per role.
   - CPU host: VM boots, fetches via nginx, applies Netplan, bond + 3 VLANs come up.
   - gpu-b300 host: same plus 8 east-west NICs + Soft-RoCE devices.
4. **Lab lifecycle end-to-end** on Lima and on DO Droplet.
   - `just lab-up` from cold start → fully working lab.
   - `just lab-test` → all e2e tests pass.
   - `just lab-down` → all resources reclaimed; no orphaned containers, Droplets, or volumes (verified by listing).
5. **Fixture loader and Netbox schema apply.**
   - Apply schema twice → idempotent.
   - Populate fixtures twice → idempotent.
   - Populate against an already-populated Netbox → conflict raises typed error with clear message.

This list is the canonical contract surface for the Tier 1 system; if you add a new contract, add it here in the same PR.

---

## 7. Observability strategy

### 7.1 Logging philosophy

- **Structured exclusively.** Every log line is key-value pairs (JSON in production, console-friendly in dev). No f-string interpolation into a single message string for variables.
- **Logs tell a story.** A reader following a single request through the logs from receive to response should understand exactly what happened, in order, with timing.
- **One source of truth for log config:** `src/host_config/logging_config.py`. All modules use `structlog.get_logger(__name__)`; the config module wires up processors, levels, and outputs.

### 7.2 Log levels

| Level | When to use |
|---|---|
| `TRACE` | Function entry/exit with arguments. Off in production; on for "wtf is happening" debugging. (Custom level; mapped to DEBUG-1.) |
| `DEBUG` | Intermediate state inside non-trivial operations. Key decision points. Enable to follow a request through the system. |
| `INFO` | Lifecycle events: process start, request received, request completed, cache miss/hit, render succeeded. Default level in production. |
| `WARN` | Degraded operation. Will continue, but operator should know (e.g., Netbox query slow, cache eviction rate high). |
| `ERROR` | Operation failed with bounded blast radius. Single request errored; system continues. |
| `CRITICAL` | Process must exit or take drastic action. Rare. |

### 7.3 Correlation IDs

Every request gets:
- `request_id` (UUID, generated in middleware, returned in response header `X-Request-Id`).
- `asset_tag` (from URL path, bound into context for all logs in this request).
- `render_id` (generated when rendering starts; binds the renderer subprocess's logs).

Bound via `structlog.contextvars.bind_contextvars`; every log line in the request scope automatically includes these fields.

### 7.4 Log fields by domain

Standard fields every log includes (set by middleware/config):
- `timestamp` (ISO 8601 UTC)
- `level`
- `logger` (module path)
- `event` (the message identifier, short)
- `request_id`, `asset_tag`, `render_id` (when applicable)

Domain-specific:
- **Renderer:** `template_name`, `output_bytes`, `duration_ms`, `golden_match` (bool)
- **Netbox client:** `endpoint`, `params`, `duration_ms`, `status_code`, `result_count`
- **Service middleware:** `method`, `path`, `status_code`, `duration_ms`, `user_agent`
- **Cache:** `cache_key`, `hit` (bool), `age_seconds`

### 7.5 Debug-level traceability requirement

**Concrete acceptance criterion:** with `LOG_LEVEL=DEBUG` set, a single request to `/render/SN12345/network-config` produces logs that let an engineer reconstruct:

1. Request received with what asset tag, what request_id.
2. Cache check, hit/miss, reason.
3. (If miss) Netbox query started, completed in X ms, returned record with what shape.
4. Pydantic model construction started, validators passed.
5. Template selection: which role, which template directory.
6. Render started, completed in X ms, produced N bytes.
7. Response sent with what status, what byte count, total request duration.

This is testable: the test asserts the expected log events occur in order with the right key fields.

### 7.6 Metrics (Prometheus)

Exposed at `/metrics`. Following Prometheus conventions:

- **Counters:**
  - `host_config_requests_total{method, path, status}`
  - `host_config_renders_total{role, outcome}` (outcome: success, validation_error, netbox_error, template_error)
  - `host_config_cache_events_total{type}` (type: hit, miss, evict, error)
- **Histograms:**
  - `host_config_request_duration_seconds{method, path}`
  - `host_config_netbox_query_duration_seconds{endpoint}`
  - `host_config_render_duration_seconds{role}`
- **Gauges:**
  - `host_config_active_requests`
  - `host_config_cache_size_bytes`

Every metric is documented in `src/host_config/observability/metrics.py` with the rationale for its existence (what question does this answer?).

### 7.7 Distributed tracing — deferred

OpenTelemetry instrumentation pays no rent in a single-service system; structured logs with correlation IDs already let an engineer follow a request end-to-end through the one process we have. **Add when a second service joins the system** (e.g., the CNI module). Captured here so it isn't lost; the future ADR will specify spans around `netbox.query`, `intent.build`, and `render.template`.

### 7.8 Health endpoints

- `/healthz` — liveness; returns 200 if the process is running.
- `/readyz` — readiness; returns 200 only if Netbox is reachable AND the cache directory is writable. Returns 503 with a JSON body describing which check failed.

---

## 8. Workflow conventions

- **Branch naming:** `<type>/<short-slug>` where type is one of `feat`, `fix`, `docs`, `chore`, `refactor`, `test`. Optional issue number suffix.
- **Commit messages:** Conventional Commits format, enforced via `commitlint` pre-commit hook. Body required for non-trivial changes; references linked issue.
- **PR title:** Same Conventional Commit format as the commit. Squash-merge preserves it.
- **Code review:** Self-review acceptable for trivial changes (docs typos, dependency bumps); substantive changes require a deliberate "looks good" comment + green CI + signed commits.
- **GPG signing:** Required on `main` (branch protection enforces).
- **Issue labels:**
  - `milestone:M0`–`milestone:M7.5`
  - `area:infra`, `area:renderer`, `area:fixtures`, `area:docs`, `area:tests`, `area:observability`, `area:ci`
  - `kind:feat`, `kind:test`, `kind:bug`, `kind:docs`, `kind:design`
  - `priority:p0`–`p2`
- **Definition of done:** Issue's acceptance criteria checked off; tests written; coverage doesn't regress meaningfully; docstring/README/ADR updated where relevant; merged to `main`; CHANGELOG entry generated.

### 8.1 ADR practice

- **When to write an ADR:** Any decision that crosses module boundaries, affects public contracts, or chooses between credible alternatives. If you'd struggle to explain the choice to a new contributor in two minutes, write the ADR.
- **Format:** Michael Nygard — Context, Decision, Consequences. Optional: Alternatives Considered.
- **Immutable once landed.** To change a decision, write a new ADR that supersedes the old one. The old ADR stays in the repo with a "Superseded by ADR-NNNN" note.
- **Numbered sequentially.** Filename: `0001-initial-stack-choices.md`.

### 8.2 Pre-commit gates

Every commit (locally and on CI re-check):
- `ruff check` (lint)
- `ruff format --check` (formatting)
- `mypy --strict` on changed files
- `gitleaks` (secret scanning)
- Commit message lint (`commitlint`)
- File size check (no >1 MB files without explicit allow)
- YAML/JSON validation on changed files

Tests run in CI on push, not in pre-commit — keeps the local commit loop fast; CI catches regressions within ~30 seconds of push.

### 8.3 CI gates

Every PR:
- All pre-commit checks repeated.
- `mypy --strict` on full codebase.
- Full `pytest` (unit + component + integration).
- Coverage report (informational drop alert at >2%; not auto-blocking — see §6.7).
- All integration tests for user-facing scenarios (§6.8) pass.
- `pip-audit` (security advisory scan).
- Conventional commit lint on PR title.
- Broken-link check on `docs/` Markdown and SVG references.
- For `main` branch: signed commits enforced; e2e tests must pass.

### 8.4 SVG diagram convention

Diagrams live in `docs/diagrams/`:

- **Source of truth:** Excalidraw `.excalidraw` files committed alongside their **exported `.svg` files**. Both are versioned.
- **Embedding:** Markdown references the SVG with relative path: `![systems overview](../diagrams/systems-overview.svg)`. GitHub renders this inline.
- **Editing:** open the `.excalidraw` in [excalidraw.com](https://excalidraw.com), edit, re-export `.svg` next to it, commit both.
- **Convention:** every architectural ADR includes at least one SVG when interactions or topology are involved. The companion `docs/architecture/<topic>.md` documents the latest state with the same SVG.
- **`docs/diagrams/README.md`** explains this convention so contributors aren't left guessing.

### 8.5 Secrets management

- **Real secrets are never committed.** A gitignored `.env` file holds local secrets — for example: `NETBOX_API_TOKEN`, `DIGITALOCEAN_TOKEN`, `SSH_KEY_FINGERPRINT`.
- **`.env.example`** is committed. It lists every required variable with a placeholder value and a one-line comment explaining what it's for.
- **README.md** has a `## Configuration` section that:
  - Names each secret and its purpose.
  - Shows how to obtain it (e.g., "Get your DO token at <link>").
  - Documents the local-file setup: `cp .env.example .env && $EDITOR .env`.
- **`just` targets source the file explicitly** with `set -a; source .env; set +a` so every task runs with the env loaded. No external tool dependency.
- **CI uses GitHub Actions secrets**, never `.env`. Required workflow secrets are documented in `docs/runbooks/ci-secrets.md`.

### 8.6 Resource lifecycle discipline ("leave no trace")

Principle 11 (§2) made concrete: every operation that brings a resource into existence is paired with the operation that destroys it. Reliable cleanup is a design feature, not a checklist item.

- **Test fixtures**: use pytest `yield` fixtures or context managers; teardown runs on both success and exception. Component-test containers are torn down at session end via `addfinalizer`.
- **Local shell wrappers (`just`)**: `just lab-up` and `just lab-down` are the inverse pair. `just lab` (no suffix) runs up → test → down with a `trap` ensuring `lab-down` runs even on script failure or SIGINT.
- **Ansible provisioning**: `just lab-down` runs the inverse Ansible play (destroys the Droplet via the DO module) and verifies via the DO API that no Droplet remains tagged with our workspace.
- **CI**: every workflow that provisions external resources has an `if: always()` teardown step. The DO-Droplet e2e workflow uses `always()` to call `just lab-down`.
- **Verification step in the M6.5 gate** (see §9): explicitly list DO resources before and after a lab run; the difference must be zero.
- **Local debris**: `just clean` removes `/tmp/seedsrv`, OVS bridges, tap interfaces, cached VM images. Documented in the README.

### 8.7 Plan ↔ GitHub issues linking (bidirectional)

For navigability across the implementation plan and the issue tracker:

- **In this plan**: after issues are seeded, each row in the milestone tables in §9 gets a hyperlink from the issue ID column to the corresponding GitHub issue URL. Example: `[M0-1](https://github.com/<user>/host-config/issues/N)`.
- **In each GitHub issue**: the issue body opens with a `**Plan reference:**` line linking back to the relevant subsection of this plan via its commit-pinned URL on GitHub. Example: `Plan reference: [§9 — M0 — Repo bootstrap](https://github.com/<user>/research/blob/<commit>/host-net-config/implementation-plan.md#m0--repo-bootstrap-layer)`.
- **Stability**: links use commit SHAs (not `main`) so they don't break when the plan is edited. If the plan is amended after seeding, the relevant issues are updated to point at the new commit.
- **Tooling**: the `gh issue create` calls in the seeding script template the issue body with both the plan reference and the standard issue template.

---

## 9. Milestone plan

8 horizontal layer milestones (M0–M7) + 7 integration gate milestones (M1.5–M7.5). Open-ended dates — milestones close when their scope is shipped.

### M0 — Repo bootstrap (layer)

**Goal:** A new public repo at `gh:<user>/host-config` with all scaffolding, conventions, ADRs for initial choices, and CI in place. No application code yet — but everything needed to start writing it.

**Issues (5):**

| ID | Title | Scope |
|---|---|---|
| M0-1 | Initialize repo with scaffolding and quality tooling | LICENSE (Apache-2.0), README skeleton, `.gitignore`, `.gitattributes`, `.python-version`, `pyproject.toml` (with `ruff`, `mypy --strict`, `pytest`/`pytest-cov` config), `CHANGELOG.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.env.example`, `justfile` with placeholder targets, `.pre-commit-config.yaml` with all hooks (ruff, mypy, gitleaks, commitlint, file-size, yaml validation), `.editorconfig` |
| M0-2 | Write `CODE_CONVENTIONS.md` | Authoritative version of §5 of this plan, lifted into the repo. Living document, edits via PR |
| M0-3 | Set up `docs/` structure | `docs/index.md` (entry point, also linked from README); `docs/architecture/` skeleton with placeholder; `docs/adr/template.md` (Michael Nygard format); `docs/runbooks/` skeleton; `docs/diagrams/README.md` explaining the SVG+Excalidraw convention. No build tool — Markdown is rendered by GitHub |
| M0-4 | Write initial ADRs 0001–0011 | The eleven ADRs documented in §11. ADR-0011 (systems overview) includes an SVG component diagram and an SVG sequence diagram, mirrored as the living `docs/architecture/systems-overview.md`. ADR-0012 (deferred signed-seed path) ships later in M3-4 when its context lands |
| M0-5 | Configure CI workflows and branch protection | `.github/workflows/ci.yml` (lint+type+unit+component+coverage); placeholder `e2e.yml`; Dependabot config; issue and PR templates; CODEOWNERS. Branch protection rule on `main`: required checks, signed commits, 1 review on substantive PRs (self-review allowed for trivial). Documented in `CONTRIBUTING.md` |

### M1 — Netbox model + fixtures (layer)

**Goal:** Local Netbox via Docker, with custom fields for our schema, populated with one B300 host and one CPU host. Every population step is logged at INFO; the fixture is idempotent.

**Issues (4):**

| ID | Title | Scope |
|---|---|---|
| M1-1 | Ansible role: `netbox-dev` | Brings up `netbox-docker` compose stack; idempotent; exposes Netbox on configurable port; role README explains boundaries and inputs; logs every action |
| M1-2 | Define Netbox custom field schema | `src/host_config/netbox/schema.py`: declares custom fields (`bf3_mode`, `roce_tc`, `numa_node`, `sriov_vfs`, `gpu_affinity`, `observed_mac`, `observed_firmware`) as typed Python definitions; idempotent `apply_schema` function. Full docstrings + Scenarios per function |
| M1-3 | Fixture script: populate B300 + CPU hosts | `fixtures/netbox/populate.py`: idempotent loader reading from `fixtures/netbox/data/*.yaml`; full structured logging; documented Scenarios; raises typed errors on conflict |
| M1-4 | Component tests for Netbox schema apply | `tests/component/netbox/test_schema.py`: spins Netbox container, applies schema twice, asserts idempotency; spins fresh container, asserts all custom fields exist |

### M1.5 — Gate: Netbox fixtures round-trip (integration)

**Goal:** Prove fixture script produces a queryable, schema-correct host.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M1.5-1 | Integration test: Netbox fixture round-trip | `tests/integration/test_netbox_fixtures.py`: brings up Netbox, runs schema + populate, queries B300 host back via `pynetbox`, asserts 10 interfaces / correct IPs / correct VLANs / all custom fields populated; same for CPU host; runs in <30 s |

### M2 — Renderer service (layer)

**Goal:** A FastAPI service that, given an asset tag, queries Netbox, builds a validated `HostIntent`, renders three cloud-init files, and returns them. Logging, metrics, traces all instrumented.

**Issues (6):**

| ID | Title | Scope |
|---|---|---|
| M2-1 | Pydantic `HostIntent` models + error hierarchy | `src/host_config/models/`: `interface.py` (PhysIface, Bond, VlanChild, RoceUnderlay, SriovParent), `intent.py` (HostIntent), `validators.py` (cross-field invariants: one default gateway, MTU monotonicity, etc.); strict Pydantic config. Companion `src/host_config/errors.py` + per-package `errors.py`: full exception hierarchy with contextual messages; tests for every error class |
| M2-2 | Netbox loader: record → HostIntent | `src/host_config/netbox/loaders.py`: pure function `load_host_intent(client, asset_tag) -> HostIntent`; raises `NetboxQueryError`, `IntentValidationError` with full context; structured logging at INFO/DEBUG |
| M2-3 | Jinja template tree per role | `src/host_config/render/templates/{cpu,gpu-b300}/`: `meta-data.j2`, `user-data.j2`, `network-config.j2`; templates documented inline; rejects unknown variables (Jinja strict undefined) |
| M2-4 | Renderer: intent → bytes | `src/host_config/render/emitter.py`: `render_for(intent, file_kind) -> bytes`; deterministic output via `ruamel.yaml` stable ordering; injected `now` for reproducibility; golden files in `src/host_config/render/golden/` |
| M2-5 | FastAPI service | `src/host_config/service/app.py`, `routes.py`, `middleware.py`, `dependencies.py`: three render routes + `/healthz` + `/readyz`; request-id middleware; structlog context binding; FastAPI exception handlers translating typed errors to consistent JSON envelopes; full OpenAPI doc |
| M2-6 | Observability — logs and metrics | `src/host_config/observability/metrics.py` (Prometheus collectors); `logging_config.py` (structlog setup); every external call timed and logged; debug-level traceability acceptance test (per §7.5). OpenTelemetry traces deferred (§7.7) |

### M2.5 — Gate: HTTP render against real Netbox (integration)

**Goal:** End-to-end through HTTP, byte-equal to golden, with all observability artifacts produced.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M2.5-1 | Integration test: Netbox → Renderer → HTTP | `tests/integration/test_renderer_e2e.py`: spins Netbox + renderer via docker-compose; populates fixtures; curls `/render/SN12345/{meta-data,user-data,network-config}`; asserts byte-equal to checked-in golden files; asserts Prometheus metrics incremented; asserts log lines match expected sequence at DEBUG level |

### M3 — nginx proxy + cache (layer)

**Goal:** nginx fronts the renderer with `proxy_cache_path` write-through cache; first request renders, subsequent requests serve from cache; cache invalidates after TTL; Netbox-down still serves cached content.

**Issues (4):**

| ID | Title | Scope |
|---|---|---|
| M3-1 | Ansible role: `nginx-cache` | Installs nginx; deploys our config with `proxy_cache_path`, logging, and a `PURGE` location for manual cache invalidation; idempotent; templated from variables; role README documents inputs and outputs |
| M3-2 | Cache behavior component tests | `tests/component/nginx/test_cache.py`: tests warm/cold paths, TTL expiry, Netbox-down (renderer unavailable) fallback, manual purge endpoint |
| M3-3 | Renderer cache-friendly headers | `Cache-Control`, `ETag`, `Last-Modified` returned by FastAPI; tested |
| M3-4 | TLS/HTTPS placeholder + ADR | nginx config stub for TLS termination; ADR-0012 documenting the deferred signed-seed path (HMAC headers, mTLS via smallstep) so a future contributor doesn't reinvent it |

### M3.5 — Gate: hybrid render via nginx cache (integration)

**Goal:** Prove the cache layer behaves correctly across warm, cold, and degraded scenarios.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M3.5-1 | Integration test: nginx + renderer hybrid | E2E test exercising warm path (<50ms), cold path (full render path), TTL expiry, Netbox-down behavior; metrics assertions; log assertions |

### M4 — OVS + QEMU harness (layer)

**Goal:** Reproducible local lab that spins up an OVS bridge with LACP + VLAN trunk and a QEMU VM plugged into it. Boot a CPU host VM that pulls config from the renderer and applies it.

**Issues (4):**

| ID | Title | Scope |
|---|---|---|
| M4-1 | Ansible role: `ovs-harness` | Installs OVS; creates bridge `br-test` with LACP partner config and VLAN trunks 100/200/300; tap interfaces pre-created; idempotent; role README explains the topology with an SVG referenced from `docs/diagrams/` |
| M4-2 | QEMU launcher (Python module) | `fixtures/vms/launch.py`: `launch_host(asset_tag) -> VMHandle`; reads Netbox MACs via the renderer's loader (DRY); constructs QEMU command with mgmt NIC + nsa/nsb; supplies SMBIOS; deterministic per asset tag; structured logging |
| M4-3 | Cloud image preparation | `fixtures/vms/prepare_image.py`: downloads Ubuntu 24.04 cloud image, verifies checksum, optionally pre-installs packages via `virt-customize` so first boot is fast; image cached and gitignored |
| M4-4 | `qemu-host` Ansible role | Installs QEMU/KVM/libvirt on the target host (Lima or DO Droplet); configures KVM permissions; idempotent |

### M4.5 — Gate: CPU host first-boot e2e (integration)

**Goal:** A CPU host VM boots, cloud-init fetches the rendered seed via the nginx cache, Netplan applies, bond + 3 VLANs come up correctly.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M4.5-1 | E2E test: CPU host full first-boot | `tests/e2e/test_cpu_host_boot.py`: brings up full stack (Netbox + renderer + nginx + OVS + VM); asserts `bond0` LACP-up, three VLAN children up with correct IPs/MTUs/routes; cloud-init exit status 0; full e2e in <5 min |

### M5 — 8 E-W NICs + Soft-RoCE (layer)

**Goal:** Extend the harness to the full B300-shaped 10-NIC VM with Soft-RoCE on east-west NICs.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M5-1 | Extend launcher and OVS for 10 NICs | QEMU launcher adds 8 E-W virtio NICs with deterministic MACs derived from Netbox; OVS role parameterized for E-W tap interfaces (no VLAN trunk on those — they're independent IPv4 underlays) |
| M5-2 | Renderer support for gpu-b300 role | Templates and emitter handle the full 10-NIC shape; golden files added for gpu-b300; tests for E-W NIC stanzas (MTU 9000, per-NIC IPs, `virtual-function-count: 16`) |
| M5-3 | Cloud-init user-data: Soft-RoCE | user-data block loads `rdma_rxe` module, creates `rxe_gpuN` devices on each E-W NIC, raises `memlock` limits; idempotent (skips on re-run) |

### M5.5 — Gate: B300-shaped first-boot e2e (integration)

**Goal:** A 10-NIC VM boots and RDMA verbs work end-to-end via Soft-RoCE.

**Issues (1):**

| ID | Title | Scope |
|---|---|---|
| M5.5-1 | E2E test: B300 host full first-boot + RDMA verbs | All 10 NICs up at correct MTUs/IPs; `ibv_devinfo` lists 8 rxe devices; `rping` between gpu0 and gpu1 succeeds; documented as the canonical "is the lab working" smoke test |

### M6 — Ansible deployment to DigitalOcean (layer)

**Goal:** One-command deploy of the lab to a DigitalOcean Droplet, with provisioning and configuration both handled by Ansible.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M6-1 | Ansible: provision + configure | `infra/ansible/playbooks/provision.yml` (Droplet, SSH key, firewall, tags via `community.digitalocean`; idempotent — checks existing tagged resources before creating; outputs inventory). `infra/ansible/playbooks/deploy-lab.yml` (composes netbox-dev + renderer + nginx-cache + ovs-harness + qemu-host roles; idempotent end-to-end). One command from fresh state to working lab |
| M6-2 | Runbook: deploy lab to DO | `docs/runbooks/deploy-do.md`: step-by-step; `ansible-playbook` invocations; smoke test commands; expected costs; teardown procedure; troubleshooting common failures |
| M6-3 | `just` target wrappers | `justfile` targets: `just lab-up` (provision + configure), `just lab-down` (Ansible destroy play + DO API verification of zero resources), `just lab-test` (run e2e tests), `just lab-logs` (collect logs from Droplet), `just lab` (composes up → test → down with trap-on-exit) |

### M6.5 — Gate: lab works on DigitalOcean (integration)

**Goal:** The full M4.5 + M5.5 e2e tests pass on a real Droplet, AND the leave-no-trace principle is verified.

**Issues (2):**

| ID | Title | Scope |
|---|---|---|
| M6.5-1 | E2E verification on DO Droplet | Documented procedure: `just lab-up`, run e2e tests, snapshot logs, `just lab-down`. Verification recorded in `docs/runbooks/deploy-do.md` as the canonical acceptance step. Costs logged in the runbook |
| M6.5-2 | Teardown integrity test | Capture DO resource inventory before `just lab-up`; verify the diff after `just lab-down` is zero — no Droplets, volumes, snapshots, firewalls, SSH keys, DNS records remain tagged with our workspace. Includes a deliberately failed `lab-up` to verify cleanup still runs (trap-on-exit pattern). Result documented in the runbook |

### M7 — GitHub Actions CI for full e2e (layer)

**Goal:** Every PR runs the full test pyramid in <10 minutes. mkdocs site deploys to GH Pages on `main`. Mutation testing runs weekly.

**Issues (3):**

| ID | Title | Scope |
|---|---|---|
| M7-1 | `e2e.yml` workflow runs M4.5 + M5.5 on PR | KVM-enabled GHA runners; pulls Netbox + builds renderer; runs OVS + QEMU + cloud-init e2e; reports timing; parallelization across multiple jobs if total >10 min. Workflow includes `if: always()` teardown step per §8.6 |
| M7-2 | Coverage reporting + PR comments | `pytest-cov` reports uploaded; coverage delta posted to PR via Codecov or similar; informational alert at >2% drop (not auto-block per §6.7) |
| M7-3 | Docs link & diagram-reference checker | CI step that scans `docs/**/*.md` and `README.md` for broken internal Markdown links, missing SVG references, and ADRs not listed in the docs index. Runs on every PR; blocks merge on regressions |

### M7.5 — Gate: CI is the source of truth (integration)

**Goal:** Branch protection makes CI failures actually block merges; coverage drops block merges; the mkdocs site stays current.

**Issues (2):**

| ID | Title | Scope |
|---|---|---|
| M7.5-1 | Branch protection finalized | Rule on `main`: required checks (lint+type-check+unit+component+integration+coverage), signed commits, 1 review on substantive PRs; documented in CONTRIBUTING.md |
| M7.5-2 | Failure-scenario verification | Deliberately open a PR with a failing test, a coverage drop, a bad commit message; verify each is blocked; document the expected error messages so future contributors recognize them |

---

## 10. Dependencies and ordering

```
M0 ─┬─ M1 ──── M1.5 ─┐
    │                │
    └─ M2 ──── M2.5 ─┴─ M3 ──── M3.5 ─┐
                                       │
                  M4 (depends on M0) ──┴── M4.5 ─┐
                                                  │
                              M5 (M2+M4) ──── M5.5 ─┐
                                                     │
                                  M6 (M0..M5) ── M6.5 ─┐
                                                        │
                                          M7 (M6) ── M7.5
```

Critical path: M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7.
Parallelizable: M1 and M2 can proceed in parallel after M0 (M2 mocks Netbox calls until M1 lands).
Bottleneck: review capacity, not dependencies.

---

## 11. Decision log seed (initial ADRs)

These ADRs ship in M0-4 to anchor the design from day one:

| ADR | Subject |
|---|---|
| **0001** | Python 3.12 as the implementation language |
| **0002** | `uv` as package and project manager |
| **0003** | FastAPI + Pydantic v2 + Jinja2 for the renderer |
| **0004** | `ruff` (lint+format) + `mypy --strict` as quality gates |
| **0005** | `pytest` + Hypothesis for testing (mutation testing deferred per §6.4) |
| **0006** | Ansible (with `community.digitalocean`) for both cloud provisioning and in-host configuration |
| **0007** | `just` as the task runner |
| **0008** | GitHub-rendered Markdown for documentation (no separate doc framework); SVG diagrams in `docs/diagrams/` with Excalidraw sources |
| **0009** | structlog + Prometheus for observability (distributed tracing via OpenTelemetry deferred per §7.7) |
| **0010** | GitHub Actions for CI |
| **0011** | Systems overview: catalog of every component in the lab, the boundaries between them, and the interactions (request/response, fixture-time, deploy-time). Includes an SVG component diagram and one SVG sequence diagram for the canonical "render a host" flow. Mirrored as the living `docs/architecture/systems-overview.md` |
| **0012** | Deferred: signed-seed delivery path (HMAC, mTLS) — recorded so it's not reinvented (lands in M3-4) |

Future ADRs will arrive as decisions cross the bar — anything that crosses module boundaries, affects public contracts, or chooses between credible alternatives. Mutation testing (§6.4) and distributed tracing (§7.7) will each become their own ADR when the time comes.

---

## 12. Issue count summary

| Milestone | Issues | Type |
|---|---|---|
| M0 | 5 | Layer |
| M1 | 4 | Layer |
| M1.5 | 1 | Gate |
| M2 | 6 | Layer |
| M2.5 | 1 | Gate |
| M3 | 4 | Layer |
| M3.5 | 1 | Gate |
| M4 | 4 | Layer |
| M4.5 | 1 | Gate |
| M5 | 3 | Layer |
| M5.5 | 1 | Gate |
| M6 | 3 | Layer |
| M6.5 | 2 | Gate |
| M7 | 3 | Layer |
| M7.5 | 2 | Gate |
| **Total** | **41** | |

41 issues across 15 milestones, sized for "full-day to multi-day" chunks per issue.

---

## 13. Next steps after sign-off

1. **You review this plan and push back.** Things to look for: principles that don't match your intent, conventions that are too lax or too strict, issues that are too big or too small, milestones with unclear acceptance criteria.
2. **We iterate to "yes."**
3. **I scaffold the repo** via `gh repo create <user>/host-config --public --license apache-2.0` from this session.
4. **I create the 15 milestones** in the new repo via `gh api`.
5. **I seed all 41 issues** with:
   - Title and full description (from §9).
   - Acceptance criteria as checkbox list.
   - Labels (`milestone:Mx`, `area:...`, `kind:...`, `priority:...`).
   - Milestone assignment.
   - **`Plan reference:` line at the top of each issue body** linking back to the relevant subsection of this plan via commit-pinned URL (see §8.7).
6. **I edit this plan once more** to backfill the bidirectional links: each issue ID in §9 tables gets a hyperlink to the GitHub issue URL.
7. **M0-1 becomes the first PR target.**
8. **Execution begins** one issue at a time, with a quick review at each gate before moving to the next layer.

This plan stays in the research repo as the durable reference. Changes to the plan after seeding happen via ADRs in the new repo (with the corresponding section in this plan getting a note that says "Amended; see ADR-NNNN in `host-config`").
