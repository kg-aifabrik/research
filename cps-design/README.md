# CPS Design

Design artifacts for the **Compute Provisioning Service (CPS)** — the system that
bridges *supply* (racked B300 GPU + CPU servers, Juniper QFX fabric, NetBox
inventory) and *demand* (a tenant requesting a Kubernetes-as-a-Service cluster
with GPUs). CPS uses **Rafay** for bare-metal provisioning + K8s control-plane
lifecycle, **Juniper Apstra** (via the Networking team's API) for fabric/VRF
isolation, and **Weka** for storage.

## Layout

```
cps-design/
  diagrams/        rendered diagrams: <name>.excalidraw (editable) + .svg + .png
  gen/             generator — one Python scene spec -> all three formats
    excalidraw_gen.py     scene model + Excalidraw/SVG emitters
    render.py             SVG -> PNG via headless Chrome (no Node needed)
    build_*.py            one build script per diagram
```

## Diagrams

| File | What it shows |
|------|---------------|
| `cps_system` | System-level component map: CPS internals, external dependencies, site substrate. |
| `cps_provision_flow` | K8s cluster-provisioning workflow (Temporal saga): the sequence from a TMS request to a running, AiFabrik-managed cluster, with compensations. |

## Regenerate

Prereqs: Python 3 and Google Chrome (or Chromium) — no Node toolchain required.

```sh
python3 gen/build_system_diagram.py      # writes diagrams/cps_system.{excalidraw,svg,png}
python3 gen/build_provision_flow.py      # writes diagrams/cps_provision_flow.{excalidraw,svg,png}
```

Edit a diagram either by tweaking its `build_*.py` and re-running, or by opening
the `.excalidraw` file at <https://excalidraw.com> (renders with the true
hand-drawn font) and re-exporting.

> Note: the `gen/` tooling is included for reproducibility. The committed
> deliverables are the files under `diagrams/`.
