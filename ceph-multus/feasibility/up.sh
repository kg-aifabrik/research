#!/usr/bin/env bash
# THROWAWAY POC feasibility harness for ceph-multus.
# Brings up N Ubuntu 24.04 arm64 VMs on a single shared QEMU multicast L2 bus,
# each with: mgmt NIC (user-net, SSH via hostfwd 222<N>) + data NIC on the mcast bus.
# Guest netplan (from NoCloud seed) puts VLAN 2031 untagged on data0 and 802.1Q
# sub-interfaces 2032/2033 on top — mirroring the Suiri lab (minus bond/LACP/jumbo).
# Shortcut taken: no bond, MTU 1500, mcast bus instead of a real switch.
set -euo pipefail

ROOT=/Users/karthikgajjala/cm-feasibility
IMG=$ROOT/images/noble-arm64.img
PUB=$(cat $ROOT/id_cm.pub)
N=${1:-2}                       # number of nodes
MCAST=230.0.0.32:10032          # shared L2 bus (one collision domain = "the trunk")
BUS=${BUS:-mcast}               # mcast | hub
LOCALADDR=${LOCALADDR:-127.0.0.1}
HUBPORT=10032
MEM=${MEM:-2048}
SMP=${SMP:-2}

QSHARE=$(brew --prefix qemu)/share/qemu
CODE=$(ls "$QSHARE"/edk2-aarch64-code.fd 2>/dev/null || find /opt/homebrew -name 'edk2-aarch64-code.fd' 2>/dev/null | head -1)
VARS_TMPL=$(ls "$QSHARE"/edk2-arm-vars.fd 2>/dev/null || find /opt/homebrew -name 'edk2-arm-vars.fd' 2>/dev/null | head -1)
echo "firmware code=$CODE"
echo "firmware vars=$VARS_TMPL"
[ -f "$CODE" ] || { echo "ERROR: edk2 code firmware not found"; exit 1; }

# Make a base overlay-able copy once (cloud img is qcow2 already)
for i in $(seq 1 "$N"); do
  WD=$ROOT/run/node$i
  mkdir -p "$WD/seed"
  OCT=$i                                   # last octet: node1=.1, node2=.2 ...
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
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $PUB
ssh_pwauth: false
package_update: false
runcmd:
  - [ modprobe, 8021q ]
  - [ sh, -c, "echo READY > /run/cm-ready" ]
EOF

  # NoCloud network-config: mgmt via DHCP (user-net), data0 untagged=VLAN2031,
  # tagged sub-ifs for 2032/2033. Matched by MAC for determinism (like the lab).
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
    addresses: [10.6.31.$OCT/24]
vlans:
  vlan2032:
    id: 2032
    link: data0
    addresses: [10.6.32.$OCT/24]
  vlan2033:
    id: 2033
    link: data0
    addresses: [10.6.33.$OCT/24]
EOF

  xorrisofs -quiet -volid cidata -joliet -rock \
    -output "$WD/seed.iso" "$WD/seed/user-data" "$WD/seed/meta-data" "$WD/seed/network-config"

  # per-node overlay disk + writable UEFI vars
  [ -f "$WD/disk.qcow2" ] || qemu-img create -q -f qcow2 -F qcow2 -b "$IMG" "$WD/disk.qcow2" 20G
  [ -f "$WD/vars.fd" ] || { if [ -f "$VARS_TMPL" ]; then cp "$VARS_TMPL" "$WD/vars.fd"; else dd if=/dev/zero of="$WD/vars.fd" bs=1m count=64 2>/dev/null; fi; }

  PFLASH=( -drive "if=pflash,format=raw,readonly=on,file=$CODE" -drive "if=pflash,format=raw,file=$WD/vars.fd" )

  # Data-plane bus: mcast (N-node hub via multicast) or hub (node1 listens, rest connect)
  if [ "$BUS" = switch ]; then
    DATA_OPT="socket,id=data,connect=127.0.0.1:$HUBPORT"   # all nodes -> userspace hub (cm_hub.py)
  elif [ "$BUS" = hub ]; then
    if [ "$i" = 1 ]; then DATA_OPT="socket,id=data,listen=:$HUBPORT"; else DATA_OPT="socket,id=data,connect=127.0.0.1:$HUBPORT"; fi
  else
    DATA_OPT="socket,id=data,mcast=$MCAST,localaddr=$LOCALADDR"
  fi

  echo "=== launching cmnode$i (ssh port $PORT, data bus: $DATA_OPT) ==="
  qemu-system-aarch64 \
    -name "cmnode$i" \
    -machine virt,accel=hvf -cpu host -smp "$SMP" -m "$MEM" \
    "${PFLASH[@]}" \
    -drive "if=virtio,format=qcow2,file=$WD/disk.qcow2" \
    -drive "if=virtio,format=raw,readonly=on,file=$WD/seed.iso" \
    -netdev "user,id=mgmt,hostfwd=tcp::$PORT-:22" -device "virtio-net-pci,netdev=mgmt,mac=$MGMT_MAC" \
    -netdev "$DATA_OPT" -device "virtio-net-pci,netdev=data,mac=$DATA_MAC" \
    -display none -serial "file:$WD/serial.log" \
    -pidfile "$WD/qemu.pid" -daemonize
  echo "  pid=$(cat "$WD/qemu.pid" 2>/dev/null || echo '?')"
  [ "$BUS" = hub ] && [ "$i" = 1 ] && sleep 2   # let the hub listener bind before connectors
done
echo "ALL $N NODES LAUNCHED"
