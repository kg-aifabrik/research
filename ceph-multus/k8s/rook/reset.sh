#!/usr/bin/env bash
# Full clean teardown of Rook so it can be reinstalled on a truly clean slate.
# (In-place CephCluster recreate + wiping /var/lib/rook leaves the mon's store.db
# missing -> CrashLoopBackOff. This resets namespace, CRDs, host dirs, and disks.)
set -uo pipefail
echo "### force-clear ceph CRs (drop finalizers)"
for kind in cephcluster cephblockpool cephobjectstore cephobjectstoreuser cephfilesystem; do
  for r in $(kubectl -n rook-ceph get "$kind" -o name 2>/dev/null); do
    kubectl -n rook-ceph patch "$r" --type=merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true
  done
done
kubectl delete obc --all -A --wait=false 2>/dev/null || true
echo "### helm uninstall + delete namespace"
helm uninstall rook-ceph -n rook-ceph 2>/dev/null || true
kubectl delete ns rook-ceph --wait=false 2>/dev/null || true
for i in $(seq 1 12); do
  kubectl get ns rook-ceph >/dev/null 2>&1 || { echo "  ns gone"; break; }
  kubectl get ns rook-ceph -o json 2>/dev/null | jq 'del(.spec.finalizers)' \
    | kubectl replace --raw /api/v1/namespaces/rook-ceph/finalize -f - >/dev/null 2>&1 || true
  sleep 5
done
echo "### delete leftover CRDs (KEEP csi.ceph.io — deleting clientprofiles breaks reinstall)"
kubectl get crd -o name 2>/dev/null | grep -E "ceph.rook.io|objectbucket.io" \
  | xargs -r kubectl delete --wait=false 2>/dev/null || true
echo "### host clean + zap disks"
sudo rm -rf /var/lib/rook /var/lib/ceph 2>/dev/null || true
bash "$HOME/k8s/rook/zap-disks.sh"
echo "RESET DONE"
