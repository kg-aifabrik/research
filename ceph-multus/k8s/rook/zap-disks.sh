#!/usr/bin/env bash
# Wipe the OSD disks so Rook can re-consume them after a CephCluster delete.
# ceph-volume lays down LVM (VG ceph-*) + bluestore superblocks on vdb/vdc.
set -uo pipefail
for vg in $(sudo vgs --noheadings -o vg_name 2>/dev/null | grep -i ceph); do sudo vgremove -f "$vg" 2>/dev/null || true; done
sudo dmsetup ls 2>/dev/null | awk '/ceph/{print $1}' | xargs -r -n1 sudo dmsetup remove 2>/dev/null || true
for d in /dev/vdb /dev/vdc; do
  sudo sgdisk --zap-all "$d" 2>/dev/null || true
  sudo wipefs -a "$d" 2>/dev/null || true
  # clear the bluestore raw label at the start (oflag=direct can silently fail on virtio)
  sudo dd if=/dev/zero of="$d" bs=1M count=200 2>/dev/null || true
done
sudo rm -rf /var/lib/rook
echo "zapped: $(lsblk -dn -o NAME,SIZE /dev/vdb /dev/vdc | tr '\n' ' ')"
