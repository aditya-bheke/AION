const fs = require('fs');
const path = require('path');

const ICON_DIR = path.dirname(require.resolve('lucide-static/icons/server.svg'));

function icon(name, size, color, stroke = 1.8) {
  let svg = fs.readFileSync(path.join(ICON_DIR, name + '.svg'), 'utf8');
  svg = svg.replace(/<!--.*?-->/s, '').trim();
  svg = svg
    .replace(/width="24"/, `width="${size}"`)
    .replace(/height="24"/, `height="${size}"`)
    .replace(/stroke="currentColor"/, `stroke="${color}"`)
    .replace(/stroke-width="2"/, `stroke-width="${stroke}"`)
    .replace(/class="[^"]*"/, '');
  return svg;
}

// Pastel palette in the spirit of the NextHire synopsis diagrams.
const C = {
  peach:  { fill: '#FDE9D9', border: '#EFA46A', ink: '#7A3E12' },
  green:  { fill: '#E2F4E6', border: '#79C08B', ink: '#1E5B2E' },
  purple: { fill: '#ECE4F8', border: '#A68AD8', ink: '#4A2C82' },
  yellow: { fill: '#FFF4CC', border: '#E2BE52', ink: '#6B5208' },
  pink:   { fill: '#FCE3E8', border: '#E58BA0', ink: '#7D2238' },
  blue:   { fill: '#DFECFB', border: '#78A6DC', ink: '#1C4677' },
  teal:   { fill: '#DBF2EF', border: '#62BAAE', ink: '#145249' },
  navy:   { fill: '#1F2A55', border: '#1F2A55', ink: '#FFFFFF' },
  grey:   { fill: '#F1F3F6', border: '#9DA6B2', ink: '#36404D' },
  mint:   { fill: '#D9F3F7', border: '#5DB7C7', ink: '#11505B' },
};

async function render(html, out, width, height, scale = 2) {
  const { chromium } = require('playwright');
  // CHROMIUM_PATH lets you use an already-installed Chromium instead of `npx playwright install chromium`.
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: scale });
  await page.setContent(html, { waitUntil: 'load' });
  await page.screenshot({ path: out, clip: { x: 0, y: 0, width, height } });
  await browser.close();
}

module.exports = { icon, C, render };
