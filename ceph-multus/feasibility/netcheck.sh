#!/usr/bin/env bash
# Proves the QEMU mcast bus carries untagged + 802.1Q-tagged L2 frames between guests.
set -uo pipefail
ROOT=/Users/karthikgajjala/cm-feasibility
KEY=$ROOT/id_cm
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o LogLevel=ERROR"
n1(){ $SSH -p 2221 ubuntu@127.0.0.1 "$@"; }
n2(){ $SSH -p 2222 ubuntu@127.0.0.1 "$@"; }

echo "### Waiting for SSH on both nodes (up to 240s) ..."
for p in 2221 2222; do
  for t in $(seq 1 48); do
    if $SSH -p $p ubuntu@127.0.0.1 true 2>/dev/null; then echo "  port $p up"; break; fi
    sleep 5
  done
done

echo "### Waiting for cloud-init to finish ..."
n1 'sudo cloud-init status --wait' 2>/dev/null
n2 'sudo cloud-init status --wait' 2>/dev/null

echo; echo "### node1 interfaces"; n1 'ip -br addr show | grep -E "data0|vlan|mgmt"'
echo; echo "### node2 interfaces"; n2 'ip -br addr show | grep -E "data0|vlan|mgmt"'
echo; echo "### node1 vlan2032 link detail (proves 802.1Q sub-interface)"; n1 'ip -d link show vlan2032 | sed -n 2p'

echo; echo "### Start tcpdump on node2 (capture tagged VLAN 2032 frames on data0)"
n2 'sudo pkill tcpdump 2>/dev/null; sudo nohup timeout 12 tcpdump -e -n -i data0 -c 5 vlan 2032 > /tmp/td.txt 2>/dev/null & sleep 1; echo armed'

echo; echo "### Connectivity from node1 -> node2"
echo "-- untagged VLAN 2031 (10.6.31.2):"; n1 'ping -c2 -W2 10.6.31.2' | grep -E "packets|rtt" || echo "FAIL"
echo "-- tagged   VLAN 2032 (10.6.32.2):"; n1 'ping -c3 -W2 10.6.32.2' | grep -E "packets|rtt" || echo "FAIL"
echo "-- tagged   VLAN 2033 (10.6.33.2):"; n1 'ping -c2 -W2 10.6.33.2' | grep -E "packets|rtt" || echo "FAIL"

echo; echo "### node2 tcpdump result (should show '802.1Q ... vlan 2032')"
sleep 2; n2 'cat /tmp/td.txt 2>/dev/null | head -5'

echo; echo "### MTU check (expect 1500 - jumbo intentionally dropped)"
n1 'ip link show vlan2032 | grep -o "mtu [0-9]*"'

echo; echo "### Host memory while 2 VMs run"
vm_stat | awk '/page size/{ps=$8} /Pages free/{f=$3} /Pages active/{a=$3} /wired/{w=$4} END{printf "  free=%.1fG active=%.1fG wired=%.1fG\n", f*16384/1e9, a*16384/1e9, w*16384/1e9}'
ps -o rss=,comm= -p $(pgrep -f qemu-system-aarch64 | tr "\n" "," | sed "s/,$//") 2>/dev/null | awk '{rss+=$1} END{printf "  qemu RSS total ~= %.1f GB across VMs\n", rss/1024/1024}'
echo "DONE"
