#!/usr/bin/env bash
# M4: scale the single-node cluster to 3 nodes (hyperconverged) so Ceph replicates
# across HOSTS over the storage VLAN. Launches cmnode2/cmnode3 (kept small for the
# 24 GB budget; cmnode1 is left running untouched), joins them, lets Rook add OSDs
# on their disks, switches the block pool to failureDomain=host/size=3, and proves
# inter-host OSD replication traffic on VLAN 2032. Host-side orchestrator.
set -uo pipefail
ROOT=/Users/karthikgajjala/cm-feasibility
REPO=/Users/karthikgajjala/code/research/ceph-multus
KEY=$ROOT/id_cm
O="-i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -o ServerAliveInterval=15 -o ServerAliveCountMax=10 -o LogLevel=ERROR"
n1(){ ssh $O -p 2221 ubuntu@127.0.0.1 "$@"; }
T="kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph --connect-timeout 5"
step(){ echo; echo "======== $* ========"; }
mem(){ vm_stat | awk '/Pages free/{f=$3}/Pages active/{a=$3}/wired/{w=$4}/occupied by comp/{c=$5} END{printf "  host: active=%.1fG wired=%.1fG compressed=%.1fG\n",a*16384/1e9,w*16384/1e9,c*16384/1e9}'; sysctl -n vm.swapusage; }

step "0 launch cmnode2 + cmnode3 (5 GB, 1 OSD disk each)"
pgrep -f cm_hub.py >/dev/null || { nohup python3 "$REPO/feasibility/cm_hub.py" 10032 >"$ROOT/lab-hub.log" 2>&1 & sleep 1; }
for i in 2 3; do MEM=5120 SMP=4 OSD_DISKS=1 OSD_GB=15 OS_GB=40 bash "$REPO/vm/lab-up.sh" "$i" | grep -E "launching|pid="; done
mem

step "1 wait ssh + cloud-init (2222/2223)"
for p in 2222 2223; do for t in $(seq 1 60); do ssh $O -p "$p" ubuntu@127.0.0.1 true 2>/dev/null && { echo "  $p up"; break; }; sleep 5; done; done
for p in 2222 2223; do ssh $O -p "$p" ubuntu@127.0.0.1 "sudo cloud-init status --wait" 2>/dev/null; done

step "2 provision both workers (parallel)"
for p in 2222 2223; do scp $O -P "$p" -r "$REPO/vm" "$REPO/k8s" ubuntu@127.0.0.1:~/ >/dev/null; done
ssh $O -p 2222 ubuntu@127.0.0.1 "bash ~/vm/provision-node.sh" >/tmp/prov2.log 2>&1 &
ssh $O -p 2223 ubuntu@127.0.0.1 "bash ~/vm/provision-node.sh" >/tmp/prov3.log 2>&1 &
wait
echo "  node2: $(tail -1 /tmp/prov2.log)"; echo "  node3: $(tail -1 /tmp/prov3.log)"

step "3 kubeadm join (node-ip pinned to the in-band VLAN)"
JOIN=$(n1 "sudo kubeadm token create --print-join-command")
ssh $O -p 2222 ubuntu@127.0.0.1 "echo 'KUBELET_EXTRA_ARGS=--node-ip=10.6.31.2' | sudo tee /etc/default/kubelet >/dev/null; sudo $JOIN --cri-socket=unix:///run/containerd/containerd.sock" 2>&1 | tail -1
ssh $O -p 2223 ubuntu@127.0.0.1 "echo 'KUBELET_EXTRA_ARGS=--node-ip=10.6.31.3' | sudo tee /etc/default/kubelet >/dev/null; sudo $JOIN --cri-socket=unix:///run/containerd/containerd.sock" 2>&1 | tail -1

step "4 wait nodes Ready"
for i in $(seq 1 24); do r=$(n1 "kubectl get nodes --no-headers 2>/dev/null | grep -cw Ready"); echo "  Ready: $r/3"; [ "${r:-0}" -ge 3 ] && break; sleep 10; done
n1 "kubectl get nodes -o wide | awk '{print \$1,\$2,\$3,\$6}'"
mem

step "5 wait Rook to add OSDs on the new nodes (expect 4 total across 3 hosts)"
for i in $(seq 1 44); do o=$(n1 "$T osd ls 2>/dev/null | grep -c ."); echo "  OSDs: ${o:-0}"; [ "${o:-0}" -ge 4 ] && break; sleep 15; done
n1 "$T osd tree"
mem

step "6 block pool -> failureDomain=host, size=3 (replicate across hosts)"
n1 "kubectl -n rook-ceph patch cephblockpool replicapool --type=merge -p '{\"spec\":{\"failureDomain\":\"host\",\"replicated\":{\"size\":3}}}'"
for i in $(seq 1 30); do h=$(n1 "$T health 2>/dev/null | head -1"); echo "  $h"; echo "$h" | grep -q HEALTH_OK && break; sleep 15; done

step "7 verify cluster + pool"
n1 "$T -s | sed -n 1,16p"
echo "--- replicapool size + crush failure domain ---"
n1 "$T osd pool get replicapool size"
n1 "$T osd crush rule dump \$($T osd pool get replicapool crush_rule -f json 2>/dev/null | sed 's/.*: *\"//;s/\".*//') 2>/dev/null | grep -E 'type' | head"

step "8 PROVE inter-host replication on the storage VLAN"
echo "--- per-OSD cluster_addr (should span 10.6.32.1/.2/.3) ---"
n1 "$T osd metadata 2>/dev/null | grep -E 'hostname|back_addr' | grep -oE '(cmnode[0-9])|10\.6\.32\.[0-9]+:[0-9]+' | paste - - | head"
echo "--- tcpdump cmnode1 vlan2032 for OSD traffic to .2/.3 during a rados write ---"
n1 "sudo nohup timeout 12 tcpdump -n -i vlan2032 -c 8 'host 10.6.32.2 or host 10.6.32.3' >/tmp/repl.txt 2>/dev/null & sleep 1; kubectl -n rook-ceph exec deploy/rook-ceph-tools -- rados bench -p replicapool 8 write --no-cleanup 2>&1 | grep -E 'Total writes|Average' ; sleep 2; echo '--- captured inter-host storage-VLAN packets ---'; sudo head -6 /tmp/repl.txt"
mem
echo; echo "======== M4 DONE ========"
