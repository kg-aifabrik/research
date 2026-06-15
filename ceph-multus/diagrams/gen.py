#!/usr/bin/env python3
"""Generate Excalidraw-style diagrams (SVG + editable .excalidraw) for ceph-multus.

Pure-Python (this Mac has no node/npm). One scene definition emits both a
hand-drawn-look SVG (for embedding in the plan MD) and an .excalidraw scene
(open/edit at excalidraw.com). Run:  python3 gen.py
"""
import json, os, random, html

random.seed(42)
OUT = os.path.dirname(os.path.abspath(__file__))

PAL = {
    'ink':    ('#1e1e1e', '#1e1e1e'), 'blue': ('#a5d8ff', '#1971c2'),
    'green':  ('#b2f2bb', '#2f9e44'), 'red':  ('#ffc9c9', '#e03131'),
    'orange': ('#ffd8a8', '#e8590c'), 'violet': ('#d0bfff', '#6741d9'),
    'yellow': ('#ffec99', '#f08c00'), 'gray': ('#f1f3f5', '#868e96'),
    'teal':   ('#96f2d7', '#0ca678'), 'white': ('#ffffff', '#1e1e1e'),
}
FONT = "Virgil, 'Comic Sans MS', 'Chalkboard SE', 'Segoe Print', 'Bradley Hand', cursive"


def esc(s):
    return html.escape(str(s), quote=True)


class Scene:
    def __init__(self, w, h):
        self.w, self.h, self.shapes, self.texts, self.ex = w, h, [], [], []

    def _seed(self):
        return random.randint(1, 2**31)

    def _ex(self, t, x, y, w, h, stroke, bg, **kw):
        e = dict(id=f"el{len(self.ex)}", type=t, x=x, y=y, width=w, height=h, angle=0,
                 strokeColor=stroke, backgroundColor=bg, fillStyle="solid", strokeWidth=2,
                 strokeStyle="solid", roughness=1, opacity=100, groupIds=[], frameId=None,
                 roundness=({"type": 3} if t == "rectangle" else None), seed=self._seed(),
                 versionNonce=self._seed(), version=1, isDeleted=False, boundElements=None,
                 updated=1, link=None, locked=False)
        e.update(kw)
        self.ex.append(e)
        return e

    def box(self, x, y, w, h, lines, color='blue', dash=False, fill=None, tsize=17):
        f, s = PAL[color]
        fill = fill or f
        da = ' stroke-dasharray="8 5"' if dash else ''
        self.shapes.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="13" ry="13" '
                           f'fill="{fill}" stroke="{s}" stroke-width="2"{da}/>')
        self._ex("rectangle", x, y, w, h, s, fill, strokeStyle=("dashed" if dash else "solid"))
        if isinstance(lines, str):
            lines = [lines]
        sizes = [tsize if i == 0 else 13.5 for i in range(len(lines))]
        total = sum(sizes) + (len(lines) - 1) * 8
        cy = y + h / 2 - total / 2 + sizes[0]
        for i, ln in enumerate(lines):
            sz = sizes[i]
            wt = '700' if i == 0 else '400'
            col = '#1e1e1e' if i == 0 else '#343a40'
            self.texts.append(f'<text x="{x+w/2}" y="{cy:.1f}" font-size="{sz}" font-weight="{wt}" '
                              f'fill="{col}" text-anchor="middle">{esc(ln)}</text>')
            self._ex("text", x + 8, cy - sz, w - 16, sz + 4, col, "transparent", text=ln,
                     fontSize=sz, fontFamily=1, textAlign="center", verticalAlign="top",
                     baseline=int(sz), containerId=None, originalText=ln, lineHeight=1.25)
            cy += sz + 8

    def label(self, x, y, s, size=14, anchor='middle', color='#1e1e1e', weight='400'):
        self.texts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
                          f'fill="{color}" text-anchor="{anchor}">{esc(s)}</text>')
        self._ex("text", x, y - size, max(8, len(s) * size * 0.55), size + 4, color, "transparent",
                 text=s, fontSize=size, fontFamily=1, textAlign=anchor, verticalAlign="top",
                 baseline=int(size), containerId=None, originalText=s, lineHeight=1.25)

    def conn(self, x1, y1, x2, y2, color='#1e1e1e', dash=False, width=2, arrow=True):
        da = ' stroke-dasharray="8 5"' if dash else ''
        mk = ' marker-end="url(#ah)"' if arrow else ''
        self.shapes.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
                           f'stroke-width="{width}"{da}{mk}/>')
        self._ex("arrow" if arrow else "line", x1, y1, x2 - x1, y2 - y1, color, "transparent",
                 points=[[0, 0], [x2 - x1, y2 - y1]], lastCommittedPoint=None, startBinding=None,
                 endBinding=None, startArrowhead=None, endArrowhead=("arrow" if arrow else None),
                 strokeStyle=("dashed" if dash else "solid"))

    def badge(self, x, y, s, color='green'):
        f, st = PAL[color]
        w = 16 + len(s) * 7.2
        self.shapes.append(f'<rect x="{x}" y="{y}" width="{w:.0f}" height="26" rx="13" ry="13" '
                           f'fill="{f}" stroke="{st}" stroke-width="2"/>')
        self.texts.append(f'<text x="{x+w/2:.0f}" y="{y+17}" font-size="13" font-weight="700" '
                          f'fill="#1e1e1e" text-anchor="middle">{esc(s)}</text>')

    def svg(self, title):
        defs = ('<defs><filter id="rough"><feTurbulence type="fractalNoise" baseFrequency="0.012" '
                'numOctaves="2" seed="7" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" '
                'scale="1.6" xChannelSelector="R" yChannelSelector="G"/></filter>'
                '<marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
                'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
                'fill="#1e1e1e"/></marker></defs>')
        body = '<g filter="url(#rough)">' + "".join(self.shapes) + '</g>' + "".join(self.texts)
        return (f'<svg viewBox="0 0 {self.w} {self.h}" xmlns="http://www.w3.org/2000/svg" '
                f'font-family="{FONT}"><style>text{{font-family:{FONT}}}</style>{defs}'
                f'<rect width="{self.w}" height="{self.h}" fill="#ffffff"/>'
                f'<text x="{self.w/2}" y="32" font-size="21" font-weight="700" fill="#1e1e1e" '
                f'text-anchor="middle">{esc(title)}</text>{body}</svg>')

    def excalidraw(self):
        return json.dumps({"type": "excalidraw", "version": 2, "source": "ceph-multus/gen.py",
                           "elements": self.ex,
                           "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
                           "files": {}}, indent=1)


def save(name, sc, title):
    open(os.path.join(OUT, name + '.svg'), 'w').write(sc.svg(title))
    open(os.path.join(OUT, name + '.excalidraw'), 'w').write(sc.excalidraw())
    print("wrote", name + '.svg', '+', name + '.excalidraw')


# ---------- 01: host & cluster topology ----------
def s01():
    sc = Scene(1060, 600)
    sc.box(24, 50, 1012, 520, [""], 'gray', fill='#f8f9fa')
    sc.label(44, 78, "MacBook Pro — Apple M4 Pro · 24 GB · arm64 · QEMU 11 / HVF", 15, 'start', '#495057', '700')
    sc.badge(770, 60, "L2 + 802.1Q verified on this Mac")
    for i, x in enumerate((60, 390, 720)):
        sc.box(x, 110, 280, 120, [f"cmnode{i+1}  (VM, 6 GB)",
                                   "kubeadm · Cilium · Multus",
                                   "Rook-Ceph mon/mgr/OSD/RGW"], 'blue')
        sc.conn(x + 140, 230, 530, 330, '#495057')
    sc.box(330, 330, 400, 56, ["cm_hub.py — userspace L2 switch (loopback)"], 'violet')
    sc.label(530, 312, "data0 trunk  →  VLAN 2031 / 2032 / 2033", 13.5, 'middle', '#6741d9', '700')
    sc.box(60, 430, 940, 120, [""], 'white')
    sc.label(80, 458, "VLANs on the trunk (mirrors Suiri lab):", 14, 'start', '#1e1e1e', '700')
    rows = [("VLAN 2031  (native / untagged)", "In-band mgmt · Cilium primary CNI", "10.6.31.0/24", 'blue'),
            ("VLAN 2032  (802.1Q tagged)", "Storage · Ceph + pod macvlan", "10.6.32.0/24", 'teal'),
            ("VLAN 2033  (802.1Q tagged)", "North-South · pod macvlan", "10.6.33.0/24", 'orange')]
    for j, (a, b, c, col) in enumerate(rows):
        yy = 482 + j * 22
        f, st = PAL[col]
        sc.shapes.append(f'<rect x="84" y="{yy-12}" width="16" height="16" rx="4" fill="{f}" stroke="{st}" stroke-width="2"/>')
        sc.label(112, yy, a, 13.5, 'start', '#1e1e1e', '700')
        sc.label(380, yy, b, 13.5, 'start', '#343a40')
        sc.label(880, yy, c, 13.5, 'start', '#343a40', '700')
    return sc


# ---------- 02: per-node interface / VLAN model ----------
def s02():
    sc = Scene(1060, 560)
    sc.box(40, 60, 600, 470, [""], 'gray', fill='#f8f9fa')
    sc.label(60, 88, "Linux guest (cmnodeN)", 15, 'start', '#495057', '700')
    sc.box(150, 430, 380, 64, ["data0  (virtio NIC → cm_hub trunk)"], 'gray', fill='#dee2e6')
    subs = [("data0  (untagged)  =  VLAN 2031", "Cilium primary · 10.6.31.N/24", 'blue', False),
            ("vlan2032@data0  (802.1Q)  =  VLAN 2032", "Storage / Ceph · 10.6.32.N/24", 'teal', True),
            ("vlan2033@data0  (802.1Q)  =  VLAN 2033", "North-South · 10.6.33.N/24", 'orange', True)]
    for k, (a, b, col, dash) in enumerate(subs):
        yy = 120 + k * 96
        sc.box(110, yy, 460, 70, [a, b], col, dash=dash)
        sc.conn(340, yy + 70, 340, 430, PAL[col][1], dash=dash)
    sc.conn(530, 462, 650, 462, '#495057')
    sc.label(840, 452, "cm_hub.py  → other nodes", 14, 'middle', '#6741d9', '700')
    sc.label(840, 474, "(tagged frames pass verbatim)", 12.5, 'middle', '#868e96')
    # tcpdump proof callout
    sc.box(670, 110, 350, 150, [""], 'yellow', fill='#fff9db')
    sc.label(690, 138, "✓ Captured on the wire (node2 ⇄ node3):", 13.5, 'start', '#1e1e1e', '700')
    for m, ln in enumerate(["da:03 > da:02  802.1Q  vlan 2032",
                            "  IPv4 10.6.32.3 > 10.6.32.2  ICMP echo",
                            "da:02 > da:03  802.1Q  vlan 2032",
                            "  IPv4 10.6.32.2 > 10.6.32.3  echo reply"]):
        sc.texts.append(f'<text x="690" y="{166+m*20}" font-size="12.5" fill="#343a40" '
                        f'font-family="ui-monospace,monospace" text-anchor="start">{esc(ln)}</text>')
    return sc


# ---------- 03: pod with 3 interfaces ----------
def s03():
    sc = Scene(1060, 560)
    sc.box(380, 90, 300, 150, ["Application pod", "(each app pod gets 3 NICs)"], 'white')
    sc.label(530, 220, "annotation: k8s.v1.cni.cncf.io/networks", 12.5, 'middle', '#868e96')
    # interfaces
    ifs = [("eth0", "Cilium primary CNI", "VLAN 2031 · 10.6.31.x", 'blue', 200, "API / ClusterIP / pod-to-pod"),
           ("net1", "Multus macvlan", "VLAN 2033 · north-south", 'orange', 530, "external / ingress"),
           ("net2", "Multus macvlan", "VLAN 2032 · storage", 'teal', 860, "S3 to Ceph RGW")]
    for nm, a, b, col, cx, note in ifs:
        sc.box(cx - 130, 360, 260, 90, [f"{nm}  →  {a}", b], col)
        sc.conn(cx if cx == 530 else (430 if cx == 200 else 630), 240, cx, 360, PAL[col][1])
        sc.label(cx, 472, note, 12.5, 'middle', '#495057')
    sc.box(700, 250, 320, 70, ["NADs: north-south-net · storage-net", "(macvlan over vlanXXXX · Whereabouts IPAM)"], 'violet')
    sc.badge(40, 60, "primary + 2 secondary")
    return sc


# ---------- 04: Ceph data paths (block vs object) ----------
def s04():
    sc = Scene(1060, 600)
    # storage VLAN band
    sc.box(40, 300, 980, 64, ["Storage VLAN 2032   ·   10.6.32.0/24   ·   all Ceph traffic rides here"], 'teal', fill='#c3fae8')
    sc.box(360, 70, 340, 90, ["Application pod", "RBD PVC mounted at /mnt/block"], 'white')
    sc.box(360, 470, 340, 90, ["Rook-Ceph (host-networked)", "public_network = 10.6.32.0/24", "mon · OSD · RGW (S3)"], 'green')
    # Path A: block / RBD (left), via host kernel
    sc.box(70, 180, 250, 80, ["Host kernel RBD client", "(ceph-csi maps the image)"], 'red')
    sc.conn(420, 160, 200, 180, '#e03131')
    sc.label(250, 150, "filesystem I/O", 12.5, 'middle', '#e03131', '700')
    sc.label(250, 168, "(pod opens NO socket)", 11.5, 'middle', '#868e96')
    sc.conn(195, 260, 410, 470, '#e03131')
    sc.label(120, 350, "BLOCK / RBD", 14, 'middle', '#e03131', '700')
    sc.label(120, 372, "host carries it on *.2032", 12, 'middle', '#495057')
    # Path B: object / S3 (right), via pod macvlan
    sc.box(740, 180, 250, 80, ["pod net2 (macvlan)", "S3 → RGW @ 10.6.32.y"], 'teal')
    sc.conn(640, 160, 865, 180, '#0ca678')
    sc.label(840, 150, "S3 / HTTP", 12.5, 'middle', '#0ca678', '700')
    sc.conn(865, 260, 660, 470, '#0ca678')
    sc.label(930, 350, "OBJECT / S3", 14, 'middle', '#0ca678', '700')
    sc.label(930, 372, "pod carries it on *.2032", 12, 'middle', '#495057')
    sc.label(530, 590, "Both paths land on VLAN 2032 — block via the host netns, object via the pod netns.", 13.5, 'middle', '#343a40', '700')
    return sc


# ---------- 05: demo workflow ----------
def s05():
    sc = Scene(1060, 470)
    steps = [("1 · Seed", ["Job downloads ~1 GB", "(food101 parquet)", "→ explode to objects", "→ upload to RGW bucket"], 'orange'),
             ("2 · Block", ["App pod requests", "RBD PVC (CephBlockPool)", "→ mounted /mnt/block"], 'blue'),
             ("3 · Model", ["Download", "Qwen2.5-0.5B-Instruct", "→ store on /mnt/block"], 'violet'),
             ("4 · Object", ["S3 over storage VLAN:", "download seeded objects", "+ upload new objects"], 'teal')]
    x = 40
    for i, (t, lines, col) in enumerate(steps):
        sc.box(x, 120, 220, 200, [t] + lines, col)
        if i < 3:
            sc.conn(x + 220, 220, x + 250, 220, '#495057')
        x += 250
    sc.label(530, 360, "Block (RBD) → host kernel on *.2032   ·   Object (S3 → RGW) → pod macvlan on *.2032", 13.5, 'middle', '#343a40', '700')
    sc.badge(40, 70, "end-to-end demo")
    return sc


save("01-architecture", s01(), "ceph-multus — local cluster on one MacBook Pro")
save("02-network-model", s02(), "Per-node interface & VLAN model (verified)")
save("03-pod-interfaces", s03(), "Every app pod: 1 Cilium primary + 2 Multus macvlan")
save("04-ceph-datapaths", s04(), "How a pod reaches Ceph — block vs object")
save("05-demo-flow", s05(), "End-to-end demo workflow")
print("done")
