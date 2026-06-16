#!/usr/bin/env bash
# Scale the 3-node cluster back to single-node (cmnode1) and free resources.
# cmnode1 (host-level size 3) holds a full replica of all data, so dropping the
# other two hosts loses no data — we just re-replicate to size 2 on cmnode1's
# two OSDs (osd.0/osd.1). Kills the worker VMs first to free RAM, then heals.
set -uo pipefail
ROOT=/Users/karthikgajjala/cm-feasibility
KEY=$ROOT/id_cm
O="-i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -o ServerAliveInterval=15 -o ServerAliveCountMax=10 -o LogLevel=ERROR"
n1(){ ssh $O -p 2221 ubuntu@127.0.0.1 "$@"; }
T="kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph --connect-timeout 6"
step(){ echo; echo "======== $* ========"; }

step "1 kill worker VMs cmnode2/cmnode3 (frees RAM)"
for i in 2 3; do p=$(cat "$ROOT/lab/node$i/qemu.pid" 2>/dev/null); [ -n "${p:-}" ] && kill "$p" 2>/dev/null && echo "  killed node$i (pid $p)"; done
sleep 3; sysctl -n vm.swapusage

step "2 mark worker OSDs out + block pool back to single-node-safe (osd domain, size 2)"
n1 "$T osd out 2 3" 2>&1 | tail -1
n1 "$T osd crush rule create-replicated replicated_osd default osd 2>/dev/null || true"
n1 "$T osd pool set replicapool crush_rule replicated_osd"
n1 "$T osd pool set replicapool size 2"
n1 "$T osd pool set replicapool min_size 1"
n1 "kubectl -n rook-ceph patch cephblockpool replicapool --type=merge -p '{\"spec\":{\"failureDomain\":\"osd\",\"replicated\":{\"size\":2}}}'" 2>&1 | tail -1

step "3 wait for recovery onto cmnode1 (osd.0/osd.1)"
for i in $(seq 1 24); do h=$(n1 "$T health 2>/dev/null | head -1"); echo "  $h"; echo "$h" | grep -q HEALTH_OK && break; sleep 15; done

step "4 remove dead workers from k8s + purge their OSDs"
n1 "kubectl delete node cmnode2 cmnode3 --timeout=60s" 2>&1 | tail -2
n1 "$T osd purge 2 --yes-i-really-mean-it 2>&1 | tail -1; $T osd purge 3 --yes-i-really-mean-it 2>&1 | tail -1"

step "5 final single-node state"
n1 "$T -s 2>/dev/null | sed -n 1,12p"
n1 "$T osd tree 2>/dev/null"
n1 "kubectl get nodes 2>/dev/null"
echo "--- host swap after scale-down ---"; sysctl -n vm.swapusage
