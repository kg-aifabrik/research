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
| M5 — seed object store ~1 GB | ⏳ |
| M6 — demo workload | ⏳ |

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
