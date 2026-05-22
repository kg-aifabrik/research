# Test strategy for the host network configuration pipeline

## Executive Summary

**Two tiers, not three.** Run the cheap structural checks in a software-only CI tier (Netbox in Docker, renderer golden-file tests, Netplan `generate --root-dir` in a container, QEMU VM with virtio NICs and an Open vSwitch (OVS) trunk for the cloud-init end-to-end). For everything else, **rent one GPU bare-metal box for a few hours per burn**. Per your simplicity preference, the GPU SKU covers the entire spectrum — bond / VLAN / cloud-init at the low end through SR-IOV and basic RoCE at the high end — in a single SSH session rather than rotating between two rentals. Expected cost per burn: $10–$20 on a Lambda or Crusoe H100/H200 bare-metal SKU at 2–4 hours.

The **irreducible silicon gap** — BF-3 `mlxconfig` mode switching, B300/ConnectX-8 firmware-specific behavior, NCCL at NVL72-rack scale — closes via NVIDIA LaunchPad (free evaluation slots) or once site-1 hardware lands. Plan one LaunchPad reservation before site-1 cutover.

## Capability matrix

Rows = what we want to validate. Columns = test tier.

| Capability | Tier 1 — Software | Tier 2 — Rented GPU bare metal | Tier 3 — LaunchPad / site-1 |
|---|---|---|---|
| Netbox schema + custom fields | ✅ Full | ✅ Full | ✅ Full |
| Renderer → Netplan correctness (golden files) | ✅ Full | ✅ Full | ✅ Full |
| `netplan generate` dry-run | ✅ Full | ✅ Full | ✅ Full |
| Cloud-init NoCloud over HTTP datasource | ✅ Full | ✅ Full | ✅ Full |
| Bond (LACP `mode=802.3ad`) negotiation | ⚠️ Via OVS partner (works) | ✅ Real switch | ✅ Real switch |
| VLAN tagging end-to-end (`bond0.100`/`.200`/`.300`) | ✅ Full (OVS trunk) | ✅ Full (vendor switch trunk) | ✅ Full |
| MTU 9000 across path | ⚠️ Kernel only, no fabric | ✅ End-to-end on rented fabric | ✅ |
| ESI-LAG / EVPN dual-leaf | ❌ (Apstra / NVIDIA Air, separate) | ❌ (single LACP partner only) | ✅ (site-1) |
| SR-IOV VF creation + udev rename | ❌ (virtio has no PFs) | ✅ on real ConnectX | ✅ |
| RoCE ping / `rping` / `ib_send_bw` | ❌ | ✅ basic | ✅ at scale |
| PFC priority 3 + ECN + DCQCN under load | ❌ | ⚠️ Renter-dependent; usually no DCB control on tenant ports | ✅ |
| GPUDirect RDMA into HBM | ❌ | ✅ (basic, same-host) | ✅ |
| NCCL all-reduce across hosts | ❌ | ⚠️ Need ≥2 boxes in same fabric | ✅ |
| BF-3 `mlxconfig` mode switching | ❌ | ❌ (provider locks firmware) | ✅ LaunchPad |
| B300-specific firmware quirks | ❌ | ❌ | ✅ LaunchPad / site-1 |

✅ = directly testable. ⚠️ = partially / with caveats. ❌ = not testable in this tier.

## Requirements

- Validate three scenarios end-to-end: Netbox setup + populate; baremetal with 2 bonded NICs + 3 VLANs; cloud-init pulling config from Netbox and applying.
- Produce a clear "can / cannot test" matrix across tiers (software-only, rented bare metal, GPU rental).
- For each tier: concrete recipe, named provider/SKU where relevant, indicative cost, what unlocks vs the previous tier.
- Recommend the rollout cadence — what runs in CI, what runs on rented hardware, what waits for site-1.

## Assumptions

- "Close enough" baremetal means ≥2 physical NICs on a vendor-managed switch port supporting LACP and tagged VLANs; no requirement for ESI-LAG, RoCE, or B300-class hardware.
- Single-host test scope; multi-host scenarios deferred.
- Vendor-managed switch is acceptable; EVPN/ESI-LAG validation is NetOps's responsibility (Apstra / NVIDIA Air), out of scope here.
- Ubuntu 24.04 + Netplan throughout.
- Budget tolerance ~$100–$500 per sprint; CI tier free.
- Pod-side networking (Cilium, Multus, SR-IOV CNI) and Day-2 reconciliation are out of scope.

## Tier 1 — Software-only (CI tier)

Runs on a laptop or any CI runner. Catches ~80% of bugs the second after they're introduced.

### Stack

| Component | Tool | What it validates |
|---|---|---|
| Netbox instance | [`netbox-docker`](https://github.com/netbox-community/netbox-docker) compose stack | Schema loads, custom fields, API responds |
| Test fixtures | Python script using `pynetbox` | One example B300, one CPU-only host, fully populated |
| Renderer | Our Python service, run as a CLI in CI | Pulls from Netbox, emits Netplan YAML + cloud-init seed tree |
| Golden-file tests | `pytest` against expected outputs | Byte-deterministic renders; regressions caught instantly |
| Netplan dry-run | `netplan generate --root-dir /tmp/T` inside `ubuntu:24.04` container | YAML is structurally valid; emits expected `/run/systemd/network/*.network` units |
| First-boot e2e | QEMU/KVM VM + Open vSwitch | Cloud-init NoCloud over HTTP actually fetches and applies; bond forms; VLANs come up |

### Concrete recipe for the QEMU end-to-end

```bash
# Host side: OVS bridge with LACP partner + VLAN trunk
ovs-vsctl add-br br-test
ovs-vsctl set port br-test lacp=active bond_mode=balance-tcp
ovs-vsctl add-port br-test veth0 tag=trunk vlan_mode=trunk trunks=100,200,300
ovs-vsctl add-port br-test veth1 tag=trunk vlan_mode=trunk trunks=100,200,300

# Seed server: nginx serving rendered /seeds/<mac>/{meta-data,user-data,network-config}
nginx -p /tmp/seedsrv -c nginx.conf  # listens on 10.0.99.1:80

# VM with two virtio NICs and NoCloud kernel cmdline
qemu-system-x86_64 -enable-kvm -m 8G -smp 4 \
  -drive file=ubuntu-24.04-server.qcow2,if=virtio \
  -netdev tap,id=n0,ifname=veth0-vm,script=no -device virtio-net,netdev=n0,mac=aa:bb:cc:00:00:01 \
  -netdev tap,id=n1,ifname=veth1-vm,script=no -device virtio-net,netdev=n1,mac=aa:bb:cc:00:00:02 \
  -smbios "type=1,serial=ds=nocloud-net;s=http://10.0.99.1/aa-bb-cc-00-00-01/"
```

Verify on the VM: `ip -d link show bond0`, `cat /proc/net/bonding/bond0`, `ip -j addr show bond0.100`, `cloud-init status --long`.

### What Tier 1 covers well

Renderer correctness, schema validity, cloud-init datasource handling, bond + VLAN topology at the Linux kernel layer, IP/route correctness, MTU plumbing, atomic seed delivery.

### What Tier 1 cannot cover

Anything in the NIC silicon or firmware path — real LACPDU exchange with switch-side hashing, hardware VLAN strip/insert offload, MTU through a real fabric, SR-IOV (no PFs in virtio), RoCE/PFC/DCB, GPUDirect, BF-3 firmware modes. The kernel sees a synthetic packet path; bugs that only manifest on real ConnectX firmware will not show up.

## Tier 2 — Single rented GPU bare-metal box

Per your simplicity preference: rent **one** box that covers both ends of the spectrum in one session.

### Provider survey (mid-2026 landscape)

| Provider | Recommended SKU | Approx hourly | NIC topology | Root + Netplan? | Notes |
|---|---|---|---|---|---|
| [Lambda Labs](https://lambda.ai/service/gpu-cloud) | 1× H100 SXM5 bare metal | ~$2.49–3.49/hr | Typically 2× NIC + IB on SXM boxes | Yes | Easiest onboarding; well-documented bare metal access |
| [Crusoe](https://crusoe.ai/cloud/) | H100 SXM bare metal | ~$2/hr | 2× host NIC + RoCE ConnectX-7 | Yes | Strong bare-metal story; B200 available; cheaper than Lambda |
| [CoreWeave](https://coreweave.com) | HGX H100/H200 bare metal | enterprise quote | Full HGX networking incl. BF-3 in some SKUs | Yes (enterprise tier) | Closest to our target topology but procurement is heavier |
| [Nebius](https://nebius.com) | H100 SXM | ~$2.0–2.5/hr | Multi-NIC | Yes | EU-based; B200 platform available |
| [Vultr Bare Metal](https://www.vultr.com/products/bare-metal/) | A100/H100 bare metal | ~$2–4/hr | Trunked VLAN supported on selected SKUs | Yes | Reliable, less GPU-specific tooling |
| [Oracle OCI BM.GPU](https://www.oracle.com/cloud/compute/gpu/) | BM.GPU.H100 | ~$10/hr | Full bare-metal; 8× 400G + 2× 100G mgmt | Yes | Heavier console UX; works |

**Recommendation:** Lambda 1×H100 bare metal or Crusoe H100 bare metal. Both give SSH + root, both have at least two host NICs you can re-bond, both support VLAN-tagged trunks on tenant ports for the SKUs that allow it. Confirm with the provider that the SKU includes **tagged VLAN trunk on at least one NIC** before booking — this varies by SKU and isn't always documented on the marketing page.

Prices above are indicative as of mid-2026 — confirm at the provider before each burn.

### Recipe for a Tier 2 burn

```text
1. Provision: 1× H100 bare metal, Ubuntu 24.04 image. ~10 min.
2. Bring up our test stack on the rented host:
     - Install Netplan (already present), nginx (for seed server), python3-pynetbox.
     - Clone the renderer repo; run docker-compose for Netbox locally on the rented host.
     - Populate Netbox with this host's actual MACs (pulled from `ip -j link`).
3. Render the host's intent → write to /etc/netplan/60-host.yaml (replace ISP-supplied netplan).
4. `netplan try` (auto-rollback safety net) → confirm bond + VLANs come up.
5. Push the same intent through cloud-init by:
     - Hosting the rendered seed at http://localhost/seeds/<mac>/
     - Running `cloud-init clean --logs` and rebooting
     - Verifying first-boot apply succeeds.
6. SR-IOV: `echo 16 > /sys/class/net/<nic>/device/sriov_numvfs`, verify VFs appear.
7. RoCE ping: `rping`, `ib_send_bw` between host's own NICs (loopback via switch).
8. Capture logs, snapshot config, deprovision.
```

Realistic time per burn: 2–4 hours of active work; box released after that. Cost: $10–$15 typical.

### What Tier 2 unlocks vs Tier 1

Real LACP negotiation against a real switch; real hardware VLAN handling; real ConnectX firmware on at least one fabric port; SR-IOV VF creation against real PFs; basic RoCE verbs (`rping`, `ibv_devinfo`, `ib_send_bw`); cloud-init against real BIOS/UEFI boot path.

### What Tier 2 still cannot cover

- **ESI-LAG / EVPN** — the provider's switch is a single logical partner; you cannot configure the dual-leaf behavior. NetOps validates this elsewhere.
- **PFC / ECN / DCQCN under contention** — most providers do not expose DCB controls to tenants. You can confirm PFC priority 3 is honored *if* the provider's fabric is RoCE-configured (rare for non-AI-specialized providers), but you cannot tune it.
- **BF-3 `mlxconfig` mode switching** — providers lock firmware; tenants cannot flip NIC mode bits.
- **B300-specific firmware quirks and NCCL at NVL72 scale** — no commercial rental of B300 in NVL72 form factor was generally available as of mid-2026; check provider rosters near each burn since this changes monthly.

## Tier 3 — NVIDIA LaunchPad / vendor labs (for the silicon gap)

[NVIDIA LaunchPad](https://www.nvidia.com/en-us/launchpad/) offers free, reservable access to reference designs (Spectrum-X fabric, BF-3 SuperNIC labs, DGX H100/H200 systems). Reservations are typically 2 weeks. This is the right place to validate:

- BF-3 mode switching via `mlxconfig` (LaunchPad's BlueField labs expose this).
- ConnectX-8/B300-class firmware behavior once those labs land (timing varies; check the LaunchPad catalog when planning).
- DCB / PFC / DCQCN tuning end-to-end against a properly configured RoCE fabric.

Supermicro's JumpStart program is the equivalent path on the OEM side — useful if you want to validate the HGX B300 specifically before site-1 hardware arrives.

Both are free but gate-keepered. Plan one reservation 4–6 weeks before site-1 cutover so you've burned in the BF-3 firmware-control unit and `mlxconfig`-based mode lock on real hardware.

## Recommended rollout

| Cadence | Tier | Scope | Cost |
|---|---|---|---|
| Every commit | Tier 1 | Renderer golden files, schema validity, `netplan generate` | Free (CI) |
| Every PR to `main` | Tier 1 | + QEMU VM first-boot e2e (~3 min) | Free (CI) |
| Bi-weekly during active dev | Tier 2 | Single H100 bare-metal burn; bond + VLAN + cloud-init + SR-IOV + basic RoCE | ~$10–20 |
| Before each milestone | Tier 2 | Same as bi-weekly, extended to ~8h with multi-NIC SR-IOV stress and `ib_send_bw` runs | ~$30 |
| Once, 4–6 weeks pre-site-1 | Tier 3 | LaunchPad reservation; lock down BF-3 mode-switch unit, DCQCN tuning, B300-class firmware behavior if available | Free (NVIDIA) |
| Post-site-1 | Real B300 | Replay every Tier 2 + Tier 3 test on production hardware; lock the template | — |

## Open gaps to revisit

- **Multi-host scenarios** — explicitly out of scope here. When we extend to multi-host (e.g., for NCCL inter-host validation), Crusoe and CoreWeave both support multi-node bare-metal reservations on a shared low-latency fabric; revisit when needed.
- **DPU mode (BF-3 as full DPU)** — covered in the [baremetal overview caveat](baremetal-network-overview.md); when/if we move to DPU mode, the test plan needs a second OS image and DPU-side cloud-init path. Add a Tier 4 column at that point.
- **Day-2 reconciliation** — separate testing concern (drift injection, `netplan try` rollback, agent behavior). Belongs in its own topic; out of scope here.
