#!/usr/bin/env bash
# M1a: kubeadm single-node control plane on the in-band VLAN (10.6.31.0/24).
# Forces kubelet --node-ip onto the VLAN (the default route is the mgmt user-net).
set -euo pipefail
NODE_IP=${NODE_IP:-10.6.31.1}
echo "KUBELET_EXTRA_ARGS=--node-ip=${NODE_IP}" | sudo tee /etc/default/kubelet >/dev/null
sudo kubeadm init \
  --apiserver-advertise-address="${NODE_IP}" \
  --pod-network-cidr=10.245.0.0/16 \
  --cri-socket=unix:///run/containerd/containerd.sock
mkdir -p "$HOME/.kube"
sudo cp -f /etc/kubernetes/admin.conf "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
# single-node: allow workloads on the control-plane node
kubectl taint nodes --all node-role.kubernetes.io/control-plane- 2>/dev/null || true
kubectl get nodes -o wide
