const path = require('path');
const { icon, C, render } = require('./common');

const W = 1100;
const MX = 270, MW = 520, BH = 100, CX = MX + MW / 2;   // main column
const LX = 18, RX = 860, SW = 222;                      // side columns
const STEP = 134;

const boxes = [];
function box(id, x, y, w, h, color, ic, title, sub, opts = {}) {
  boxes.push({ id, x, y, w, h, color, ic, title, sub, opts });
  return { x, y, w, h, cx: x + w / 2, cy: y + h / 2, r: x + w, b: y + h };
}
const Y = i => 20 + i * STEP;
const b1 = box('b1', MX, Y(0), MW, BH, C.peach, 'server', 'Production Application', 'Live service emitting structured JSON logs');
const b2 = box('b2', MX, Y(1), MW, BH, C.green, 'filter', 'Log Collection &amp; Normalization', 'File tail · HTTP ingest · Stack-frame parsing');
const b3 = box('b3', MX, Y(2), MW, BH, C.purple, 'layers', 'Deduplication &amp; Incident Detection', 'Template masking · Fingerprints · Spike detection');
const b4 = box('b4', MX, Y(3), MW, BH, C.yellow, 'git-branch', 'Git &amp; Deployment Correlation', 'git blame · Deployment window · Suspect ranking');
const b5 = box('b5', MX, Y(4), MW, BH, C.pink, 'brain', 'AI Root-Cause Analysis', 'Evidence pack · LLM diagnosis · Grounding checks');
const b6 = box('b6', MX, Y(5), MW, BH, C.blue, 'file-code-2', 'Candidate Patch Generation', 'Isolated branch · Code edits + regression test');
const b7 = box('b7', MX, Y(6), MW, BH, C.teal, 'flask-conical', 'Automated Validation (CI)', 'Syntax · Fail-to-pass · Unit tests · Staging · Replay');
const D = { cx: CX, cy: Y(7) + 55, hw: 165, hh: 55 };
const b8 = box('b8', MX, Y(7) + 146, MW, BH, C.navy, 'user-check', 'Human Approval Gate', 'Engineer approves the exact validated commit');
const b9 = box('b9', MX, Y(8) + 146, MW, BH, C.green, 'rocket', 'Deployment &amp; Verification', 'Fast-forward merge · Commit check · Replay');
const b10 = box('b10', MX + 50, Y(9) + 146, MW - 100, BH, C.mint, 'badge-check', 'Incident Resolved', 'Complete audit trail recorded');
const H = b10.b + 20;

// side boxes
const sGit = box('sGit', LX, b4.y, SW, BH, C.grey, 'history', 'Git Repository', 'Commits &amp; deploy history', { small: true, dashed: true });
const sLlm = box('sLlm', RX, b5.y, SW, BH, C.grey, 'sparkles', 'LLM', 'Claude API / Local model', { small: true, dashed: true });
const sRep = box('sRep', LX, b5.y, SW, BH, C.pink, 'file-text', 'Incident Report', 'RCA document &amp; ticket', { small: true });
const sFix = box('sFix', RX, D.cy - 60, SW, 120, C.yellow, 'refresh-cw', 'Repair &amp; Retry', 'Bounded repair loop · Revert fallback', { small: true });
const sEng = box('sEng', LX, b8.y, SW, BH, C.peach, 'user', 'Engineer / SRE', 'Reviews evidence, diff &amp; tests', { small: true, dashed: true });
const sRej = box('sRej', RX, b8.y, SW, BH, C.grey, 'circle-x', 'Rejected', 'Closed / re-investigated', { small: true });

function boxHtml(bx) {
  const { x, y, w, h, color, ic, title, sub, opts } = bx;
  const small = opts.small;
  const iconSize = small ? 32 : 42;
  const border = opts.dashed ? 'dashed' : 'solid';
  return `<div class="box" style="left:${x}px;top:${y}px;width:${w}px;height:${h}px;background:${color.fill};border:2px ${border} ${color.border};">
    ${small ? '' : `<div class="ic">${icon(ic, iconSize, color.ink)}</div>`}
    <div class="tx" style="color:${color.ink}">
      <div class="t ${small ? 'ts' : ''}">${title}</div>
      <div class="s ${small ? 'ss' : ''}" style="color:${color.ink === '#FFFFFF' ? '#D9DEF0' : '#3d4652'}">${sub}</div>
    </div></div>`;
}

const ink = '#3B4250';
const arrows = [];
function line(pts, label, lx, ly, anchor = 'middle') {
  arrows.push(`<polyline points="${pts.map(p => p.join(',')).join(' ')}" fill="none" stroke="${ink}" stroke-width="2.2" marker-end="url(#ah)"/>`);
  if (label) arrows.push(`<text x="${lx}" y="${ly}" text-anchor="${anchor}" class="lab">${label}</text>`);
}
// main flow
[[b1, b2], [b2, b3], [b3, b4], [b4, b5], [b5, b6], [b6, b7], [b8, b9], [b9, b10]].forEach(([a, b]) =>
  line([[CX, a.b], [CX, b.y - 2]]));
line([[CX, b7.b], [CX, D.cy - D.hh - 2]]);
line([[CX, D.cy + D.hh], [CX, b8.y - 2]], 'Yes', CX + 14, D.cy + D.hh + 26, 'start');
// side arrows
line([[sGit.r, sGit.cy], [MX - 2, sGit.cy]]);
line([[RX, sLlm.cy], [MX + MW + 2, sLlm.cy]]);
line([[MX, b5.cy], [sRep.r + 2, b5.cy]]);
line([[D.cx + D.hw, D.cy], [RX - 2, D.cy]], 'No', (D.cx + D.hw + RX) / 2, D.cy - 10);
line([[sFix.cx, sFix.y], [sFix.cx, b6.cy], [MX + MW + 2, b6.cy]], 'retry', sFix.cx + 10, (b6.cy + sFix.y) / 2, 'start');
line([[sEng.r, sEng.cy], [MX - 2, sEng.cy]]);
line([[MX + MW, b8.cy], [RX - 2, b8.cy]], 'Reject', (MX + MW + RX) / 2, b8.cy - 10);
arrows.push(`<text x="${CX + 14}" y="${b8.b + 26}" text-anchor="start" class="lab">Approve</text>`);

const diamond = `<polygon points="${D.cx},${D.cy - D.hh} ${D.cx + D.hw},${D.cy} ${D.cx},${D.cy + D.hh} ${D.cx - D.hw},${D.cy}" fill="#FFF8E6" stroke="#E2BE52" stroke-width="2.2"/>
  <text x="${D.cx}" y="${D.cy - 4}" text-anchor="middle" class="dt">Validation</text>
  <text x="${D.cx}" y="${D.cy + 20}" text-anchor="middle" class="dt">passed?</text>`;

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;background:#fff;}
  body{width:${W}px;height:${H}px;position:relative;font-family:'Liberation Sans',Arial,sans-serif;}
  .box{position:absolute;box-sizing:border-box;border-radius:14px;display:flex;align-items:center;justify-content:center;gap:12px;padding:6px 12px;box-shadow:0 1px 2px rgba(0,0,0,.06);}
  .ic{flex:0 0 auto;display:flex;}
  .tx{text-align:center;}
  .t{font-weight:700;font-size:26px;line-height:1.12;}
  .s{font-size:19px;margin-top:5px;line-height:1.2;}
  .ts{font-size:22px;} .ss{font-size:17px;}
  svg.arrows{position:absolute;left:0;top:0;}
  .lab{font-size:18px;font-weight:700;fill:#3B4250;font-family:'Liberation Sans',Arial,sans-serif;}
  .dt{font-size:22px;font-weight:700;fill:#6B5208;font-family:'Liberation Sans',Arial,sans-serif;}
</style></head><body>
<svg class="arrows" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${ink}"/></marker></defs>
  ${arrows.join('\n')}
  ${diamond}
</svg>
${boxes.map(boxHtml).join('\n')}
</body></html>`;

render(html, process.argv[2] || path.join(__dirname, '..', '..', 'images', 'process_diagram.png'), W, H).then(() => console.log('ok'));
