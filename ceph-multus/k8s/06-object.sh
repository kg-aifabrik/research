#!/usr/bin/env bash
# M3c: object storage — CephObjectStore (RGW) + ObjectBucketClaim, host shim,
# and an S3 PUT/GET from a pod over the storage VLAN (net2 macvlan -> shim -> RGW).
set -euo pipefail
kubectl apply -f "$HOME/k8s/rook/objectstore.yaml"
echo "### wait for RGW + OBC bound"
kubectl -n rook-ceph wait --for=condition=Ready cephobjectstore/my-store --timeout=300s 2>/dev/null || true
for i in $(seq 1 30); do
  ph=$(kubectl get obc seed-bucket -o jsonpath="{.status.phase}" 2>/dev/null)
  echo "  obc phase=$ph"; [ "$ph" = "Bound" ] && break; sleep 8
done
kubectl get obc seed-bucket
echo "### host macvlan shim on storage VLAN"
bash "$HOME/k8s/storage-shim.sh"

echo "### S3 client pod on the storage VLAN"
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: s3-test
  annotations:
    k8s.v1.cni.cncf.io/networks: storage-net
spec:
  containers:
    - name: c
      image: python:3.12-slim
      command: ["sleep","3600"]
      envFrom:
        - configMapRef: { name: seed-bucket }
        - secretRef: { name: seed-bucket }
EOF
kubectl wait --for=condition=Ready pod/s3-test --timeout=120s
echo "### route to RGW shim must use net2 (storage VLAN), not eth0:"
kubectl exec s3-test -- sh -c "apt-get -qq update >/dev/null 2>&1; apt-get -qq install -y iproute2 >/dev/null 2>&1; ip route get 10.6.32.250" || true
echo "### install boto3 and do an S3 round-trip over the storage VLAN"
kubectl exec s3-test -- sh -c '
pip install -q boto3 2>/dev/null
python3 - <<PY
import os, boto3
from botocore.config import Config
b=os.environ["BUCKET_NAME"]
s3=boto3.client("s3", endpoint_url="http://10.6.32.250",
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name="us-east-1", config=Config(signature_version="s3v4", s3={"addressing_style":"path"}))
s3.put_object(Bucket=b, Key="hello.txt", Body=b"hello-ceph-object-over-storage-vlan")
got=s3.get_object(Bucket=b, Key="hello.txt")["Body"].read().decode()
print("bucket:", b)
print("GET hello.txt ->", got)
print("keys:", [o["Key"] for o in s3.list_objects_v2(Bucket=b).get("Contents",[])])
PY'
