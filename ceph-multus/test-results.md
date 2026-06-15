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
| M2 — Multus + 3-interface pod | ⏳ |
| M3 — Rook-Ceph block + object | ⏳ |
| M4 — scale to 3 nodes | ⏳ |
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
