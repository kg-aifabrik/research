# host-net-config

Research on configuring host network interfaces during baremetal provisioning — declarative intent in Netbox, rendered to Netplan + cloud-init, delivered to the host on first boot.

## State

- **[Baremetal network overview](baremetal-network-overview.md)** — explainer covering the B300 host NIC topology (2× BF-3 DPU bonded N-S with VLAN trunk; 8× ConnectX-8 SuperNIC E-W RoCE underlay) and the five packet classes traversing the host. Paired Excalidraw + SVG diagrams in [diagrams/](diagrams/).
- **[Test strategy](test-strategy.md)** — two-tier plan: software-only CI (Netbox + on-demand FastAPI renderer + nginx cache + OVS + QEMU + Soft-RoCE) on Lima/DO/GHA; one rented GPU bare-metal box (Lambda / Crusoe H100) per burn for hardware-specific validation; NVIDIA LaunchPad for the silicon gap before site-1.
- **[Implementation plan](implementation-plan.md)** — durable charter and milestone breakdown for the `host-config` repo: 8 horizontal layer milestones + 7 integration gates, ~37 issues total. Captures repo charter, quality bar (mypy strict, ruff, coverage gates, signed commits, mkdocs, observability from day one), workflow conventions, and the issue list to be seeded.
- Larger pipeline research is in flight: Netbox → typed intent → renderer → cloud-init NoCloud seed → Netplan/systemd-networkd, plus Day-2 reconciliation. Requirements & assumptions signed off; full report not yet written.

## Open threads

- OS-level backend comparison: Netplan vs nmstate vs raw systemd-networkd (recommendation pending).
- Day-2 reconciliation: custom GitOps agent vs Ansible push vs re-image (recommendation pending).
- Renderer architecture: Python service triggered by Netbox webhook + scheduled poll (assumed; not yet built).
- BGP-to-host (FRR) as a future schema extension; v1 implements LACP-ESI-LAG only.
- Validation tiers: golden-file CI is in scope; live-VM and rented-hardware tiers tracked as deferred decisions.
