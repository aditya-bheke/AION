// Builds the AION preliminary report (.docx) in the ADYPSOE BE Project Work-I format.
// Usage: node build.js out.docx [pages.json]
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType, AlignmentType,
  BorderStyle, HeadingLevel, Footer, PageNumber, NumberFormat, LevelFormat, TabStopType, ShadingType,
  PageBreak, VerticalAlign, PageBorderDisplay, PageBorderOffsetFrom, TableLayoutType, SectionType, LeaderType,
} = require('docx');

const OUT = process.argv[2] || 'AION_Report.docx';
const PAGES = process.argv[3] && fs.existsSync(process.argv[3]) ? JSON.parse(fs.readFileSync(process.argv[3])) : {};
const DIAG = path.join(__dirname, 'diag');
const FONT = 'Times New Roman';
const TITLE = 'AION: AUTONOMOUS INCIDENT OBSERVATION AND NAVIGATION';
const TITLE_CASE = 'AION: Autonomous Incident Observation and Navigation';
const STUDENTS = ['ADITYA BHEKE', 'HARSHAL BHOGAWADE', 'MALHAR BHOI'];
const GUIDE = 'Dr. Yogesh Bahendwar';
const TEXT_W = 8640; // 8.5in - 1.5in - 1in = 6in

const content = [...require('./content1'), ...require('./content2'), ...require('./content3'), ...require('./content4')];
const REFS = JSON.parse(fs.readFileSync(path.join(__dirname, 'refs.json')));   // key -> {n, runs:[{text, italics}]}

// ------------------------------------------------------------------ inline text
function mathRuns(s, base) {
  // subscripts: x_k, f_norm, max_{c ∈ C}; superscripts: ^1.05
  const out = [];
  const re = /([A-Za-zΣκλρτ]+)_\{([^}]+)\}|(^|[^A-Za-z])([A-Za-zΣκλρτ])_([A-Za-z0-9*]{1,5})(?![A-Za-z0-9])|\^([0-9.]+)/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m[1]) { out.push({ ...base, text: s.slice(last, m.index) + m[1] }); out.push({ ...base, text: m[2], subScript: true }); }
    else if (m[4]) { out.push({ ...base, text: s.slice(last, m.index) + m[3] + m[4] }); out.push({ ...base, text: m[5], subScript: true }); }
    else { out.push({ ...base, text: s.slice(last, m.index) }); out.push({ ...base, text: m[6], superScript: true }); }
    last = re.lastIndex;
  }
  out.push({ ...base, text: s.slice(last) });
  return out.filter(r => r.text !== '');
}
function cite(keys) {
  return keys.map(k => { if (!REFS[k]) throw new Error('unknown ref ' + k); return `[${REFS[k].n}]`; });
}
function runs(text, opts = {}) {
  const size = opts.size || 24;
  const base = { font: FONT, size, bold: opts.bold, italics: opts.italics };
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[@[^\]]+\])/g;
  let last = 0, m;
  const plain = (s, b) => mathRuns(s, b).forEach(r => out.push(new TextRun(r)));
  while ((m = re.exec(text))) {
    plain(text.slice(last, m.index), base);
    const tok = m[0];
    if (tok.startsWith('**')) runs(tok.slice(2, -2), { ...opts, bold: true }).forEach(r => out.push(r));
    else if (tok.startsWith('`')) out.push(new TextRun({ text: tok.slice(1, -1), font: 'Courier New', size: size - 2, bold: opts.bold }));
    else if (tok.startsWith('[@')) out.push(new TextRun({ ...base, text: cite(tok.slice(2, -1).split(/;\s*@?/)).join(', ') }));
    else plain(tok.slice(1, -1), { ...base, italics: !opts.italics });
    last = re.lastIndex;
  }
  plain(text.slice(last), base);
  return out;
}

// ------------------------------------------------------------------ paragraph helpers
const LINE15 = 360;
function para(text, o = {}) {
  return new Paragraph({
    alignment: o.align || AlignmentType.JUSTIFIED,
    spacing: { line: o.line || LINE15, before: o.before || 0, after: o.after === undefined ? 240 : o.after },
    indent: o.indent || (o.noIndent ? undefined : { firstLine: 720 }),
    keepNext: o.keepNext, keepLines: o.keepLines,
    children: Array.isArray(text) ? text : runs(text, o),
  });
}
function centered(text, size, bold, o = {}) {
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { line: o.line || 240, before: o.before || 0, after: o.after || 0 },
    keepNext: o.keepNext, children: [new TextRun({ text, font: FONT, size, bold, italics: o.italics })] });
}
function blank(n = 1, size = 24) { return Array.from({ length: n }, () => new Paragraph({ spacing: { line: 240, after: 0 }, children: [new TextRun({ text: '', font: FONT, size })] })); }
function pageBreak() { return new Paragraph({ children: [new PageBreak()] }); }

const borderNone = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };
const noBorders = { top: borderNone, bottom: borderNone, left: borderNone, right: borderNone, insideHorizontal: borderNone, insideVertical: borderNone };
const line = { style: BorderStyle.SINGLE, size: 4, color: '000000' };
const allBorders = { top: line, bottom: line, left: line, right: line, insideHorizontal: line, insideVertical: line };

function cell(children, width, o = {}) {
  return new TableCell({ width: { size: width, type: WidthType.DXA }, children, verticalAlign: o.vAlign || VerticalAlign.CENTER,
    shading: o.shade ? { fill: o.shade, type: ShadingType.CLEAR, color: 'auto' } : undefined,
    margins: { top: 30, bottom: 30, left: 90, right: 90 }, columnSpan: o.span });
}
function cellPara(text, o = {}) {
  return new Paragraph({ alignment: o.align || AlignmentType.LEFT, spacing: { line: o.line || 240, after: 0 },
    children: runs(text, { size: o.size || 21, bold: o.bold }) });
}

// ------------------------------------------------------------------ numbering state
let chapter = 0, figN = 0, tabN = 0, eqN = 0, chapKey = '', numInst = 0;
const figList = [], tabList = [], tocRows = [];
const P = (key, fallback = '') => (PAGES[key] !== undefined ? String(PAGES[key]) : fallback);

function chapterHeading(label, title, key) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, alignment: AlignmentType.CENTER, pageBreakBefore: true,
    spacing: { before: 0, after: 480, line: 360 },
    children: [new TextRun({ text: label, font: FONT, size: 28, bold: true }), new TextRun({ text: title, font: FONT, size: 28, bold: true, break: 1 })] });
}

function render(blocks) {
  const out = [];
  for (const b of blocks) {
    switch (b.t) {
      case 'chapter':
        chapter = b.n; chapKey = String(b.n); figN = 0; tabN = 0; eqN = 0;
        tocRows.push({ kind: 'ch', no: String(b.n).padStart(2, '0'), title: b.titleCase || titleCase(b.title), key: 'ch' + b.n });
        out.push(chapterHeading(`CHAPTER ${b.n}`, b.title, 'ch' + b.n));
        break;
      case 'appendix':
        chapKey = b.n; figN = 0; tabN = 0; eqN = 0;
        tocRows.push({ kind: 'app', no: '', title: `Appendix ${b.n}: ${titleCase(b.title)}`, key: 'app' + b.n });
        out.push(chapterHeading(`APPENDIX ${b.n}`, b.title, 'app' + b.n));
        break;
      case 'h2':
        if (/^\d/.test(b.n)) tocRows.push({ kind: 'sec', no: b.n, title: titleCase(b.title), key: 'sec' + b.n });
        out.push(new Paragraph({ heading: HeadingLevel.HEADING_2, alignment: AlignmentType.LEFT, keepNext: true,
          spacing: { before: 480, after: 240, line: 276 }, children: [new TextRun({ text: `${b.n} ${b.title}`, font: FONT, size: 24, bold: true })] }));
        break;
      case 'h3':
        out.push(new Paragraph({ heading: HeadingLevel.HEADING_3, alignment: AlignmentType.LEFT, keepNext: true,
          spacing: { before: 240, after: 120, line: 276 }, children: [new TextRun({ text: `${b.n} ${b.title}`, font: FONT, size: 24, bold: true })] }));
        break;
      case 'p':
        out.push(para(b.text));
        break;
      case 'bullets': case 'num': {
        const inst = ++numInst;
        b.items.forEach((it, i) => out.push(new Paragraph({
          alignment: AlignmentType.JUSTIFIED, spacing: { line: LINE15, after: i === b.items.length - 1 ? 240 : 80 },
          numbering: { reference: b.t === 'num' ? 'nums' : 'bullets', level: 0, instance: b.t === 'num' ? inst : undefined },
          children: runs(it) })));
        break; }
      case 'eq': {
        const children = runs(b.text, {});
        if (b.n) { eqN++; children.unshift(new TextRun({ text: '\t', font: FONT })); children.push(new TextRun({ text: `\t(${chapKey}.${eqN})`, font: FONT, size: 24 })); }
        out.push(new Paragraph({ alignment: b.n ? AlignmentType.LEFT : AlignmentType.CENTER, spacing: { line: LINE15, before: 60, after: 180 },
          tabStops: b.n ? [{ type: TabStopType.CENTER, position: TEXT_W / 2 }, { type: TabStopType.RIGHT, position: TEXT_W }] : undefined,
          children }));
        break; }
      case 'fig': {
        figN++; const no = `${chapKey}.${figN}`;
        figList.push({ no, title: b.title, key: 'fig' + no });
        const file = path.join(DIAG, b.file);
        const buf = fs.readFileSync(file);
        const W = buf.readUInt32BE(16), H = buf.readUInt32BE(20);
        let wIn = b.w, hIn = wIn * H / W;
        if (hIn > 7.0) { hIn = 7.0; wIn = hIn * W / H; }
        out.push(new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 120 },
          children: [new ImageRun({ type: 'png', data: buf, transformation: { width: Math.round(wIn * 96), height: Math.round(hIn * 96) } })] }));
        out.push(new Paragraph({ alignment: AlignmentType.CENTER, keepNext: !!b.legend, spacing: { after: b.legend ? 60 : 240, line: 276 },
          children: [new TextRun({ text: `Figure ${no}: `, font: FONT, size: 24, bold: true }), ...runs(b.title, { size: 24 })] }));
        if (b.legend) out.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240, line: 240 }, children: runs(b.legend, { size: 20, italics: true }) }));
        break; }
      case 'table': {
        tabN++; const no = `${chapKey}.${tabN}`;
        tabList.push({ no, title: b.title, key: 'tab' + no });
        const tot = b.widths.reduce((a, c) => a + c, 0);
        const widths = b.widths.map(w => Math.round(TEXT_W * w / tot));
        widths[widths.length - 1] += TEXT_W - widths.reduce((a, c) => a + c, 0);
        out.push(new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 120, line: 276 },
          children: [new TextRun({ text: `Table ${no}: `, font: FONT, size: 24, bold: true }), ...runs(b.title, { size: 24 })] }));
        const rows = [new TableRow({ tableHeader: true, cantSplit: true, children: b.head.map((h, i) => cell([cellPara(h, { bold: true, align: AlignmentType.CENTER })], widths[i], { shade: 'D9D9D9' })) })];
        b.rows.forEach(r => rows.push(new TableRow({ cantSplit: true, children: r.map((c, i) => cell([cellPara(c, { align: i === 0 || c.length > 14 ? AlignmentType.LEFT : AlignmentType.CENTER })], widths[i])) })));
        out.push(new Table({ width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: widths, borders: allBorders, alignment: AlignmentType.CENTER, rows }));
        out.push(new Paragraph({ spacing: { after: 120, line: 240 }, children: [] }));
        break; }
      case 'paper': {
        const r = REFS[b.key];
        out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, keepNext: true, spacing: { line: 276, after: 60 }, indent: { left: 567, hanging: 567 },
          children: [new TextRun({ text: `[${r.n}]\t`, font: FONT, size: 24, bold: true }), ...r.runs.map(x => new TextRun({ text: x.text, font: FONT, size: 24, italics: x.italics }))],
          tabStops: [{ type: TabStopType.LEFT, position: 567 }] }));
        out.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { line: 276, after: 220 }, indent: { left: 567 },
          children: [new TextRun({ text: 'Summary: ', font: FONT, size: 24, bold: true, italics: true }), ...runs(b.text)] }));
        break; }
      default: throw new Error('block ' + b.t);
    }
  }
  return out;
}
function titleCase(s) {
  const small = new Set(['and', 'of', 'the', 'to', 'for', 'in', 'on', 'a', 'w.r.t.']);
  return s.toLowerCase().split(' ').map((w, i) => {
    if (w === 'sdlc' || w === 'np-hard' || w === 'uml' || w === 'dfd') return w.toUpperCase().replace('NP-HARD', 'NP-Hard');
    if (i > 0 && small.has(w)) return w;
    return w.replace(/^(\(?)(\w)/, (m0, p1, c) => p1 + c.toUpperCase());
  }).join(' ').replace('W.r.t.', 'w.r.t.').replace(': Sdlc', ': SDLC');
}

const body = render(content);

// ------------------------------------------------------------------ references
const refOrder = Object.entries(REFS).sort((a, b) => a[1].n - b[1].n);
tocRows.push({ kind: 'ref', no: '', title: 'References', key: 'refs' });
const refBlocks = [chapterHeading('', 'REFERENCES', 'refs')];
refBlocks[0] = new Paragraph({ heading: HeadingLevel.HEADING_1, alignment: AlignmentType.CENTER, pageBreakBefore: true, spacing: { after: 360, line: 360 },
  children: [new TextRun({ text: 'REFERENCES', font: FONT, size: 28, bold: true })] });
for (const [k, r] of refOrder) {
  refBlocks.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { line: 276, after: 140 }, indent: { left: 567, hanging: 567 },
    tabStops: [{ type: TabStopType.LEFT, position: 567 }],
    children: [new TextRun({ text: `[${r.n}]\t`, font: FONT, size: 24 }), ...r.runs.map(x => new TextRun({ text: x.text, font: FONT, size: 24, italics: x.italics }))] }));
}

// ------------------------------------------------------------------ front matter
const logo = fs.readFileSync(path.join(__dirname, 'src/media/word/media/image1.png'));
const logoPara = (w = 1.05) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 0 },
  children: [new ImageRun({ type: 'png', data: logo, transformation: { width: Math.round(w * 96), height: Math.round(w * 96 * 145 / 161) } })] });

function studentTable(size) {
  const w = [3500, 3500];
  return new Table({ width: { size: 7000, type: WidthType.DXA }, columnWidths: w, borders: noBorders, alignment: AlignmentType.CENTER,
    rows: STUDENTS.map(n => new TableRow({ children: [
      cell([new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: n, font: FONT, size, bold: true })] })], w[0]),
      cell([new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: 'Exam No : _____________', font: FONT, size, bold: true })] })], w[1]),
    ] })) });
}

const cover = [
  ...blank(4),
  centered('A PRELIMINARY REPORT ON', 24, true),
  ...blank(2),
  centered(TITLE, 32, true, { line: 276 }),
  ...blank(2),
  centered('SUBMITTED TO THE SAVITRIBAI PHULE PUNE UNIVERSITY, PUNE', 24, false),
  centered('IN THE PARTIAL FULFILLMENT OF THE REQUIREMENTS', 24, false),
  centered('FOR THE AWARD OF THE DEGREE', 24, false),
  ...blank(1),
  centered('OF', 24, false),
  ...blank(2),
  centered('BACHELOR OF ENGINEERING', 32, true),
  centered('(COMPUTER ENGINEERING)', 32, true),
  ...blank(2),
  centered('SUBMITTED BY', 24, true),
  ...blank(1),
  studentTable(24),
  ...blank(1),
  centered('Under the Guidance of', 24, true),
  centered(GUIDE, 24, true),
  ...blank(1),
  logoPara(1.0),
  ...blank(1),
  centered('DEPARTMENT OF COMPUTER ENGINEERING', 24, true),
  ...blank(1),
  centered('AJEENKYA DY PATIL SCHOOL OF ENGINEERING', 24, true),
  centered('CHARHOLI BUDRUK, LOHEGAON, PUNE 412105', 24, false),
  ...blank(1),
  centered('SAVITRIBAI PHULE PUNE UNIVERSITY', 24, true),
  centered('2026-2027', 24, true),
];

function sigTable(rows, widths = [4320, 4320]) {
  return new Table({ width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: widths, borders: noBorders,
    rows: rows.map(r => new TableRow({ children: r.map((c, i) => cell(c.map(([t, b, al]) => new Paragraph({ alignment: al || AlignmentType.CENTER, spacing: { after: 0 },
      children: [new TextRun({ text: t, font: FONT, size: 24, bold: b })] })), widths[i], { vAlign: VerticalAlign.TOP })) })) });
}

const certificate = [
  new Paragraph({ pageBreakBefore: true, alignment: AlignmentType.CENTER, children: [] }),
  logoPara(0.95),
  centered('AJEENKYA DY PATIL SCHOOL OF ENGINEERING', 24, true),
  centered('DEPARTMENT OF COMPUTER ENGINEERING', 24, true),
  ...blank(2),
  centered('CERTIFICATE', 32, true),
  ...blank(1),
  centered('This is to certify that the Project Report Entitled', 24, false),
  ...blank(1),
  centered(`“${TITLE}”`, 24, true, { line: 276 }),
  ...blank(1),
  centered('Submitted by', 24, false),
  ...blank(1),
  studentTable(24),
  ...blank(1),
  para(`are bonafide students of this institute and the work has been carried out by them under the supervision of **${GUIDE}** and it is approved for the partial fulfillment of the requirement of Savitribai Phule Pune University, for the award of the degree of **Bachelor of Engineering** in Computer Engineering.`, { noIndent: true, after: 0 }),
  ...blank(2),
  sigTable([[[[`(${GUIDE})`, true, AlignmentType.LEFT], ['Guide', false, AlignmentType.LEFT], ['Department of Computer Engineering', false, AlignmentType.LEFT]],
             [['Dr. Pankaj Agarkar', true, AlignmentType.LEFT], ['H.O.D', false, AlignmentType.LEFT], ['Department of Computer Engineering', false, AlignmentType.LEFT]]]]),
  ...blank(2),
  sigTable([[[['Signature of Internal Examiner:', false, AlignmentType.LEFT]], [['Signature of External Examiner:', false, AlignmentType.LEFT]]]]),
  ...blank(2),
  centered('Dr. F. B. Sayyad', 24, true),
  centered('Principal', 24, false),
  centered('AJEENKYA DY PATIL SCHOOL OF ENGINEERING, Lohegaon, Pune – 412105', 24, false),
  ...blank(1),
  para('Place : Pune', { noIndent: true, after: 0, line: 240 }),
  para('Date :', { noIndent: true, after: 0, line: 240 }),
];

function fmHeading(t, first) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, alignment: AlignmentType.CENTER, pageBreakBefore: !first, spacing: { after: 480, line: 360 },
    children: [new TextRun({ text: t, font: FONT, size: 28, bold: true })] });
}
const ack = [
  fmHeading('ACKNOWLEDGEMENT', true),
  para(`It gives us great pleasure in presenting the preliminary project report on “${TITLE_CASE}”.`),
  para(`We would like to take this opportunity to thank our Internal Guide **${GUIDE}** for giving us all the help and guidance we needed. We are really grateful to him for his kind support. His valuable suggestions were very helpful.`),
  para('We are also grateful to **Dr. Pankaj Agarkar**, Head of Computer Engineering Department, ADYPSOE, Lohegaon, Pune and to our Project Co-ordinator **Dr. Amruta Chitari** for their indispensable support, suggestions and motivation during the entire course of the project.'),
  para('We would also be grateful to our Principal **Dr. F. B. Sayyad** who encouraged us and created a healthy environment for all of us to learn in the best possible way.'),
  para('We also thank all the staff members of our college and technicians for their help in making this project a successful one.'),
  ...blank(2),
  ...STUDENTS.map(n => new Paragraph({ alignment: AlignmentType.RIGHT, spacing: { after: 60 }, children: [new TextRun({ text: n, font: FONT, size: 24, bold: true })] })),
];
const abstract = [
  fmHeading('ABSTRACT'),
  para('Resolving a production incident still requires engineers to search large volumes of logs, trace the failure to the code change that caused it, write and test a fix, and deploy it under time pressure, using several disconnected tools. Research in AIOps automates individual stages of this process, such as log parsing, anomaly detection, root-cause analysis and automated program repair, but the stages are usually studied in isolation, and letting a Large Language Model (LLM) change production code without checks is unsafe.'),
  para('This report presents AION (Autonomous Incident Observation & Navigation), a closed-loop, human-gated platform that connects these stages. AION collects structured application logs, deduplicates them into error signatures and detects incidents as error spikes against a baseline. It ranks the commits that probably caused each incident with an explainable score based on git blame, function scope, dependency overlap and deployment timing, and asks an LLM, either the Claude API or a locally hosted model, for a diagnosis that must cite the evidence it is given. Candidate patches are generated on isolated branches under a code-enforced policy and validated by compilation, the existing tests, a staging deployment and a replay of the failing requests. Deployment is possible only through an explicit human approval that is bound to the exact validated commit, and every action is written to an append-only audit trail.'),
  para('A working prototype of about 7.1 KLOC with 44 automated tests runs the complete loop. On four seeded scenarios it detected every incident with no false positive and ranked the true culprit first in all three faulty cases; a locally hosted 7B model named the culprit in two of three cases, and every incorrect AI patch was stopped by validation before reaching the approval gate. The report covers the problem definition, project plan, requirements specification, system design with UML and data-flow models, and a complexity analysis of the problem.'),
  para('**Keywords:** AIOps, Incident Management, Log Analysis, Root-Cause Analysis, Large Language Models, Automated Program Repair, CI/CD, Human-in-the-Loop', { noIndent: true }),
];

// table of contents
function tocLine(t, key) {
  return new Paragraph({ spacing: { after: 60, line: 276 }, indent: { left: 1440 }, tabStops: [{ type: TabStopType.RIGHT, position: 7200, leader: LeaderType.DOT }],
    children: [new TextRun({ text: t, font: FONT, size: 24 }), new TextRun({ text: `\t${P(key, 'i')}`, font: FONT, size: 24 })] });
}
function tocTable() {
  const w = [1100, 6340, 1200];
  const rows = [new TableRow({ tableHeader: true, children: [cell([cellPara('Sr. No.', { bold: true, size: 24, align: AlignmentType.CENTER })], w[0]), cell([cellPara('Title of Chapter', { bold: true, size: 24 })], w[1]), cell([cellPara('Page No.', { bold: true, size: 24, align: AlignmentType.CENTER })], w[2])] })];
  for (const r of tocRows) {
    const bold = r.kind !== 'sec';
    rows.push(new TableRow({ cantSplit: true, children: [
      cell([cellPara(r.no, { bold, size: 24, align: r.kind === 'sec' ? AlignmentType.RIGHT : AlignmentType.CENTER })], w[0]),
      cell([new Paragraph({ spacing: { after: 0 }, indent: { left: r.kind === 'sec' ? 360 : 0 }, children: [new TextRun({ text: r.title, font: FONT, size: 24, bold })] })], w[1]),
      cell([cellPara(P(r.key, '00'), { bold, size: 24, align: AlignmentType.CENTER })], w[2]),
    ] }));
  }
  return new Table({ width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: w, borders: allBorders, rows });
}
const toc = [
  fmHeading('TABLE OF CONTENTS'),
  tocLine('LIST OF ABBREVIATIONS', 'fm_abbr'),
  tocLine('LIST OF FIGURES', 'fm_figs'),
  tocLine('LIST OF TABLES', 'fm_tabs'),
  tocLine('NOMENCLATURE', 'fm_nom'),
  ...blank(1),
  new Paragraph({ spacing: { after: 120 }, tabStops: [{ type: TabStopType.CENTER, position: TEXT_W / 2 }, { type: TabStopType.RIGHT, position: TEXT_W }],
    children: [new TextRun({ text: 'CHAPTER\tTITLE\tPAGE NO.', font: FONT, size: 24, bold: true })] }),
  tocTable(),
];

function listTable(head, widths, rows) {
  return new Table({ width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: widths, borders: noBorders,
    rows: [new TableRow({ tableHeader: true, children: head.map((h, i) => cell([cellPara(h, { bold: true, size: 24, align: i === 1 ? AlignmentType.LEFT : AlignmentType.CENTER })], widths[i])) }),
      ...rows.map(r => new TableRow({ cantSplit: true, children: r.map((c, i) => cell([cellPara(c, { size: 24, align: i === 1 ? AlignmentType.LEFT : AlignmentType.CENTER })], widths[i])) }))] });
}
const ABBR = [
  ['AIOps', 'Artificial Intelligence for IT Operations'], ['API', 'Application Programming Interface'], ['APR', 'Automated Program Repair'],
  ['CI/CD', 'Continuous Integration / Continuous Deployment'], ['CNF', 'Conjunctive Normal Form'], ['COCOMO', 'Constructive Cost Model'],
  ['DFD', 'Data Flow Diagram'], ['FSM', 'Finite-State Machine'], ['GPU', 'Graphics Processing Unit'], ['HTTP', 'Hypertext Transfer Protocol'],
  ['HTTPS', 'Hypertext Transfer Protocol Secure'], ['JSON', 'JavaScript Object Notation'], ['KLOC', 'Thousand Lines of Code'], ['LLM', 'Large Language Model'],
  ['LOC', 'Lines of Code'], ['LSTM', 'Long Short-Term Memory'], ['MTTR', 'Mean Time to Resolution'], ['MVP', 'Minimum Viable Product'],
  ['ORM', 'Object-Relational Mapper'], ['RAM', 'Random Access Memory'], ['RCA', 'Root-Cause Analysis'], ['REST', 'Representational State Transfer'],
  ['SAT', 'Boolean Satisfiability Problem'], ['SDK', 'Software Development Kit'], ['SDLC', 'Software Development Life Cycle'], ['SHA', 'Secure Hash Algorithm (commit identifier)'],
  ['SRE', 'Site Reliability Engineer'], ['SSD', 'Solid-State Drive'], ['UML', 'Unified Modeling Language'], ['VRAM', 'Video Random Access Memory'], ['WAL', 'Write-Ahead Logging'],
];
const NOM = [
  ['S', 'The system, S = { s, e, X, Y, F, DD, NDD, Sc, Fc }'], ['X, Y, F', 'Sets of inputs, outputs and functions'], ['L', 'Stream of log events; l ∈ L is one event'],
  ['C, D', 'Sets of recent commits and deployments'], ['τ(l)', 'Template of event l (variable values masked)'], ['s(l)', 'Signature of event l'],
  ['h', 'Hash function used to compute signatures'], ['W, B', 'Detection window (60 s) and baseline period (30 min)'], ['c_t(s)', 'Occurrences of signature s in the current window'],
  ['b(s)', 'Average occurrences of s per window over the baseline'], ['m, ρ', 'Minimum count (5) and spike ratio (3)'], ['f_k(c)', 'Value (0 or 1) of correlation signal k for commit c'],
  ['w_k', 'Weight of correlation signal k'], ['λ(c)', 'Damping factor for code already running before the errors (0.5 or 1)'], ['S(c)', 'Suspicion score of commit c'],
  ['c*', 'Top-ranked suspect commit'], ['E, R', 'Evidence pack and root-cause report'], ['κ(R)', 'Confidence of report R'], ['P', 'Candidate patch'],
  ['V(P)', 'Validation result of patch P (1 = passed)'], ['A', 'Human approval decision'], ['sha(·)', 'Commit identifier of a patch or approval'],
  ['N', 'Maximum number of AI patch attempts (2)'], ['M = (Q, Σ, δ, q₀, F)', 'Finite automaton of the incident life cycle'], ['E (COCOMO)', 'Effort in person-months; D: duration in months'],
];
const nomRows = NOM.map(([a, b]) => [a, b]);
const lists = [
  fmHeading('LIST OF ABBREVIATIONS'), listTable(['ABBREVIATION', 'ILLUSTRATION'], [2400, 6240], ABBR),
  fmHeading('LIST OF FIGURES'), listTable(['FIGURE', 'ILLUSTRATION', 'PAGE NO.'], [1200, 6240, 1200], figList.map(f => [f.no, f.title, P(f.key, '00')])),
  fmHeading('LIST OF TABLES'), listTable(['TABLE', 'ILLUSTRATION', 'PAGE NO.'], [1200, 6240, 1200], tabList.map(f => [f.no, f.title, P(f.key, '00')])),
  fmHeading('NOMENCLATURE'),
  new Table({ width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: [2600, 6040], borders: noBorders,
    rows: [new TableRow({ children: [cell([cellPara('SYMBOL', { bold: true, size: 24, align: AlignmentType.CENTER })], 2600), cell([cellPara('DESCRIPTION', { bold: true, size: 24 })], 6040)] }),
      ...nomRows.map(([a, b]) => new TableRow({ cantSplit: true, children: [cell([new Paragraph({ alignment: AlignmentType.CENTER, children: runs(a, { size: 24 }) })], 2600), cell([cellPara(b, { size: 24 })], 6040)] }))] }),
];

// ------------------------------------------------------------------ sections
const page = {
  size: { width: 12240, height: 15840 },
  margin: { top: 1440, left: 2160, bottom: 1800, right: 1440, footer: 720, header: 720 },
  borders: {
    pageBorderTop: { style: BorderStyle.SINGLE, size: 4, color: '000000', space: 24 },
    pageBorderLeft: { style: BorderStyle.SINGLE, size: 4, color: '000000', space: 24 },
    pageBorderBottom: { style: BorderStyle.SINGLE, size: 4, color: '000000', space: 24 },
    pageBorderRight: { style: BorderStyle.SINGLE, size: 4, color: '000000', space: 24 },
    pageBorders: { display: PageBorderDisplay.ALL_PAGES, offsetFrom: PageBorderOffsetFrom.PAGE },
  },
};
function footer() {
  return new Footer({ children: [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 0 }, children: [new TextRun({ text: 'ADYPSOE, Department of Computer Engineering 2026-27', font: FONT, size: 20 })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 0 }, children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 20 })] }),
  ] });
}
const emptyFooter = new Footer({ children: [new Paragraph({ children: [] })] });

const doc = new Document({
  creator: 'Aditya Bheke, Harshal Bhogawade, Malhar Bhoi',
  title: 'AION: Autonomous Incident Observation and Navigation — Preliminary Project Report',
  description: 'BE Project Work-I preliminary report, Department of Computer Engineering, ADYPSOE, 2026-27',
  styles: {
    default: { document: { run: { font: FONT, size: 24 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 28, bold: true, color: '000000' }, paragraph: { outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 24, bold: true, color: '000000' }, paragraph: { outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 24, bold: true, color: '000000' }, paragraph: { outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    { reference: 'nums', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ] },
  sections: [
    { properties: { page, titlePage: false }, footers: { default: emptyFooter }, children: [...cover, ...certificate] },
    { properties: { page: { ...page, pageNumbers: { start: 1, formatType: NumberFormat.LOWER_ROMAN } }, type: SectionType.NEXT_PAGE }, footers: { default: footer() },
      children: [...ack, ...abstract, ...toc, ...lists] },
    { properties: { page: { ...page, pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL } }, type: SectionType.NEXT_PAGE }, footers: { default: footer() },
      children: [...body, ...refBlocks] },
  ],
});

Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log('wrote', OUT, 'figs', figList.length, 'tables', tabList.length, 'refs', refOrder.length); });
module.exports = { figList, tabList, tocRows };
