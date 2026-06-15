#!/usr/bin/env bash
# THROWAWAY POC. Runs inside a guest to prepare it as a kubeadm node:
# swap off, kernel modules + sysctls, containerd (SystemdCgroup), kube* v1.31.
set -euo pipefail
K8S_MINOR=${K8S_MINOR:-v1.31}

echo "### swap off"
sudo swapoff -a || true
sudo sed -i '/\bswap\b/s/^/#/' /etc/fstab || true

echo "### kernel modules + sysctls"
printf 'overlay\nbr_netfilter\n' | sudo tee /etc/modules-load.d/k8s.conf >/dev/null
sudo modprobe overlay; sudo modprobe br_netfilter
cat <<'EOF' | sudo tee /etc/sysctl.d/k8s.conf >/dev/null
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sudo sysctl --system >/dev/null

echo "### containerd"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq containerd apt-transport-https ca-certificates curl gpg jq conntrack socat ethtool >/dev/null
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml >/dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd && sudo systemctl enable containerd >/dev/null 2>&1

echo "### kube* ${K8S_MINOR}"
sudo mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/Release.key" | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/kubernetes.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y -qq kubelet kubeadm kubectl >/dev/null
sudo apt-mark hold kubelet kubeadm kubectl >/dev/null

echo "### done: $(kubeadm version -o short), containerd $(containerd --version | awk '{print $3}')"
