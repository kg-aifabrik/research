#!/usr/bin/env bash
# Demonstrate the pull-through model cache on Ceph RGW (S3):
#   miss -> fill from HF + cache to Ceph;  hit -> serve from Ceph over the storage
#   VLAN (no HF traffic);  TTL expiry -> refill. Proves the hit's model bytes flow
#   on VLAN 2032 by capturing the RGW shim interface during the hit.
set -uo pipefail
MODEL=${MODEL:-Qwen/Qwen2.5-0.5B-Instruct}

echo "### cache bucket (ObjectBucketClaim)"
kubectl apply -f "$HOME/k8s/model-cache-obc.yaml"
for i in $(seq 1 24); do ph=$(kubectl get obc model-cache -o jsonpath="{.status.phase}" 2>/dev/null); echo "  obc=$ph"; [ "$ph" = Bound ] && break; sleep 5; done

echo "### ship the cache script + puller pod (storage-net)"
kubectl create configmap model-cache-script --from-file=model-cache.py="$HOME/k8s/model-cache.py" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl delete pod modelcache --grace-period=0 --force 2>/dev/null || true
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: modelcache
  annotations:
    k8s.v1.cni.cncf.io/networks: storage-net
spec:
  containers:
    - name: c
      image: python:3.12-slim
      command: ["sleep","7200"]
      envFrom:
        - configMapRef: { name: model-cache }
        - secretRef: { name: model-cache }
      volumeMounts:
        - { name: script, mountPath: /opt/cache }
        - { name: models, mountPath: /models }
      resources: { requests: { memory: "768Mi" }, limits: { memory: "1536Mi" } }
  volumes:
    - { name: script, configMap: { name: model-cache-script } }
    - { name: models, emptyDir: {} }
EOF
kubectl wait --for=condition=Ready pod/modelcache --timeout=150s
kubectl exec modelcache -- pip install -q boto3 huggingface_hub 2>/dev/null

run(){ kubectl exec modelcache -- env HF_REPO="$MODEL" TTL_SECONDS="$1" LOCAL_DIR="$2" python3 /opt/cache/model-cache.py 2>&1 | grep -E "model-cache"; }

echo; echo "### RUN 1 — cold cache (MISS): fill from Hugging Face, cache into Ceph"
run 3600 /models/m1

echo; echo "### RUN 2 — warm cache (HIT): serve from Ceph over the storage VLAN"
echo "    (capturing the RGW shim interface to prove model bytes ride VLAN 2032)"
sudo pkill tcpdump 2>/dev/null || true
sudo nohup timeout 40 tcpdump -n -i storage-shim 'tcp port 80' -w /tmp/hit.pcap >/dev/null 2>&1 &
sleep 1
run 3600 /models/m2
sleep 2; sudo pkill tcpdump 2>/dev/null || true; sleep 1
echo "    storage-VLAN bytes captured during the HIT (RGW shim, port 80):"
sudo tcpdump -nr /tmp/hit.pcap 2>/dev/null | wc -l | sed 's/^/      packets: /'
sudo tcpdump -nr /tmp/hit.pcap 2>/dev/null | head -2 | sed 's/^/      /'

echo; echo "### RUN 3 — TTL expiry (TTL_SECONDS=1 => STALE): cache re-fills from HF"
run 1 /models/m3

echo; echo "### S3 lifecycle (RGW-native TTL) on the cache bucket:"
kubectl exec modelcache -- python3 - <<'PY' 2>/dev/null
import os, json, boto3
from botocore.config import Config
s=boto3.client("s3", endpoint_url="http://10.6.32.250", aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
  aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"], region_name="us-east-1",
  config=Config(signature_version="s3v4", s3={"addressing_style":"path"}))
print("   ", json.dumps(s.get_bucket_lifecycle_configuration(Bucket=os.environ["BUCKET_NAME"])["Rules"]))
PY
echo "DONE"
