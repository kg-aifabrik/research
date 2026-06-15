#!/usr/bin/env bash
# THROWAWAY POC. Launch one lab node (index $1) for the ceph-multus build.
# Bigger than the feasibility VMs: more RAM/CPU, a 40G OS disk, and raw disks
# for Ceph OSDs. Data NIC joins the cm_hub.py L2 switch (VLAN trunk). mgmt NIC
# is QEMU user-net (SSH on 222<idx>, outbound NAT for apt / image pulls).
#   start hub first:  python3 feasibility/cm_hub.py 10032 &
#   MEM=14336 SMP=6 OSD_DISKS=2 bash vm/lab-up.sh 1
set -euo pipefail
ROOT=/Users/karthikgajjala/cm-feasibility
IMG=$ROOT/images/noble-arm64.img
PUB=$(cat $ROOT/id_cm.pub)
LAB=$ROOT/lab
i=${1:?node index}
MEM=${MEM:-14336}; SMP=${SMP:-6}; OS_GB=${OS_GB:-40}
OSD_DISKS=${OSD_DISKS:-2}; OSD_GB=${OSD_GB:-15}; HUBPORT=10032
QSHARE=$(brew --prefix qemu)/share/qemu
CODE=$(ls "$QSHARE"/edk2-aarch64-code.fd 2>/dev/null | head -1)
VARS_TMPL=$(ls "$QSHARE"/edk2-arm-vars.fd 2>/dev/null | head -1)

WD=$LAB/node$i; mkdir -p "$WD/seed"
MGMT_MAC=$(printf '52:54:00:00:01:%02x' "$i")
DATA_MAC=$(printf '52:54:00:00:da:%02x' "$i")
PORT=$((2220 + i))

cat > "$WD/seed/meta-data" <<EOF
instance-id: cmnode$i
local-hostname: cmnode$i
EOF
cat > "$WD/seed/user-data" <<EOF
#cloud-config
hostname: cmnode$i
fqdn: cmnode$i
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys: [ $PUB ]
ssh_pwauth: false
write_files:
  - path: /etc/hosts
    append: true
    content: |
      10.6.31.1 cmnode1
      10.6.31.2 cmnode2
      10.6.31.3 cmnode3
EOF
cat > "$WD/seed/network-config" <<EOF
version: 2
ethernets:
  mgmt:
    match: {macaddress: "$MGMT_MAC"}
    set-name: mgmt
    dhcp4: true
  data0:
    match: {macaddress: "$DATA_MAC"}
    set-name: data0
    dhcp4: false
    addresses: [10.6.31.$i/24]
vlans:
  vlan2032: {id: 2032, link: data0, addresses: [10.6.32.$i/24]}
  vlan2033: {id: 2033, link: data0, addresses: [10.6.33.$i/24]}
EOF
xorrisofs -quiet -volid cidata -joliet -rock -output "$WD/seed.iso" \
  "$WD/seed/user-data" "$WD/seed/meta-data" "$WD/seed/network-config"

[ -f "$WD/disk.qcow2" ] || qemu-img create -q -f qcow2 -F qcow2 -b "$IMG" "$WD/disk.qcow2" "${OS_GB}G"
[ -f "$WD/vars.fd" ] || cp "$VARS_TMPL" "$WD/vars.fd"
OSD_ARGS=()
for d in $(seq 1 "$OSD_DISKS"); do
  f="$WD/osd$d.raw"; [ -f "$f" ] || qemu-img create -q -f raw "$f" "${OSD_GB}G"
  OSD_ARGS+=( -drive "if=virtio,format=raw,file=$f" )   # vdb, vdc, ... (raw → Rook OSDs)
done

echo "launching cmnode$i: ${MEM}MB ${SMP}vcpu, ${OSD_DISKS}x${OSD_GB}G OSD disks, ssh $PORT"
qemu-system-aarch64 -name "cmnode$i" \
  -machine virt,accel=hvf -cpu host -smp "$SMP" -m "$MEM" \
  -drive "if=pflash,format=raw,readonly=on,file=$CODE" -drive "if=pflash,format=raw,file=$WD/vars.fd" \
  -drive "if=virtio,format=qcow2,file=$WD/disk.qcow2" \
  "${OSD_ARGS[@]}" \
  -drive "if=virtio,format=raw,readonly=on,file=$WD/seed.iso" \
  -netdev "user,id=mgmt,hostfwd=tcp::$PORT-:22" -device "virtio-net-pci,netdev=mgmt,mac=$MGMT_MAC" \
  -netdev "socket,id=data,connect=127.0.0.1:$HUBPORT" -device "virtio-net-pci,netdev=data,mac=$DATA_MAC" \
  -display none -serial "file:$WD/serial.log" -pidfile "$WD/qemu.pid" -daemonize
echo "  pid=$(cat "$WD/qemu.pid")"
