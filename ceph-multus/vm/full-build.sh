#!/usr/bin/env bash
# End-to-end clean build on a FRESH VM (all known fixes baked in). Host-side
# orchestrator: nukes node1, boots a pristine VM (fresh OS + OSD disks), then
# runs provision -> kubeadm -> Cilium -> Multus -> Rook (block+object). Each step
# streams a marker so progress is monitorable. Run from the Mac.
set -uo pipefail
ROOT=/Users/karthikgajjala/cm-feasibility
REPO=/Users/karthikgajjala/code/research/ceph-multus
KEY=$ROOT/id_cm
O="-i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -o ServerAliveInterval=15 -o ServerAliveCountMax=8 -o LogLevel=ERROR"
sshn(){ ssh $O -p 2221 ubuntu@127.0.0.1 "$@"; }
step(){ echo; echo "======== $* ========"; }

step "0 teardown + pristine VM"
kill "$(cat "$ROOT/lab/node1/qemu.pid" 2>/dev/null)" 2>/dev/null || true; sleep 3
rm -rf "$ROOT/lab/node1"
pgrep -f cm_hub.py >/dev/null || { nohup python3 "$REPO/feasibility/cm_hub.py" 10032 >"$ROOT/lab-hub.log" 2>&1 & sleep 1; }
MEM=14336 SMP=6 OSD_DISKS=2 OSD_GB=15 OS_GB=40 bash "$REPO/vm/lab-up.sh" 1 | grep -E "launching|pid="

step "1 wait ssh + cloud-init"
for t in $(seq 1 60); do sshn true 2>/dev/null && { echo "ssh up"; break; }; sleep 5; done
sshn "sudo cloud-init status --wait" 2>/dev/null
sshn "ip -br addr | grep -E 'data0|vlan'"

step "2 copy scripts"
scp $O -P 2221 -r "$REPO/vm" "$REPO/k8s" ubuntu@127.0.0.1:~/ >/dev/null

step "3 provision (k8s prereqs)"; sshn "bash ~/vm/provision-node.sh" 2>&1 | tail -2
step "4 kubeadm (M1a)";          sshn "bash ~/k8s/01-kubeadm-init.sh" 2>&1 | tail -2
step "5 Cilium (M1b)";           sshn "bash ~/k8s/02-cilium.sh" 2>&1 | tail -3
step "6 Multus + 3-iface (M2)";  sshn "bash ~/k8s/03-multus.sh" 2>&1 | tail -6
step "7 Rook operator+cluster (M3a)"; sshn "bash ~/k8s/04-rook.sh" 2>&1 | tail -2
step "7b converge"
sshn 'for i in $(seq 1 40); do
  osd=$(kubectl -n rook-ceph get pod -l app=rook-ceph-osd --no-headers 2>/dev/null | grep -c Running)
  mon=$(kubectl -n rook-ceph get pod -l app=rook-ceph-mon --no-headers 2>/dev/null | awk "{print \$3}" | head -1)
  h=""; [ "$mon" = Running ] && h=$(kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph --connect-timeout 4 health 2>/dev/null | head -1)
  printf "[%2d] mon=%s osd=%s health=%s\n" "$i" "${mon:-?}" "${osd:-0}" "${h:-?}"
  { [ "${osd:-0}" -ge 2 ] && [ -n "$h" ]; } && break; sleep 15
done
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph --connect-timeout 5 osd pool set .mgr size 1 2>/dev/null || true'
step "8 block (M3b)";  sshn "bash ~/k8s/05-block.sh" 2>&1 | tail -6
step "9 object (M3c)"; sshn "bash ~/k8s/06-object.sh" 2>&1 | tail -12
step "DONE — final ceph -s + osd addrs"
sshn 'kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph --connect-timeout 5 -s 2>&1 | sed -n 1,12p
echo "--- osd addrs ---"; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph --connect-timeout 5 osd dump 2>/dev/null | grep -oE "10\.6\.32\.[0-9]+:[0-9]+" | head -4'
