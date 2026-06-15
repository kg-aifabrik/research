#!/usr/bin/env bash
# M3b: block storage — CephBlockPool + RBD StorageClass, then a PVC mounted in a pod.
set -euo pipefail
kubectl apply -f "$HOME/k8s/rook/blockpool-sc.yaml"
echo "### wait for CephBlockPool Ready"
for i in $(seq 1 20); do
  p=$(kubectl -n rook-ceph get cephblockpool replicapool -o jsonpath="{.status.phase}" 2>/dev/null)
  echo "  pool phase=$p"; [ "$p" = "Ready" ] && break; sleep 6
done
echo "### PVC + pod that writes to the RBD volume"
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: block-pvc }
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: rook-ceph-block
  resources: { requests: { storage: 3Gi } }
---
apiVersion: v1
kind: Pod
metadata: { name: block-test }
spec:
  containers:
    - name: c
      image: busybox:1.36
      command: ["sh","-c","echo hello-ceph-block-$(date +%s) > /mnt/block/test.txt; sync; sleep 3600"]
      volumeMounts: [{ name: vol, mountPath: /mnt/block }]
  volumes:
    - name: vol
      persistentVolumeClaim: { claimName: block-pvc }
EOF
kubectl wait --for=condition=Ready pod/block-test --timeout=180s
echo "### evidence"
kubectl get pvc block-pvc
kubectl exec block-test -- sh -c 'cat /mnt/block/test.txt; echo "---"; df -h /mnt/block | tail -1; echo "---"; mount | grep /mnt/block'
