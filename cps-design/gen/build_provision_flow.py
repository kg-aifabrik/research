"""
Build the CPS K8s cluster-provisioning workflow diagram — a sequence-style
Excalidraw scene of the Temporal saga.

Run:  python3 gen/build_provision_flow.py
Emits to ../diagrams/: cps_provision_flow.{excalidraw,svg,png}

Layout: seven lifelines (participants) across the top; messages step down the
canvas. CPS-internal steps render as yellow notes on the CPS lifeline. Secondary
(fan-out) calls are drawn lighter. Compensating actions are orange annotations
under the forward arrow nearest the orchestrator (they run in reverse on cancel).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excalidraw_gen import Scene
from render import render

GEN = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(GEN, "..", "diagrams"))
os.makedirs(OUT, exist_ok=True)

W, H = 1560, 1000
s = Scene(W, H, "CPS — K8s Cluster Provisioning Workflow")
s.note(W/2, 62,
       "async · Frontend Platform polls the Operation   ·   teardown counterpart of each step in orange   ·   "
       "on failure: workflow fails cleanly → retry or DeleteCluster",
       size=13, color="#868e96", bold=False, anchor="middle")

# ---- participants (lifelines) ----
LL_TOP, LL_BOT = 130, 925
parts: dict[str, float] = {}

def participant(key, x, title, sub, fill):
    s.box(x - 85, 78, 170, 52, title, sub, fill)
    s.line((x, LL_TOP), (x, LL_BOT), dashed=True, color="#ced4da", width=1.8)
    parts[key] = x

participant("tms", 110,  "Frontend Platform", "caller", "gray")
participant("cps", 360,  "CPS", "Temporal orchestrator", "violet")
participant("nps", 590,  "NPS", "NetBox + Apstra", "blue")
participant("nb",  800,  "NetBox", "inventory SoR", "teal")
participant("ap",  1000, "Apstra", "fabric controller", "green")
participant("rc",  1210, "Rafay Controller", "OS + K8s · REST", "orange")
participant("rh",  1430, "Rafay Head", "site agent", "orange")

PRIMARY, SECONDARY, COMP = "#495057", "#adb5bd", "#e8590c"

def msg(src, dst, y, label, dashed=False, secondary=False):
    s.edge((parts[src], y), (parts[dst], y), label=label, dashed=dashed,
           color=SECONDARY if secondary else PRIMARY)

def comp(src, y, text):
    s.note(parts[src] + 14, y + 15, "compensate: " + text, size=11.5,
           color=COMP, bold=True)

def note_over(key, y, title, sub="", w=250):
    s.box(parts[key] - w / 2, y, w, 46 if sub else 32, title, sub, fill="yellow")

# ---- messages (top -> bottom) ----
y = 168
msg("tms", "cps", y,      "1   ProvisionCluster(idem_key, tenant, spec)")
msg("cps", "tms", y + 38, "operation handle (async)", dashed=True, secondary=True)

note_over("cps", y + 66,  "2   acquire reservation lock", "auto-expiry · wait if held", w=262)

msg("cps", "nps", y + 150, "3   list available servers")
msg("nps", "nb",  y + 188, "query inventory", secondary=True)

note_over("cps", y + 216, "4   schedule / select subset",
          "GPU match · RDMA locality · CP anti-affinity", w=362)

msg("cps", "nps", y + 300, "5   reserve nodes for tenant")
comp("cps", y + 300, "release")
msg("nps", "nb",  y + 338, "write allocation fields", secondary=True)

note_over("cps", y + 366, "6   release reservation lock", w=244)

msg("cps", "nps", y + 436, "7   create tenant VRF / VLAN + IPAM")
comp("cps", y + 436, "delete VRF / VLAN")
msg("nps", "ap",  y + 474, "configure fabric + leaf data ports", secondary=True)

note_over("cps", y + 502, "8   preflight check",
          "health · reachability on reserved nodes", w=322)

msg("cps", "rc", y + 586, "9   provision OS on nodes")
comp("cps", y + 586, "wipe / decommission")
msg("rc",  "rh", y + 624, "IPMI power + PXE over OOB VLAN", secondary=True)

msg("cps", "rc", y + 664, "10   build K8s cluster (CP + workers)")
comp("cps", y + 664, "delete cluster")

msg("cps", "rc", y + 702, "11   deploy AiFabrik addon (mgmt / monitoring)")

msg("cps", "tms", y + 744, "SUCCEEDED  ·  Frontend Platform records mapping",
    dashed=True)

s.note(W / 2, 970,
       "Storage (Weka), kubeconfig and client connectivity are still to be built — "
       "see 'To be included'.",
       size=12.5, color="#868e96", bold=False, anchor="middle")

base = os.path.join(OUT, "cps_provision_flow")
s.save_excalidraw(base + ".excalidraw")
s.save_svg(base + ".svg")
render(base + ".svg")
print("OK ->", OUT)
