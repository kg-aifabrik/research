"""
excalidraw_gen.py — reusable diagram generator for the CPS design session.

Purpose
-------
One scene description -> two artifacts:
  * a valid `.excalidraw` JSON file (editable at excalidraw.com / VS Code ext)
  * a standalone `.svg` (rendered to PNG separately via headless Chrome)

Why hand-rolled: this machine has no Node toolchain, so the official Excalidraw
renderer is unavailable. We author the scene once and emit both formats so the
hand-drawn editable master and the shareable raster stay in sync.

Scene model is deliberately tiny: containers (titled zones), boxes (titled nodes
with optional subtitle), and edges (arrows, optionally dashed/labelled). Layout
is explicit (caller supplies coordinates) — architecture diagrams need deliberate
placement, not auto-layout.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Optional

# Excalidraw signature palette (stroke is near-black; fills are the soft tints).
INK = "#1e1e1e"
PALETTE = {
    "blue":   "#a5d8ff",
    "violet": "#d0bfff",
    "green":  "#b2f2bb",
    "yellow": "#ffec99",
    "red":    "#ffc9c9",
    "orange": "#ffd8a8",
    "gray":   "#e9ecef",
    "white":  "#ffffff",
    "teal":   "#96f2d7",
}
ZONE_FILL = "#f8f9fa"
FONT = "'Excalifont','Virgil','Chalkboard SE','Comic Sans MS','Comic Neue',sans-serif"

_seed = 1000
def _next_seed() -> int:
    global _seed
    _seed += 7
    return _seed

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class El:
    x: float; y: float; w: float; h: float
    title: str = ""
    sub: str = ""
    fill: str = "white"          # palette key
    stroke: str = INK
    kind: str = "box"            # box | zone
    dashed: bool = False
    title_color: str = INK
    eid: str = ""
    text_id: str = ""

@dataclass
class Edge:
    x1: float; y1: float; x2: float; y2: float
    label: str = ""
    dashed: bool = False
    color: str = "#495057"
    bidir: bool = False
    src: str = ""
    dst: str = ""

@dataclass
class Free:           # free-floating text (titles, notes)
    x: float; y: float; text: str; size: int = 16; color: str = INK
    bold: bool = True; anchor: str = "start"

@dataclass
class Line:           # plain connector / divider (no arrowheads)
    x1: float; y1: float; x2: float; y2: float
    dashed: bool = True; color: str = "#adb5bd"; width: float = 2.0

@dataclass
class Route:          # multi-segment (orthogonal) connector through waypoints
    points: list      # [(x, y), ...]
    dashed: bool = False; color: str = "#495057"; arrow: bool = True
    width: float = 2.2


class Scene:
    def __init__(self, width: int, height: int, title: str = ""):
        self.width = width; self.height = height
        self.els: list[El] = []
        self.edges: list[Edge] = []
        self.frees: list[Free] = []
        self.lines: list[Line] = []
        self.routes: list[Route] = []
        self._n = 0
        if title:
            self.frees.append(Free(width / 2, 38, title, size=26, color=INK,
                                   bold=True, anchor="middle"))

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"

    def zone(self, x, y, w, h, title, color=INK) -> El:
        e = El(x, y, w, h, title=title, kind="zone", title_color=color,
               eid=self._id("zone"))
        self.els.append(e); return e

    def box(self, x, y, w, h, title, sub="", fill="white", dashed=False) -> El:
        e = El(x, y, w, h, title=title, sub=sub, fill=fill, dashed=dashed,
               eid=self._id("box"), text_id=self._id("txt"))
        self.els.append(e); return e

    def edge(self, p1, p2, label="", dashed=False, color="#495057",
             bidir=False, src="", dst="") -> Edge:
        ed = Edge(p1[0], p1[1], p2[0], p2[1], label=label, dashed=dashed,
                  color=color, bidir=bidir, src=src, dst=dst)
        self.edges.append(ed); return ed

    def note(self, x, y, text, size=14, color="#868e96", bold=False, anchor="start"):
        self.frees.append(Free(x, y, text, size=size, color=color, bold=bold,
                               anchor=anchor))

    def line(self, p1, p2, dashed=True, color="#adb5bd", width=2.0) -> Line:
        ln = Line(p1[0], p1[1], p2[0], p2[1], dashed=dashed, color=color, width=width)
        self.lines.append(ln); return ln

    def route(self, points, dashed=False, color="#495057", arrow=True, width=2.2) -> Route:
        """Orthogonal/multi-segment connector. `points` is a list of (x, y)
        waypoints; arrowhead (if any) sits on the final segment."""
        r = Route(points=[(float(x), float(y)) for x, y in points],
                  dashed=dashed, color=color, arrow=arrow, width=width)
        self.routes.append(r); return r

    # ---- anchor helpers (edge endpoints on a box border) -------------------
    @staticmethod
    def a(e: El, side: str) -> tuple[float, float]:
        cx, cy = e.x + e.w / 2, e.y + e.h / 2
        return {
            "t": (cx, e.y), "b": (cx, e.y + e.h),
            "l": (e.x, cy), "r": (e.x + e.w, cy),
            "c": (cx, cy),
            "tl": (e.x, e.y), "tr": (e.x + e.w, e.y),
            "bl": (e.x, e.y + e.h), "br": (e.x + e.w, e.y + e.h),
        }[side]

    # ======================= EXCALIDRAW EMITTER =============================
    def _common(self, eid, x, y, w, h, stroke, bg, fillstyle="solid",
                strokestyle="solid", roundness=True):
        return {
            "id": eid, "type": "", "x": x, "y": y, "width": w, "height": h,
            "angle": 0, "strokeColor": stroke, "backgroundColor": bg,
            "fillStyle": fillstyle, "strokeWidth": 2, "strokeStyle": strokestyle,
            "roughness": 1, "opacity": 100, "groupIds": [], "frameId": None,
            "roundness": {"type": 3} if roundness else None,
            "seed": _next_seed(), "version": 1, "versionNonce": _next_seed(),
            "isDeleted": False, "boundElements": [], "updated": 1,
            "link": None, "locked": False,
        }

    def _text_el(self, tid, container_id, text, x, y, w, h, size=16,
                 align="center", color=INK, auto=True):
        # auto=False lets Excalidraw wrap/center the text inside its container
        return {
            **self._common(tid, x, y, w, h, color, "transparent", roundness=False),
            "type": "text", "text": text, "rawText": text, "originalText": text,
            "fontSize": size, "fontFamily": 1, "textAlign": align,
            "verticalAlign": "middle", "containerId": container_id,
            "lineHeight": 1.25, "baseline": int(size * 0.9),
            "autoResize": auto,
        }

    def to_excalidraw(self) -> dict:
        # Paint order mirrors the SVG emitter: zones -> lines -> boxes ->
        # edges (+label pills) -> routes -> free text, so boxes cover the
        # lifelines/dividers running beneath them.
        elements = []
        for e in [z for z in self.els if z.kind == "zone"]:
            rect = self._common(e.eid, e.x, e.y, e.w, e.h, "#adb5bd", ZONE_FILL,
                                 strokestyle="dashed" if e.dashed else "solid")
            rect["type"] = "rectangle"
            rect["boundElements"] = []
            elements.append(rect)
            # zone title sits top-left as a separate text, not bound/centered
            t = self._text_el(e.text_id or self._id("txt"), None, e.title,
                              e.x + 16, e.y + 10, max(40, len(e.title) * 11),
                              26, align="left", color=e.title_color)
            t["containerId"] = None
            elements.append(t)
        for ln in self.lines:
            dx, dy = ln.x2 - ln.x1, ln.y2 - ln.y1
            le = self._common(self._id("line"), ln.x1, ln.y1, abs(dx), abs(dy),
                              ln.color, "transparent",
                              strokestyle="dashed" if ln.dashed else "solid",
                              roundness=False)
            le["type"] = "line"
            le["points"] = [[0, 0], [dx, dy]]
            le["startArrowhead"] = None
            le["endArrowhead"] = None
            elements.append(le)
        for e in [b for b in self.els if b.kind == "box"]:
            rect = self._common(e.eid, e.x, e.y, e.w, e.h, e.stroke,
                                 PALETTE.get(e.fill, e.fill),
                                 strokestyle="dashed" if e.dashed else "solid")
            rect["type"] = "rectangle"
            label = e.title + (("\n" + e.sub) if e.sub else "")
            rect["boundElements"] = [{"type": "text", "id": e.text_id}]
            elements.append(rect)
            t = self._text_el(e.text_id, e.eid, label, e.x + 10, e.y + 6,
                              e.w - 20, e.h - 12, size=14, auto=False)
            elements.append(t)
        for ed in self.edges:
            dx, dy = ed.x2 - ed.x1, ed.y2 - ed.y1
            aid = self._id("arr")
            arr = self._common(aid, ed.x1, ed.y1, abs(dx), abs(dy),
                               ed.color, "transparent",
                               strokestyle="dashed" if ed.dashed else "solid",
                               roundness=False)
            arr["type"] = "arrow"
            arr["points"] = [[0, 0], [dx, dy]]
            arr["startArrowhead"] = "arrow" if ed.bidir else None
            arr["endArrowhead"] = "arrow"
            arr["roundness"] = {"type": 2}
            if ed.src:
                arr["startBinding"] = {"elementId": ed.src, "focus": 0, "gap": 6}
            if ed.dst:
                arr["endBinding"] = {"elementId": ed.dst, "focus": 0, "gap": 6}
            elements.append(arr)
            if ed.label:
                # SVG-style pill: white rounded rect + text riding above the line,
                # so the arrow itself stays fully visible underneath
                mx, my = (ed.x1 + ed.x2) / 2, (ed.y1 + ed.y2) / 2
                lw = len(ed.label) * 8.0 + 16
                rid = self._id("lbox"); tid = self._id("elab")
                rect = self._common(rid, mx - lw / 2, my - 28, lw, 22,
                                    "#dee2e6", "#ffffff")
                rect["type"] = "rectangle"
                rect["strokeWidth"] = 1
                rect["boundElements"] = [{"type": "text", "id": tid}]
                elements.append(rect)
                t = self._text_el(tid, rid, ed.label, mx - lw / 2 + 5, my - 26,
                                  lw - 10, 18, size=12.5, color="#495057",
                                  auto=False)
                elements.append(t)
        for r in self.routes:
            xs = [p[0] for p in r.points]; ys = [p[1] for p in r.points]
            x0, y0 = r.points[0]
            re = self._common(self._id("route"), min(xs), min(ys),
                              max(xs) - min(xs), max(ys) - min(ys),
                              r.color, "transparent",
                              strokestyle="dashed" if r.dashed else "solid",
                              roundness=False)
            re["type"] = "arrow"
            re["x"] = x0; re["y"] = y0
            re["points"] = [[p[0] - x0, p[1] - y0] for p in r.points]
            re["startArrowhead"] = None
            re["endArrowhead"] = "arrow" if r.arrow else None
            re["roundness"] = None
            elements.append(re)
        for f in self.frees:
            tid = self._id("free")
            # SVG semantics: f.x is the anchor point, f.y the baseline. Excalidraw
            # wants top-left, so shift by estimated width/ascent.
            est_w = len(f.text) * f.size * 0.6
            fx = f.x - est_w / 2 if f.anchor == "middle" else f.x
            fy = f.y - f.size * 1.15
            t = self._text_el(tid, None, f.text, fx, fy, est_w,
                              f.size * 1.4, size=f.size, color=f.color,
                              align=("center" if f.anchor == "middle" else "left"))
            t["containerId"] = None
            elements.append(t)
        return {
            "type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
            "elements": elements,
            "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
            "files": {},
        }

    def save_excalidraw(self, path: str):
        with open(path, "w") as fh:
            json.dump(self.to_excalidraw(), fh, indent=2)

    # ============================ SVG EMITTER ===============================
    def _wrap_lines(self, text: str) -> list[str]:
        return text.split("\n")

    def to_svg(self) -> str:
        out = []
        out.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
            f'font-family="{_esc(FONT)}">')
        out.append('<defs>'
                   '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
                   'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                   '<path d="M0,0 L10,5 L0,10 L3,5 z" fill="#495057"/></marker>'
                   '<marker id="arrowS" viewBox="0 0 10 10" refX="1" refY="5" '
                   'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                   '<path d="M10,0 L0,5 L10,10 L7,5 z" fill="#495057"/></marker>'
                   '</defs>')
        out.append(f'<rect x="0" y="0" width="{self.width}" height="{self.height}" fill="#ffffff"/>')

        # zones first (behind), then boxes, then edges, then free text
        for e in [z for z in self.els if z.kind == "zone"]:
            out.append(
                f'<rect x="{e.x}" y="{e.y}" width="{e.w}" height="{e.h}" rx="14" '
                f'fill="{ZONE_FILL}" stroke="#adb5bd" stroke-width="1.5" '
                f'stroke-dasharray="{"8 6" if e.dashed else "none"}"/>')
            out.append(
                f'<text x="{e.x + 18}" y="{e.y + 30}" font-size="22" font-weight="700" '
                f'fill="{e.title_color}">{_esc(e.title)}</text>')

        for ln in self.lines:
            dash = 'stroke-dasharray="9 7" ' if ln.dashed else ""
            out.append(
                f'<line x1="{ln.x1}" y1="{ln.y1}" x2="{ln.x2}" y2="{ln.y2}" '
                f'stroke="{ln.color}" stroke-width="{ln.width}" {dash}stroke-linecap="round"/>')

        for e in [b for b in self.els if b.kind == "box"]:
            fill = PALETTE.get(e.fill, e.fill)
            out.append(
                f'<rect x="{e.x}" y="{e.y}" width="{e.w}" height="{e.h}" rx="10" '
                f'fill="{fill}" stroke="{e.stroke}" stroke-width="2" '
                f'stroke-dasharray="{"7 5" if e.dashed else "none"}"/>')
            lines = []
            for ln in self._wrap_lines(e.title):
                lines.append((ln, 15, "700"))
            for ln in self._wrap_lines(e.sub) if e.sub else []:
                lines.append((ln, 12.5, "400"))
            n = len(lines)
            cx = e.x + e.w / 2
            lh = 17
            start = e.y + e.h / 2 - (n - 1) * lh / 2
            for i, (ln, sz, wt) in enumerate(lines):
                col = INK if wt == "700" else "#495057"
                out.append(
                    f'<text x="{cx}" y="{start + i * lh + sz * 0.35:.1f}" '
                    f'font-size="{sz}" font-weight="{wt}" fill="{col}" '
                    f'text-anchor="middle">{_esc(ln)}</text>')

        for ed in self.edges:
            dash = 'stroke-dasharray="7 5" ' if ed.dashed else ""
            start_marker = 'marker-start="url(#arrowS)" ' if ed.bidir else ""
            out.append(
                f'<line x1="{ed.x1}" y1="{ed.y1}" x2="{ed.x2}" y2="{ed.y2}" '
                f'stroke="{ed.color}" stroke-width="2.2" {dash}{start_marker}'
                f'marker-end="url(#arrow)"/>')
            if ed.label:
                # label rides just above the line so arrowheads stay visible
                mx, my = (ed.x1 + ed.x2) / 2, (ed.y1 + ed.y2) / 2
                w = len(ed.label) * 7.2 + 10
                out.append(
                    f'<rect x="{mx - w/2:.1f}" y="{my - 26}" width="{w:.1f}" height="20" '
                    f'rx="5" fill="#ffffff" stroke="#dee2e6" stroke-width="1"/>')
                out.append(
                    f'<text x="{mx:.1f}" y="{my - 11}" font-size="12.5" '
                    f'fill="#495057" text-anchor="middle">{_esc(ed.label)}</text>')

        for r in self.routes:
            pts = " ".join(f"{x},{y}" for x, y in r.points)
            dash = 'stroke-dasharray="7 5" ' if r.dashed else ""
            marker = 'marker-end="url(#arrow)" ' if r.arrow else ""
            out.append(
                f'<polyline points="{pts}" fill="none" stroke="{r.color}" '
                f'stroke-width="{r.width}" stroke-linejoin="round" '
                f'stroke-linecap="round" {dash}{marker}/>')

        for f in self.frees:
            wt = "700" if f.bold else "400"
            out.append(
                f'<text x="{f.x}" y="{f.y}" font-size="{f.size}" font-weight="{wt}" '
                f'fill="{f.color}" text-anchor="{f.anchor}">{_esc(f.text)}</text>')

        out.append("</svg>")
        return "\n".join(out)

    def save_svg(self, path: str):
        with open(path, "w") as fh:
            fh.write(self.to_svg())
