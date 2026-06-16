# Deploying multi-VLAN K8s + Multus + Rook-Ceph on baremetal — do's & don'ts

Operational lessons from the `ceph-multus` POC, retargeted at a **dedicated baremetal test
environment** (real hosts, real VLAN-aware switches). The POC ran on one Mac with virtual VMs; this
guide separates the **design lessons that carry over** from the **local workarounds you should drop**
on real hardware. Pair it with [implementation-plan.md](implementation-plan.md) (architecture) and
[test-results.md](test-results.md) (the blow-by-blow).

## TL;DR — the five that cost the most time

1. **Pin Rook to a version with embedded CSI (v1.16.x).** Rook v1.20's mandatory `ceph-csi-operator`
   never deployed the RBD driver in our runs — PVCs stuck `Pending`. This was the single biggest sink.
2. **Build Ceph OSDs only on truly clean disks**, and **never recreate a CephCluster in place** — wipe
   and rebuild. ceph-volume's raw bluestore labels survive `dd`/`sgdisk`.
3. **Set `cni.exclusive=false` on Cilium** or Multus secondary interfaces silently never attach.
4. **Scope Cilium's `ipv4NativeRoutingCIDR` to the pod CIDR only** — too wide a CIDR breaks pod DNS/egress.
5. **Right-size OSD memory and host RAM up front.** Ceph defaults to a 4 GiB `osd_memory_target`; plan
   RAM accordingly (baremetal makes this easy — the POC's pain was a 24 GB laptop).

---

## Network fabric & VLANs

On baremetal the network is real, so the POC's software hub / macvlan-shim hacks go away — but the
**switch** now has to be configured to match.

**Do**
- Configure the **switch trunk ports** to carry the tagged VLANs (mgmt/north-south/storage) with the
  correct **native (untagged) VLAN** for in-band/PXE. Mismatched native VLAN breaks DHCP/PXE — the
  Suiri lab hit exactly this.
- Set **jumbo MTU end-to-end** if you want it on the storage VLAN: switch fabric (e.g. `mtu 9216`),
  the bond, and the VLAN sub-interface must all agree. A switch defaulting to 1500 silently blackholes
  large frames while small pings pass — diagnose with `ping -M do -s 8972`.
- Use **LACP (802.3ad)** bonds to real switch port-channels; match `lacp-rate`/hash policy on both ends.
- Match interfaces by **MAC** in netplan (deterministic across reboots/kernel reordering).
- Keep the **Kubernetes API / etcd / node-IP on the in-band VLAN**, not the storage VLAN.

**Don't**
- Don't assume jumbo works because the host is configured — the **switch** is the usual culprit.
- Don't put the k8s `--node-ip` on the storage VLAN; keep control-plane traffic in-band.
- Don't reuse a VLAN's DHCP/static host range for pod IPAM (see Whereabouts below).

*Dropped from the POC:* the userspace L2 hub (real switch instead), the macvlan **host shim** (needed
only because a single host can't reach its own macvlan children — irrelevant once pods and Ceph/RGW
live on **different** hosts), and the `active-backup` bond substitute (use real LACP).

## Host OS prep

**Do**
- Provision via your existing baremetal flow (Redfish/PXE + cloud-init/netplan, per the
  [host-net-config](../host-net-config/) design).
- Install prerequisites the installer assumes exist: `containerd` (with `SystemdCgroup = true`),
  `conntrack`, `socat`, `ethtool`; disable swap; load `overlay` + `br_netfilter`; set the bridge/forward
  sysctls. Missing `conntrack` fails `kubeadm` preflight; missing `SystemdCgroup` causes kubelet churn.
- Drop the **CNI reference plugins** (`containernetworking-plugins`: `macvlan`, `host-local`, …) into
  `/opt/cni/bin` on **every** node — Cilium ships only its own binary, and macvlan fails silently without them.

**Don't**
- Don't rely on a node reboot to "fix" a wedged CNI/Ceph state — on our VM an ungraceful reboot left
  Multus crashlooping and pods stuck `Terminating`, which cascaded. Fix forward or reprovision the node.

## Cilium (primary CNI)

**Do**
- `cni.exclusive=false` (the one non-negotiable for Multus coexistence), `routingMode=native`,
  `autoDirectNodeRoutes=true`, `ipam.mode=kubernetes`, and **`ipv4NativeRoutingCIDR` = the pod CIDR**.
- Verify on a node that `/etc/cni/net.d/00-multus.conf` was **not** renamed to `*.cilium_bak`.

**Don't**
- Don't set `ipv4NativeRoutingCIDR` to a broad supernet (we used `10.0.0.0/8`): it swallowed the
  upstream-DNS subnet, so pod→DNS wasn't masqueraded and **all DNS/egress timed out**. Scope it to pods.
- Don't enable `kubeProxyReplacement` blindly for a first bring-up; stock kube-proxy is fewer variables.
  (It's orthogonal to Multus — enable it later if you want eBPF service handling.)

## Multus + macvlan + Whereabouts

**Do**
- Install **Multus thick v4.3.0** (pinned) + **Whereabouts** for cluster-wide IPAM. There is **no
  standalone "Multus operator"** — the thick DaemonSet is the right path.
- Write the pod annotation in **block-style YAML**:
  `k8s.v1.cni.cncf.io/networks: north-south-net, storage-net`. Flow style
  `{ ...: a, b }` parses the comma as a second key and **silently drops the secondaries** — this cost us a debug cycle.
- Give each secondary NAD a Whereabouts range that **excludes host/gateway IPs** (e.g. exclude the
  low `/26`); only the **north-south** NAD should carry a default route.

**Don't**
- Don't put a default route on the storage NAD — it hijacks the pod default route off Cilium.

## Rook-Ceph version & CSI (read this first)

**Do**
- Use **Rook v1.16.9 + Ceph v19.2.2** (embedded CSI: `enableRbdDriver: true`) for a test build — the
  RBD/CephFS driver pods deploy automatically and PVCs bind out of the box. Install via the **Helm
  chart** (it bundles CRDs correctly).
- If you must run Rook ≥ v1.20, budget real time for the **ceph-csi-operator**: you need its
  `csi.ceph.io` CRDs (incl. `clientprofiles`) **and** the `Driver` CRs actually reconciled into
  `csi-rbdplugin` pods. In our runs the operator reconciled the `ClientProfile` but never produced the
  driver pods, so PVCs stayed `Pending` — verify `kubectl get csidrivers` shows the driver before relying on it.

**Don't**
- Don't de\-\/re-apply Rook from the raw `deploy/examples` manifests for v1.20 — `crds.yaml` omits the
  `csi.ceph.io` CRDs and the apply fails (`no matches for kind OperatorConfig/Driver`).
- Don't delete the `csi.ceph.io` CRDs during a teardown and expect a plain reinstall to recreate them.

## Ceph networking (storage VLAN)

**Do**
- Run Ceph **host-networked** and set `public_network`/`cluster_network` to the **storage VLAN CIDR**
  in the `rook-config-override` ConfigMap. OSDs then bind on the storage VLAN, and **all data + OSD-to-OSD
  replication rides it** (we captured the inter-host replication traffic on the storage VLAN). Host-network
  CSI reaches host-network Ceph natively — no shim.
- Set the pool **`failureDomain: host`** for real multi-host replicas. Confirm the **crush rule actually
  flipped to `host`** (`ceph osd crush rule dump`) — Rook's CR field didn't always propagate for us; set
  the rule explicitly if needed.

**Don't**
- Don't expect the **mon** to move onto the storage VLAN with host networking — Rook pins the mon endpoint
  to the node IP (in-band) regardless of `network.addressRanges`. The **data path** is what rides the
  storage VLAN; chasing the mon there with `addressRanges` + in-place recreate **corrupted our cluster**.
  Accept mon-on-in-band, or use `network.provider: multus` for Ceph (heavier — see the CSI host-routing
  caveat below) if mon-on-storage-VLAN is a hard requirement.
- Don't reach for `network.provider: multus` for Ceph unless you need it: the RBD/CephFS CSI plugin runs
  in the host netns and can't reach a macvlan-only Ceph public net without per-node `public-shim` +
  routes that Rook won't auto-configure.

## OSD disks

**Do**
- Present **raw, empty** block devices (no partition table, no filesystem, no old LVM/bluestore). On
  baremetal, `wipefs -a` + zap the start of each device, and confirm with `ceph-volume inventory`.
- Prefer dedicated NVMe/SSD per OSD; set `osd_memory_target` deliberately (we used ~1.5 GiB for a
  cramped lab — on baremetal use 4 GiB+).

**Don't**
- Don't trust a quick `dd`/`sgdisk` to clear a disk that previously held an OSD — ceph-volume's raw
  bluestore label **survives** and the disk is skipped as "belonging to a different ceph cluster." Zap
  thoroughly (and on VMs we had to recreate the disk image). **Never recreate a CephCluster in place**:
  wiping `/var/lib/rook` out from under a tracked mon corrupts it (`store.db` missing → CrashLoopBackOff).

## Resources & sizing

**Do**
- Size RAM for Ceph honestly: mon + mgr + (OSD count × `osd_memory_target`) + RGW/MDS + k8s + workloads.
  Baremetal removes the POC's pain — give OSD nodes plenty of RAM.
- For "disaggregated storage," consider **dedicated storage nodes** (OSDs) separate from compute, both
  on the storage VLAN — cleaner than hyperconverged and matches the storage-VLAN intent.

**Don't**
- Don't run a 3-node hyperconverged Ceph on a memory-starved host — our 3×VM scale-out on 24 GB drove
  ~14 GB of swap and the cluster flapped `HEALTH_WARN`/`pgs not active` (a host-resource artifact, not a
  Ceph fault). It reached `HEALTH_OK` but wasn't steady.

## Workflow discipline

**Do**
- Bring up and **verify each layer before the next**: substrate → kubeadm/Cilium (pod-to-pod + DNS) →
  Multus (a 3-interface test pod) → Rook health → block PVC → object PUT/GET → scale. Each green first.
- Keep the build **scripted and reproducible** (we did the whole stack from `vm/full-build.sh`); on
  baremetal the equivalent is your provisioning + GitOps/Helm pipeline.

**Don't**
- Don't debug Ceph through a hanging `ceph` CLI — always bound it (`ceph --connect-timeout 5`); a
  crashlooped mon makes every unbounded call hang.

## Quick reference

| Area | Do | Don't |
|---|---|---|
| Switch | trunk + native VLAN + jumbo `9216` + LACP | leave switch at MTU 1500; mismatch native VLAN |
| Cilium | `cni.exclusive=false`; native CIDR = pod CIDR | broad `ipv4NativeRoutingCIDR`; clobber `00-multus.conf` |
| Multus | thick v4.3.0 + Whereabouts; block-style annotation | flow-style annotation; default route on storage NAD |
| Rook/Ceph | **v1.16.9 + Ceph v19.2.2 (embedded CSI)**; Helm install | Rook v1.20 raw manifests; expect `Driver` CRs for free |
| Ceph net | host net + `public_network` = storage VLAN; `failureDomain host` | force mon onto storage VLAN; recreate CephCluster in place |
| Disks | raw/empty; thorough zap; dedicated devices | trust `dd` on ex-OSD disks; wipe `/var/lib/rook` live |
| Sizing | RAM for `osd_memory_target` × OSDs; dedicated storage nodes | hyperconverged Ceph on a RAM-starved host |
