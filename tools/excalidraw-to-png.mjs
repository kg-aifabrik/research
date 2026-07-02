// Render a .excalidraw file to PNG at 2x scale, matching excalidraw.com output.
//
// Drives the locally installed Chrome (headless, via puppeteer-core) to run
// Excalidraw's own exportToSvg (loaded from esm.sh — needs network), then
// screenshots the resulting SVG element at its exact rendered size.
// A browser is required because Excalidraw measures text with canvas APIs
// that jsdom-based converters don't implement.
//
// Setup (once):  cd tools && npm install
// Usage:         node tools/excalidraw-to-png.mjs <in.excalidraw> <out.png>
// Chrome path defaults to the macOS app bundle; override with $CHROME_PATH.
import fs from 'fs';
import path from 'path';
import os from 'os';
import puppeteer from 'puppeteer-core';

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const [, , inFile, outFile] = process.argv;
if (!inFile || !outFile) {
  console.error('usage: node excalidraw-to-png.mjs <in.excalidraw> <out.png>');
  process.exit(1);
}

const scene = JSON.parse(fs.readFileSync(inFile, 'utf8'));

const html = `<!doctype html>
<meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#fff}svg{display:block}</style>
<script type="module">
const { exportToSvg } = await import("https://esm.sh/@excalidraw/excalidraw@0.18.0");
const scene = ${JSON.stringify(scene)};
const svg = await exportToSvg({
  elements: scene.elements,
  appState: { exportBackground: true, viewBackgroundColor: "#ffffff", exportPadding: 24 },
  files: scene.files || {},
});
// Normalize: 1 SVG unit = 1 CSS px regardless of exportScale/devicePixelRatio.
const vb = svg.viewBox.baseVal;
svg.setAttribute('width', vb.width);
svg.setAttribute('height', vb.height);
document.body.appendChild(svg);
</script>`;

const htmlPath = path.join(os.tmpdir(), `excalidraw-render-${process.pid}.html`);
fs.writeFileSync(htmlPath, html);

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1200, deviceScaleFactor: 2 });
  await page.goto(`file://${htmlPath}`, { waitUntil: 'networkidle0', timeout: 60000 });
  await page.waitForSelector('svg', { timeout: 60000 });
  await page.evaluate(() => document.fonts.ready); // Virgil etc. loaded before shot
  const el = await page.$('svg');
  await el.screenshot({ path: outFile });
  const box = await el.boundingBox();
  console.log(`${outFile}: ${Math.round(box.width)}x${Math.round(box.height)} logical px`);
} finally {
  await browser.close();
  fs.unlinkSync(htmlPath);
}
