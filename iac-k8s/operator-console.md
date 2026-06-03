# iac-k8s — Operator Console: screens

The screens of the operator console and the features each one exposes. Styling is **Bootstrap 5** (a popular open-source user-interface toolkit). A clickable mockup of every screen is in **[`console-mockup.html`](console-mockup.html)** — open it in a browser to see the styled, navigable version (it is static, with illustrative data, no backend). This document is the spec; the mockup is the picture.

Each screen below lists its **purpose**, **layout** (the Bootstrap pieces used), **features**, and the **backend action** it triggers (endpoints defined in [design.md](design.md)). Every change-making action follows the same rule: it opens a reviewed pull request — nothing is applied without approval (requirement R8).

Common chrome: a dark **left sidebar** (`navbar`/list) with the six screen links and the operator identity; a top bar with the screen title and a "MOCK" badge in the mockup. Acronyms: UI = user interface; PR = pull request; FOP = Fleet Operations Plane; MGMT = Management Plane.

---

## 1. Inventory  (`#inventory` — the landing screen)

- **Purpose:** see every cluster at a glance — the answer to "what do we have and is it healthy?"
- **Layout:** a Bootstrap `table` on a white `shadow-sm` card; colored `badge`s for environment (dev/stage/prod), status, hardened state, and audit result.
- **Features:** one row per cluster showing **cluster name, environment, purpose, status, hardened/enforced state (with a lock icon when Confidential), last audit result, and monthly cost**. The 6 rows are the {dev,stage,prod} × {FOP,MGMT} matrix. Clicking a row opens its **Cluster & Day-2** screen.
- **Backend:** `GET /clusters` — merges desired state (Git), live state (via GKE Connect Gateway), and cost (BigQuery).

## 2. Create cluster  (`#create`)

- **Purpose:** stand up a new hardened cluster by choosing environment + purpose.
- **Layout:** a `card` with a two-column `form` (`form-select`, `form-control`), a node-pool `table` with `form-check` toggles, and a primary button.
- **Features:** pick **environment** and **purpose**; set **region** and **release channel** (update cadence); define **node pools** (name, machine type, min/max) with a **Confidential (memory-encrypting) toggle per pool** (operator choice, R11). The button **"Open pull request (preview)"** does not build anything — it proposes the change.
- **Backend:** `POST /clusters` → writes the Terraform spec into the env folder and opens a PR. The operator then goes to **Review & approve**.

## 3. Review & approve  (`#review`)

- **Purpose:** the approval gate — see exactly what will change, then approve (R8).
- **Layout:** a master/detail split — a `table` of open/recent PRs on the left; on the right a `card` showing the **plan** (the preview of changes) in a dark `pre` code block, with the approver note and action buttons.
- **Features:** select a PR → read its **plan** ("14 to add, 0 to change…") → **Approve & apply** (or open it in GitHub). Status `badge`s show *awaiting approval / applied*. Required on **every** change, all environments.
- **Backend:** `GET /runs`, `GET /runs/{id}` (plan from the Actions artifact), `POST /runs/{id}/approve` (approve the GitHub Environment / merge → apply runs).

## 4. Cluster & Day-2  (`#cluster`)

- **Purpose:** everyday administration of one cluster (requirement R7) — and the screen that shows the cluster's recorded shape.
- **Layout:** a header with cluster identity + action buttons (`btn-outline-*`); a node-pool `card` with a `table` and per-row action buttons; a footer line with version/channel/maintenance.
- **Features (each opens a reviewed PR):**
  - **Node pools:** add a pool; add a pool of a **different machine type** (e.g. graphics-processing-unit, or Confidential); **resize** (min/max); **remove**; **drain** a pool's nodes.
  - **Versions:** **upgrade** control plane / node pools; set the **maintenance** window.
  - **Lifecycle:** **delete** the cluster.
- **Source of truth:** what is shown here — pools, machine types, Confidential flags — is exactly what is committed in Git for this cluster (R7).
- **Backend:** `POST /clusters/{id}/nodepools`, `.../upgrade`, `.../maintenance`, `DELETE /clusters/{id}` — all author PRs; read-only status comes via Connect Gateway.

## 5. Security & audit  (`#security`)

- **Purpose:** show that security is being **enforced as a closed loop** (R5) and provide the daily **evidence** (R6).
- **Layout:** two cards — left: closed-loop status; right: latest audit with an `alert` for anomalies and a results `table`.
- **Features:**
  - **Closed-loop status (ArgoCD):** per cluster, *Synced / Healthy*, number of Kyverno policies, self-heal on; Pod Security level; Binary Authorization mode. A **"Run scan now"** button for an on-demand check.
  - **Latest audit:** anomalies flagged in an `alert` (e.g. "drift — a policy was edited out of band, self-healed 22s later"); a table of per-cluster **benchmark score, drift count, and a link to the archived report**.
- **Backend:** `GET /audit/reports` (from `reports/` in Git), `POST /audit/run`; closed-loop status read from ArgoCD.

## 6. Cost  (`#cost`)

- **Purpose:** per-cluster cost transparency (R12).
- **Layout:** a `card` with a `table`; simple CSS bars give a quick visual; a total in the footer.
- **Features:** **cost per cluster this month**, ranked, with a bar and dollar figure; grouped by the **environment / purpose / cluster labels**; a monthly total. Sourced from GKE Cost Allocation exported to BigQuery (Google's billing data warehouse).
- **Backend:** `GET /cost` — queries the cost-allocation export.

---

## Notes for the build

- Build with **Bootstrap 5** (via the official Cloud Delivery Network link, as the mockup does) + **Bootstrap Icons**; the front end is **React** (requirement D9 / design.md), the mockup is plain HTML only to illustrate.
- Keep the **six-item sidebar** as the primary navigation; the screens map one-to-one to the backend endpoint groups in [design.md](design.md).
- Reuse the proof-of-concept console shell (`iac-console-poc`) for the inventory/review/report views — those patterns are already proven.
- The golden rule visible in the UI everywhere: **mutating actions open a pull request; nothing applies without an approver.**
