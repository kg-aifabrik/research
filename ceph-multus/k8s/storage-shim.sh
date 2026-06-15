#!/usr/bin/env bash
# Host macvlan shim on the storage VLAN. macvlan children (pods on storage-net)
# cannot reach their own parent host interface (10.6.32.1), but they CAN reach a
# sibling macvlan child. This shim (10.6.32.250) is such a sibling in the host
# netns, so pod S3 traffic to RGW reaches the host over VLAN 2032. A DNAT
# forwards :80 to the RGW public address in case RGW binds only 10.6.32.1.
set -euo pipefail
sudo ip link show storage-shim >/dev/null 2>&1 || \
  sudo ip link add storage-shim link vlan2032 type macvlan mode bridge
sudo ip addr add 10.6.32.250/24 dev storage-shim 2>/dev/null || true
sudo ip link set storage-shim up
# The host has two IPs in 10.6.32.0/24 (Ceph's vlan2032 .1 and this shim .250).
# Replies to pod macvlan IPs must egress the SHIM (a sibling macvlan child), not
# the parent vlan2032 (parent->child is isolated). Pin the Whereabouts pod range
# (.64+) to the shim so the return path works.
sudo ip route replace 10.6.32.64/26  dev storage-shim src 10.6.32.250 2>/dev/null || true
sudo ip route replace 10.6.32.128/25 dev storage-shim src 10.6.32.250 2>/dev/null || true
sudo sysctl -qw net.ipv4.conf.all.route_localnet=1
# Forward shim:80 -> RGW public addr:80 (idempotent)
sudo iptables -t nat -C PREROUTING -d 10.6.32.250 -p tcp --dport 80 -j DNAT --to-destination 10.6.32.1:80 2>/dev/null || \
  sudo iptables -t nat -A PREROUTING -d 10.6.32.250 -p tcp --dport 80 -j DNAT --to-destination 10.6.32.1:80
sudo iptables -t nat -C POSTROUTING -d 10.6.32.1 -p tcp --dport 80 -j MASQUERADE 2>/dev/null || \
  sudo iptables -t nat -A POSTROUTING -d 10.6.32.1 -p tcp --dport 80 -j MASQUERADE
ip -o addr show storage-shim | sed 's/^/  /'
