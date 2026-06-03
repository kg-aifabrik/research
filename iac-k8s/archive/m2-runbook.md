# M2 Runbook — Deploy hardening + conformance report

Milestone 2: use **ArgoCD (D10)** to deploy the workload-hardening guardrails (k8s-hardening Tier-1 + Kyverno) onto the M1 cluster, then produce a **before/after conformance report**. Companion to the [implementation plan](implementation-plan.md). **Status: draft for review (M2 not started).**

## Access model — read this first

The M1 cluster has a **public control-plane endpoint restricted to your operator IP** (`108.221.21.223/32`). GitHub-hosted runners have dynamic IPs **not** on that allowlist, so they **cannot** run `kubectl`/`helm`/ArgoCD against the cluster.

**Decision for M2:** run the steps **from your authorized machine** (where Claude executes `kubectl`/`helm` locally — its calls originate from your allowed IP). M1's *infra* went through GitHub Actions; M2's *in-cluster* work runs locally for the POC.

> **M3 will need a better path.** For the console/runners to reach the cluster without IP allowlisting, M3 will use **GKE Connect Gateway** (fleet) — reach the API via Google's endpoint, no public IP exposure. Flagged for M3, out of scope here.

Tools: `kubectl`, `helm`, `gcloud`, plus the [`AI-Fabrik/k8s-hardening`](https://github.com/AI-Fabrik/k8s-hardening) repo (source of the Tier-1 manifests).

## Steps

### 1. Get kubeconfig + confirm reachability
```bash
gcloud container clusters get-credentials poc --region us-central1 --project k8s-iac-poc
kubectl get nodes -o wide   # expect ~5 nodes Ready across us-central1-a/b/c
```

### 2. Baseline scan (pre-hardening)
```bash
# kube-bench, GKE benchmark
kubectl apply -f scan/kube-bench-job.yaml   # patched with --benchmark gke-1.6.0
# kubescape CIS framework
kubescape scan framework cis-v1.10.0 --format json --output reports/baseline/kubescape.json
```
Save kube-bench + kubescape output under `iac-gke-poc/reports/baseline_<ts>/`.

### 3. Install ArgoCD (pinned)
```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/<vX.Y.Z>/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server
```

### 4. Deploy guardrails via ArgoCD (D10)
Vendor the Tier-1 content into `iac-gke-poc/gitops/guardrails/` (PSS labels, default-deny NetworkPolicy, RBAC, SA-automount-off + `kyverno-policies/`), then create two Apps:

- **`kyverno`** — Helm chart, **sync wave -1** (must exist before its policies).
- **`guardrails`** — `path: gitops/guardrails`, **sync wave 0**, `syncPolicy.automated` with **`selfHeal: true`, `prune: true`**.

```bash
kubectl apply -f gitops/argocd-apps/app-of-apps.yaml
argocd app wait guardrails --health   # (or kubectl wait on the Applications)
```

### 5. Post scan + delta
```bash
kubectl apply -f scan/kube-bench-job.yaml          # re-run
kubescape scan framework cis-v1.10.0 --format json --output reports/post/kubescape.json
# delta: diff baseline vs post (k8s-hardening harden.py renders delta.md, or diff scores.json)
```
Write `reports/post_<ts>/` + `reports/delta.md`.

### 6. Behavioral validation
```bash
# (a) Kyverno enforces: a privileged pod must be REJECTED
kubectl run pwn --image=nginx --privileged --restart=Never -o name   # expect admission DENY
# (b) Drift self-heal: delete a policy, ArgoCD restores it
kubectl delete clusterpolicy disallow-privileged
sleep 30 && kubectl get clusterpolicy disallow-privileged   # should be back
```

### 7. Commit the report (store of record)
```bash
cd iac-gke-poc && git checkout -b m2-report
git add reports/ gitops/ && git commit -m "M2: hardening guardrails + conformance report" && git push
gh pr create ...   # review like M1
```

## M2 done when
- Tier-1 guardrails live and **enforcing** (privileged pod rejected),
- drift **self-heals** (deleted policy restored by ArgoCD),
- a **baseline→post delta report** is produced and committed to `iac-gke-poc/reports/`.

## Things to watch
- **Binary Authorization (audit-only):** ArgoCD/Kyverno images (quay.io/ghcr) aren't on the BinAuthz whitelist, so they'll be **logged as would-deny** — expected, not blocking (DRYRUN).
- **`e2-small` capacity:** ArgoCD + Kyverno on small/Spot nodes may be tight. If pods stay Pending, bump `system`/`general` `machine_type` (one tfvars change → M1 apply) and retry.
- **Repo source for guardrails:** vendoring Tier-1 into `iac-gke-poc` avoids giving ArgoCD private-repo creds for `k8s-hardening`; keep the two in sync manually for the POC.
