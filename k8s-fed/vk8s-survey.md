# Virtualized Kubernetes for the Edge Inference Platform: OSS Survey

## Table of contents

- [Executive Summary](#executive-summary)
- [Requirements](#requirements)
- [Assumptions Made](#assumptions-made)
- [Where virtualization sits in the stack](#where-virtualization-sits-in-the-stack)
- [Virtualization technology candidates](#virtualization-technology-candidates)
  - [vCluster](#vcluster)
  - [Kamaji](#kamaji)
  - [Hypershift](#hypershift)
  - [KCP](#kcp)
  - [Capsule, HNC — adjacent, not virtualization](#capsule-hnc--adjacent-not-virtualization)
- [Does virtualization change the federation choice?](#does-virtualization-change-the-federation-choice)
- [The translation layer](#the-translation-layer)
- [Recommended architecture](#recommended-architecture)
- [Risks and open threads](#risks-and-open-threads)

## Executive Summary

For per-tenant Kubernetes (K8s) virtualization on the master cluster, with 100+ tenants, full K8s API per tenant, cluster-admin scope, the same K8s version across tenants, and a federation layer underneath: **[vCluster](https://www.vcluster.com/) is the recommended virtualization layer; [Karmada](https://karmada.io) + [Argo CD ApplicationSets](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/) from [topic 1](oss-federation-survey.md) remain the right federation stack; the translation from tenant annotations to federation primitives can start as a default Karmada `PropagationPolicy` in each tenant's host namespace plus a small mutating webhook — no Crossplane, no Kratix, no custom CRDs needed at day one.** Virtualization does not flip the topic-1 federation choice, but it does weaken the strongest argument for Karmada (K8s API conformance on the master) since tenants now meet the vcluster, not Karmada directly. The report explicitly compares Karmada + Argo CD vs Argo CD ApplicationSets alone in this new light.

### Comparison table

| Dimension | vCluster | Kamaji | Hypershift | KCP |
|---|---|---|---|---|
| Pattern | K8s API server in a host pod, sync to host namespace | Hosted control plane (real API server + shared datastore) | Hosted control plane (OpenShift-flavored) | Logical workspaces sharing one logical API |
| Tenant gets cluster-admin | Yes | Yes (real K8s API) | Yes (real K8s API) | Yes per workspace |
| Cluster-scoped resources (CRDs, ClusterRoles) | Yes | Yes | Yes | Yes |
| Different K8s versions per tenant | Yes (limited matrix) | Yes (full matrix) | Yes (full matrix) | No (shared) |
| Footprint per tenant | ~100–300 MB | ~500 MB–1 GB | ~1 GB+ | Shared, very low |
| Density on master | Hundreds | Dozens to ~100 | Dozens | Thousands of workspaces |
| Host-side visibility of tenant resources | Excellent (sync to host namespace) | None (separate API + datastore) | None | Native (workspaces are first-class) |
| Translation-layer integration | Trivial (read host namespace) | Bridge controller required | Bridge controller required | Native, but bespoke ecosystem |
| CNCF status (Jan 2026) | Sandbox (joined 2024) | Sandbox (joined 2023) | Not CNCF (Red Hat) | Sandbox (joined 2024) |
| Primary backers | Loft Labs | CLASTIX | Red Hat | Red Hat (historic), broader CNCF community |
| Public production references | Adobe, Codefresh, Datadog, Equinix | Telefonica, Adidas, NTT Data | ARO HCP, ROSA HCP, IBM Cloud | Limited; mostly research / early-stage platforms |
| OSS clarity (clickbait risk) | Core Apache 2.0; Loft Platform is the paid wrapper; vcluster usable standalone | Apache 2.0; CLASTIX commercial offerings are separate | Apache 2.0; tightly tied to OpenShift in practice | Apache 2.0; ecosystem still forming |

### Verdict

**Prefer vCluster over Kamaji / Hypershift / KCP for this use case because:**

1. **Host-side visibility maps directly onto the translation pattern.** vCluster's sync mechanism deposits tenant resources into a known host namespace, where a Karmada `PropagationPolicy` and a small mutating webhook can pick them up. Kamaji and Hypershift give tenants their own etcd and API server — stronger isolation, but the translation layer would need a bridge controller running *inside* each tenant control plane.
2. **Highest density on a single master.** vCluster's footprint is ~100–300 MB per tenant; 100+ tenants on one master is routine. Kamaji and Hypershift fit dozens, not hundreds, per host before the shared datastore (Kamaji) or pod count (Hypershift) starts to bite.
3. **OSS clarity.** vCluster core is Apache 2.0 and runs without any Loft Platform component. The paid wrapper is a value-add, not a gate. No clickbait-OSS issue.
4. **You don't need what vCluster gives up.** vCluster is "soft multi-tenant" — tenants share the host kernel via their workload pods on host nodes, *but* in your design tenant workloads never run on the master; they run on dedicated edge nodes. The on-master soft-tenancy is irrelevant because the only thing on the master is the vcluster's control plane pods. You are getting Kamaji-level isolation for tenant workloads (dedicated edge nodes) without paying Kamaji's price on the master.

**Kamaji** is the alternative when control-plane-level isolation on the master itself becomes a hard requirement (compliance, hostile-tenant model). **Hypershift** makes sense only inside an OpenShift world. **KCP** is conceptually elegant — workspaces fold virtualization and multi-cluster into one abstraction — but the production track record outside Red Hat / early-adopter platforms is thin, and the project has been through visible governance shifts; not a 2026 production bet.

### Federation recap

Karmada + Argo CD from topic 1 is still the recommendation. Argo CD ApplicationSets *alone* (no Karmada) is now a more credible alternative than before, since the "kubectl-on-master for end users" argument is moot once tenants only touch their vcluster. See [Does virtualization change the federation choice?](#does-virtualization-change-the-federation-choice) for the head-to-head.

## Requirements

- Virtualization lives only on the master K8s cluster in the hyperscaler. Edge clusters are plain K8s.
- Each tenant gets a dedicated K8s API endpoint with cluster-admin, supporting CRDs / ClusterRoles / webhooks.
- Each physical compute node is dedicated to a single tenant (no kernel sharing).
- One K8s cluster per site, per-tenant node pools (labels/taints); per-tenant namespace per site.
- Same K8s version across all tenant virtual clusters; no per-tenant version flexibility needed.
- Tenants author standard K8s objects with **placement annotations** (e.g. `platform.example.com/sites: all` or `[site-1, site-3]`); they never see federation primitives.
- Translation from tenant intent to federation primitives is in scope; recommend the lightest viable approach.
- Scale: 100+ tenants, 50+ sites.
- Re-examine the topic-1 federation recommendation (Karmada + Argo CD) and call out whether virtualization changes it.
- Same OSS bar as topic 1: Apache-2.0-class core, documented production references at scale, no paywalled critical features, healthy multi-vendor community.

## Assumptions Made

- Platform's own inference workloads run directly on the host master in platform-owned namespaces, not inside a platform vcluster. (The "platform also uses a vcluster, for symmetry" variant is feasible and discussed briefly; not recommended as primary because the platform owns the master.)
- "Soft-multi-tenant" virtualization (vCluster) is acceptable because tenant *workloads* never run on the master — only tenant *control planes* do. Tenant workloads run on edge nodes that *are* hard-isolated by node-pool dedication.
- No regulatory-grade isolation needed (per the topic-1 sign-off). If that changes, Kamaji becomes the recommendation.
- KubeVirt is explicitly out of scope (VM-on-K8s, wrong abstraction).
- Capsule and HNC are mentioned but not in the recommendation set — they manage namespaces, not virtual clusters.
- The platform's federation problem and Customer A's federation problem are isomorphic — both are workload owners pinning to their own node-pool slice across all sites. A single federation engine on the host serves both; the translation layer provides per-owner scoping.

## Where virtualization sits in the stack

```
+---------------------- Master K8s (hyperscaler) -----------------------+
|                                                                      |
|  Per-tenant host namespaces                  Platform namespaces     |
|  +-----------------------+                   +-------------------+   |
|  | tenant-customer-a/    |                   | platform-system/  |   |
|  |  - vcluster A pods    |                   |  - Argo CD        |   |
|  |  - synced resources   |                   |  - Karmada CP     |   |
|  |  - default Propag.    |                   |  - vcluster op    |   |
|  |    Policy             |                   |  - placement      |   |
|  |                       |                   |    webhook        |   |
|  +-----------------------+                   +-------------------+   |
|        ...                                                           |
|  +-----------------------+                                           |
|  | tenant-customer-n/    |                                           |
|  +-----------------------+                                           |
|                                                                      |
|       Karmada controllers watch every tenant's host namespace        |
+------------------------------|---------------------------------------+
                               v  (push or pull, Karmada propagation)
       +-------+-------+-------+-------+      ...      +-------+
       v       v       v       v       v               v
   Site-1 K8s   Site-2 K8s   Site-3 K8s   ...        Site-N K8s
   ns: tenant-customer-a   /  tenant-customer-...  /  platform-*
   nodes: gpu-owner=customer-a / =customer-... / =platform
```

Read top to bottom: tenants author K8s objects against their vcluster API. vCluster syncs those objects into the tenant's host namespace on the master. Karmada watches host namespaces and propagates the resources outward, with `PropagationPolicy` controlling site selection and `OverridePolicy` applying tenant-scoped node selectors. Site clusters land each tenant's resources in a per-tenant namespace, pinned to that tenant's node pool.

## Virtualization technology candidates

### vCluster

[vCluster](https://www.vcluster.com/) ([github.com/loft-sh/vcluster](https://github.com/loft-sh/vcluster)) is Loft Labs's virtual-cluster project, donated to CNCF Sandbox in 2024. A vcluster is a K8s API server (k3s by default, full kube-apiserver as an option) running as a pod in a host namespace, with its own in-memory or SQLite-backed state. Workloads created in the vcluster get *synced* to the host namespace as real host-cluster pods.

Why it fits this problem:

- **Host-side visibility.** The synced resources in the host namespace are exactly what the federation layer needs to see. The translation layer is "look at this host namespace" — no bridge controllers reaching into tenant control planes.
- **Density.** Each vcluster is ~100–300 MB of memory and a handful of pods. [Public benchmarks](https://www.vcluster.com/docs/) and KubeCon presentations describe deployments with hundreds of vclusters on a single host.
- **Tenant ergonomics.** Tenant points kubectl at the vcluster's endpoint, gets a real cluster-admin shell. CRDs they install are visible only inside their vcluster (configurable). Their controllers run as pods inside the vcluster's host namespace, also synced.
- **Operator ecosystem.** [vcluster-platform-cli](https://github.com/loft-sh/vcluster) for provisioning; ArgoCD-friendly install model; works with cert-manager, ingress-nginx, etc. without surprises.
- **OSS clarity.** The vcluster project itself is fully Apache 2.0 and standalone. Loft Platform (paid) layers SSO, UI, sleep-mode, and policy on top — none of which are needed for the architecture above. Adobe, Codefresh, Datadog, and Equinix have publicly described production deployments at KubeCon.

Watch-outs:

- **Single-vendor concentration.** Loft Labs produces the bulk of commits. CNCF Sandbox status is a partial hedge, not a full one. Re-evaluate at contract time.
- **Networking.** Services inside a vcluster are translated to host services; CoreDNS rewrites handle in-vcluster discovery. Edge cases (NodePort, hostNetwork) need attention but are documented.
- **Storage.** PVCs in vcluster get synced to host PVCs by default. Works, but the storage class is the host's, not the tenant's choice. Probably fine for your design (tenant workloads don't run on master).

### Kamaji

[Kamaji](https://kamaji.clastix.io/) is CLASTIX's hosted-control-plane operator, CNCF Sandbox since 2023. Each tenant gets a `TenantControlPlane` custom resource that materializes a full set of K8s control-plane pods (kube-apiserver, controller-manager, scheduler) on the host cluster, with control-plane state stored in a **shared datastore** (PostgreSQL, MySQL, NATS, or an etcd cluster) — Kamaji's distinctive design choice.

Why it is the runner-up, not the recommendation:

- **Real K8s API per tenant.** Tenants get a kubernetes.io-conformant API server, not a k3s-style approximation. Audit logs, admission webhooks, network policies all behave precisely as in a standalone cluster.
- **Strong isolation.** Tenant control-plane processes are separate; only the underlying datastore is shared.
- **Solid backers.** [Telefonica's CNCF case study](https://www.cncf.io/case-studies/clastix/) describes Kamaji running tenant clusters at scale; Adidas and NTT Data have spoken publicly.
- **License clarity.** Apache 2.0 OSS core; CLASTIX sells support and an enterprise platform layer separately.

Watch-outs (and why it loses to vCluster here):

- **No host-side visibility.** Tenant resources live in the tenant's etcd/database, not in a host namespace. The translation layer would have to run *inside* each tenant control plane (a vendored controller per tenant) or scrape the tenant API. Adds operational burden for the "annotations → propagation" pattern you want.
- **Density.** Each tenant is a full control plane pod set + datastore rows. Comfortable at dozens of tenants; the shared datastore is the scaling axis to watch at 100+ tenants.
- **Footprint on the master.** ~500 MB–1 GB per tenant control plane is a meaningful master sizing question.

### Hypershift

[Hypershift](https://github.com/openshift/hypershift) is Red Hat's hosted-control-plane infrastructure. It is what runs **Azure Red Hat OpenShift Hosted Control Planes (ARO HCP)**, **Red Hat OpenShift Service on AWS Hosted Control Planes (ROSA HCP)**, and the equivalent IBM Cloud offering. Each `HostedCluster` runs as a Deployment-set in the "management cluster."

In principle Hypershift can host vanilla K8s; in practice it is heavily co-evolved with OpenShift. Production references are massive *within* the OpenShift ecosystem (Red Hat operates this at hyperscaler-cloud-region scale), and essentially absent outside it. For a greenfield non-OpenShift platform, Hypershift would mean adopting a Red-Hat-flavored control plane purely to get its hosted-control-plane benefits — Kamaji gives most of those benefits with much less ecosystem pull.

### KCP

[KCP](https://www.kcp.io/) is "K8s on K8s" via the concept of **workspaces** — logical K8s API surfaces that share one set of underlying infrastructure. Originated at Red Hat, donated to CNCF Sandbox in 2024 after a period of governance and roadmap uncertainty. The model is conceptually beautiful for this problem: workspaces *are* the per-tenant K8s endpoints, and KCP has native multi-cluster placement (`APIBinding`, transformations, syncer) that arguably replaces both vCluster and Karmada with one abstraction.

Why it's not the recommendation today:

- **Maturity gap.** Documented production deployments outside Red Hat's internal platforms and a handful of European platform-engineering teams are sparse. The project shipped its 1.0 in 2024 and continues to harden, but the operator-experience and CRD ecosystem trail vCluster + Karmada by years.
- **Different K8s versions across workspaces — no.** Workspaces share the underlying KCP server's K8s API version. (Your requirement; not a constraint for you, but a constraint generally.)
- **Bespoke ecosystem.** Pieces that "just work" in a normal cluster (Helm charts, operators, even kubectl plugins) often need adaptation for the workspace model.

Worth tracking. Worth a pilot in 2–3 years. Not a 2026 commitment.

### Capsule, HNC — adjacent, not virtualization

[Capsule](https://capsule.clastix.io/) (CLASTIX, CNCF Sandbox) and [Hierarchical Namespace Controller (HNC)](https://github.com/kubernetes-sigs/hierarchical-namespaces) (SIG-Multitenancy) give strong multi-tenant *namespace* semantics — Tenant CRDs, hierarchical quotas, RBAC inheritance — but tenants do not get their own K8s API endpoint. They are excellent tools for namespace-level multi-tenancy and would compose with vCluster on the master only if you decided that *some* low-touch tenants (e.g. internal teams) don't merit a vcluster. Not in the primary recommendation set for the stated requirement.

## Does virtualization change the federation choice?

Topic 1 concluded: **Karmada + Argo CD ApplicationSets**, primarily because Karmada keeps the master as a real K8s API surface for end users.

Once virtualization is in the picture, **end users no longer interact with the master's K8s API directly — they interact with their vcluster's API.** That weakens the topic-1 argument. Reconsider:

| Aspect | Karmada + Argo CD ApplicationSets | Argo CD ApplicationSets alone |
|---|---|---|
| Translation layer target | Karmada `PropagationPolicy` + `OverridePolicy` CRs in tenant's host namespace | `Application` / `ApplicationSet` in a platform namespace |
| Status aggregation | Native, via Karmada's `Resource.Status` merge | Per-Application sync status (one level higher) |
| Per-attribute overrides | `OverridePolicy` with cluster label selectors | Helm/Kustomize values + ApplicationSet generators |
| Number of control planes on the master | Two (Karmada + Argo CD) | One (Argo CD) |
| Tenant-facing UX | Identical — tenants see vcluster only | Identical — tenants see vcluster only |
| Site-cluster registration | Once with Karmada | Once with Argo CD |
| Re-evaluation hook for topic-1 argument | "K8s API on master" argument is now moot | Same |

**Conclusion: Karmada + Argo CD still wins, but by a smaller margin.** The reason it still wins is operational, not user-facing:

- Karmada's status-aggregation across sites for `Deployment`, `StatefulSet`, etc. is native; Argo CD's is one indirection up.
- `OverridePolicy` with label-based clusterAffinity is a clean fit for the node-pool / GPU-SKU dimension overrides you'll inevitably need.
- The translation layer emitting Karmada CRs into a tenant's host namespace is a strictly more declarative target than emitting Argo CD Applications into a platform namespace.

If your platform team has deep Argo CD experience and limited appetite for operating two control planes, **Argo CD ApplicationSets alone is a defensible simplification** — you give up some status fidelity for one fewer thing to operate.

## The translation layer

Given your "option 2a, annotations only, simpler" preference, the recommended translation layer is **almost no layer at all**:

1. **Per-tenant host-namespace bootstrap.** When a tenant is provisioned, the platform creates:
   - A host namespace (`tenant-customer-a`).
   - A vcluster in that namespace.
   - A **default `ClusterPropagationPolicy`** scoped to that namespace, with `placement.clusterAffinity` matching all member clusters and an `overridePolicy` injecting `nodeSelector: gpu-owner=customer-a` into every workload.
   - Per-tenant namespaces on each site cluster (`tenant-customer-a` on site-1, site-2, …) with quotas and RBAC.
2. **Placement-annotation webhook.** A small mutating admission webhook on the master watches resources in tenant host namespaces. When a resource carries `platform.example.com/sites: [site-1, site-3]`, the webhook emits a per-resource `PropagationPolicy` narrowing the default to the specified sites. When the annotation is absent, the default policy applies.
3. **That's it.** No tenant-facing CRDs. No Crossplane Composition. No Kratix promise. The "translation" is two pieces of templated YAML installed at tenant provisioning plus a webhook of ~few-hundred-LOC.

When (not if) the abstraction needs to grow:

- **Custom controller (recommended growth path).** If placement logic gets richer than "list of sites" — e.g. SLO-driven placement, capacity-aware spreading, GPU-SKU affinity — promote the webhook into a controller that owns higher-level placement CRs. Stay in Go + controller-runtime; do not over-engineer with a composition framework until the controller hits real complexity ceilings.
- **[Crossplane](https://www.crossplane.io/) composition** is the right tool when the tenant abstraction expands to multi-cloud or non-K8s resources (cloud storage, DNS, IAM). For purely-K8s placement, it is overkill.
- **[Kratix](https://kratix.io/)** has the cleanest "platform as a product" promise abstraction (Promises, GitOps integration) and is worth a serious look *if* you decide the tenant abstraction should be richer from the start. Smaller community than Crossplane; one to watch but not commit to today.

## Recommended architecture

| Layer | Choice | Why |
|---|---|---|
| Virtualization (master) | vCluster | Host-side visibility, density, OSS clarity (see verdict) |
| Federation engine (master) | Karmada (push by default, pull where edges require) | Topic-1 conclusion still holds; native status aggregation, `OverridePolicy` fits node-pool pinning |
| GitOps delivery (master) | Argo CD ApplicationSets | Bootstraps tenants, manages Karmada policies, manages site-cluster provisioning manifests |
| Tenant abstraction | Plain K8s + `platform.example.com/sites` annotation | Matches your "option 2a, simpler" stance |
| Translation layer | Default `PropagationPolicy` per tenant + mutating webhook for annotation overrides | Lightest viable; promote to a controller only when complexity demands it |
| Edge clusters | One K8s cluster per site, per-tenant node pools, per-tenant namespaces | Matches your topology answer |
| Identity / RBAC | OIDC at each vcluster API, Argo CD via Dex, Karmada via host OIDC | All three layers integrate with the same external IdP |
| Site-level multi-tenancy add-on | Not initially needed | Per-tenant namespace + node pool is enough; revisit Capsule if cross-cluster quota enforcement becomes a pain point |

## Risks and open threads

- **Loft Labs concentration on vCluster.** Single-vendor concentration is real. Mitigations: pin to vCluster releases, monitor CNCF Sandbox graduation progress, design the platform so a future swap to Kamaji or KCP is a localized change (the translation layer reads from a host namespace — Kamaji would require a different ingest mechanism but the rest of the stack does not move).
- **Datastore scaling for Kamaji if you switch.** If Kamaji becomes the choice (regulatory shift, hostile tenant model), the shared datastore is the scaling axis; benchmark before committing to >50 tenants.
- **vCluster networking corner cases at scale.** Service translation and ingress are well-trodden; hostNetwork and admission-webhook tenants need spot-checking.
- **Translation-layer controller as it grows.** Resist building a heavyweight composition framework. The "default policy + annotation webhook" is a deliberately minimal contract; preserve that property as long as possible.
- **Status surfacing to the tenant.** Tenants see vcluster-level status; the platform needs to project Karmada's per-cluster propagation status back into the tenant's view (e.g. as a custom `SiteStatus` CR in each vcluster). Lightweight, but not nothing. Open-source patterns exist but no off-the-shelf controller — likely small in-house piece.
- **Pilot scope.** Recommend a 3-tenant, 3-site pilot before committing platform-wide. Validates vCluster density, Karmada propagation latency, and the translation webhook end-to-end.
