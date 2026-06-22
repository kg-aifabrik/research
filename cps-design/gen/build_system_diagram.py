"""
Build the CPS system-level component diagram.

Run:  python3 gen/build_system_diagram.py
Emits to ../diagrams/: cps_system.excalidraw (editable), .svg, .png

Layout note: the three external->site connectors use orthogonal routing
(exit right -> drop down a dedicated lane in the right margin -> step in to the
target) so they never fan across each other or the boxes. Topmost source takes
the farthest lane so the exit segments don't cross.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excalidraw_gen import Scene
from render import render

GEN = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(GEN, "..", "diagrams"))
os.makedirs(OUT, exist_ok=True)

W, H = 1560, 1180
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
site = s.zone(40, 930, 1500, 200, "Site — NJ", "#2f9e44")
gpu = s.box(90, 995, 240, 72, "GPU Servers — B300", "tenant workers + Weka NVMe", "green")
cpu = s.box(350, 995, 220, 72, "CPU Servers", "tenant ctrl planes + Weka", "green")
qfx = s.box(590, 995, 190, 72, "QFX Fabric", "backend RDMA + frontend", "green")
conn = s.box(840, 995, 190, 72, "Rafay Connector", "provisioning agent", "green")
apstra = s.box(1050, 995, 170, 72, "Juniper Apstra", "fabric controller", "green")
weka = s.box(1245, 995, 180, 72, "Weka Cluster", "disaggregated NVMe", "teal")

# VPN divider
s.line((40, 905), (1540, 905), dashed=True, color="#fa5252", width=2.5)
s.note(W/2, 925, "— VPN tunnel —   cloud above / site (NJ) below",
       size=13, color="#fa5252", bold=True, anchor="middle")
s.note(W/2, 1118, "(fabric & storage wiring detailed in the interface / VRF diagram)",
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

# adapters -> their systems (clean horizontals)
s.edge(A(inv, "r"), A(netbox, "b"), label="reserve", src=inv.eid, dst=netbox.eid)
s.edge(A(net, "r"), A(napi, "l"), label="VRF ops", src=net.eid, dst=napi.eid)
s.edge(A(prov, "r"), A(rctl, "l"), label="provision", src=prov.eid, dst=rctl.eid)
s.edge(A(stor, "r"), A(wcp, "l"), label="fs + access", src=stor.eid, dst=wcp.eid)

# external API -> its site agent (across VPN), orthogonal: right -> lane -> in.
# Topmost source uses the farthest lane; horizontals stagger highest=leftmost target.
s.route([(1410, 472), (1520, 472), (1520, 940), (1135, 940), (1135, 995)])  # Networking API -> Apstra
s.route([(1410, 552), (1490, 552), (1490, 912), (935, 912), (935, 995)])    # Rafay Controller -> Connector
s.route([(1410, 632), (1455, 632), (1455, 968), (1335, 968), (1335, 995)])  # Weka CP -> Weka cluster

base = os.path.join(OUT, "cps_system")
s.save_excalidraw(base + ".excalidraw")
s.save_svg(base + ".svg")
render(base + ".svg")
print("OK ->", OUT)
