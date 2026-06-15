#!/usr/bin/env bash
# M3a: install the Rook operator via Helm and create the CephCluster.
# Pinned to v1.16.9 (embedded CSI: deploys csi-rbdplugin directly). v1.20 was
# tried first but its mandatory ceph-csi-operator never deployed the rbd Driver
# pods in this lab (PVCs stuck Pending) — the documented v1.20 CSI breaking change.
# v1.16.9 + Ceph v19.2.2 is a tested combo that provisions RBD out of the box.
set -euo pipefail
ROOK_VER=${ROOK_VER:-v1.16.9}
B="https://raw.githubusercontent.com/rook/rook/${ROOK_VER}/deploy/examples"

echo "### clean any partial manual Rook install"
kubectl delete -f "${B}/operator.yaml" --ignore-not-found 2>/dev/null || true
kubectl delete -f "${B}/common.yaml"   --ignore-not-found 2>/dev/null || true
kubectl delete -f "${B}/crds.yaml"     --ignore-not-found 2>/dev/null || true
kubectl delete ns rook-ceph --ignore-not-found --timeout=90s 2>/dev/null || true

echo "### Rook operator via Helm ${ROOK_VER} (bundles ceph-csi-operator CRDs)"
command -v helm >/dev/null 2>&1 || curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | sudo bash >/dev/null
helm repo add rook-release https://charts.rook.io/release >/dev/null 2>&1 || true
helm repo update >/dev/null
helm install rook-ceph rook-release/rook-ceph --version "${ROOK_VER}" -n rook-ceph --create-namespace
kubectl -n rook-ceph rollout status deploy/rook-ceph-operator --timeout=300s

echo "### config-override + CephCluster (host-net on storage VLAN)"
kubectl apply -f "$HOME/k8s/rook/config-override.yaml"
kubectl apply -f "$HOME/k8s/rook/cluster.yaml"
kubectl apply -f "https://raw.githubusercontent.com/rook/rook/${ROOK_VER}/deploy/examples/toolbox.yaml" >/dev/null 2>&1 || true
kubectl -n rook-ceph rollout status deploy/rook-ceph-tools --timeout=180s 2>/dev/null || true
echo "### applied; convergence polled separately"
