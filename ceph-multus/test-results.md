# ceph-multus — test results

Running log of the build (milestones from [implementation-plan.md](implementation-plan.md)). Each
milestone lists the **actions** taken and the **observed result** with evidence. Executed on a
**single beefy node first** (the plan's M3-first guidance) for reliability on 24 GB; the 3-node
scale is M4.

**Environment:** Apple M4 Pro · 24 GB · macOS. Node `cmnode1` = QEMU/HVF VM, Ubuntu 24.04 LTS arm64
(kernel 6.8.0-117), **6 vCPU / 14 GB**, 40 G OS disk + 2×15 G raw disks for Ceph OSDs. Data NIC on
the `cm_hub.py` L2 switch carrying the VLAN trunk; mgmt NIC = QEMU user-net (SSH + NAT egress).
Toolchain: containerd 2.2.1, kubeadm/kubelet/kubectl **v1.31.14**, Cilium **1.19.4**, Helm 3.

| Milestone | Result |
|---|---|
| M0 — multi-VLAN substrate | ✅ pass |
| M1 — kubeadm + Cilium primary | ✅ pass |
| M2 — Multus + 3-interface pod | ✅ pass |
| M3 — Rook-Ceph block + object | ✅ pass |
| M4 — scale to 3 nodes | ⏸ not run (single-node; see notes) |
| M5 — seed object store ~1 GB | ✅ pass |
| M6 — demo workload | ✅ pass |

---

## M0 — multi-VLAN substrate ✅

Covered in detail in [implementation-plan.md](implementation-plan.md#feasibility-results-proven-on-this-mac).
3 VMs on the `cm_hub.py` L2 switch, 18/18 cross-VLAN mesh, 802.1Q tags captured on the wire.

## M1 — kubeadm control plane + Cilium primary CNI ✅

**Actions** ([vm/provision-node.sh](vm/provision-node.sh), [k8s/01-kubeadm-init.sh](k8s/01-kubeadm-init.sh),
[k8s/02-cilium.sh](k8s/02-cilium.sh), [k8s/cilium-values.yaml](k8s/cilium-values.yaml)):

1. Provision node: swap off, `overlay`/`br_netfilter`, sysctls, containerd (SystemdCgroup), kube* v1.31, plus `conntrack socat ethtool`.
2. `kubeadm init --apiserver-advertise-address=10.6.31.1 --pod-network-cidr=10.245.0.0/16`, with `kubelet --node-ip=10.6.31.1` forced onto the in-band VLAN (the default route is the mgmt NIC). Single-node: control-plane untainted.
3. Install Cilium 1.19.4 via Helm: `routingMode=native`, `kubeProxyReplacement=false`, `cni.exclusive=false`, `ipam=kubernetes`.

**Result:** node `Ready`, control plane advertised on the VLAN, pod-to-pod + cluster DNS + internet egress all working.

```
NAME      STATUS   ROLES           VERSION    INTERNAL-IP   CONTAINER-RUNTIME
cmnode1   Ready    control-plane   v1.31.14   10.6.31.1     containerd://2.2.1     # node IP on VLAN 2031

# pod-to-pod (Cilium native routing)
64 bytes from 10.245.0.185: seq=0 ttl=63 time=0.298 ms   # 0% loss

# cluster DNS + internet egress (from a pod)
kubernetes.default.svc.cluster.local -> 10.96.0.1
https://huggingface.co -> HTTP/1.1 200 OK   (egress-OK)
```

**Issue found & fixed (recorded for the build):** with `ipv4NativeRoutingCIDR=10.0.0.0/8`, CoreDNS
could not reach its upstream resolver — `read udp …->10.0.2.3:53: i/o timeout`. The QEMU NAT DNS
(`10.0.2.3`) sits in `10.0.2.0/24`, *inside* `10.0.0.0/8`, so Cilium treated it as natively routable
and did **not** masquerade pod→NAT-DNS traffic, which the SLIRP NAT then dropped. Fix: set
`ipv4NativeRoutingCIDR=10.245.0.0/16` (the pod CIDR only) so pod-to-pod stays native while node /
NAT-DNS / internet traffic is masqueraded. DNS and egress worked immediately after `helm upgrade`.

## M2 — Multus + Whereabouts + 3-interface pod ✅

**Actions** ([k8s/03-multus.sh](k8s/03-multus.sh), [k8s/nads.yaml](k8s/nads.yaml), [k8s/test-pod-3if.yaml](k8s/test-pod-3if.yaml)):

1. Install CNI reference plugins v1.6.2 (`macvlan`, `host-local`, …) into `/opt/cni/bin` — Cilium ships only its own binary.
2. Multus **thick DaemonSet v4.3.0**; Whereabouts **v0.8.0** (cluster-wide IPAM).
3. Apply two macvlan NADs (`storage-net` over `vlan2032`, `north-south-net` over `vlan2033`); deploy `tri-net` with `k8s.v1.cni.cncf.io/networks: north-south-net, storage-net`.

**Result:** `cni.exclusive=false` held — both `00-multus.conf` and `05-cilium.conflist` coexist (Multus
not renamed to `.cilium_bak`). `tri-net` came up with **exactly 3 interfaces**:

```
eth0  10.245.0.243/32   cilium (primary, default route)
net1  10.6.33.64/24     default/north-south-net  (macvlan over vlan2033)
net2  10.6.32.64/24     default/storage-net      (macvlan over vlan2032)
```

Confirmed via the Multus `k8s.v1.cni.cncf.io/network-status` annotation (3 attachments, eth0 `default:true`).

**Design constraint confirmed:** from `tri-net`, `ping 10.6.32.1` (the host's own `vlan2032`) **fails** —
the classic macvlan parent↔child isolation. This is why object/S3 traffic to a host-networked RGW on
the *same* node needs a host **macvlan shim** (added in M3) rather than targeting the host IP directly.

**Fix recorded:** `03-multus.sh` originally ran `ls /etc/cni/net.d` without sudo under `set -o pipefail`,
which aborted the script before the NADs applied; changed to `sudo … || true`.

## M3 — Rook-Ceph: block (RBD) + object (RGW/S3) on the storage VLAN ✅

**Actions** ([k8s/04-rook.sh](k8s/04-rook.sh), [k8s/rook/](k8s/rook/), [k8s/05-block.sh](k8s/05-block.sh),
[k8s/06-object.sh](k8s/06-object.sh), [k8s/storage-shim.sh](k8s/storage-shim.sh)):

1. Rook operator via Helm; `CephCluster` with `network.provider: host` + a `rook-config-override` setting `public_network=10.6.32.0/24` so Ceph binds on the storage VLAN; OSDs on raw disks `vdb`/`vdc`; memory tuned (`osd_memory_target≈1.5 GiB`).
2. `CephBlockPool` (`failureDomain: osd`, `size 2`) + RBD StorageClass → PVC mounted in a pod.
3. `CephObjectStore` (RGW) + `ObjectBucketClaim` → bucket + S3 creds; host macvlan **shim** so storage-net pods can reach RGW over the VLAN; S3 PUT/GET from a pod.

**Result:** Ceph **HEALTH_OK**, **2 OSDs UP on the storage VLAN** (`10.6.32.1:68xx`), RGW active.

```
# BLOCK (RBD): PVC bound, /dev/rbd0 mounted, write+read verified
block-pvc   Bound   pvc-...   3Gi   RWO   rook-ceph-block
/dev/rbd0  2.9G  /mnt/block  ext4 ;  cat test.txt -> hello-ceph-block-1781560893

# OBJECT (RGW/S3) from a pod over the storage VLAN (net2 macvlan -> shim -> RGW):
GET hello.txt -> hello-object-over-storage-vlan      # PUT+GET+LIST all OK
```

**Three real issues found & fixed (the meat of this milestone):**

1. **Rook v1.20 CSI never deployed the RBD driver.** v1.20's mandatory `ceph-csi-operator` reconciled the `ClientProfile` but produced **no `Driver` CRs / no `csi-rbdplugin` pods**, so PVCs stuck `Pending` — even after manually creating `Driver` CRs. This is the documented v1.20 CSI breaking change. **Fix:** pin **Rook v1.16.9 + Ceph v19.2.2** (embedded CSI, `enableRbdDriver: true`) — RBD provisions out of the box.
2. **Ceph mon stays on the in-band VLAN.** With host networking Rook pins the mon endpoint to the node IP (`10.6.31.1`) regardless of `network.addressRanges`. The **data path (OSD/RBD/RGW + replication) is on the storage VLAN**; only the mon control channel is in-band. Chasing this with `addressRanges` + in-place recreate corrupted the cluster (mon `store.db` wiped out from under it → CrashLoopBackOff), forcing a rebuild — so this is accepted and documented rather than forced.
3. **OSD disks must be truly pristine.** ceph-volume raw-mode bluestore labels survive `dd`/`sgdisk` (the disks keep "belonging to a different ceph cluster"); reliable reuse needed recreating the virtual disk **files** + a clean rebuild. **Lesson baked into [vm/full-build.sh](vm/full-build.sh):** always build on a fresh VM with fresh disks; never recreate a CephCluster in place.

**macvlan shim return-path fix (object on the storage VLAN):** a storage-net pod's S3 request reached the host shim, but replies left via the **parent** `vlan2032` (which can't reach macvlan children). Pinning the Whereabouts pod range (`10.6.32.64/26`, `10.6.32.128/25`) to `dev storage-shim` in [storage-shim.sh](k8s/storage-shim.sh) routes replies out the sibling shim → pod S3 works.

## M5 — seed the object store (~1 GB) ✅

**Actions** ([k8s/07-seed.sh](k8s/07-seed.sh)): a storage-net pod lists the real food101 parquet
files on the Hugging Face Hub, downloads shards until >1 GB, and uploads them as objects via boto3
to the RGW shim endpoint (over the storage VLAN).

**Result:**
```
parquet files in repo: 11
uploaded train-00000..02-of-00008.parquet  (466 + 442 + 450 MB)
=== SEEDED: 3 objects, 1359 MB ===
```

**Fix recorded:** first attempt used an s5cmd release URL that 404'd (wrong asset name) and aborted
before downloading. Switched to **boto3** (already proven over the shim) and **dynamic file listing**
(`list_repo_files`) instead of guessed paths.

## M6 — end-to-end demo workload ✅

**Actions** ([k8s/08-demo.sh](k8s/08-demo.sh)): a pod with **3 interfaces** + an RBD block PVC
downloads a small Hugging Face model onto the block volume, then does an S3 round-trip (download
seeded objects + upload new ones) over the storage VLAN.

**Result:**
```
interfaces:  eth0 10.245.0.201 (Cilium) · net1 10.6.33.65 (north-south) · net2 10.6.32.67 (storage)
block:       /dev/rbd1 ext4 on /mnt/block ; Qwen2.5-0.5B-Instruct = 954 MB on the block volume
S3 route:    ip route get 10.6.32.250 -> dev net2        # object traffic on the storage VLAN
S3 I/O:      3 seeded objects visible; downloaded 2 -> /mnt/block/dl; uploaded 10 -> demo/ (count 10)
```

**Fix recorded:** the demo pod's Multus annotation was written in YAML **flow style**
`{ k8s.v1.cni.cncf.io/networks: north-south-net, storage-net }` — the comma makes YAML parse it as
*two keys*, so the value was malformed and only `eth0` attached (S3 then fell back to the Cilium
path). Rewrote as block style; the pod then got all 3 interfaces and S3 routed via `net2`.

---

## M4 — scale to 3 nodes (not run — deliberate)

Executed single-node (the plan's M3-first guidance) for reliability on 24 GB. Single-node proves the
full functional stack — multi-VLAN host, Cilium primary + Multus (3 NICs/pod), Rook-Ceph block +
object on the storage VLAN, seed, and demo. The 3-node scale (inter-host OSD replication across the
storage VLAN) is the one piece not exercised; [vm/lab-up.sh](vm/lab-up.sh) takes a node index and the
kubeadm join flow is standard, so it is a follow-up rather than a redesign. Given the Ceph-recovery
time spent reaching a clean healthy cluster, multi-node was left as future work.

## Summary

M0–M3, M5, M6 **pass** on a single Apple-silicon Mac: a multi-VLAN Kubernetes cluster (Cilium
primary + Multus macvlan, every app pod with 3 interfaces) with Rook-Ceph serving **block (RBD)** and
**object (RGW/S3)** storage, all Ceph **data** traffic on the storage VLAN, ~1.3 GB seeded into the
object store, and a demo pod that mounts block storage, stores a Hugging Face model on it, and reads
and writes objects over the storage VLAN. The whole stack is reproducible from scratch via
[vm/full-build.sh](vm/full-build.sh).
