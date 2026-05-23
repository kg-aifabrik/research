# Test strategy for the host network configuration pipeline

## Executive Summary

**Two tiers, not three.** Run the cheap structural checks in a software-only CI tier — Netbox in Docker, an on-demand renderer service behind nginx (with proxy-level caching as the hybrid sweet spot), QEMU/KVM VMs plugged into an Open vSwitch (OVS) trunk, and Soft-RoCE for verbs-level checks. For everything else, **rent one GPU bare-metal box for a few hours per burn**. Per the simplicity preference, the GPU SKU covers the entire spectrum — bond / VLAN / cloud-init at the low end through SR-IOV and basic RoCE at the high end — in a single SSH session rather than rotating between two rentals. Expected cost per burn: $10–$20 on a Lambda or Crusoe H100/H200 bare-metal SKU at 2–4 hours.

The **irreducible silicon gap** — BF-3 `mlxconfig` mode switching, B300/ConnectX-8 firmware-specific behavior, NCCL at NVL72-rack scale — closes via NVIDIA LaunchPad (free evaluation slots) or once site-1 hardware lands. Plan one LaunchPad reservation before site-1 cutover.

## Capability matrix

Rows = what we want to validate. Columns = test tier.

| Capability | Tier 1 — Software | Tier 2 — Rented GPU bare metal | Tier 3 — LaunchPad / site-1 |
|---|---|---|---|
| Netbox schema + custom fields | ✅ Full | ✅ Full | ✅ Full |
| Renderer → Netplan correctness (golden files) | ✅ Full | ✅ Full | ✅ Full |
| Renderer service on-demand path (FastAPI behind nginx) | ✅ Full | ✅ Full | ✅ Full |
| `netplan generate` dry-run | ✅ Full | ✅ Full | ✅ Full |
| Cloud-init NoCloud over HTTP datasource | ✅ Full | ✅ Full | ✅ Full |
| Bond (LACP `mode=802.3ad`) negotiation | ⚠️ Via OVS partner (works) | ✅ Real switch | ✅ Real switch |
| VLAN tagging end-to-end (`bond0.100`/`.200`/`.300`) | ✅ Full (OVS trunk) | ✅ Full (vendor switch trunk) | ✅ Full |
| MTU 9000 across path | ⚠️ Kernel only, no fabric | ✅ End-to-end on rented fabric | ✅ |
| ESI-LAG / EVPN dual-leaf | ❌ (Apstra / NVIDIA Air, separate) | ❌ (single LACP partner only) | ✅ (site-1) |
| 8 east-west NICs as virtio interfaces | ✅ (renderer correctness only) | ✅ (real ConnectX-8) | ✅ |
| RDMA verbs API works (`ibv_devinfo`, `rping`) | ✅ via Soft-RoCE (rxe) | ✅ real | ✅ |
| SR-IOV VF creation + udev rename | ❌ (virtio has no PFs) | ✅ on real ConnectX | ✅ |
| RoCE v2 real performance / lossless behavior | ❌ (Soft-RoCE is software, no PFC) | ⚠️ provider-dependent | ✅ |
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
- US-based cloud providers preferred for the public-cloud tier (DigitalOcean).

## Tier 1 — Software-only (CI tier)

Runs on a developer laptop, a small public-cloud VM, or a CI runner. Catches ~80% of bugs the second after they're introduced.

### Architecture

```
   ┌────────────────────────────────────────────────────────────┐
   │  HOST (Lima VM / DO Droplet / GHA runner)                  │
   │                                                            │
   │   Netbox (docker-compose) ◄────── pynetbox API             │
   │                                       │                    │
   │                                       ▼                    │
   │                                  Renderer service          │
   │                                  (FastAPI)                 │
   │                                       │                    │
   │                                       ▼ proxy_pass         │
   │                                  nginx (:80)               │
   │                                  proxy_cache_path          │
   │                                  /var/cache/seeds          │
   │                                       ▲                    │
   │  ───── kernel netdev boundary ────────│──── OVS bridge ─── │
   │                                       │      br-test       │
   │                                       │      (LACP partner,│
   │                                       │       VLAN trunk)  │
   │                                       │       ▲            │
   │  ┌────────────────────────────────────│───────┴──┐         │
   │  │ QEMU/KVM VM (host-under-test)      │          │         │
   │  │   eth0 (mgmt, HTTP to renderer) ───┘          │         │
   │  │   nsa, nsb  (bonded → bond0)                  ┘         │
   │  │   gpu0..gpu7 (8× virtio for E-W renderer test)          │
   │  │     + Soft-RoCE rxe_gpuN on each for verbs              │
   │  │                                                         │
   │  │ cloud-init NoCloud fetches from renderer via mgmt NIC,  │
   │  │ writes Netplan, Netplan applies, bond+VLANs come up.    │
   │  └─────────────────────────────────────────────────────────┘
   └────────────────────────────────────────────────────────────┘
```

### Stack

| Component | Tool | What it validates |
|---|---|---|
| Netbox instance | [`netbox-docker`](https://github.com/netbox-community/netbox-docker) compose stack | Schema loads, custom fields, API responds |
| Test fixtures | Python script using `pynetbox` | One example B300, one CPU-only host, fully populated |
| **Renderer service** | **FastAPI app, behind nginx reverse proxy** | **On-demand render at request time; queries Netbox by asset tag** |
| **Seed delivery** | **nginx `proxy_cache_path` (write-through cache, ~5 min TTL)** | **First request renders; subsequent requests served from disk cache → burst-safe** |
| Golden-file tests | `pytest` against expected renderer output | Byte-deterministic renders; regressions caught instantly |
| Netplan dry-run | `netplan generate --root-dir /tmp/T` inside `ubuntu:24.04` container | YAML is structurally valid; emits expected `/run/systemd/network/*.network` units |
| First-boot e2e | QEMU/KVM VM + Open vSwitch | Cloud-init NoCloud over HTTP fetches and applies; bond + VLANs come up |
| **E-W simulation** | **8× virtio-net interfaces + Soft-RoCE (`rdma_rxe`)** | **Renderer emits correct config for 8 NICs; RDMA verbs API plumbing works** |

### The renderer model: on-demand with proxy-level cache (hybrid)

The renderer is a FastAPI service. nginx is a thin reverse proxy with a write-through cache on top:

```nginx
proxy_cache_path /var/cache/seeds keys_zone=seedcache:10m
                 inactive=24h max_size=1g;

location /render/ {
    proxy_pass http://127.0.0.1:8000;     # FastAPI renderer
    proxy_cache seedcache;
    proxy_cache_valid 200 5m;             # cache successful renders 5 min
    proxy_cache_key "$request_uri";
}
```

Cloud-init's kernel cmdline points at `s=http://<host>/render/<asset-tag>/`. The first request for a given asset tag hits the FastAPI renderer, which queries Netbox, builds a `HostIntent`, and returns the rendered files; nginx caches the response. Subsequent requests for the same asset tag are served from `/var/cache/seeds` at static-file speed. The cache invalidates after 5 minutes, so Netbox changes propagate quickly during dev.

This gives us:
- **Operational simplicity:** one renderer service, no separate "publish" step during development.
- **Always-fresh on first boot:** the cache only kicks in on repeat requests.
- **Burst safety:** a fleet bring-up of N hosts → N first-requests then static reads.
- **Tight Netbox coupling is acceptable** at our scale because the renderer + nginx are site-local (run on the bootstrap appliance) and Netbox is projected per-site. Site autonomy is preserved.

For production we may add pre-render-on-Netbox-webhook as a fleet-validation gate (render → run policy checks → only then allow boots), but the on-demand path is the trunk.

### Concrete recipe for the QEMU end-to-end

```bash
# 1. Host-side: OVS bridge with LACP partner + VLAN trunk
sudo ovs-vsctl add-br br-test
sudo ovs-vsctl set port br-test lacp=active bond_mode=balance-tcp
sudo ovs-vsctl add-port br-test veth0 trunks=100,200,300
sudo ovs-vsctl add-port br-test veth1 trunks=100,200,300

# 2. Renderer service + nginx (cache layer) on host loopback
docker compose up netbox             # ~30s
python -m renderer.service &         # listens on 127.0.0.1:8000
nginx -p $PWD/nginx -c nginx.conf    # 10.0.99.1:80, proxies to :8000

# 3. Optional: Soft-RoCE on the test VM's east-west NICs (after VM boots)
sudo modprobe rdma_rxe
# Inside the VM, post-cloud-init:
#   for n in gpu{0..7}; do rdma link add rxe_$n type rxe netdev $n; done

# 4. Launch the VM with two N-S NICs + 8 E-W NICs + mgmt NIC
qemu-system-x86_64 -enable-kvm -m 8G -smp 4 \
  -drive file=ubuntu-24.04-server.qcow2,if=virtio \
  -netdev user,id=mgmt -device virtio-net,netdev=mgmt        \
  -netdev tap,id=n0,ifname=tap-nsa,script=no -device virtio-net,netdev=n0,mac=aa:bb:cc:00:00:01 \
  -netdev tap,id=n1,ifname=tap-nsb,script=no -device virtio-net,netdev=n1,mac=aa:bb:cc:00:00:02 \
  $(for i in $(seq 0 7); do echo "-netdev tap,id=g$i,ifname=tap-gpu$i,script=no \
                                  -device virtio-net,netdev=g$i,mac=aa:bb:cc:00:00:1$i"; done) \
  -smbios "type=1,serial=ds=nocloud-net;s=http://10.0.99.1/render/SN12345/" \
  -smbios "type=3,asset=SN12345"
```

Verify on the VM: `ip -d link show bond0`, `cat /proc/net/bonding/bond0`, `ip -j addr show bond0.100`, `cloud-init status --long`, `ibv_devinfo`.

### What Tier 1 covers

Renderer correctness for both N-S and E-W zones, schema validity, cloud-init NoCloud handling via the FastAPI/nginx hybrid, bond + VLAN topology at the Linux kernel layer, IP/route correctness, MTU plumbing, atomic seed delivery, RDMA verbs API plumbing (via Soft-RoCE).

### What Tier 1 cannot cover

Anything in the NIC silicon or firmware path — real LACPDU exchange with switch-side hashing, hardware VLAN strip/insert offload, jumbo MTU through a real fabric, SR-IOV (no PFs in virtio), **real RoCE behavior including PFC, ECN, DCQCN, and lossless flow control**, GPUDirect, BF-3 firmware modes.

**Soft-RoCE caveat:** Soft-RoCE makes RDMA verbs work over any Ethernet interface, but it implements RoCE in software — no PFC pause frames, no ECN marking under contention, no DCQCN rate adjustment, no offload. Use it to validate **API plumbing only** (does NCCL initialize, does our code open queue pairs correctly, do `memlock` limits work). Do **not** add Soft-RoCE bandwidth/latency numbers to CI — the numbers track software-stack performance, not anything about the real fabric.

### Where Tier 1 actually runs

| Use case | Environment | Cost |
|---|---|---|
| Local interactive dev (Mac) | [Lima](https://lima-vm.io) with Ubuntu 24.04 VM, `vmType: vz`, 4 vCPU / 8 GB | $0 |
| Local interactive dev (Linux) | Native | $0 |
| Shared persistent reference box | **DigitalOcean Droplet `s-4vcpu-8gb`** at ~$0.07/hr or $48/mo | ~$48/mo |
| CI | GitHub Actions `ubuntu-24.04` hosted runners (KVM enabled, Docker ready) | Free for our volume |

The three environments share a single setup script (Ansible playbook or `setup.sh`) so they don't fork. **Mac users on Apple Silicon: stay on ARM Ubuntu inside Lima** — Tier 1 validates renderer + cloud-init plumbing, not anything CPU-architecture-specific.

**EC2 is intentionally excluded.** AWS VPC's L2 abstractions (Nitro vSwitch) block LACP negotiation and arbitrary VLAN tags on the wire, even on bare-metal instances. The "real bare-metal NICs" advantage doesn't help us because everything below the host is AWS-managed, not configurable. EC2 GPU instances are also a poor fit for Tier 2: ENA/EFA is not ConnectX/RoCE, so the silicon-specific behaviors we want to validate aren't present.

## Tier 2 — Single rented GPU bare-metal box

Per the simplicity preference: rent **one** box that covers both ends of the spectrum in one session.

### Provider survey (mid-2026 landscape)

| Provider | Recommended SKU | Approx hourly | NIC topology | Root + Netplan? | Notes |
|---|---|---|---|---|---|
| [Lambda Labs](https://lambda.ai/service/gpu-cloud) | 1× H100 SXM5 bare metal | ~$2.49–3.49/hr | Typically 2× NIC + IB on SXM boxes | Yes | Easiest onboarding; well-documented bare metal access |
| [Crusoe](https://crusoe.ai/cloud/) | H100 SXM bare metal | ~$2/hr | 2× host NIC + RoCE ConnectX-7 | Yes | Strong bare-metal story; B200 available; cheaper than Lambda |
| [CoreWeave](https://coreweave.com) | HGX H100/H200 bare metal | enterprise quote | Full HGX networking incl. BF-3 in some SKUs | Yes (enterprise tier) | Closest to our target topology but procurement is heavier |
| [Nebius](https://nebius.com) | H100 SXM | ~$2.0–2.5/hr | Multi-NIC | Yes | EU-based; B200 platform available |
| [Vultr Bare Metal](https://www.vultr.com/products/bare-metal/) | A100/H100 bare metal | ~$2–4/hr | Trunked VLAN supported on selected SKUs | Yes | Reliable, less GPU-specific tooling |
| [Oracle OCI BM.GPU](https://www.oracle.com/cloud/compute/gpu/) | BM.GPU.H100 | ~$10/hr | Full bare-metal; 8× 400G + 2× 100G mgmt | Yes | Heavier console UX; works |

**Recommendation:** Lambda 1×H100 bare metal or Crusoe H100 bare metal. Both give SSH + root, both have at least two host NICs you can re-bond, both have real Mellanox NICs on a RoCE-configured fabric. Confirm with the provider that the SKU includes **tagged VLAN trunk on at least one NIC** before booking — this varies by SKU and isn't always documented.

Prices above are indicative as of mid-2026 — confirm at the provider before each burn.

### OVS is still useful inside the rented host

Even on real ConnectX hardware, the provider's leaf switch is a *single* logical LACP partner. To validate behaviors that need multiple leaves (e.g., leaf-failover, our ESI-LAG bond reaction), you'd build an OVS topology inside the rented host that simulates the multi-leaf side, while one bond member talks to the real switch. OVS is the constant across both tiers; the host-under-test doesn't care whether the LACP partner is a real switch port or an OVS bridge.

### Recipe for a Tier 2 burn

```text
1. Provision: 1× H100 bare metal, Ubuntu 24.04 image. ~10 min.
2. Bring up our test stack on the rented host:
     - Install Netplan (already present), nginx, python3 + FastAPI, Docker.
     - Clone the renderer repo; run docker-compose for Netbox locally on the rented host.
     - Populate Netbox with this host's actual MACs (pulled from `ip -j link`).
3. Render the host's intent via the on-demand path → write /etc/netplan/60-host.yaml.
4. `netplan try` (auto-rollback safety net) → confirm bond + VLANs come up.
5. Push the same intent through cloud-init by:
     - Starting the renderer service + nginx cache layer on localhost
     - Running `cloud-init clean --logs` and rebooting with cmdline pointing at it
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
- **PFC / ECN / DCQCN under contention** — most providers do not expose DCB controls to tenants.
- **BF-3 `mlxconfig` mode switching** — providers lock firmware; tenants cannot flip NIC mode bits.
- **B300-specific firmware quirks and NCCL at NVL72 scale** — no commercial rental of B300 in NVL72 form factor was generally available as of mid-2026.

## Tier 3 — NVIDIA LaunchPad / vendor labs (for the silicon gap)

[NVIDIA LaunchPad](https://www.nvidia.com/en-us/launchpad/) offers free, reservable access to reference designs (Spectrum-X fabric, BF-3 SuperNIC labs, DGX H100/H200 systems). Reservations are typically 2 weeks. This is the right place to validate:

- BF-3 mode switching via `mlxconfig` (LaunchPad's BlueField labs expose this).
- ConnectX-8/B300-class firmware behavior once those labs land (timing varies; check the LaunchPad catalog when planning).
- DCB / PFC / DCQCN tuning end-to-end against a properly configured RoCE fabric.

Supermicro's JumpStart program is the equivalent path on the OEM side — useful for validating HGX B300 specifically before site-1 hardware arrives.

Both are free but gate-keepered. Plan one reservation 4–6 weeks before site-1 cutover so the BF-3 firmware-control unit and `mlxconfig`-based mode lock are burned in on real hardware.

## Recommended rollout

| Cadence | Tier | Scope | Cost |
|---|---|---|---|
| Every commit | Tier 1 | Renderer golden files, schema validity, `netplan generate` | Free (CI) |
| Every PR to `main` | Tier 1 | + QEMU VM first-boot e2e (~3 min) + Soft-RoCE verbs check | Free (CI) |
| Bi-weekly during active dev | Tier 2 | Single H100 bare-metal burn; bond + VLAN + cloud-init + SR-IOV + basic RoCE | ~$10–20 |
| Before each milestone | Tier 2 | Same as bi-weekly, extended to ~8h with multi-NIC SR-IOV stress and `ib_send_bw` runs | ~$30 |
| Once, 4–6 weeks pre-site-1 | Tier 3 | LaunchPad reservation; lock down BF-3 mode-switch unit, DCQCN tuning, B300-class firmware behavior if available | Free (NVIDIA) |
| Post-site-1 | Real B300 | Replay every Tier 2 + Tier 3 test on production hardware; lock the template | — |

## Open gaps to revisit

- **Multi-host scenarios** — explicitly out of scope here. When we extend to multi-host (e.g., for NCCL inter-host validation), Crusoe and CoreWeave both support multi-node bare-metal reservations on a shared low-latency fabric.
- **DPU mode (BF-3 as full DPU)** — covered in the [baremetal overview caveat](baremetal-network-overview.md); when/if we move to DPU mode, the test plan needs a second OS image and DPU-side cloud-init path. Add a Tier 4 column at that point.
- **Day-2 reconciliation** — separate testing concern (drift injection, `netplan try` rollback, agent behavior). Belongs in its own topic.
- **Production rendering model** — Tier 1 uses on-demand-with-cache. Production may add a parallel pre-render path triggered by Netbox webhook for fleet-validation gating before bring-ups. Revisit once we have load numbers from Tier 2.
