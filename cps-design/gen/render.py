#!/usr/bin/env python3
"""
render.py — SVG -> PNG via headless Chrome (no Node toolchain required).

Shared by every diagram build script. Chrome is used purely as a rendering
engine: it loads the SVG inside a minimal HTML wrapper and screenshots it at a
retina scale factor. Window size is read from the SVG's own width/height so the
capture is never clipped.
"""
import sys, subprocess, tempfile, os, re

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    raise SystemExit("No Chrome/Chromium found — install one or edit CHROME_CANDIDATES.")


def render(svg_path: str, png_path: str | None = None, scale: int = 2) -> str:
    svg = open(svg_path).read()
    m = re.search(r'width="(\d+)"\s+height="(\d+)"', svg)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1600, 1200)
    png_path = png_path or os.path.splitext(svg_path)[0] + ".png"
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;background:#fff}svg{display:block}</style>"
            "</head><body>" + svg + "</body></html>")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
        fh.write(html)
        html_path = fh.name
    try:
        subprocess.run(
            [find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--force-device-scale-factor={scale}", f"--window-size={w},{h}",
             "--default-background-color=ffffffff",
             f"--screenshot={png_path}", "file://" + html_path],
            check=True, capture_output=True)
    finally:
        os.unlink(html_path)
    print(f"rendered {png_path} ({w}x{h} @{scale}x)")
    return png_path


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
