#!/usr/bin/env bash
# M5: seed ~1 GB of objects into the bucket over the storage VLAN.
# A pod on storage-net downloads a real public dataset (food101 parquet shards from
# the Hugging Face CDN, no auth), splits into ~4 MB chunks (-> many objects), and
# uploads via s5cmd to the RGW shim endpoint (10.6.32.250 = storage VLAN).
set -euo pipefail
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: seed
  annotations: { k8s.v1.cni.cncf.io/networks: storage-net }
spec:
  restartPolicy: Never
  containers:
    - name: c
      image: python:3.12-slim
      command: ["sleep","7200"]
      envFrom:
        - configMapRef: { name: seed-bucket }
        - secretRef: { name: seed-bucket }
      resources: { requests: { memory: "512Mi" }, limits: { memory: "1Gi" } }
EOF
kubectl wait --for=condition=Ready pod/seed --timeout=150s
kubectl exec seed -- bash -c '
set -e
apt-get -qq update >/dev/null && apt-get -qq install -y curl >/dev/null
pip install -q huggingface_hub >/dev/null
curl -fsSL https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_linux_arm64.tar.gz | tar -xz -C /usr/local/bin s5cmd
mkdir -p /data/dl /data/obj
python3 - <<PY
from huggingface_hub import snapshot_download
snapshot_download(repo_id="ethz/food101", repo_type="dataset",
  allow_patterns=["data/train-0000[0-5]*.parquet"], local_dir="/data/dl")
PY
echo "downloaded:"; du -sh /data/dl
cd /data/obj; for f in $(find /data/dl -type f); do split -b 4m -d "$f" "o_$(basename "$f")_"; done
echo "object count to upload:"; ls | wc -l
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
s5cmd --endpoint-url http://10.6.32.250 cp "/data/obj/*" "s3://$BUCKET_NAME/seed/"
echo "=== bucket object count ==="; s5cmd --endpoint-url http://10.6.32.250 ls "s3://$BUCKET_NAME/seed/" | wc -l
echo "=== bucket size ==="; s5cmd --endpoint-url http://10.6.32.250 du "s3://$BUCKET_NAME/" 2>/dev/null | tail -1
'
