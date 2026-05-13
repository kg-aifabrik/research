#!/usr/bin/env python3
"""Convert nvidia-b300-k8s-inference.md to a self-contained HTML report."""
import re
import sys
from pathlib import Path

import markdown

SRC = Path("/Users/karthikgajjala/code/research/gpu-infra/nvidia-b300-k8s-inference.md")
DST = Path("/Users/karthikgajjala/code/research/gpu-infra/nvidia-b300-k8s-inference.html")

# Inline SVG to replace the single mermaid block — drawn to match the prose
MERMAID_SVG = """
<svg viewBox="0 0 920 380" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Pod with primary CNI and SR-IOV secondary interface to GPU">
  <style>
    .node { fill: #f6f8fa; stroke: #5b6770; stroke-width: 1.2; }
    .node-accent { fill: #eaf3ff; stroke: #2563eb; stroke-width: 1.4; }
    .node-gpu { fill: #fff7ed; stroke: #c2410c; stroke-width: 1.4; }
    .label { font: 14px ui-sans-serif, -apple-system, system-ui, sans-serif; fill: #111; }
    .label-sub { font: 12px ui-sans-serif, -apple-system, system-ui, sans-serif; fill: #4b5563; }
    .edge { fill: none; stroke: #5b6770; stroke-width: 1.5; }
    .edge-data { fill: none; stroke: #c2410c; stroke-width: 1.8; }
    .edge-label { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; fill: #374151; }
  </style>
  <!-- Pod -->
  <rect class="node-accent" x="20" y="150" width="170" height="80" rx="8"/>
  <text class="label" x="105" y="185" text-anchor="middle">Tenant pod</text>
  <text class="label-sub" x="105" y="205" text-anchor="middle">in vCluster A</text>
  <!-- Cilium -->
  <rect class="node" x="280" y="60" width="170" height="80" rx="8"/>
  <text class="label" x="365" y="95" text-anchor="middle">Cilium eBPF</text>
  <text class="label-sub" x="365" y="115" text-anchor="middle">pod / control plane CNI</text>
  <!-- SR-IOV CNI -->
  <rect class="node" x="280" y="240" width="170" height="80" rx="8"/>
  <text class="label" x="365" y="275" text-anchor="middle">SR-IOV CNI</text>
  <text class="label-sub" x="365" y="295" text-anchor="middle">Multus secondary</text>
  <!-- ConnectX-8 -->
  <rect class="node" x="540" y="240" width="170" height="80" rx="8"/>
  <text class="label" x="625" y="275" text-anchor="middle">ConnectX-8 VF</text>
  <text class="label-sub" x="625" y="295" text-anchor="middle">host PF, 800 Gb/s</text>
  <!-- GPU -->
  <rect class="node-gpu" x="800" y="240" width="100" height="80" rx="8"/>
  <text class="label" x="850" y="275" text-anchor="middle">GPU HBM</text>
  <text class="label-sub" x="850" y="295" text-anchor="middle">288 GB</text>
  <!-- Spectrum-X planes -->
  <rect class="node" x="540" y="60" width="170" height="40" rx="8"/>
  <text class="label" x="625" y="85" text-anchor="middle">Spectrum-X plane 1</text>
  <rect class="node" x="540" y="115" width="170" height="40" rx="8"/>
  <text class="label" x="625" y="140" text-anchor="middle">Spectrum-X plane 2</text>
  <!-- Edges -->
  <path class="edge" d="M190,180 C235,180 235,100 280,100"/>
  <text class="edge-label" x="200" y="135">eth0</text>
  <path class="edge-data" d="M190,200 C235,200 235,280 280,280"/>
  <text class="edge-label" x="200" y="250">net1 (RDMA)</text>
  <path class="edge-data" d="M450,280 L540,280"/>
  <path class="edge-data" d="M710,280 L800,280"/>
  <text class="edge-label" x="725" y="270">GPUDirect</text>
  <path class="edge-data" d="M625,240 L625,155"/>
  <text class="edge-label" x="635" y="200">400 Gb/s</text>
  <path class="edge-data" d="M650,240 L650,95"/>
</svg>
"""

def md_to_html(md_text: str) -> str:
    # Pull out the mermaid block so we can replace it with the inline SVG.
    md_text = re.sub(
        r"```mermaid[\s\S]*?```",
        "<!--MERMAID-PLACEHOLDER-->",
        md_text,
    )
    extensions = ["tables", "fenced_code", "toc", "attr_list", "sane_lists"]
    html_body = markdown.markdown(md_text, extensions=extensions)
    html_body = html_body.replace("<!--MERMAID-PLACEHOLDER-->", f"<figure class='diagram'>{MERMAID_SVG}<figcaption>Pod data path: primary CNI (Cilium) for the pod network; Multus + SR-IOV CNI projects a ConnectX-8 VF as a secondary interface for GPUDirect RDMA traffic onto both Spectrum-X planes.</figcaption></figure>")
    # Slugified anchors for headings so the TOC links work.
    def slugify(s):
        s = re.sub(r"[^\w\s-]", "", s).strip().lower()
        return re.sub(r"[\s-]+", "-", s)
    def add_id(match):
        level = match.group(1)
        text = match.group(2)
        plain = re.sub(r"<.*?>", "", text)
        return f'<h{level} id="{slugify(plain)}">{text}</h{level}>'
    html_body = re.sub(r"<h([23])>(.*?)</h\1>", add_id, html_body)
    return html_body

CSS = """
:root {
  --fg: #1a1a1a;
  --fg-muted: #4b5563;
  --bg: #ffffff;
  --bg-soft: #f7f7f5;
  --border: #d8dcdf;
  --accent: #1f3a8a;
  --accent-soft: #eef2ff;
  --warn: #b45309;
  --code-bg: #f3f4f6;
  --code-fg: #111827;
}
* { box-sizing: border-box; }
html { font-size: 16px; -webkit-text-size-adjust: 100%; }
body {
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 1rem;
  line-height: 1.6;
  color: var(--fg);
  background: var(--bg);
  margin: 0;
  padding: 0;
}
.wrap {
  max-width: 980px;
  margin: 0 auto;
  padding: 56px 28px 96px;
}
h1, h2, h3, h4 {
  color: var(--fg);
  line-height: 1.25;
  margin-top: 1.8em;
  margin-bottom: 0.5em;
  font-weight: 650;
  letter-spacing: -0.01em;
}
h1 { font-size: 2.1rem; margin-top: 0; border-bottom: 1px solid var(--border); padding-bottom: 0.4em; }
h2 { font-size: 1.45rem; margin-top: 2.6em; padding-top: 0.4em; border-top: 1px solid var(--border); }
h3 { font-size: 1.15rem; color: var(--accent); }
h4 { font-size: 1rem; color: var(--fg-muted); text-transform: none; }
p { margin: 0.7em 0; }
a { color: var(--accent); text-decoration: none; border-bottom: 1px solid rgba(31,58,138,0.25); }
a:hover { background: var(--accent-soft); border-bottom-color: var(--accent); }
ul, ol { margin: 0.6em 0 0.8em 1.4em; padding: 0; }
li { margin: 0.25em 0; }
li > ul, li > ol { margin-top: 0.25em; }
hr { border: 0; border-top: 1px solid var(--border); margin: 2em 0; }
blockquote { border-left: 3px solid var(--border); padding-left: 1em; color: var(--fg-muted); margin: 0.8em 0; }
code {
  background: var(--code-bg);
  color: var(--code-fg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.9em;
  padding: 0.1em 0.35em;
  border-radius: 3px;
}
pre {
  background: var(--code-bg);
  color: var(--code-fg);
  padding: 1em 1.1em;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 0.88em;
  line-height: 1.5;
}
pre code { background: transparent; padding: 0; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0 1.4em;
  font-size: 0.93em;
  display: block;
  overflow-x: auto;
}
table thead { background: var(--bg-soft); }
table th, table td {
  border: 1px solid var(--border);
  padding: 8px 12px;
  vertical-align: top;
  text-align: left;
}
table th { font-weight: 650; color: var(--fg); }
table td p { margin: 0.2em 0; }
strong { font-weight: 650; color: var(--fg); }
em { color: var(--fg-muted); }
.lead {
  font-size: 1.05rem;
  color: var(--fg-muted);
  margin-bottom: 1.6em;
}
.diagram {
  margin: 1.4em 0;
  padding: 1.2em;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 6px;
}
.diagram svg { width: 100%; height: auto; display: block; }
.diagram figcaption {
  margin-top: 0.8em;
  font-size: 0.88em;
  color: var(--fg-muted);
  line-height: 1.5;
}
.toc { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 6px; padding: 1em 1.2em; }
.toc ol { margin: 0; padding-left: 1.4em; }
.toc li { margin: 0.15em 0; }
header.meta {
  margin-bottom: 1em;
  color: var(--fg-muted);
  font-size: 0.9em;
}
@media (max-width: 720px) {
  .wrap { padding: 32px 18px 64px; }
  h1 { font-size: 1.65rem; }
  h2 { font-size: 1.25rem; }
  table { font-size: 0.85em; }
}
"""

def main():
    md_text = SRC.read_text()
    html_body = md_to_html(md_text)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NVIDIA B-series Kubernetes inference architecture</title>
  <style>{CSS}</style>
</head>
<body>
  <main class="wrap">
    <header class="meta">Research note — gpu-infra / nvidia-b300-k8s-inference</header>
    {html_body}
  </main>
</body>
</html>
"""
    DST.write_text(html)
    print(f"Wrote {DST} ({len(html)} bytes)")

if __name__ == "__main__":
    main()
