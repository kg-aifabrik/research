# ceph-multus

A completed local proof-of-concept (POC): a multi-VLAN Kubernetes (K8s) cluster on **one
Apple-silicon Mac**, with **Rook-Ceph** serving **block (RBD)** and **object (RGW/S3)** storage to pods
over a dedicated **storage VLAN**, plus a **pull-through model cache** that loads Hugging Face models
over that same storage VLAN. It builds the storage half the Suiri lab left unbuilt, on a faithful copy
of the [host-net-config](../host-net-config/) network design (VLANs 2031/2032/2033).

![architecture](diagrams/01-architecture.svg)

## What it does

- **3 Ubuntu 24.04 arm64 VMs** under QEMU/Hypervisor.framework (HVF), joined by a small userspace
  Layer-2 switch carrying an 802.1Q VLAN trunk: in-band mgmt (2031), north-south (2033), storage (2032).
- **Cilium** is the primary Container Network Interface (CNI) on the in-band VLAN; **Multus** adds two
  **macvlan** secondaries (north-south + storage), so every app pod has **3 interfaces**.
- **Rook-Ceph runs host-networked** with `public_network = 10.6.32.0/24`, so all Ceph data — clients,
  replication, heartbeat — rides the storage VLAN. It serves a **block StorageClass (RBD)** and an
  **S3 object store (RGW)**.
- **Model cache:** Hugging Face models are cached in the object store and loaded by pods **over the
  storage VLAN** (cache miss → fetch from HF once; hit → serve from Ceph), with a TTL.

## Status — complete ✅

**M0–M6 all pass, plus the model cache**, end-to-end on the Mac (full run log: [test-results.md](test-results.md)):

- Multi-VLAN substrate with **802.1Q tags verified between VMs**; Cilium + Multus give every app pod
  **3 interfaces**; Rook-Ceph **block PVC** mounted in a pod and **object PUT/GET over the storage VLAN**.
- Seeded **~1.3 GB** of objects; a demo pod stores a **954 MB Hugging Face model on block** and does an
  S3 round-trip over the storage VLAN.
- Scaled to **3 nodes with host-level replication** — OSD-to-OSD traffic between hosts captured on VLAN 2032.
- **Model cache** proven: a cache hit moved a 953 MB model **entirely over VLAN 2032** (14.5k packets
  pod ↔ RGW, zero Hugging Face traffic); TTL via an S3 lifecycle rule + app-level freshness.

Two findings worth carrying forward: pin **Rook v1.16.9 + Ceph v19.2.2** (embedded CSI) — v1.20's
ceph-csi-operator never deployed the RBD driver here; and the **binding constraint is 24 GB RAM** —
single-node runs comfortably, 3 nodes swap hard. Both are written up in
[baremetal-deployment-guide.md](baremetal-deployment-guide.md).

## The network

| Network | VLAN | CIDR | Role | Realized as |
|---|---|---|---|---|
| In-band mgmt | 2031 (native/untagged) | 10.6.31.0/24 | Cilium primary CNI, API/etcd | `data0` |
| North-South | 2033 (tagged) | 10.6.33.0/24 | external / ingress | `vlan2033@data0` → Multus macvlan |
| Storage | 2032 (tagged) | 10.6.32.0/24 | **all Ceph traffic + model cache** | `vlan2032@data0` → Multus macvlan + Ceph host-net |

## How to use this project

All commands run from this directory on an Apple-silicon Mac. The scripts use `~/cm-feasibility` as
scratch (VM disks, base image, SSH key) and reach the cluster on `127.0.0.1:2221` (in-guest `kubectl`).

```bash
# helper for node-side scripts
SSH="ssh -i ~/cm-feasibility/id_cm -o StrictHostKeyChecking=no -p 2221 ubuntu@127.0.0.1"

# 1. one-time prerequisites (QEMU + xorriso, scratch dir, SSH key, base image)
bash vm/prereqs.sh

# 2. build the single-node cluster end to end (~25 min):
#    fresh VM -> kubeadm -> Cilium -> Multus (+3-iface pod) -> Rook-Ceph -> block + object
bash vm/full-build.sh

# 3. exercise it (scripts were copied to the node by step 2):
$SSH "bash ~/k8s/07-seed.sh"          # seed ~1 GB of objects over the storage VLAN
$SSH "bash ~/k8s/08-demo.sh"          # demo pod: 3 NICs + block PVC + HF model on block + S3 round-trip
$SSH "bash ~/k8s/09-model-cache.sh"   # pull-through model cache: HF -> Ceph -> pod over storage VLAN (TTL)

# 4. (optional) scale to 3 nodes for host-level replication, then back to one
bash vm/scale-out.sh
bash vm/scale-down.sh

# 5. tear everything down and reclaim the disk
kill $(cat ~/cm-feasibility/lab/node*/qemu.pid) 2>/dev/null; pkill -f cm_hub.py; rm -rf ~/cm-feasibility
```

Direct cluster access while it's up: `ssh -i ~/cm-feasibility/id_cm -p 2221 ubuntu@127.0.0.1` then
`kubectl ...` (the kubeconfig lives on the node).

## Repo layout

```
ceph-multus/
├── README.md                      # this file
├── implementation-plan.md         # architecture & design (with diagrams)
├── test-results.md                # full run log: actions, results, fixes, lessons
├── baremetal-deployment-guide.md  # do's & don'ts for real hardware
├── vm/        prereqs · lab-up · full-build · scale-out · scale-down · provision-node
├── k8s/       cilium values · multus · NADs · rook/ · block/object · seed · demo · model-cache
├── feasibility/   the M0 substrate harness (cm_hub.py L2 switch + up/netcheck/down)
└── diagrams/      gen.py -> *.svg (embedded) + editable *.excalidraw
```

## Documentation

[implementation-plan.md](implementation-plan.md) (design) · [test-results.md](test-results.md) (results)
· [baremetal-deployment-guide.md](baremetal-deployment-guide.md) (do's & don'ts)

## Not in scope

Deliberately excluded from this POC — the natural next steps for a real deployment:

- **Production-grade 3-node steady state.** A 24 GB laptop can demonstrate 3 nodes but swaps under load;
  a real cluster wants more RAM and/or **dedicated storage nodes** (true disaggregation).
- **Ceph public network on Multus** (`network.provider: multus`) instead of host networking — heavier
  and exposes the fragile CSI host-routing path; host networking was sufficient here.
- **True 802.1Q on VLAN-aware hardware.** This POC fakes the fabric with a software L2 switch and a
  macvlan host shim; on baremetal those are replaced by a real switch (and the shim disappears).
- **GPU / InfiniBand / RDMA tier** (Suiri VLAN 2037, SR-IOV) — no GPU/IB hardware locally.
- **Production hardening:** HA mons (3+), observability/metrics, backups, secrets management, automated
  tests, and any performance benchmarking (the software-switched datapath is functional-only).
