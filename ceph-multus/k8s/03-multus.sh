#!/usr/bin/env bash
# M2: CNI reference plugins (macvlan) + Multus thick + Whereabouts + NADs + 3-interface pod.
set -euo pipefail
CNI_VER=${CNI_VER:-v1.6.2}
MULTUS_VER=${MULTUS_VER:-v4.3.0}
WB_VER=${WB_VER:-v0.8.0}

echo "### CNI reference plugins (${CNI_VER}) -> /opt/cni/bin (Cilium ships only its own)"
sudo mkdir -p /opt/cni/bin
curl -fsSL "https://github.com/containernetworking/plugins/releases/download/${CNI_VER}/cni-plugins-linux-arm64-${CNI_VER}.tgz" \
  | sudo tar -xz -C /opt/cni/bin ./macvlan ./host-local ./loopback ./static ./tuning
ls -1 /opt/cni/bin/macvlan

echo "### Multus thick ${MULTUS_VER}"
kubectl apply -f "https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/${MULTUS_VER}/deployments/multus-daemonset-thick.yml"
kubectl -n kube-system set image ds/kube-multus-ds kube-multus="ghcr.io/k8snetworkplumbingwg/multus-cni:${MULTUS_VER}-thick" 2>/dev/null || true
kubectl -n kube-system rollout status ds/kube-multus-ds --timeout=240s

echo "### Whereabouts ${WB_VER}"
for f in daemonset-install.yaml whereabouts.cni.cncf.io_ippools.yaml whereabouts.cni.cncf.io_overlappingrangeipreservations.yaml; do
  kubectl apply -f "https://raw.githubusercontent.com/k8snetworkplumbingwg/whereabouts/${WB_VER}/doc/crds/${f}"
done
kubectl -n kube-system rollout status ds/whereabouts --timeout=180s

echo "### Cilium did not clobber Multus (00-multus.conf present, no .cilium_bak):"
sudo ls -1 /etc/cni/net.d/ | sed 's/^/    /' || true

echo "### NADs + 3-interface pod"
kubectl apply -f "$HOME/k8s/nads.yaml"
kubectl get net-attach-def
kubectl apply -f "$HOME/k8s/test-pod-3if.yaml"
kubectl wait --for=condition=Ready pod/tri-net --timeout=150s
echo "--- interfaces in tri-net ---"
kubectl exec tri-net -- ip -br addr
