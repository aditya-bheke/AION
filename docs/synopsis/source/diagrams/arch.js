const path = require('path');
const { icon, C, render } = require('./common');

// Designed to print at ~6.5" wide on its own page, so body text lands near 7-8 pt.
const W = 1000;
const ink = '#3B4250';
const parts = [];
const lines = [];
const el = html => parts.push(html);

function arrow(pts, opts = {}) {
  const color = opts.color || ink;
  const mk = opts.mk || 'k';
  lines.push(`<polyline points="${pts.map(p => p.join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="${opts.w || 2.2}" ${opts.both ? `marker-start="url(#ah-${mk})"` : ''} marker-end="url(#ah-${mk})"/>`);
  if (opts.label) lines.push(`<text x="${opts.lx}" y="${opts.ly}" text-anchor="${opts.anchor || 'start'}" class="lab">${opts.label}</text>`);
}

function rowBox(x, y, w, h, col, ic, title, sub, extra = '') {
  el(`<div class="box row" style="left:${x}px;top:${y}px;width:${w}px;height:${h}px;background:${col.fill};border:2px solid ${col.border};${extra}">
    ${icon(ic, 32, col.ink)}<div class="cen"><div class="t" style="color:${col.ink}">${title}</div><div class="s">${sub}</div></div></div>`);
}

// ---- Row 1: actors ------------------------------------------------------------
rowBox(16, 16, 380, 78, C.grey, 'server', 'Production Application', 'Monitored service · JSON logs', 'border-style:dashed;');
rowBox(412, 16, 340, 78, C.peach, 'user-check', 'Engineer / SRE', 'Reviews incidents · Approves fixes');

// ---- Row 2: frontend ------------------------------------------------------------
el(`<div class="box" style="left:176px;top:128px;width:808px;height:122px;background:${C.purple.fill};border:2px solid ${C.purple.border};">
  <div class="row" style="justify-content:center;gap:12px;margin-top:10px;">${icon('monitor', 32, C.purple.ink)}
  <div class="cen"><div class="t" style="color:${C.purple.ink}">Frontend (Web Dashboard)</div><div class="s">(React.js + Vite)</div></div></div>
  <div class="menu">Incident List &nbsp;|&nbsp; Pipeline Stepper &nbsp;|&nbsp; Evidence &amp; RCA &nbsp;|&nbsp; Patch Diff Viewer<br>Approval Panel &nbsp;|&nbsp; Audit Log &nbsp;|&nbsp; System Status</div></div>`);

// ---- Row 3: API -----------------------------------------------------------------
rowBox(300, 286, 560, 80, { fill: '#E6EAF2', border: '#8C97AD', ink: '#2B3550' }, 'network', 'REST API Layer (FastAPI + Uvicorn)', 'Log ingest · Incidents · Approve / Reject · Deploy · System');

// ---- Row 4: backend services (2 x 4 grid) ------------------------------------------
const PY = 402, PH = 404;
el(`<div class="panel" style="left:16px;top:${PY}px;width:968px;height:${PH}px;"></div>`);
el(`<div class="ptitle" style="left:32px;top:${PY + 10}px;">Backend Services — AION Core (modular monolith)</div>`);
const services = [
  ['filter', 'Log Service', ['File-tail collector', 'HTTP log ingest', 'JSON normalization', 'Stack-frame parsing'], C.pink],
  ['layers', 'Detection Service', ['Template masking', 'Error fingerprints', 'Spike vs. baseline', 'Incident dedup'], C.pink],
  ['git-branch', 'Correlation Service', ['git blame at deploy', 'Function ranges (ast)', 'Deployment window', 'Suspect ranking'], C.pink],
  ['brain', 'RCA Service', ['Evidence pack', 'LLM diagnosis', 'Grounding checks', 'Incident report'], C.pink],
  ['file-code-2', 'Remediation Service', ['Worktree per attempt', 'Search/replace edits', 'Patch policy', 'Revert fallback'], C.pink],
  ['flask-conical', 'Validation Service', ['Syntax &amp; unit tests', 'Fail-to-pass check', 'Staging run', 'Traffic replay'], C.pink],
  ['rocket', 'Deployment Service', ['SHA-bound approval', 'Preflight checks', 'Fast-forward merge', 'Post-deploy verify'], C.pink],
  ['workflow', 'Orchestrator', ['Pipeline &amp; worker', 'Incident state machine', 'Human approval gate', 'Audit logger'], C.yellow],
];
const GX = 31, GW = 230, GG = 6, GH = 168, GY = PY + 44;
services.forEach(([ic, title, items, col], i) => {
  const x = GX + (i % 4) * (GW + GG);
  const y = GY + Math.floor(i / 4) * (GH + 10);
  el(`<div class="box svc" style="left:${x}px;top:${y}px;width:${GW}px;height:${GH}px;background:${col.fill};border:2px solid ${col.border};">
    <div class="row" style="gap:8px;justify-content:flex-start;">${icon(ic, 24, col.ink)}<div class="st" style="color:${col.ink}">${title}</div></div>
    <ul>${items.map(t => `<li>${t}</li>`).join('')}</ul></div>`);
});

// ---- Row 5: layers ----------------------------------------------------------------
const LY = PY + PH + 62, LH = 330;
el(`<div class="box" style="left:16px;top:${LY}px;width:420px;height:${LH}px;background:${C.green.fill};border:2px solid ${C.green.border};padding:10px 14px;">
  <div class="row" style="gap:10px;justify-content:center;">${icon('sparkles', 28, C.green.ink)}<div class="t" style="color:${C.green.ink}">AI &amp; LLM Layer</div></div>
  <div class="stage" style="margin-top:8px;"><div class="sgt">Stage 1 : Root-Cause Analysis</div><ul>
    <li>Evidence pack with evidence IDs</li><li>Observations vs. inferences</li><li>Grounding checks &amp; confidence</li></ul></div>
  <div class="stage" style="margin-top:8px;"><div class="sgt">Stage 2 : Patch Generation</div><ul>
    <li>Code edits + regression test</li><li>Code-enforced patch policy</li><li>Bounded repair loop</li></ul></div>
  <div class="prov">Claude API · Local LLM (Ollama) · Fallback</div></div>`);
el(`<div class="box" style="left:450px;top:${LY}px;width:250px;height:${LH}px;background:${C.blue.fill};border:2px solid ${C.blue.border};padding:10px 14px;">
  <div class="row" style="gap:10px;justify-content:center;">${icon('database', 28, C.blue.ink)}<div class="cen"><div class="t" style="color:${C.blue.ink}">Data Layer</div><div class="s">(SQLite + SQLAlchemy)</div></div></div>
  <ul class="big"><li>Log events &amp; signatures</li><li>Incidents &amp; suspects</li><li>RCA reports</li><li>Patch proposals</li><li>Validation runs</li><li>Approvals &amp; deployments</li><li>Audit events</li></ul></div>`);
el(`<div class="box" style="left:714px;top:${LY}px;width:270px;height:${LH}px;background:${C.purple.fill};border:2px solid ${C.purple.border};padding:10px 14px;">
  <div class="row" style="gap:10px;justify-content:center;">${icon('cloud', 28, C.purple.ink)}<div class="t" style="color:${C.purple.ink}">External Systems</div></div>
  <ul class="big"><li>Git repository</li><li>Deployment history</li><li>Staging &amp; production</li><li>LLM endpoint</li><li>GitHub Actions <i>(planned)</i></li><li>ELK stack <i>(planned)</i></li><li>Slack / Teams <i>(planned)</i></li></ul></div>`);

// ---- connectors ---------------------------------------------------------------------
arrow([[582, 94], [582, 126]]);
arrow([[580, 250], [580, 284]], { label: 'REST / JSON', lx: 592, ly: 274 });
arrow([[580, 366], [580, PY + 34]]);
arrow([[96, 94], [96, 326], [298, 326]], { label: 'logs', lx: 106, ly: 300 });
const by = PY + PH, ty = LY - 2;
arrow([[226, by], [226, ty]], { color: '#4E9A62', mk: 'g', label: 'LLM calls', lx: 236, ly: by + 36 });
arrow([[575, by], [575, ty]], { color: '#4F7FBF', mk: 'b', both: true, label: 'read / write', lx: 585, ly: by + 36 });
arrow([[849, by], [849, ty]], { color: '#8565C4', mk: 'p', both: true, label: 'git · HTTP', lx: 859, ly: by + 36 });

const H = LY + LH + 16;
const mk = (id, c) => `<marker id="ah-${id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`;
const html = `<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;background:#fff;}
  body{width:${W}px;height:${H}px;position:relative;font-family:'Liberation Sans',Arial,sans-serif;color:#2f3742;}
  .box{position:absolute;box-sizing:border-box;border-radius:12px;box-shadow:0 1px 2px rgba(0,0,0,.06);}
  .row{display:flex;align-items:center;justify-content:center;}
  .box.row{gap:12px;padding:4px 12px;}
  .cen{text-align:center;}
  .t{font-weight:700;font-size:22px;line-height:1.15;}
  .s{font-size:16px;margin-top:3px;color:#47505c;}
  .menu{text-align:center;font-size:16.5px;margin-top:8px;color:#3a2a5c;line-height:1.45;}
  .panel{position:absolute;box-sizing:border-box;border:2px dashed #8FB3DA;background:#F3F8FD;border-radius:14px;}
  .ptitle{position:absolute;font-weight:700;font-size:18px;color:#1C4677;}
  .svc{padding:10px 10px;}
  .st{font-weight:700;font-size:16.5px;line-height:1.1;}
  ul{margin:8px 0 0 0;padding-left:20px;font-size:16.5px;line-height:1.5;}
  ul.big{font-size:16.5px;line-height:1.55;margin-top:12px;}
  .stage{border:2px dashed #79C08B;border-radius:10px;background:#F4FBF5;padding:8px 10px;}
  .stage ul{margin-top:4px;}
  .sgt{font-weight:700;font-size:17px;color:#1E5B2E;}
  .prov{margin-top:10px;text-align:center;font-size:15.5px;color:#1E5B2E;font-weight:700;}
  svg.arrows{position:absolute;left:0;top:0;}
  .lab{font-size:16px;font-weight:700;fill:#3B4250;font-family:'Liberation Sans',Arial,sans-serif;}
</style></head><body>
${parts.join('\n')}
<svg class="arrows" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs>${mk('k', ink)}${mk('g', '#4E9A62')}${mk('b', '#4F7FBF')}${mk('p', '#8565C4')}</defs>
${lines.join('\n')}</svg>
</body></html>`;

render(html, process.argv[2] || path.join(__dirname, '..', '..', 'images', 'system_architecture.png'), W, H, 2.4).then(() => console.log('ok', W, H));
