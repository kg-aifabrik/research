# k8s-fed

Research on Kubernetes federation and per-tenant virtualization technologies for a planned edge inference platform: one master cluster in a hyperscaler plus 50+ share-nothing edge clusters (scaling to 100+ tenants and 50+ sites), full K8s API conformance, GitOps delivery, multi-tenant RBAC, per-tenant dedicated GPU capacity.

- **Federation engine + GitOps delivery:** [Karmada](https://karmada.io) on the master + [Argo CD ApplicationSets](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/) for declarative delivery. Both Apache 2.0, multi-vendor governance, named production references at scale (ICBC, Intuit). Push by default with stable master-to-edge connectivity; pull supported per-cluster for awkward network postures. See [oss-federation-survey.md](oss-federation-survey.md) / [.html](oss-federation-survey.html).
- **Virtualization layer:** [vCluster](https://www.vcluster.com/) on the master, one vcluster per tenant. Host-side visibility of synced tenant resources makes the federation translation trivial; density supports 100+ tenants per master. Kamaji is the alternative if hard control-plane isolation becomes a requirement; Hypershift only inside OpenShift; KCP not ready for production commitment. See [vk8s-survey.md](vk8s-survey.md) / [.html](vk8s-survey.html).
- **Translation layer (tenant intent → federation primitives):** Start lightest — a default Karmada `PropagationPolicy` per tenant host namespace + a small mutating webhook honoring `platform.example.com/sites` annotations. No tenant-facing CRDs, no Crossplane, no Kratix at day one. Promote to a custom controller only when placement logic outgrows annotations.
- **Site-cluster topology:** One plain K8s cluster per site (no virtualization at edges), per-tenant node pools via labels/taints, per-tenant namespaces. Each physical node dedicated to one tenant (no kernel sharing). Federation propagates resources into the right tenant namespace pinned to the right node pool.
- **Local POC playbook:** End-to-end on-macOS recipe (Colima + kind + Karmada + Argo CD + vCluster + placement controller) with 10 milestones and ~2 hours hands-on. See [local-poc-playbook.md](local-poc-playbook.md) / [.html](local-poc-playbook.html).
- **Excluded after review:** KubeFed v2 (dormant), Liqo (wrong abstraction — offloading not federation), Clusternet as primary (community traction below the inclusion bar), KubeVirt (VM-on-K8s, off-topic), Capsule / HNC (namespace-level multi-tenancy, not virtualization). Rancher Fleet flagged as borderline on the clickbait-OSS criterion.
- **Does virtualization change the federation choice?** No — Karmada + Argo CD still wins, but the topic-1 "K8s API on master for end users" argument weakens because tenants now meet the vcluster, not Karmada. Argo CD ApplicationSets alone is a more credible simplification post-virtualization than it was pre-virtualization.
- **Out of scope:** Cross-cluster networking (Submariner, Cilium ClusterMesh, Skupper) and cross-cluster identity (SPIFFE/SPIRE) — the share-nothing-edges design makes these unnecessary at the federation layer.

## Open threads

- Which specific IdP the platform will integrate with — affects whether Argo CD's built-in Dex is sufficient and how the per-vcluster OIDC configuration is bootstrapped.
- Status aggregation for tenant-installed CRDs likely requires per-CRD `ResourceInterpreterCustomization` in Karmada; not yet enumerated.
- Single-vendor concentration on vCluster (Loft Labs) and on Karmada (Huawei) — mitigation plan should be revisited at contract time.
- Projecting Karmada's per-site propagation status back into each tenant's vcluster (as a custom `SiteStatus` CR or equivalent) — no off-the-shelf controller; likely a small in-house piece.
- Validate Flux community health post-Weaveworks at decision time (relevant only if Flux replaces Argo CD).
- Edge-cluster control-plane sizing has not been benchmarked.
- Open thread on stateful workloads: model-cache and vector-store data placement is a separate decision from the federation choice and has not been researched in this area yet.
- Recommended next step: a 3-tenant, 3-site pilot validating vCluster density, Karmada propagation latency, and the translation webhook end-to-end before committing platform-wide.
