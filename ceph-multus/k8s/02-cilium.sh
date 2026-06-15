#!/usr/bin/env bash
# M1b: install Cilium as the primary CNI (native routing, kube-proxy kept,
# cni.exclusive=false so Multus can chain secondaries).
set -euo pipefail
CIL_VER=${CIL_VER:-1.19.4}
command -v helm >/dev/null 2>&1 || curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | sudo bash >/dev/null
echo "### installing cilium $CIL_VER"
helm install cilium oci://quay.io/cilium/charts/cilium --version "$CIL_VER" \
  -n kube-system -f "$HOME/k8s/cilium-values.yaml"
kubectl -n kube-system rollout status ds/cilium --timeout=360s
kubectl -n kube-system rollout status deploy/cilium-operator --timeout=360s
echo "### nodes + cilium pods"
kubectl get nodes -o wide
kubectl -n kube-system get pods -l k8s-app=cilium -o wide
