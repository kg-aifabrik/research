#!/usr/bin/env bash
# M6: end-to-end demo. A pod with 3 interfaces (Cilium + 2 macvlan) and an RBD
# block PVC: downloads a small Hugging Face model onto the block volume, then does
# an S3 round-trip (download seeded objects + upload new ones) over the storage VLAN.
set -euo pipefail
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: demo-block }
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: rook-ceph-block
  resources: { requests: { storage: 4Gi } }
---
apiVersion: v1
kind: Pod
metadata:
  name: demo
  annotations: { k8s.v1.cni.cncf.io/networks: north-south-net, storage-net }
spec:
  containers:
    - name: c
      image: python:3.12-slim
      command: ["sleep","7200"]
      envFrom:
        - configMapRef: { name: seed-bucket }
        - secretRef: { name: seed-bucket }
      volumeMounts: [{ name: blk, mountPath: /mnt/block }]
      resources: { requests: { memory: "1Gi" }, limits: { memory: "2Gi" } }
  volumes:
    - name: blk
      persistentVolumeClaim: { claimName: demo-block }
EOF
kubectl wait --for=condition=Ready pod/demo --timeout=180s
echo "### demo pod interfaces (expect eth0 + net1 + net2):"
kubectl exec demo -- sh -c 'apt-get -qq update >/dev/null 2>&1; apt-get -qq install -y iproute2 >/dev/null 2>&1; ip -o -4 addr show | awk "{print \$2, \$4}" | grep -E "eth0|net1|net2"'
echo "### RBD block volume mounted:"
kubectl exec demo -- sh -c 'df -h /mnt/block | tail -1; mount | grep /mnt/block'
echo "### download small HF model onto the block volume:"
kubectl exec demo -- bash -c '
pip install -q huggingface_hub boto3 >/dev/null
python3 - <<PY
from huggingface_hub import snapshot_download
snapshot_download(repo_id="Qwen/Qwen2.5-0.5B-Instruct", local_dir="/mnt/block/model",
  allow_patterns=["*.safetensors","*.json","merges.txt","vocab.json","tokenizer*"])
PY
echo "model size on block:"; du -sh /mnt/block/model'
echo "### S3 round-trip over the storage VLAN (download seeded + upload new):"
kubectl exec demo -- bash -c '
python3 - <<PY
import os, boto3
from botocore.config import Config
b=os.environ["BUCKET_NAME"]
s3=boto3.client("s3", endpoint_url="http://10.6.32.250",
  aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
  region_name="us-east-1", config=Config(signature_version="s3v4", s3={"addressing_style":"path"}))
seeded=s3.list_objects_v2(Bucket=b, Prefix="seed/").get("Contents",[])
print("seeded objects visible:", len(seeded))
os.makedirs("/mnt/block/dl", exist_ok=True)
for o in seeded[:5]:
    s3.download_file(b, o["Key"], "/mnt/block/dl/"+o["Key"].split("/")[-1])
print("downloaded 5 seeded objects -> /mnt/block/dl")
for i in range(10):
    s3.put_object(Bucket=b, Key=f"demo/new-{i}.bin", Body=os.urandom(1024))
print("uploaded 10 new objects under demo/; demo/ count:",
      len(s3.list_objects_v2(Bucket=b, Prefix="demo/").get("Contents",[])))
PY
echo "local downloads on block:"; ls /mnt/block/dl | wc -l'
