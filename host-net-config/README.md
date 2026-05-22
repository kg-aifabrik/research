# host-net-config

Research on configuring host network interfaces during baremetal provisioning — declarative intent in Netbox, rendered to Netplan + cloud-init, delivered to the host on first boot.

## State

- **[Baremetal network overview](baremetal-network-overview.md)** — explainer covering the B300 host NIC topology (2× BF-3 DPU bonded N-S with VLAN trunk; 8× ConnectX-8 SuperNIC E-W RoCE underlay) and the five packet classes traversing the host. Paired Excalidraw + SVG diagrams in [diagrams/](diagrams/).
- **[Test strategy](test-strategy.md)** — two-tier plan: software-only CI (Netbox in Docker + QEMU + OVS) for fast iteration; one rented GPU bare-metal box (Lambda / Crusoe H100) per burn for everything else; NVIDIA LaunchPad for the silicon-specific gap before site-1.
- Larger pipeline research is in flight: Netbox → typed intent → renderer → cloud-init NoCloud seed → Netplan/systemd-networkd, plus Day-2 reconciliation. Requirements & assumptions signed off; full report not yet written.

## Open threads

- OS-level backend comparison: Netplan vs nmstate vs raw systemd-networkd (recommendation pending).
- Day-2 reconciliation: custom GitOps agent vs Ansible push vs re-image (recommendation pending).
- Renderer architecture: Python service triggered by Netbox webhook + scheduled poll (assumed; not yet built).
- BGP-to-host (FRR) as a future schema extension; v1 implements LACP-ESI-LAG only.
- Validation tiers: golden-file CI is in scope; live-VM and rented-hardware tiers tracked as deferred decisions.
