"""
Build the CPS system-level component diagram.

Run:  python3 gen/build_system_diagram.py
Emits to ../diagrams/: cps_system.excalidraw (editable), .svg, .png
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excalidraw_gen import Scene
from render import render

GEN = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(GEN, "..", "diagrams"))
os.makedirs(OUT, exist_ok=True)

W, H = 1460, 1130
s = Scene(W, H, "Compute Provisioning Service (CPS) — System Components")
s.note(W/2, 64, "single site (us-east-1 / NJ)  ·  per-tenant dedicated GPU nodes + dedicated K8s control plane",
       size=14, color="#868e96", bold=False, anchor="middle")
s.note(W/2, 86, "blue = CPS service   violet = orchestrator   gray = cross-cutting   "
                "orange = external dependency   green = site substrate   teal = inventory / storage",
       size=12.5, color="#adb5bd", bold=False, anchor="middle")

# ---- actors / planes ----
tenant = s.box(60, 110, 150, 52, "Tenant", "portal user", "gray")
mp = s.zone(40, 185, 1010, 700, "Management Plane — GKE", "#1971c2")
portal = s.box(120, 240, 250, 58, "Portal / API", "Add-Cluster form · auth", "yellow")
netbox = s.box(770, 250, 250, 56, "NetBox", "Inventory SoT · DCIM/IPAM", "teal")

cps = s.zone(70, 315, 950, 555, "Compute Provisioning Service (CPS)", "#6741d9")

# central vertical flow
intake = s.box(150, 360, 260, 60, "Request Intake API", "validate · admit · quote", "blue")
orch   = s.box(150, 450, 260, 130, "Orchestrator", "workflow / saga engine\nlifecycle state machine", "violet")
cat    = s.box(150, 610, 260, 60, "Cluster Catalog", "state store / system of record", "blue")

# adapter stack
inv  = s.box(470, 360, 260, 64, "Inventory & Allocation", "atomic reserve · capacity", "blue")
net  = s.box(470, 440, 260, 64, "Network Orchestration", "VRF flip · reachability · probe", "blue")
prov = s.box(470, 520, 260, 64, "Provisioning Adapter", "Rafay: bare-metal + K8s", "blue")
stor = s.box(470, 600, 260, 64, "Storage Adapter", "Weka filesystem + CSI", "blue")

# cross-cutting
ident = s.box(150, 700, 250, 64, "Identity & Tenancy", "org → project → cluster · RBAC", "gray")
meter = s.box(420, 700, 230, 64, "Metering & Billing", "usage → invoices", "gray")
obs   = s.box(680, 700, 320, 64, "Observability & Audit", "logs · metrics · traces · audit", "gray")

# external dependencies
ext = s.zone(1070, 415, 360, 375, "External — SaaS / other teams", "#e8590c")
napi = s.box(1090, 440, 320, 64, "Networking Team API", "VRF lifecycle → Juniper Apstra", "orange")
rctl = s.box(1090, 520, 320, 64, "Rafay Controller", "SaaS · BM + K8s lifecycle", "orange")
wcp  = s.box(1090, 600, 320, 64, "Weka Control Plane", "filesystem / quota · org · access", "orange")
ztka = s.box(1090, 700, 320, 64, "Tenant API Access", "Rafay ZTKA — OPEN ITEM", "white", dashed=True)

# ---- site ----
site = s.zone(40, 930, 1390, 185, "Site — NJ", "#2f9e44")
gpu = s.box(90, 990, 240, 70, "GPU Servers — B300", "tenant workers + Weka NVMe", "green")
cpu = s.box(350, 990, 230, 70, "CPU Servers", "tenant ctrl planes + Weka", "green")
qfx = s.box(600, 990, 210, 70, "QFX Fabric", "backend RDMA + frontend", "green")
conn = s.box(840, 990, 200, 70, "Rafay Connector", "provisioning agent", "green")
apstra = s.box(1060, 990, 160, 70, "Juniper Apstra", "fabric controller", "green")
weka = s.box(1240, 990, 170, 70, "Weka Cluster", "disaggregated NVMe", "teal")

# VPN divider
s.line((40, 900), (1430, 900), dashed=True, color="#fa5252", width=2.5)
s.note(W/2, 922, "— VPN tunnel —   cloud above / site (NJ) below",
       size=13, color="#fa5252", bold=True, anchor="middle")
s.note(715, 1100, "(fabric & storage wiring detailed in the interface / VRF diagram)",
       size=12.5, color="#868e96", bold=False, anchor="middle")

# ---- edges ----
A = s.a
s.edge(A(tenant, "b"), A(portal, "t"), src=tenant.eid, dst=portal.eid)
s.edge(A(portal, "b"), A(intake, "t"), src=portal.eid, dst=intake.eid)
s.edge(A(intake, "b"), A(orch, "t"), src=intake.eid, dst=orch.eid)
s.edge(A(orch, "b"), A(cat, "t"), label="read/write", bidir=True, src=orch.eid, dst=cat.eid)

# orchestrator drives the adapters
for tgt in (inv, net, prov, stor):
    s.edge(A(orch, "r"), A(tgt, "l"), src=orch.eid, dst=tgt.eid)

# adapters -> their systems
s.edge(A(inv, "r"), A(netbox, "b"), label="reserve", src=inv.eid, dst=netbox.eid)
s.edge(A(net, "r"), A(napi, "l"), label="VRF ops", src=net.eid, dst=napi.eid)
s.edge(A(prov, "r"), A(rctl, "l"), label="provision", src=prov.eid, dst=rctl.eid)
s.edge(A(stor, "r"), A(wcp, "l"), label="fs + access", src=stor.eid, dst=wcp.eid)
s.edge(A(ztka, "t"), A(rctl, "b"), dashed=True, src=ztka.eid, dst=rctl.eid)

# external -> site (across VPN)
s.edge(A(napi, "b"), A(apstra, "t"), src=napi.eid, dst=apstra.eid)
s.edge(A(rctl, "b"), A(conn, "t"), src=rctl.eid, dst=conn.eid)
s.edge(A(wcp, "b"), A(weka, "t"), src=wcp.eid, dst=weka.eid)

base = os.path.join(OUT, "cps_system")
s.save_excalidraw(base + ".excalidraw")
s.save_svg(base + ".svg")
render(base + ".svg")
print("OK ->", OUT)
