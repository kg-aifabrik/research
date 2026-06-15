#!/usr/bin/env bash
# Tear down all feasibility VMs.
ROOT=/Users/karthikgajjala/cm-feasibility
for pf in "$ROOT"/run/node*/qemu.pid; do
  [ -f "$pf" ] || continue
  pid=$(cat "$pf"); kill "$pid" 2>/dev/null && echo "killed $pid ($pf)"
  rm -f "$pf"
done
pkill -f qemu-system-aarch64 2>/dev/null && echo "swept stray qemu" || true
