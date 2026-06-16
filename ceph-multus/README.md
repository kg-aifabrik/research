# ceph-multus

Local proof-of-concept (POC): a multi-VLAN Kubernetes (K8s) cluster on **one Apple-silicon Mac**,
with **Rook-Ceph** serving **block (RBD)** and **object (RGW/S3)** storage to pods over a dedicated
storage VLAN. It builds the storage half the Suiri lab left unbuilt, on a faithful copy of the
[host-net-config](../host-net-config/) network design (VLANs 2031/2032/2033).

![architecture](diagrams/01-architecture.svg)

- **3 Ubuntu 24.04 arm64 VMs** under QEMU/Hypervisor.framework (HVF), joined by a small userspace
  Layer-2 (L2) switch that carries an 802.1Q VLAN trunk: in-band mgmt (2031), north-south (2033),
  storage (2032).
- **Cilium** is the primary Container Network Interface (CNI) on the in-band VLAN; **Multus** adds
  two **macvlan** secondaries (north-south + storage), so every app pod has **3 interfaces**.
- **Rook-Ceph runs host-networked** with `public_network = 10.6.32.0/24`, so *all* Ceph traffic
  (clients, replication, heartbeat) rides the storage VLAN. Serves a block StorageClass and an S3
  object store.
- **Demo:** a pod mounts a block volume, downloads a small Hugging Face model onto it, then reads
  and writes objects in the S3 store over the storage VLAN.
- **Status: built and verified end-to-end on the Mac. M0–M6 all pass.** Cilium primary + Multus
  (3 NICs/pod), Rook-Ceph block (RBD) + object (RGW/S3) with all Ceph data on the storage VLAN,
  ~1.3 GB seeded, a demo pod that stores a Hugging Face model on block and does an S3 round-trip over
  the storage VLAN, and a **3-node scale** with **host-level replication** (OSD-to-OSD traffic between
  hosts captured on VLAN 2032). Full run log in [test-results.md](test-results.md). Pinned **Rook
  v1.16.9 + Ceph v19.2.2** (embedded CSI) after v1.20's ceph-csi-operator wouldn't deploy the RBD
  driver. Binding constraint: 24 GB RAM — single-node runs comfortably; 3 nodes swaps hard.

**Full plan:** [implementation-plan.md](implementation-plan.md) · **Results:** [test-results.md](test-results.md) · **Baremetal do's & don'ts:** [baremetal-deployment-guide.md](baremetal-deployment-guide.md) · **Harness:** [feasibility/](feasibility/) + [vm/full-build.sh](vm/full-build.sh)

## Open threads

- **Done:** M0–M6 (build + seed + demo + 3-node host-level replication) **plus a pull-through model
  cache** on Ceph object store — Hugging Face models cached in RGW and loaded by pods **over the
  storage VLAN** (TTL via S3 lifecycle + app-level freshness). See [test-results.md](test-results.md).
- 3-node steady-state needs more RAM than 24 GB (heavy swap; HEALTH flaps under pressure). Run on a
  bigger host, or use dedicated storage nodes, for a stable multi-node cluster.
- Optional advanced milestone: put the Ceph public network on the Multus storage VLAN (vs host
  networking) — heavier, fragile Container Storage Interface (CSI) host-routing path.
- Optional: replace the macvlan host shim with true 802.1Q if ever moved onto real VLAN-aware hardware.
