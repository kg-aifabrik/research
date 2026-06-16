#!/usr/bin/env python3
"""Pull-through model cache backed by Ceph RGW (S3).

On a cache HIT the model is served from the Ceph object store over the STORAGE
VLAN (the pod's macvlan -> RGW); only a MISS or an expired entry fetches from
Hugging Face. Freshness/TTL is tracked by a per-model manifest object
(.cache-meta.json) holding the fill timestamp.

Env: HF_REPO, HF_REVISION (default main), TTL_SECONDS (default 86400),
     S3_ENDPOINT (default the storage-VLAN RGW shim), BUCKET_NAME + AWS creds
     (from the ObjectBucketClaim), LOCAL_DIR (where the model lands).
"""
import os, sys, time, json, boto3
from botocore.config import Config

REPO = os.environ["HF_REPO"]
REV = os.environ.get("HF_REVISION", "main")
TTL = int(os.environ.get("TTL_SECONDS", "86400"))
ENDPOINT = os.environ.get("S3_ENDPOINT", "http://10.6.32.250")   # RGW on the storage VLAN
BUCKET = os.environ["BUCKET_NAME"]
LOCAL = os.environ.get("LOCAL_DIR", "/models/current")
PREFIX = f"models/{REPO}@{REV}/"
META = PREFIX + ".cache-meta.json"
ALLOW = ["*.safetensors", "*.json", "merges.txt", "vocab.json", "tokenizer*", "*.model"]

s3 = boto3.client(
    "s3", endpoint_url=ENDPOINT,
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name="us-east-1",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)


def cache_state():
    try:
        m = json.loads(s3.get_object(Bucket=BUCKET, Key=META)["Body"].read())
        age = time.time() - m["cached_at"]
        return ("HIT" if age < TTL else "STALE"), age, m.get("files", 0)
    except Exception:
        return "MISS", None, 0


def download_from_cache():
    os.makedirs(LOCAL, exist_ok=True)
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".cache-meta.json"):
                continue
            dst = os.path.join(LOCAL, o["Key"][len(PREFIX):])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            s3.download_file(BUCKET, o["Key"], dst)
            n += 1
    return n


def fill_from_hf():
    from huggingface_hub import snapshot_download
    snapshot_download(REPO, revision=REV, local_dir=LOCAL, allow_patterns=ALLOW)
    files = 0
    for root, _, fs in os.walk(LOCAL):
        for f in fs:
            full = os.path.join(root, f)
            s3.upload_file(full, BUCKET, PREFIX + os.path.relpath(full, LOCAL))
            files += 1
    s3.put_object(Bucket=BUCKET, Key=META,
                  Body=json.dumps({"cached_at": time.time(), "files": files,
                                   "repo": REPO, "rev": REV}).encode())
    return files


def ensure_lifecycle(days=1):
    """RGW-native TTL: auto-expire cached objects after N days (storage reclaim)."""
    try:
        s3.put_bucket_lifecycle_configuration(
            Bucket=BUCKET,
            LifecycleConfiguration={"Rules": [{
                "ID": "model-cache-ttl", "Filter": {"Prefix": "models/"},
                "Status": "Enabled", "Expiration": {"Days": days}}]})
    except Exception as e:
        print(f"[model-cache] lifecycle set skipped: {e}")


ensure_lifecycle(int(os.environ.get("LIFECYCLE_DAYS", "1")))
state, age, nfiles = cache_state()
agestr = f" (age={int(age)}s, {nfiles} files cached)" if age is not None else ""
print(f"[model-cache] {REPO}@{REV}  TTL={TTL}s  ->  {state}{agestr}")

if state == "HIT":
    n = download_from_cache()
    print(f"[model-cache] CACHE HIT: served {n} files FROM CEPH OBJECT STORE over the storage VLAN "
          f"(zero Hugging Face / north-south traffic)")
else:
    print(f"[model-cache] {state}: filling from Hugging Face (one-time) then caching to Ceph...")
    f = fill_from_hf()
    print(f"[model-cache] cached {f} files to s3://{BUCKET}/{PREFIX} — future loads served over the storage VLAN")

print(f"[model-cache] model ready at {LOCAL}: {sorted(os.listdir(LOCAL))[:8]}")
