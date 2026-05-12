# k8s-fed

Research on Kubernetes federation technologies for a planned edge inference platform: one master cluster in a hyperscaler plus 50+ share-nothing edge clusters, full K8s API conformance, GitOps delivery, multi-tenant RBAC.

- **Current recommendation:** [Karmada](https://karmada.io) as the federation engine on the master + [Argo CD ApplicationSets](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/) for declarative delivery. Both Apache 2.0, both with strong multi-vendor governance and named production references at scale (ICBC, Intuit). See [oss-federation-survey.md](oss-federation-survey.md) / [.html](oss-federation-survey.html).
- **Credible alternative:** Open Cluster Management (OCM) + Argo CD addon, when a pull-only network posture or Red Hat ecosystem alignment is required.
- **Lean alternative:** Argo CD ApplicationSets alone (no federation engine) — simpler stack, but the master is no longer a transparent K8s API for end users.
- **Excluded:** KubeFed v2 (dormant), Liqo (wrong abstraction — offloading, not federation), Clusternet as primary (community traction below the inclusion bar). Rancher Fleet flagged as borderline on the clickbait-OSS criterion.
- **Push vs pull:** With stable master-to-edge connectivity, push is the cleaner default — lower latency, simpler debugging. Pull becomes the right call when edges sit behind NAT / customer firewalls or when defense-in-depth against a compromised master matters. Karmada supports both and can be mixed per-cluster.
- **Out of scope:** Cross-cluster networking (Submariner, Cilium ClusterMesh, Skupper) and cross-cluster identity (SPIFFE/SPIRE) — the share-nothing-edges design makes these unnecessary at the federation layer.

## Open threads

- Which specific IdP the platform will integrate with — affects whether Argo CD's built-in Dex is sufficient or whether a separate OIDC proxy is needed at the Karmada API.
- How status of CRDs (KServe `InferenceService`, vLLM operator CRDs, GPU Operator configs) should be aggregated on the master — likely requires per-CRD `ResourceInterpreterCustomization` in Karmada.
- Validate Flux community health at decision time, given the post-Weaveworks reorganization.
- Edge-cluster control-plane sizing has not been characterized; agent footprints in the survey are documented but the platform has not been benchmarked.
- Open question on stateful workloads: model-cache and vector-store data placement is a separate decision from the federation choice and has not been researched in this area yet.
