#!/usr/bin/env bash
# One-time prerequisites for the ceph-multus lab on an Apple-silicon Mac.
# Idempotent: installs QEMU + xorriso, creates the scratch dir + SSH key, and
# downloads the Ubuntu 24.04 arm64 cloud image the VMs boot from. The other
# scripts (vm/lab-up.sh, vm/full-build.sh, ...) assume this layout under ~/cm-feasibility.
set -euo pipefail
ROOT="$HOME/cm-feasibility"
IMG_URL="https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-arm64.img"

echo "### tools (qemu >= 9.2, xorriso)"
command -v qemu-system-aarch64 >/dev/null 2>&1 || brew install qemu
command -v xorrisofs >/dev/null 2>&1 || brew install xorriso

echo "### scratch dir + SSH key"
mkdir -p "$ROOT/images" "$ROOT/lab"
[ -f "$ROOT/id_cm" ] || ssh-keygen -t ed25519 -N '' -f "$ROOT/id_cm" -C cm-lab

echo "### Ubuntu 24.04 arm64 base image (~600 MB, one-time)"
[ -f "$ROOT/images/noble-arm64.img" ] || curl -fL --retry 3 -o "$ROOT/images/noble-arm64.img" "$IMG_URL"

echo "prereqs ready in $ROOT  (qemu $(qemu-system-aarch64 --version | head -1 | awk '{print $4}'))"
