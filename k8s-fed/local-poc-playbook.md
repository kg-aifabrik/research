# Local POC Playbook: k8s Federation + Virtualization on macOS

Stitch the recommended stack end-to-end on a single macOS laptop. Validates the architectural flow from [oss-federation-survey.md](oss-federation-survey.md) and [vk8s-survey.md](vk8s-survey.md) without GPUs, without real edge networking, and without scale.

## Scope

**In scope:**
- 1 master Kubernetes cluster + 2 site clusters + 2 tenant vClusters, all on one laptop, on Colima (no Docker Desktop).
- Karmada federation in push mode, master → sites.
- Argo CD on the master (used to bootstrap Karmada policies and tenant vClusters from manifests).
- A minimal placement controller (Python, ~80 LOC) that turns `platform.example.com/sites` annotations on tenant resources into Karmada `PropagationPolicy` objects on the master.
- End-to-end test: tenant authors a Deployment in their vCluster with a placement annotation; Pod lands on the right site(s), in the right per-tenant namespace, pinned to a labeled "node pool."

**Out of scope (per your direction):**
- GPU scheduling, fake-GPU operators.
- Network latency, partition simulation, pull-mode federation.
- Real IdP integration, real SSO. Tenant authentication uses the vCluster's auto-generated kubeconfig.
- Production hardening of the placement controller (no caching, no retries beyond what kopf provides).

## Tool inventory (installed during M0)

| Tool | Why | Install |
|---|---|---|
| Colima | Docker-compatible runtime (no Docker Desktop) | `brew install colima` |
| kind | Three K8s clusters in containers | `brew install kind` |
| kubectl | K8s CLI | `brew install kubectl` |
| helm | Argo CD / Karmada Helm charts (optional, depends on path) | `brew install helm` |
| karmadactl | Karmada install + cluster registration | `brew install karmada-io/tap/karmadactl` |
| vcluster | vCluster CLI | `brew install vcluster` |
| Python 3 + kopf | Placement controller | `pip3 install kopf kubernetes` |

Expected end-state RAM usage: ~5 GB. Configure Colima with at least 12 GB RAM and 4 CPUs.

## Milestones overview

| # | Milestone | Time |
|---|---|---|
| M0 | Prerequisites: Colima + CLI tools | ~10 min |
| M1 | Three kind clusters (`master`, `site-1`, `site-2`) on the kind Docker network | ~10 min |
| M2 | Karmada control plane on the master | ~10 min |
| M3 | Register `site-1` and `site-2` with Karmada (push mode) | ~5 min |
| M4 | Argo CD on the master | ~5 min |
| M5 | vCluster operator + two tenant vClusters (`tenant-a`, `tenant-b`) | ~10 min |
| M6 | Per-tenant namespaces + "node pool" labels on each site cluster | ~5 min |
| M7 | Default `ClusterPropagationPolicy` + `OverridePolicy` per tenant | ~10 min |
| M8 | Placement controller (Python/kopf) | ~30 min |
| M9 | End-to-end validation: deploy from tenant vCluster, verify on sites | ~15 min |
| M10 | Teardown | ~5 min |

Total: ~2 hours hands-on if everything goes smoothly.

---

## M0: Prerequisites

**Goal.** Colima running with 12 GB RAM / 4 CPUs; all CLI tools installed; `docker ps` works.

**Commands.**
```bash
brew install colima kind kubectl helm vcluster
brew install karmada-io/tap/karmadactl   # or download release binary if tap unavailable

# Start Colima with enough headroom
colima start --memory 12 --cpu 4 --disk 60

# Python placement controller deps
python3 -m pip install --user kopf kubernetes pyyaml
```

**Verify.**
```bash
colima status              # status: Running
docker ps                  # empty list, no error
kind version               # >= 0.22
kubectl version --client
karmadactl version
vcluster version
python3 -c "import kopf, kubernetes; print('ok')"
```

**Troubleshoot.**
- `docker: command not found` → Colima ships its own docker CLI shim. If missing, `brew install docker` (the CLI only, not Desktop).
- Colima fails to start with VM error → `colima delete && colima start --memory 12 --cpu 4 --vm-type vz` (vz uses macOS Virtualization.framework, fastest on Apple Silicon).

---

## M1: Three kind clusters

**Goal.** Three K8s clusters running on the kind Docker network with cross-cluster reachability of their API servers.

**Commands.**
```bash
mkdir -p ~/kfed-poc && cd ~/kfed-poc

cat > kind-master.yaml <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: master
networking:
  apiServerAddress: "127.0.0.1"
  apiServerPort: 6443
nodes:
  - role: control-plane
EOF

cat > kind-site-1.yaml <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: site-1
networking:
  apiServerAddress: "127.0.0.1"
  apiServerPort: 6444
nodes:
  - role: control-plane
  - role: worker
  - role: worker
EOF

cat > kind-site-2.yaml <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: site-2
networking:
  apiServerAddress: "127.0.0.1"
  apiServerPort: 6445
nodes:
  - role: control-plane
  - role: worker
  - role: worker
EOF

kind create cluster --config kind-master.yaml
kind create cluster --config kind-site-1.yaml
kind create cluster --config kind-site-2.yaml
```

**Verify.**
```bash
kind get clusters                                   # master, site-1, site-2
kubectl --context kind-master get nodes             # 1 node, Ready
kubectl --context kind-site-1 get nodes             # 3 nodes
kubectl --context kind-site-2 get nodes             # 3 nodes
docker network inspect kind | grep -A1 Containers   # 9 containers (3+3+3 nodes)
```

**Generate internal kubeconfigs for sites** (needed for Karmada join in M3; Karmada must reach site API servers via the kind Docker network, not via `127.0.0.1:644x`).
```bash
# Get internal IPs of the site control planes
SITE1_IP=$(docker inspect site-1-control-plane -f '{{.NetworkSettings.Networks.kind.IPAddress}}')
SITE2_IP=$(docker inspect site-2-control-plane -f '{{.NetworkSettings.Networks.kind.IPAddress}}')

kind get kubeconfig --name site-1 --internal | sed "s/site-1-control-plane/${SITE1_IP}/" > ~/kfed-poc/site-1.internal.kubeconfig
kind get kubeconfig --name site-2 --internal | sed "s/site-2-control-plane/${SITE2_IP}/" > ~/kfed-poc/site-2.internal.kubeconfig
```

**Troubleshoot.**
- Port already in use → change `apiServerPort` in the config and recreate.
- Out-of-memory during kind create → bump Colima RAM (`colima stop && colima start --memory 16 --cpu 4`).

---

## M2: Karmada on master

**Goal.** Karmada control plane running in `karmada-system` on the master cluster, with its own apiserver, etcd, controllers, scheduler, and webhook.

**Commands.**
```bash
kubectl config use-context kind-master

karmadactl init \
  --karmada-data ~/kfed-poc/karmada \
  --karmada-pki ~/kfed-poc/karmada/pki \
  --kube-image-mirror-country=""    # leave empty unless behind a regional mirror

# karmadactl init writes a kubeconfig pointing at the karmada-apiserver
export KARMADA_KUBECONFIG=~/kfed-poc/karmada/karmada-apiserver.config
```

**Verify.**
```bash
kubectl --context kind-master -n karmada-system get pods
# Expect: karmada-apiserver, karmada-controller-manager, karmada-scheduler,
#         karmada-webhook, karmada-aggregated-apiserver, etcd-0 (all Running)

kubectl --kubeconfig $KARMADA_KUBECONFIG get clusters
# Expect: No resources found (sites not joined yet)
```

**Troubleshoot.**
- karmadactl init pulls multiple ~500 MB images → first run is slow. Wait it out.
- Image pull failures → set `--kube-image-registry` to a mirror reachable from your network.

---

## M3: Register sites with Karmada (push mode)

**Goal.** Both site clusters appear as `Cluster` resources in the Karmada apiserver, status `Ready`.

**Commands.**
```bash
karmadactl --kubeconfig $KARMADA_KUBECONFIG join site-1 \
  --cluster-kubeconfig ~/kfed-poc/site-1.internal.kubeconfig

karmadactl --kubeconfig $KARMADA_KUBECONFIG join site-2 \
  --cluster-kubeconfig ~/kfed-poc/site-2.internal.kubeconfig
```

**Verify.**
```bash
kubectl --kubeconfig $KARMADA_KUBECONFIG get clusters
# NAME     VERSION   MODE   READY   AGE
# site-1   v1.30.x   Push   True    1m
# site-2   v1.30.x   Push   True    1m
```

**Troubleshoot.**
- Status `Unknown`/`False` → confirm kubeconfig has the kind-network IP, not `127.0.0.1`. Re-run M1's IP substitution.
- `x509: certificate signed by unknown authority` → re-generate site internal kubeconfigs; the `--internal` flag from M1 must be present.

---

## M4: Argo CD on master

**Goal.** Argo CD running in `argocd` namespace on the master, UI reachable via port-forward. Argo will manage Karmada policies and tenant vCluster manifests in later milestones.

**Commands.**
```bash
kubectl --context kind-master create namespace argocd
kubectl --context kind-master -n argocd apply -f \
  https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for Argo CD to be ready
kubectl --context kind-master -n argocd wait --for=condition=available --timeout=300s deploy/argocd-server
```

**Verify.**
```bash
kubectl --context kind-master -n argocd get pods            # all Running
ARGO_PASSWORD=$(kubectl --context kind-master -n argocd \
  get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)
echo "Argo CD admin password: $ARGO_PASSWORD"

# Optional: port-forward in another terminal to access UI
# kubectl --context kind-master -n argocd port-forward svc/argocd-server 8080:443
# Open https://localhost:8080 (user: admin, password: $ARGO_PASSWORD)
```

---

## M5: vCluster operator + two tenant vClusters

**Goal.** Two host namespaces (`tenant-customer-a`, `tenant-customer-b`) on the master, each running a vCluster.

**Commands.**
```bash
kubectl --context kind-master create namespace tenant-customer-a
kubectl --context kind-master create namespace tenant-customer-b

# vCluster CLI provisions the vcluster as a StatefulSet in the target namespace
vcluster create tenant-a -n tenant-customer-a --context kind-master --connect=false
vcluster create tenant-b -n tenant-customer-b --context kind-master --connect=false
```

**Verify.**
```bash
kubectl --context kind-master -n tenant-customer-a get pods   # tenant-a-0 Running
kubectl --context kind-master -n tenant-customer-b get pods   # tenant-b-0 Running

# Connect to tenant-a as if you were the tenant and confirm it looks like a real cluster
vcluster connect tenant-a -n tenant-customer-a --context kind-master -- kubectl get ns
# Expect: default, kube-system, kube-public, kube-node-lease (tenant's view, not host's)
```

**Troubleshoot.**
- vcluster pod CrashLoopBackOff with TLS errors → delete and recreate; sometimes the first attempt races on TLS cert generation.
- `vcluster connect` hangs → check that the vcluster service has an endpoint: `kubectl -n tenant-customer-a get endpoints tenant-a`.

---

## M6: Per-tenant namespaces and node-pool labels on sites

**Goal.** Each site cluster has `tenant-customer-a` and `tenant-customer-b` namespaces. Worker nodes are labeled so the OverridePolicy can pin Pods to "their tenant's nodes" — synthetic stand-in for the production node-pool dedication.

**Commands.**
```bash
for site in site-1 site-2; do
  kubectl --context kind-$site create namespace tenant-customer-a
  kubectl --context kind-$site create namespace tenant-customer-b
  kubectl --context kind-$site create namespace platform-system

  # Two worker nodes per site → assign one to each tenant for the POC
  WORKERS=$(kubectl --context kind-$site get nodes -l '!node-role.kubernetes.io/control-plane' -o name | head -2)
  W1=$(echo "$WORKERS" | sed -n 1p)
  W2=$(echo "$WORKERS" | sed -n 2p)
  kubectl --context kind-$site label $W1 gpu-owner=customer-a --overwrite
  kubectl --context kind-$site label $W2 gpu-owner=customer-b --overwrite
done
```

**Verify.**
```bash
kubectl --context kind-site-1 get nodes -L gpu-owner
# control-plane node has no label; workers split between customer-a and customer-b
```

---

## M7: Default propagation + override per tenant

**Goal.** Resources in `tenant-customer-a` on the Karmada apiserver propagate to both sites by default, with `nodeSelector: gpu-owner=customer-a` injected. Same for tenant-b.

**Commands.**
```bash
cat > tenant-a-defaults.yaml <<'EOF'
---
apiVersion: policy.karmada.io/v1alpha1
kind: ClusterPropagationPolicy
metadata:
  name: tenant-a-default
spec:
  resourceSelectors:
    - apiVersion: apps/v1
      kind: Deployment
      namespace: tenant-customer-a
    - apiVersion: v1
      kind: Service
      namespace: tenant-customer-a
    - apiVersion: v1
      kind: ConfigMap
      namespace: tenant-customer-a
  placement:
    clusterAffinity:
      clusterNames: [site-1, site-2]
---
apiVersion: policy.karmada.io/v1alpha1
kind: ClusterOverridePolicy
metadata:
  name: tenant-a-nodepool
spec:
  resourceSelectors:
    - apiVersion: apps/v1
      kind: Deployment
      namespace: tenant-customer-a
  overrideRules:
    - targetCluster:
        clusterNames: [site-1, site-2]
      overriders:
        plaintext:
          - path: /spec/template/spec/nodeSelector
            operator: replace
            value:
              gpu-owner: customer-a
EOF

# tenant-b-defaults.yaml: identical with customer-a → customer-b throughout
sed 's/customer-a/customer-b/g; s/tenant-a/tenant-b/g' tenant-a-defaults.yaml > tenant-b-defaults.yaml

kubectl --kubeconfig $KARMADA_KUBECONFIG apply -f tenant-a-defaults.yaml
kubectl --kubeconfig $KARMADA_KUBECONFIG apply -f tenant-b-defaults.yaml
```

**Verify.**
```bash
kubectl --kubeconfig $KARMADA_KUBECONFIG get clusterpropagationpolicy
kubectl --kubeconfig $KARMADA_KUBECONFIG get clusteroverridepolicy
```

A propagation will not happen yet because no Deployment has been created in `tenant-customer-a` on the Karmada apiserver. That happens in M9.

---

## M8: Placement controller

**Goal.** A Python controller on the master watches the Karmada apiserver. When a Deployment carries `platform.example.com/sites: [site-1, site-2]` or `[site-1]`, it creates a per-resource `PropagationPolicy` that narrows the default. If the annotation is absent or equals `all`, the default policy from M7 applies and no per-resource policy is generated.

**Code.** `~/kfed-poc/placement-controller/main.py`
```python
import kopf
import kubernetes
import os

KARMADA_KUBECONFIG = os.environ["KARMADA_KUBECONFIG"]

@kopf.on.startup()
def configure(settings, **_):
    kubernetes.config.load_kube_config(KARMADA_KUBECONFIG)

ANNOTATION = "platform.example.com/sites"

def parse_sites(v):
    if not v or v.strip().lower() == "all":
        return None
    return [s.strip() for s in v.strip("[] ").split(",") if s.strip()]

@kopf.on.create("apps", "v1", "deployments")
@kopf.on.update("apps", "v1", "deployments")
def upsert_pp(name, namespace, annotations, **_):
    if not namespace.startswith("tenant-customer-"):
        return
    sites = parse_sites(annotations.get(ANNOTATION))
    api = kubernetes.client.CustomObjectsApi()
    pp_name = f"auto-{name}"
    if sites is None:
        try:
            api.delete_namespaced_custom_object(
                "policy.karmada.io", "v1alpha1", namespace,
                "propagationpolicies", pp_name)
        except kubernetes.client.exceptions.ApiException:
            pass
        return
    body = {
        "apiVersion": "policy.karmada.io/v1alpha1",
        "kind": "PropagationPolicy",
        "metadata": {"name": pp_name, "namespace": namespace,
                     "annotations": {"managed-by": "placement-controller"}},
        "spec": {
            "resourceSelectors": [{"apiVersion": "apps/v1", "kind": "Deployment", "name": name}],
            "placement": {"clusterAffinity": {"clusterNames": sites}},
            "priority": 10,
        },
    }
    try:
        api.create_namespaced_custom_object(
            "policy.karmada.io", "v1alpha1", namespace,
            "propagationpolicies", body)
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 409:
            api.replace_namespaced_custom_object(
                "policy.karmada.io", "v1alpha1", namespace,
                "propagationpolicies", pp_name, body)
        else:
            raise
```

**Run.**
```bash
cd ~/kfed-poc/placement-controller
export KARMADA_KUBECONFIG=~/kfed-poc/karmada/karmada-apiserver.config
python3 -m kopf run main.py --verbose
# Leave running in its own terminal
```

**Verify.** Sanity test the controller by hand-applying a Deployment in M9.

**Notes.** For POC simplicity the controller runs on your laptop as a Python process, not on the cluster. Productionizing it means wrapping in a container, adding RBAC, and deploying as a Deployment on the master in `platform-system`.

---

## M9: End-to-end validation

**Goal.** Tenant A authors a Deployment in their vCluster with a placement annotation. Pod lands on site-1 only, in `tenant-customer-a` namespace, on a node labelled `gpu-owner=customer-a`.

**Commands.**
```bash
# Connect as tenant-a
KUBECONFIG_A=$(vcluster connect tenant-a -n tenant-customer-a --context kind-master --print)

# Tenant-a creates a namespace and a Deployment
kubectl --kubeconfig <(echo "$KUBECONFIG_A") create namespace inference

cat > tenant-a-app.yaml <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: echo-server
  namespace: inference
  annotations:
    platform.example.com/sites: "site-1"
spec:
  replicas: 1
  selector:
    matchLabels: { app: echo }
  template:
    metadata:
      labels: { app: echo }
    spec:
      containers:
        - name: echo
          image: ealen/echo-server:0.9.2
          ports: [{ containerPort: 80 }]
EOF

kubectl --kubeconfig <(echo "$KUBECONFIG_A") apply -f tenant-a-app.yaml
```

**Verify (end-to-end trace).**
```bash
# 1. vCluster syncs the Deployment to the host namespace on the master
kubectl --context kind-master -n tenant-customer-a get deploy
# Expect: a Deployment named echo-server-x-inference-x-tenant-a (vcluster name mangling)

# 2. The Deployment appears on the Karmada apiserver (vCluster's syncer writes to the host k8s,
#    but Karmada watches host-cluster resources via the same apiserver, so we look there).
#    Note: depending on vcluster sync config, the Deployment may need to be in a specific shape.
kubectl --kubeconfig $KARMADA_KUBECONFIG -n tenant-customer-a get deploy

# 3. The placement controller has created a PropagationPolicy
kubectl --kubeconfig $KARMADA_KUBECONFIG -n tenant-customer-a get propagationpolicy
# Expect: auto-echo-server-x-inference-x-tenant-a (or similar, scoped to site-1)

# 4. Karmada has propagated to site-1 only
kubectl --context kind-site-1 -n tenant-customer-a get pods -o wide
# Expect: pod Running, node has label gpu-owner=customer-a

kubectl --context kind-site-2 -n tenant-customer-a get pods
# Expect: No resources found

# 5. Flip the annotation to site-1,site-2 and re-apply; pods should appear on both sites
```

**Troubleshoot.**
- Deployment created in vCluster does not appear in host namespace → vCluster sync filters; ensure default sync (Pods, Services, Deployments) is enabled. `vcluster connect tenant-a -n tenant-customer-a -- kubectl get deploy -A` to confirm tenant view; check `kubectl -n tenant-customer-a logs statefulset/tenant-a` for sync errors.
- Pod stuck Pending on site → check nodeSelector + node labels match.
- Karmada says `Applied=False` → `kubectl --kubeconfig $KARMADA_KUBECONFIG describe propagationpolicy <name> -n tenant-customer-a` for the reason.

---

## M10: Teardown

**Goal.** Free the laptop.

**Commands.**
```bash
kind delete clusters master site-1 site-2
colima stop
# Optional: colima delete   # removes the VM entirely
# Optional: brew uninstall colima kind karmada-io/tap/karmadactl vcluster
```

---

## What the POC proves

- Tenant uses their vCluster API, never touches the Karmada apiserver.
- Default propagation hits all sites, override pins workloads to a tenant-specific node label, per-tenant namespaces are honored.
- Placement annotation on tenant resource overrides the default to a subset of sites, dynamically, with no tenant-visible federation construct.

## What the POC does **not** prove

- Real GPU scheduling, real GPU drivers, real GPU isolation.
- Partition handling, network latency, pull-mode federation.
- Scale (Karmada's per-site controllers, vCluster density on master, etcd write rates at 100+ tenants).
- IdP integration.
- Persistent storage choices.
- Status surfacing back to the tenant (the "SiteStatus CR in each vcluster" piece from the survey is not implemented here).

Validate those separately on real infrastructure before any production commitment.
