# Open Source Kubernetes Federation: Survey for a 50+ Edge Inference Platform

## Table of contents

- [Executive Summary](#executive-summary)
- [Requirements](#requirements)
- [Assumptions Made](#assumptions-made)
- [Landscape: two layers, not one](#landscape-two-layers-not-one)
- [Why KubeFed v2 is out](#why-kubefed-v2-is-out)
- [Push vs Pull: which control flow](#push-vs-pull-which-control-flow)
- [Federation engines](#federation-engines)
  - [Karmada](#karmada)
  - [Open Cluster Management (OCM)](#open-cluster-management-ocm)
  - [Clusternet](#clusternet)
  - [Liqo — wrong shape, brief mention](#liqo--wrong-shape-brief-mention)
- [GitOps delivery layers](#gitops-delivery-layers)
  - [Argo CD ApplicationSets](#argo-cd-applicationsets)
  - [Flux + multi-tenancy / "fleet" pattern](#flux--multi-tenancy--fleet-pattern)
  - [Rancher Fleet](#rancher-fleet)
- [The non-k8s master question](#the-non-k8s-master-question)
- [Recommended architectures](#recommended-architectures)

## Executive Summary

For a 50+ edge cluster, GitOps-first, k8s-API-conformant federation stack with per-tenant RBAC, the strongest combination today is **[Karmada](https://karmada.io) as the federation engine on the master, fronted by [Argo CD ApplicationSets](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/) for declarative delivery**. Karmada preserves the master as a real Kubernetes (K8s) API surface — end users `kubectl apply` to the master and Karmada propagates to selected edges with full Custom Resource Definition (CRD) and StatefulSet support. Argo CD adds the GitOps pipeline, an Identity Provider (IdP)-friendly RBAC layer via [Dex](https://dexidp.io/), and a mature multi-tenant UI. [Open Cluster Management (OCM)](https://open-cluster-management.io/) is the credible alternative when a pull-only network policy or Red Hat alignment is required.

### Comparison table

| Dimension | Karmada | OCM | Argo CD ApplicationSets | Flux (multi-cluster) |
|---|---|---|---|---|
| Project layer | Federation engine | Federation engine | GitOps delivery | GitOps delivery |
| Control flow | Push (default), pull supported | Pull (hub-and-spoke) | Push from hub | Pull (agent per cluster) |
| Master = real K8s API | Yes, full K8s + CRDs | Partial (ManifestWork wraps manifests) | No (end users push to git) | No (end users push to git) |
| CRD / StatefulSet propagation | Yes (Resource Template + PropagationPolicy) | Yes (raw ManifestWork) | Native (same as single cluster) | Native (same as single cluster) |
| Per-attribute overrides | OverridePolicy with label selectors | Placement + transformer addon | ApplicationSet generators + Helm/Kustomize values | Kustomize overlays per cluster |
| Multi-tenant RBAC | K8s RBAC scoped on master + propagation | K8s RBAC + ManagedClusterSet + Placement | AppProject scoping + SSO | Tenant CRD + multi-tenancy lockdown |
| IdP integration | K8s OIDC at master API | K8s OIDC + Hub | Dex (OIDC / SAML / LDAP / GitHub) built in | Git provider + K8s OIDC |
| GitOps fit | Pair with Argo CD/Flux at the master | Pair with the Argo CD or app-manager addon | Native | Native |
| CNCF status (Jan 2026) | Incubating | Sandbox | Graduated (Argo) | Graduated |
| Primary backers | Huawei, Red Hat, Intel, FedEx | Red Hat, IBM, Microsoft, Alibaba | Intuit, Red Hat, Akuity | CNCF community, Microsoft, GitHub |
| Public production references | ICBC, Vipshop, Xiaohongshu, China Mobile | RHACM customers, IBM Cloud | Intuit, Tesla, Adobe, BlackRock | Mercedes-Benz, State Farm, Microsoft |
| Edge-cluster footprint | ~80 MB agent in pull mode; none in push | ~50 MB klusterlet | None (hub-only) | ~30 MB flux-system per cluster |

### Verdict

**Prefer Karmada + Argo CD ApplicationSets over the alternatives because:**

1. **K8s-API parity on the master.** Karmada is the only mature engine that lets end users keep using vanilla `kubectl`, native RBAC, and CRDs against the master — exactly what the platform contract you described requires.
2. **Strongest combined production track record.** [Karmada at ICBC](https://www.cncf.io/case-studies/icbc/) (100+ clusters, financial-grade workloads) plus [Argo CD at Intuit](https://www.cncf.io/case-studies/intuit/) (the project's birthplace, thousands of apps) is the best-documented pair in the OSS space.
3. **No clickbait-OSS risk.** Both are Apache 2.0 with multi-vendor governance; no core feature is paywalled.

[OCM](https://open-cluster-management.io/) is the recommended fallback for a pull-only network posture or where a Red Hat ecosystem alignment is preferred. [Pure Argo CD ApplicationSets](#argo-cd-applicationsets) without a federation engine is a viable simpler alternative if you can give up the "master is a K8s cluster" contract at the end-user surface.

## Requirements

- One master K8s cluster in a hyperscaler plus 50+ share-nothing edge clusters, each an independent failure domain.
- GPU inference workloads, mix of stateless and stateful, full K8s object conformance including CRDs and StatefulSets.
- Survey covers both push and pull control flows with explicit tradeoffs.
- Master is itself a K8s cluster; report whether a non-K8s control plane offers a material advantage.
- GitOps, declarative delivery model. End users do not need an imperative API.
- Per-attribute overrides (GPU SKU, model variant, replica count); location is not an override dimension.
- Stable master-to-edge connectivity assumed.
- Multi-tenant RBAC: end users see only their own namespaces/resources across the fleet. IdP integration required (specific IdP to be determined).
- Federation surfaces native K8s object status. Metrics / GPU utilization handled by a separate observability stack.
- Workload/config federation only. Cross-cluster networking and identity (Submariner, Cilium ClusterMesh, SPIFFE) are out of scope.
- Inclusion bar: OSI-licensed core, at least one documented production-grade deployment at scale, healthy multi-vendor community.

## Assumptions Made

- Greenfield — no existing federation, GitOps, mesh, or identity broker.
- Hyperscaler-agnostic master (AWS / GCP / Azure); candidates tightly coupled to one cloud will be flagged.
- IdP integration via OpenID Connect (OIDC) + K8s RBAC is the assumed integration shape.
- Each edge cluster is small-to-medium (single-digit to low-double-digit GPU nodes); edge control-plane footprint matters and is in scope of the evaluation.
- Stateful workloads are inference-side (model caches, vector stores backed by PersistentVolumeClaims (PVCs)); cross-cluster data replication is **not** an expectation of the federation layer.
- "Production grade" evidence = ≥1 of: KubeCon talk by an operator (not vendor), engineering blog from a named end-user at scale, or public case study with concrete numbers.
- KubeFed v2 is excluded from the recommendation set on grounds of project dormancy but is contextualized.

## Landscape: two layers, not one

A common conflation is to treat "K8s federation" as one decision. It is two:

1. **Federation engine** — what makes a *fleet* of clusters addressable through a single API or hub. Examples: Karmada, OCM, Clusternet, the archived KubeFed v2.
2. **GitOps delivery** — what turns a git repository into reconciled state on N clusters. Examples: Argo CD ApplicationSets, Flux multi-cluster patterns, Rancher Fleet.

The two layers can stand alone or compose. Argo CD ApplicationSets used directly against many edges *is* a form of federation — push-from-hub, no master K8s API surface for end users. Karmada by itself can be driven imperatively without GitOps. The most production-proven shape is to stack them: Karmada (or OCM) as the API surface, Argo CD (or Flux) as the pipeline that fills it.

Two patterns we will explicitly *not* recommend:

- **DIY multi-context kubectl scripts** — does not pass the RBAC, status-aggregation, or override requirements.
- **Service mesh as federation** — Cilium ClusterMesh, Submariner, and Skupper solve cross-cluster networking, not workload propagation. Out of scope by your direction.

## Why KubeFed v2 is out

[KubeFed v2](https://github.com/kubernetes-sigs/kubefed) was the SIG-Multicluster reference implementation of K8s federation. The repo has had no functional releases since 2023, the project README warns it is in maintenance-only mode, and SIG-Multicluster has redirected effort toward the [Multi-Cluster Services (MCS)](https://github.com/kubernetes-sigs/mcs-api) API and the [Work API](https://github.com/kubernetes-sigs/work-api) — the latter is in fact the lineage of OCM's ManifestWork. **Treat KubeFed v2 as historical**. The work has not been abandoned; it has *forked* into Karmada (which started as a Huawei rework of KubeFed v2 internals) and into OCM's Work API.

## Push vs Pull: which control flow

| | Push | Pull |
|---|---|---|
| Where credentials live | Master holds N kubeconfigs for edges | Each edge holds one kubeconfig / bootstrap token for the hub |
| Network direction | Master → edge (master must reach each edge's API server) | Edge → master (edges dial out) |
| NAT / firewall friendliness | Poor — every edge needs ingress | Excellent — edges only need egress |
| Blast radius on master compromise | High — attacker has direct API to every edge | Lower — attacker controls hub state but cannot bypass agent policies |
| Latency to apply changes | Lower (master decides, applies directly) | Higher (depends on agent polling / watch reconnect) |
| Behavior during partition | Edge stops receiving updates; existing workloads keep running | Edge stops receiving updates; existing workloads keep running |
| Status aggregation | Master watches edge API directly | Agent reports up; centralizes naturally |
| Best-known engine | Karmada (default), KubeFed v2 | OCM, Clusternet, Flux, Rancher Fleet |

With connectivity stable and the master in a hyperscaler, **push is the cleaner default** for this use case: lower latency, simpler debugging, and Karmada is mature in this mode. Pull becomes attractive if edges sit behind unpredictable network policies (NAT, customer firewalls), or if you want strong per-edge agent-side admission control as a defense-in-depth against a compromised master. Karmada actually supports both modes, and you can mix per cluster — a useful hedge.

## Federation engines

### Karmada

[Karmada](https://karmada.io) ("Kubernetes Armada") originated at Huawei as a from-scratch rework of KubeFed v2 internals and joined CNCF Incubation in December 2023. Architecturally, a Karmada control plane runs *as* a K8s API server (with its own etcd) on the master cluster. End users apply standard K8s objects to it; Karmada controllers convert them into **ResourceTemplates**, attach a **PropagationPolicy** (which selects member clusters) and optional **OverridePolicy** (which mutates per-target), and either *push* via the karmada-controller-manager directly or have a *pull-mode agent* on the member cluster reconcile.

What makes Karmada the right shape for the stated problem:

- **K8s-native UX on the master.** `kubectl get deployment -A` on Karmada returns the union of all member-cluster deployments with cluster names attached. RBAC at the master uses standard K8s primitives — no custom permission model to learn.
- **Full CRD propagation.** A `ClusterPropagationPolicy` with a `resourceSelectors` clause matches arbitrary GroupVersionKinds, including KServe `InferenceService`, vLLM operators, and GPU Operator configs. This is exactly the "full K8s conformance" requirement.
- **Per-attribute overrides without per-location code.** `OverridePolicy` uses `clusterAffinity` with label selectors. Edges labelled `gpu-sku=H100` get one override; `model-variant=llama-3-70b` gets another. No location ever appears as an override key.
- **Pull mode is first-class.** Same Resource Template + PropagationPolicy model; only the data path changes. Lets you mix push and pull per-cluster, which matters if even a few edges sit behind awkward network policies.
- **IdP via standard K8s OIDC.** The Karmada API server accepts the same `--oidc-*` flags as kube-apiserver. Any OIDC-compliant IdP works; no project-specific integration is required.
- **Production references.** [ICBC's Karmada deployment](https://www.cncf.io/case-studies/icbc/) (100+ clusters in financial-grade production), Vipshop, Xiaohongshu, FedEx, and others have presented at KubeCon. Adopters list is publicly maintained at [karmada.io/adopters](https://karmada.io/docs/adopters/).
- **GitOps composition.** The recommended composition is to run Argo CD or Flux on the master, with Karmada PropagationPolicy CRs as the GitOps target — Argo CD does not need to know about edges at all, only the Karmada API.

Watch-outs:

- **Single backer concentration.** Huawei still produces the bulk of commits; multi-vendor governance is real but the project would feel a Huawei withdrawal.
- **Status reporting depth.** Karmada surfaces aggregated `Resource.Status` reasonably for built-in workload types; for CRDs you may need to declare a `ResourceInterpreterCustomization` to teach Karmada how to merge status across edges.
- **Stateful workloads.** StatefulSet and PVC propagation works, but cross-cluster data replication is *not* in scope — that is your model-cache / vector-store choice, not Karmada's job.

### Open Cluster Management (OCM)

[OCM](https://open-cluster-management.io/) is the upstream of [Red Hat Advanced Cluster Management (RHACM)](https://www.redhat.com/en/technologies/management/advanced-cluster-management), donated to CNCF Sandbox in 2021 and currently working toward Incubation. The architecture is pull-only: a **klusterlet** runs on each managed cluster, registers with the hub, and reconciles **ManifestWork** resources that the hub writes to a per-cluster namespace.

Strengths:

- **Mature multi-tenancy primitives.** `ManagedClusterSet` groups clusters, `Placement` selects from a set, `ManifestWork` delivers to the selected. Tenant boundaries align cleanly with namespaces on the hub.
- **Defense-in-depth pull model.** Edges never accept inbound traffic from the hub. Compromise of the hub gives an attacker the ability to alter ManifestWork specs but the klusterlet's local admission policies still apply.
- **Strong backer set.** Red Hat, IBM, Microsoft, Alibaba contribute; RHACM ships OCM as its kernel, so there is a paid-product downstream that funds engineering, while the OSS layer remains fully usable.
- **Production references.** RHACM is in widespread enterprise use; OCM itself underpins IBM Cloud Satellite and is presented regularly at KubeCon by [Red Hat](https://www.youtube.com/results?search_query=open+cluster+management+kubecon) and Microsoft.

Watch-outs:

- **Master is not a transparent K8s API.** End users do not `kubectl apply -n my-ns my-deployment.yaml` to OCM and get propagation. They author ManifestWork (or use an addon like Argo CD that does it for them). The platform-owner side absorbs that abstraction, but it is not the same UX as Karmada.
- **More opinionated.** Multi-cluster scheduling decisions live in Placement, not in standard K8s scheduling. Useful, but a new model to learn.
- **CNCF level.** Sandbox as of January 2026 — lower maturity stamp than Karmada's Incubation, despite arguably comparable production usage via RHACM.

### Clusternet

[Clusternet](https://clusternet.io) is an open-source multi-cluster management project originating at Tencent, CNCF Sandbox. It supports pull-mode child clusters dialing home over a tunnel, which is genuinely useful for clusters behind NAT or carrier-grade firewalls.

It does not clear the inclusion bar for the recommendation set. Documented production deployments outside Tencent are sparse; community KubeCon presence is thinner than Karmada or OCM; the contributor base is narrow. Worth knowing about as a niche option if NAT-traversal becomes a hard requirement and OCM / Karmada pull-mode are insufficient — not as a primary choice.

### Liqo — wrong shape, brief mention

[Liqo](https://liqo.io) does cross-cluster *resource offloading*: a remote cluster appears in the local cluster as a virtual kubelet, and pods scheduled to it actually run there. Useful for cloud bursting or peer-to-peer cluster sharing. **Not the federation shape this problem needs** — there is no central control plane delivering config to N stable edges; there is bidirectional offload between peers. Mentioned for completeness.

## GitOps delivery layers

### Argo CD ApplicationSets

[Argo CD](https://argoproj.github.io/cd/) is the CNCF Graduated GitOps controller; **ApplicationSet** is its mechanism for fanning a templated `Application` out to N targets. Targets come from **generators**: List, Cluster (every cluster registered with Argo CD), Git (directory or file glob), or Matrix (combinations).

Why it matters for this problem, even alongside Karmada:

- **Native multi-tenancy.** `AppProject` scopes a tenant to a set of source repos, destination clusters, and namespaces. Combined with Argo CD's [Dex](https://dexidp.io)-based SSO (OIDC / SAML / LDAP / GitHub / Google), an end user logs in via the org IdP and only sees their own apps. This is precisely the per-tenant cross-fleet visibility the requirements call for.
- **Override model fits.** Cluster generator labels each registered cluster with arbitrary metadata; the ApplicationSet template substitutes those labels into Helm values or Kustomize overlays. A single ApplicationSet can produce 50 cluster-specific Applications.
- **Maturity.** First production user was the project's birthplace, Intuit. [Tesla, Adobe, BlackRock, BMW Group](https://argo-cd.readthedocs.io/en/stable/) and many others have publicly described deployments. Argo CD is the de facto enterprise GitOps controller as of 2026.
- **Status surfacing.** Argo CD's per-cluster sync status is the K8s-object status answer for this use case — what each Application's resources are doing on each edge.

When Argo CD stands alone (no Karmada): you trade the K8s-API-on-master abstraction for simpler operations. End users author manifests in git, Argo CD reconciles to selected edges. RBAC is enforced at the Argo CD UI/API layer, not at a K8s master API. If your end users are platform-engineering-savvy and content to interact with Argo CD as the platform, this is the leanest viable architecture.

### Flux + multi-tenancy / "fleet" pattern

[Flux](https://fluxcd.io) is the other CNCF Graduated GitOps controller. The "fleet" pattern (described in the [multi-tenancy lockdown](https://fluxcd.io/flux/installation/configuration/multitenancy/) and [flagger fleet examples](https://github.com/fluxcd/flux2-multi-tenancy)) puts a Flux instance on each cluster, each one watching its own subdirectory of a single fleet repo. Per-edge variation comes from Kustomize overlays — `clusters/edge-042/kustomization.yaml`.

Comparison with Argo CD ApplicationSets for this use case:

- **Pull vs push.** Flux is fundamentally pull — agent on each cluster, no central control-plane component required. Better defense-in-depth, worse single-pane-of-glass UX out of the box.
- **No native multi-tenant UI.** Tenants are enforced by namespace/repo isolation and by [Flux Tenant CRDs](https://fluxcd.io/flux/components/notification/), but there is no built-in SSO-aware UI like Argo CD's. Some teams pair Flux with [Weave GitOps OSS](https://github.com/weaveworks/weave-gitops) or [Capacitor](https://github.com/gimlet-io/capacitor) for a UI; these add components and a maturity gap.
- **Production references.** [Mercedes-Benz](https://www.cncf.io/case-studies/mercedes-benz/) (900+ clusters at the time of writing of the case study), State Farm, Microsoft (multiple internal platforms) have all spoken publicly about Flux at scale.
- **Weaveworks shut-down caveat.** Weaveworks, the original primary backer, [closed in early 2024](https://kubernetes.io/blog/2024/02/30/flux-update/). The project transitioned to a CNCF-community maintainer model and continues to ship releases; do confirm the maintainer activity at the moment of the build decision via [github.com/fluxcd/flux2/graphs/contributors](https://github.com/fluxcd/flux2/graphs/contributors). As of January 2026, the project is actively maintained, with new contributors from Microsoft, GitHub, and ControlPlane.

### Rancher Fleet

[Rancher Fleet](https://fleet.rancher.io) is SUSE/Rancher's GitOps engine, Apache 2.0, designed from day one for "fleet of fleets" — thousands of downstream clusters. Bundle, GitRepo, and Cluster CRDs map cleanly to "deliver this app to these clusters."

It is a near-borderline pass on the clickbait-OSS bar. The core Fleet controller is genuinely open-source and standalone-usable, and there are documented public deployments. But Fleet's *operability story* — the UI, the cluster-management glue, the IdP integration — is much smoother when run under Rancher Manager, which itself has a paid tier (Rancher Prime). If your team is committed to a Rancher-centric world, Fleet is excellent; if you want a project whose first-class UX assumes pure OSS, Argo CD ApplicationSets is the safer choice.

## The non-k8s master question

You asked whether a non-K8s control plane that simply *speaks* the K8s API to edges would offer a material advantage. Short answer: **no, not for this problem**. Reasoning:

- Every serious open-source federation engine in this survey is itself a K8s control plane (Karmada literally runs `kube-apiserver`; OCM, Clusternet, Fleet all run on K8s). The non-K8s option is a green-field bespoke service using `client-go`.
- The benefits of a non-K8s control plane (no etcd, smaller footprint, custom data model) are dwarfed by what you give up: the K8s API surface, RBAC, CRD/controller ecosystem, kubectl tooling, and the ability for end users to integrate with anything in CNCF without a translation layer.
- The non-K8s option becomes interesting only at *very* high scale (hundreds of thousands of edges, e.g. carrier-grade Radio Access Network deployments) where K8s control-plane scaling at the hub becomes the bottleneck. At 50+ edges it is not in the relevant trade-off zone.

Stick with a K8s master. The control-plane components on the master that *aren't* the K8s API server (Karmada controllers, Argo CD, etc.) can be sized appropriately.

## Recommended architectures

### Primary recommendation: Karmada + Argo CD ApplicationSets

```
+---------------- Master (hyperscaler K8s) ----------------+
|                                                          |
|   Argo CD ApplicationSets                                |
|        |                                                 |
|        v   (kubectl apply equivalent, via Argo)          |
|   Karmada API server  ←  end-user kubectl  ←  IdP/OIDC   |
|        |                                                 |
|   Karmada controllers + PropagationPolicy/OverridePolicy |
+-----|----------|----------|----------|-------------------+
      v          v          v          v
   Edge-01    Edge-02    Edge-03   ...  Edge-50
   (full K8s, GPU nodes, KServe/vLLM, Karmada agent if pull)
```

- End users authenticate to the master via OIDC and `kubectl apply` standard K8s objects scoped to their namespace.
- Argo CD lives on the master and reconciles a tenant's git repo into PropagationPolicy / OverridePolicy / workload resources on Karmada — i.e. Argo CD's destination is the Karmada API, not the edges directly.
- ApplicationSets fan out per-tenant Applications. AppProject + Dex/OIDC enforce that a tenant only sees their own apps.
- Push mode by default; declare specific clusters as pull-mode if their network policy requires.
- Status flows back: Karmada surfaces per-edge object status on the master; Argo CD UI surfaces Application sync status per cluster.

### Alternative 1: Argo CD ApplicationSets alone (no Karmada)

If you can give up the "master is a K8s cluster end users talk to" abstraction, run Argo CD on the master directly against the 50+ edges. ApplicationSet's Cluster generator already does the per-edge fan-out; per-attribute overrides come from cluster labels feeding the Helm/Kustomize templates.

Tradeoff: end users now interact with Argo CD (UI / API / git) rather than the K8s API. Simpler stack, fewer moving parts, but the platform contract changes.

### Alternative 2: OCM + Argo CD addon (pull-only)

If a strict no-inbound network policy at edges is non-negotiable, replace Karmada with OCM. Use the [OCM Argo CD addon](https://open-cluster-management.io/concepts/policy/) to drive ManifestWork from a Git source. The end-user UX is closer to Argo CD's than Karmada's (no transparent master K8s API), but the agent-side pull semantics are stronger than Karmada's pull mode in defense-in-depth posture and have a longer multi-vendor production history through RHACM.

### What not to do

- Do not build on KubeFed v2 — dormant.
- Do not use Liqo for this shape — wrong abstraction.
- Do not pick Clusternet as primary unless you specifically need its NAT-traversal story and accept the smaller community.
- Do not use a service mesh (Submariner, Cilium ClusterMesh, Skupper) *as* federation — those are L4/L7 networking layers, not config federation, and out of scope per your direction.
