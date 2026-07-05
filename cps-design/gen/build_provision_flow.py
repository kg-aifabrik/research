"""
Build the CPS K8s cluster-provisioning workflow diagram — a sequence-style
Excalidraw scene of the Temporal saga.

Run:  python3 gen/build_provision_flow.py
Emits to ../diagrams/: cps_provision_flow.{excalidraw,svg,png}

Layout: eight lifelines (participants) across the top; messages step down the
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

W, H = 1960, 1460
s = Scene(W, H, "CPS — K8s Cluster Provisioning Workflow")
s.note(W/2, 64,
       "async · Frontend Platform polls the Operation   ·   orange = per-step compensation (rollback)   ·   "
       "on failure: pause → human review → resume or cancel + rollback  (transitional)",
       size=13, color="#868e96", bold=False, anchor="middle")

# ---- participants (lifelines) ----
LL_TOP, LL_BOT = 140, 1370
parts: dict[str, float] = {}

def participant(key, x, title, sub, fill):
    s.box(x - 100, 84, 200, 54, title, sub, fill)
    s.line((x, LL_TOP), (x, LL_BOT), dashed=True, color="#ced4da", width=1.8)
    parts[key] = x

participant("tms", 120,  "Frontend Platform", "caller", "gray")
participant("cps", 370,  "CPS", "Temporal orchestrator", "violet")
participant("his", 610,  "HW Inventory Svc", "NetBox dcim wrapper", "teal")
participant("nps", 850,  "NPS", "NetBox ipam + Apstra", "blue")
participant("nb",  1080, "NetBox", "inventory SoR", "teal")
participant("ap",  1300, "Apstra", "fabric controller", "green")
participant("rc",  1530, "Rafay Controller", "OS + K8s · REST", "orange")
participant("rh",  1770, "Rafay Head", "site agent", "orange")

PRIMARY, SECONDARY, COMP = "#495057", "#adb5bd", "#e8590c"

def msg(src, dst, y, label, dashed=False, secondary=False):
    s.edge((parts[src], y), (parts[dst], y), label=label, dashed=dashed,
           color=SECONDARY if secondary else PRIMARY)

def comp(src, y, text):
    s.note(parts[src] + 14, y + 16, "compensate: " + text, size=11.5,
           color=COMP, bold=True)

def note_over(key, y, title, sub="", w=250):
    s.box(parts[key] - w / 2, y, w, 46 if sub else 32, title, sub, fill="yellow")

# ---- messages (top -> bottom) ----
y = 178
msg("tms", "cps", y,      "1   ProvisionCluster(idem_key, tenant, spec)")
msg("cps", "tms", y + 42, "operation handle (async)", dashed=True, secondary=True)

msg("cps", "nps", y + 84, "2   tenant onboarding (async): tenant + VRFs (fe/be) + segments + IRB")
comp("cps", y + 84, "offboard tenant / delete VRFs")
msg("nps", "nb",  y + 126, "create tenant · VRFs · VLANs + IPAM", secondary=True)
msg("nps", "ap",  y + 168, "configure fabric VRF", secondary=True)

note_over("cps", y + 200, "poll until onboarded",
          "block until success — gates all later steps", w=380)

note_over("cps", y + 288, "3   acquire reservation lock", "auto-expiry · wait if held", w=280)

msg("cps", "his", y + 376, "4   list available servers (free pool)")
msg("his", "nb",  y + 418, "query dcim: role=compute · tenant=null", secondary=True)

note_over("cps", y + 450, "5   schedule / select subset",
          "GPU match · RDMA locality · CP anti-affinity", w=380)

msg("cps", "his", y + 538, "6   reserve nodes for tenant")
comp("cps", y + 538, "release")
msg("his", "nb",  y + 580, "write allocation — set tenant", secondary=True)

note_over("cps", y + 612, "7   release reservation lock", w=260)

msg("cps", "his", y + 686, "8   fetch per-server hardware facts")
msg("his", "nb",  y + 728, "dcim: BMC/IPMI IP + creds · bootstrap + RDMA/data MACs · switch ports",
    secondary=True)

msg("cps", "nps", y + 770, "9   fetch scope network config")
msg("nps", "nb",  y + 812, "ipam: VRF · VLANs · IP ranges · MTU", secondary=True)

msg("cps", "nps", y + 854, "10   attach node ports to tenant VLANs")
msg("nps", "ap",  y + 896, "configure leaf data ports", secondary=True)

note_over("cps", y + 928, "11   preflight check",
          "health · reachability on reserved nodes", w=340)

msg("cps", "rc", y + 1016, "12   provision OS on nodes — BMC + bootstrap MAC from HIS")
comp("cps", y + 1016, "wipe / decommission")
msg("rc",  "rh", y + 1058, "IPMI power + PXE over OOB VLAN", secondary=True)

msg("cps", "rc", y + 1100, "13   build K8s cluster (CP + workers)")
comp("cps", y + 1100, "delete cluster")

msg("cps", "rc", y + 1142, "14   deploy AiFabrik addon (mgmt / monitoring)")

msg("cps", "tms", y + 1186, "SUCCEEDED  ·  Frontend Platform records mapping",
    dashed=True)

s.note(W / 2, 1420,
       "Storage (Weka), kubeconfig and client connectivity are still to be built — "
       "see 'To be included'.",
       size=12.5, color="#868e96", bold=False, anchor="middle")

base = os.path.join(OUT, "cps_provision_flow")
s.save_excalidraw(base + ".excalidraw")
s.save_svg(base + ".svg")
render(base + ".svg")
print("OK ->", OUT)
