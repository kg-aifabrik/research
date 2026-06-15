#!/usr/bin/env bash
# M5: seed ~1 GB of objects into the bucket over the storage VLAN.
# A pod on storage-net downloads real public data (food101 parquet shards from the
# Hugging Face CDN, no auth) and uploads them as objects via boto3 to the RGW shim
# endpoint (10.6.32.250 = storage VLAN). Repo files are listed dynamically (no
# guessed paths); boto3 streams uploads (no extra CLI dependency).
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
      resources: { requests: { memory: "768Mi" }, limits: { memory: "1536Mi" } }
EOF
kubectl wait --for=condition=Ready pod/seed --timeout=150s
kubectl exec seed -- bash -c '
set -e
pip install -q huggingface_hub boto3 2>/dev/null
python3 - <<PY
import os, boto3
from botocore.config import Config
from huggingface_hub import list_repo_files, hf_hub_download
files = sorted(f for f in list_repo_files("ethz/food101", repo_type="dataset") if f.endswith(".parquet"))
print("parquet files in repo:", len(files))
b = os.environ["BUCKET_NAME"]
s3 = boto3.client("s3", endpoint_url="http://10.6.32.250",
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name="us-east-1", config=Config(signature_version="s3v4", s3={"addressing_style":"path"}))
total = 0
for f in files:
    if total > 1_000_000_000:
        break
    p = hf_hub_download("ethz/food101", f, repo_type="dataset", local_dir="/data")
    s3.upload_file(p, b, "seed/" + os.path.basename(f))
    total += os.path.getsize(p)
    print(f"  uploaded {os.path.basename(f)}  (+{os.path.getsize(p)//1024//1024} MB, total {total//1024//1024} MB)")
    os.remove(p)
objs = s3.list_objects_v2(Bucket=b, Prefix="seed/").get("Contents", [])
print("=== SEEDED:", len(objs), "objects,", sum(o["Size"] for o in objs)//1024//1024, "MB ===")
PY'
