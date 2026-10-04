// Builds the AION project synopsis in the NextHire synopsis layout, using real
// styles, list numbering and page-flow controls instead of spaces/blank lines.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
  WidthType, AlignmentType, LevelFormat, BorderStyle, ExternalHyperlink,
  Footer, PageNumber, VerticalAlign, TableLayoutType, HeightRule,
  PageBorderDisplay, PageBorderOffsetFrom, PageBorderZOrder, UnderlineType,
} = require('docx');

const FONT = 'Times New Roman';
const DIAG = path.join(__dirname, '..', 'images');
const OUT = process.argv[2] || path.join(__dirname, '..', 'AION_Synopsis.docx');

// ---------------------------------------------------------------- helpers
// "**bold** text" -> runs
function runs(text, base = {}) {
  return text.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map(seg =>
    seg.startsWith('**')
      ? new TextRun({ ...base, text: seg.slice(2, -2), bold: true })
      : new TextRun({ ...base, text: seg }));
}
const BODY_SPACING = { line: 312, after: 120 };

function body(text, opts = {}) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    spacing: opts.spacing || BODY_SPACING,
    indent: opts.indent,
    keepNext: opts.keepNext,
    children: runs(text, opts.run),
  });
}
function bullet(text, opts = {}) {
  return new Paragraph({
    numbering: { reference: opts.ref || 'bullets', level: opts.level || 0 },
    alignment: opts.align || AlignmentType.LEFT,
    spacing: opts.spacing || { line: 312, after: 80 },
    keepNext: opts.keepNext,
    keepLines: true,
    children: runs(text, opts.run),
  });
}
function h1(text, { numbered = true, pageBreak = true } = {}) {
  return new Paragraph({
    style: 'Heading1',
    numbering: numbered ? { reference: 'sections', level: 0 } : undefined,
    pageBreakBefore: pageBreak,
    children: [new TextRun({ text, underline: { type: UnderlineType.SINGLE } })],
  });
}
function h2(text, { numbered = false, pageBreak = false } = {}) {
  return new Paragraph({
    style: 'Heading2',
    numbering: numbered ? { reference: 'sections', level: 1 } : undefined,
    pageBreakBefore: pageBreak,
    children: [new TextRun({ text, underline: { type: UnderlineType.SINGLE } })],
  });
}
function group(text) {            // "❖ FRONTEND:" style sub-groups
  return new Paragraph({
    style: 'Heading3',
    numbering: { reference: 'diamond', level: 0 },
    children: [new TextRun(text)],
  });
}
function image(file, widthIn) {
  const buf = fs.readFileSync(path.join(DIAG, file));
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  const wpx = Math.round(widthIn * 96);
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 120, after: 120 },
    children: [new ImageRun({ type: 'png', data: buf, transformation: { width: wpx, height: Math.round(wpx * h / w) },
      altText: { title: file, description: file, name: file } })],
  });
}
const link = (url, text) => new ExternalHyperlink({ link: url, children: [new TextRun({ text: text || url, style: 'Hyperlink' })] });

// ---------------------------------------------------------------- cover page
const center = (text, size, bold, before = 0, after = 0) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before, after },
  children: [new TextRun({ text, size, bold })],
});
const cover = [
  center('Project Proposal', 52, true, 360, 720),
  center('AION', 40, true, 0, 60),
  center('Autonomous Incident Observation & Navigation', 30, true, 0, 720),
  center('Project work for', 28, false, 0, 120),
  center('B.E. in Computer Engineering', 32, true, 0, 720),
  center('At', 28, false, 0, 120),
  center('Department of Computer Engineering', 32, true, 0, 80),
  center('Ajeenkya D Y Patil School of Engineering, Charholi Bk', 32, true, 0, 720),
  center('Students', 28, false, 0, 200),
  center('330114 - Aditya Bheke', 28, true, 0, 160),
  center('330115 - Harshal Bhogawade', 28, true, 0, 160),
  center('330116 - Malhar Bhoi', 28, true, 0, 720),
  center('Guide', 28, false, 0, 120),
  center('Dr. Yogesh Bahendwar', 32, true, 0, 720),
  center('AY 2026-27', 36, true, 0, 0),
];

// ---------------------------------------------------------------- project details page
function info(label, value, opts = {}) {
  const children = [new TextRun({ text: label, bold: true, size: 28 })];
  if (value) children.push(new TextRun({ text: ' ' + value, size: 28 }));
  return new Paragraph({
    numbering: { reference: 'info', level: 0 },
    spacing: { before: opts.before ?? 200, after: 80, line: 300 },
    pageBreakBefore: opts.pageBreak,
    keepNext: opts.keepNext,
    children,
  });
}
const cellBorder = { style: BorderStyle.SINGLE, size: 4, color: '000000' };
const borders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
const teamCols = [1230, 830, 1500, 1150, 2700, 1270, 680];       // sums to 9360 (6.5")
function teamCell(content, width, header = false) {
  const child = typeof content === 'string'
    ? new TextRun({ text: content, bold: header, size: 20 })
    : content;
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders, verticalAlign: VerticalAlign.CENTER,
    margins: { top: 60, bottom: 60, left: 70, right: 70 },
    children: [new Paragraph({ children: [child] })],
  });
}
const members = [
  ['72331906F', '330114', 'Aditya Bheke', 'aditya.bheke@dypic.in', '7620166066'],
  ['72331908B', '330115', 'Harshal Bhogawade', 'harshal.bhogawade@dypic.in', '9373685636'],
  ['72331910D', '330116', 'Malhar Bhoi', 'malhar.bhoi@dypic.in', '8237832141'],
];
const teamTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: teamCols,
  layout: TableLayoutType.FIXED,
  rows: [
    new TableRow({ tableHeader: true, height: { value: 640, rule: HeightRule.ATLEAST },
      children: ['PRN', 'Roll No', 'Name', 'Role / Task Assigned', 'Email', 'Mobile', 'Sign'].map((t, i) => teamCell(t, teamCols[i], true)) }),
    ...members.map(([prn, roll, name, email, mob]) => new TableRow({ height: { value: 640, rule: HeightRule.ATLEAST },
      children: [teamCell(prn, teamCols[0]), teamCell(roll, teamCols[1]), teamCell(name, teamCols[2]), teamCell('', teamCols[3]),
        teamCell(new ExternalHyperlink({ link: 'mailto:' + email, children: [new TextRun({ text: email, style: 'Hyperlink', size: 20 })] }), teamCols[4]),
        teamCell(mob, teamCols[5]), teamCell('', teamCols[6])] })),
  ],
});
const details = [
  info('Project Group ID:', '42', { pageBreak: true, before: 0 }),
  info('Title of the Project:', 'AION – Autonomous Incident Observation and Navigation'),
  info('Domain:', 'Artificial Intelligence (AIOps), Large Language Models, DevOps (CI/CD), Full Stack Development'),
  info('Team Members:', '', { keepNext: true }),
  new Paragraph({ spacing: { after: 0 }, keepNext: true, children: [] }),
  teamTable,
  info('Sponsorship details, if any (Name, External Guide name and Designation with Signature, e-Mail ID):', 'Not Applicable', { before: 360 }),
  info('Internal Guide Name (with signature of approval):', 'Prof. Anamika Jain'),
  info('Type of Project:', 'Software / Application-Based Project', { keepNext: true }),
  new Paragraph({ indent: { left: 720 }, spacing: { before: 60 }, children: [new TextRun({ text: 'AI-Powered Incident Detection, Root-Cause Analysis and Remediation Platform', size: 28, italics: true })] }),
];

// ---------------------------------------------------------------- abstract + problem definition
const ABS = { spacing: { line: 360, after: 120 }, indent: { firstLine: 720 } };
const abstract = [
  h1('Abstract', { numbered: false, pageBreak: true }),
  body('**AION (Autonomous Incident Observation & Navigation)** is an AI-assisted incident response and remediation platform that reduces the time, effort and risk involved in resolving software production incidents. In conventional incident management, engineers manually inspect large volumes of logs, trace the failure to a recent code change, write and test a fix, and run the deployment pipeline, using several disconnected tools.', ABS),
  body('AION connects these activities in a single, auditable **closed-loop workflow**. It collects structured application logs, deduplicates repeated errors into signatures, and detects incidents as error spikes against a baseline. Each incident is correlated with **Git commit and deployment history** using git blame, deployment timing and code-dependency signals to produce an explainable ranking of suspect commits.', ABS),
  body('A **Large Language Model (LLM)** layer, using the Claude API or a locally hosted model, receives a curated evidence pack and produces an evidence-cited root-cause analysis that is checked for grounding. AION then generates a **candidate code patch** with a regression test on an isolated Git branch, and validates it through syntax checks, a fail-to-pass test, the existing unit tests, a staging deployment and a replay of the failing production requests.', ABS),
  body('AI may investigate, analyse, propose and validate, but **only a human engineer can approve production deployment**, and the approval is bound to the exact commit that passed validation. Every step is recorded in an append-only audit trail, so incidents are resolved faster while deployment stays safe and accountable.', ABS),
  body('**Keywords:** AIOps, Observability, Incident Management, Log Analysis, Root-Cause Analysis, Large Language Models, Automated Program Repair, CI/CD, Human-in-the-Loop, DevOps', { spacing: { line: 312, before: 120, after: 240 } }),
  h1('PROBLEM DEFINITION', { pageBreak: false }),
  body('Design and development of an AI-powered incident observation and remediation platform that collects and analyses production application logs, detects and deduplicates incidents, correlates them with Git commits and deployment history, performs evidence-based root-cause analysis using Large Language Models, generates candidate code patches that are validated through automated testing and staging, and deploys a fix to production only after explicit human approval.', { spacing: { line: 360 } }),
];

// ---------------------------------------------------------------- modules
const modules = [
  ['Log Collection and Normalization', 'Collect application logs from production services and convert them into a uniform, structured form for analysis.', [
    'File-tail log collector for running services',
    'HTTP log-ingest API for external log sources',
    'Normalization of structured JSON log records',
    'Extraction of service, level, message, request and timestamp fields',
    'Parsing of stack traces into individual frames (file, line, function)',
    'Registration of monitored services and recording of deployment events']],
  ['Log Deduplication and Incident Detection', 'Group repeated errors into unique signatures and decide when an error pattern becomes an incident.', [
    'Template masking of variable values such as IDs, numbers and timestamps',
    'Error fingerprinting using the exception type and stack frames',
    'Signature table with occurrence counts and first/last-seen times',
    'Spike detection: current error rate compared with a historical baseline',
    'Configurable detection window, minimum error count and spike ratio',
    'Incident-level deduplication, so repeated errors attach to the open incident',
    'No re-detection from late log lines after an incident is closed']],
  ['Git and Deployment Correlation', 'Identify the code changes that most probably caused the incident.', [
    'Analysis of recent commits and the deployment history of the service',
    'git blame of the failing lines at the deployed revision',
    'Function-level code ranges using Python ast analysis',
    'Deployment-window, file-overlap and code-dependency signals',
    'Explainable weighted scoring with a reason for every signal',
    'Ranked list of suspect commits for the incident']],
  ['AI Root-Cause Analysis', 'Produce an evidence-based explanation of why the incident occurred.', [
    'Curated evidence pack: log clusters, stack trace, deployments, suspect commits, source code and similar past incidents',
    'Stable evidence IDs that the model must cite',
    'Provider-neutral LLM layer (Claude API or a local OpenAI-compatible model)',
    'Structured output that separates observations from inferences',
    'Grounding checks that reject claims not supported by evidence',
    'Confidence score for the diagnosis',
    'Clearly labelled deterministic fallback analyzer when no LLM is configured']],
  ['Incident Report and Ticket Generation', 'Document every incident in a consistent, reviewable format.', [
    'Incident summary: affected service, error signature, impact and timeline',
    'Root cause with cited evidence and the identified culprit commit',
    'Recommended fix together with its validation results',
    'Storage of the exact evidence shown to the AI for later review',
    'Retrieval of similar past incidents and how they were fixed',
    'Ticket creation in an issue tracker such as GitHub Issues or Jira']],
  ['Candidate Patch Generation', 'Generate a reviewable code fix for the diagnosed root cause.', [
    'Isolated Git worktree and branch for every patch attempt',
    'LLM-generated search/replace code edits, shown as a unified diff',
    'Generated regression test that reproduces the incident',
    'Code-enforced patch policy: protected test, CI and dependency files, and limits on files and lines changed',
    'Automatic repair of indentation-only errors in AI edits',
    'Bounded generate–validate–repair loop',
    'git revert of the suspect commit as a fallback fix']],
  ['Automated Validation (CI and Staging)', 'Verify that a candidate patch fixes the incident without breaking existing behaviour.', [
    'Syntax check of every changed file',
    'Fail-to-pass check: the regression test fails on the old code and passes on the fix',
    'Execution of the service’s existing unit-test suite',
    'Deployment of the patched service to staging, with a health check',
    'Replay of the failing production requests and of baseline requests against staging',
    'Step-by-step validation report with logs and timeouts',
    'Validation commands defined by the operator, never by the AI']],
  ['Human Approval Gate', 'Ensure that no change reaches production without an explicit human decision.', [
    'Incident lifecycle implemented as a finite-state machine',
    'No automated transition from “awaiting approval” to deployment',
    'Engineer reviews the evidence, root cause, diff and validation results',
    'Approval bound to the exact validated commit SHA',
    'Approve, reject, or withdraw an approval before deployment',
    'Re-run of the investigation after a failed validation or deployment',
    'Approver name, decision and comments recorded']],
  ['Production Deployment and Verification', 'Deploy the approved fix safely and confirm that the service has recovered.', [
    'Pre-flight checks of the approval, commit and branch state',
    'GitOps-style fast-forward merge of the approved commit',
    'Verification that production is running the approved commit',
    'Replay of the previously failing requests on production',
    'Incident marked resolved only after successful verification',
    'Failed deployments reported back for re-investigation']],
  ['Incident Dashboard and Audit Trail', 'Provide one interface for monitoring incidents and reviewing every step AION takes.', [
    'Incident list with status, service and timestamps',
    'Incident detail view with a live pipeline stepper',
    'Log, evidence and root-cause analysis views',
    'Diff viewer for candidate patches',
    'Approval panel for approve, reject and deploy actions',
    'Append-only audit log of every automated and human action',
    'System status page: services, AI mode and worker health']],
];
function moduleBlock([title, purpose, features], i) {
  const out = [
    new Paragraph({ style: 'Heading3', keepNext: true, keepLines: true, children: [new TextRun(`Module ${i + 1}: ${title}`)] }),
    new Paragraph({ indent: { left: 360 }, spacing: { after: 60, line: 300 }, keepNext: true, keepLines: true,
      children: [new TextRun({ text: 'Purpose: ', bold: true }), new TextRun(purpose)] }),
    new Paragraph({ indent: { left: 360 }, spacing: { after: 40 }, keepNext: true, children: [new TextRun({ text: 'Key Features:', bold: true })] }),
  ];
  features.forEach((f, j) => out.push(bullet(f, { ref: 'modbullets', keepNext: j < features.length - 1,
    spacing: { line: 288, after: j < features.length - 1 ? 20 : 280 } })));
  return out;
}

const section2 = [
  h1('PROCESS DIAGRAM, SYSTEM ARCHITECTURE, MODULES & FUNCTIONALITIES'),
  h2('Process Diagram', { numbered: true }),
  image('process_diagram.png', 5.75),
  h2('System Architecture', { numbered: true, pageBreak: true }),
  image('system_architecture.png', 6.4),
  h2('Modules', { numbered: true, pageBreak: true }),
  ...modules.flatMap(moduleBlock),
];

// ---------------------------------------------------------------- literature survey
const products = [
  ['ELK Stack (Elasticsearch, Logstash, Kibana)',
    'Collects, indexes, searches and visualises large volumes of application logs, with dashboards and alerting.',
    'Focused on log storage, search and visualisation; root-cause analysis, code fixing and validation of the fix remain manual work for engineers.'],
  ['Sentry',
    'Groups application errors with their stack traces, links them to releases and suspect commits, and offers AI-assisted issue analysis and fix suggestions.',
    'Fixes are proposed as code changes or pull requests; staging validation with request replay, an approval gate bound to the validated commit, and verified production deployment are left to the team’s own CI/CD process.'],
  ['PagerDuty',
    'Provides alerting, on-call scheduling, incident coordination and event grouping that reduces alert noise.',
    'Concentrates on notifying and coordinating responders; finding the faulty code change and writing, testing and deploying a fix are left to the engineers.'],
];
const roman = ['I', 'II', 'III', 'IV'];
const literature = [
  h1('LITERATURE SURVEY'),
  body('Modern software systems generate very large volumes of logs, metrics and alerts. Research in **AIOps**, the application of artificial intelligence to IT operations, studies how this data can support failure management: failure prevention, detection, root-cause analysis and remediation [1], [12].'),
  body('Early work focused on understanding logs. Log-parsing techniques such as Drain convert raw log lines into structured templates using a fixed-depth parse tree [2], while deep-learning approaches such as DeepLog [3] and LogAnomaly [4] learn normal log sequences and flag deviations as anomalies. Recent studies apply **Large Language Models to log analysis** [13] and demonstrate LLM-based anomaly detection on real-world system logs [14]. These methods detect that something is wrong, but they generally stop at detection.'),
  body('A second line of research addresses **root-cause analysis**. MicroRCA localises the root cause of performance issues in microservices [5], and later work progresses from anomaly detection towards automated log labelling and root-cause analysis [6]. LLM-based approaches for cloud incidents [7] and LLM agents for root-cause analysis [10] show that language models can diagnose incidents when given relevant context, but also expose risks such as hallucinated root causes and telemetry volumes that exceed the model’s context window [15].'),
  body('A third line of research studies **automated program repair**. A systematic review shows the rapid growth of LLM-based repair techniques [9]; RepairAgent demonstrates an autonomous LLM agent that gathers information, proposes fixes and validates them with tests [8]; and a study on vulnerability repair shows that patch-validation feedback improves the quality of LLM-generated fixes [11]. These techniques are, however, usually evaluated on benchmark bugs, disconnected from live production telemetry, deployment history and CI/CD pipelines.'),
  body('Overall, existing research shows a progression from **log monitoring → anomaly detection → root-cause analysis → LLM-based program repair**, but each stage is usually studied and built separately, and validating and safely deploying a fix remain manual. AION combines the stages into one closed-loop workflow: log detection → Git and deployment correlation → evidence-cited root-cause analysis → candidate patch → CI and staging validation → human-approved deployment. Every AI output is checked deterministically and every production change requires human approval.'),
  h2('SIMILAR SYSTEMS / PRODUCTS AVAILABLE:', { pageBreak: true }),
  ...products.flatMap(([name, pros, cons], i) => [
    new Paragraph({ indent: { left: 360 }, spacing: { before: 160, after: 60 }, keepNext: true, children: [new TextRun({ text: `${roman[i]}. ${name}`, bold: true })] }),
    body(`**Pros:** ${pros}`, { indent: { left: 720 }, keepNext: true, spacing: { line: 300, after: 60 } }),
    body(`**Cons:** ${cons}`, { indent: { left: 720 }, spacing: { line: 300, after: 60 } }),
  ]),
];

// ---------------------------------------------------------------- objectives / scope
const OBJ_SPACING = { line: 360, after: 60 };
const objectives = [
  h1('OBJECTIVES'),
  ...[
    'To collect and normalize production application logs from file and HTTP sources.',
    'To group repeated errors into unique signatures using template masking and error fingerprints.',
    'To detect incidents automatically as error spikes against a historical baseline.',
    'To correlate each incident with Git commits and deployment history to identify the probable culprit commit.',
    'To perform evidence-based root-cause analysis using Large Language Models with grounding checks.',
    'To generate a structured incident report and ticket for every detected incident.',
    'To generate candidate code patches as reviewable diffs on isolated Git branches.',
    'To generate regression tests that reproduce the incident and prove the fix.',
    'To validate every patch through syntax checks, unit tests, staging deployment and request replay.',
    'To enforce a human approval gate, bound to the exact validated commit, before production deployment.',
    'To deploy approved fixes and verify the recovery of the production service.',
    'To maintain a complete, append-only audit trail of all automated and human actions.',
    'To support both a cloud LLM (Claude API) and local LLMs, so that sensitive logs can stay on premises.',
    'To evaluate the system on realistic bug scenarios with known root causes.',
    'To provide an integrated dashboard for monitoring and managing the complete incident lifecycle.',
  ].map(t => bullet(t, { spacing: OBJ_SPACING })),
];
const scope = [
  h1('SCOPE OF PROJECT'),
  ...[
    '**Log Ingestion:** Collection and normalization of structured logs from monitored services through file tailing and an HTTP API.',
    '**Incident Detection:** Deduplication of errors into signatures and detection of error spikes against a baseline.',
    '**Change Correlation:** Ranking of suspect commits using Git history and deployment records.',
    '**Root-Cause Analysis:** LLM-based, evidence-cited diagnosis with a deterministic fallback.',
    '**Incident Documentation:** Incident reports and tickets for every detected incident.',
    '**Patch Generation:** AI-generated code fixes with regression tests, or a revert of the suspect commit.',
    '**Automated Validation:** CI-style testing, staging deployment and request replay for each patch.',
    '**Human Approval:** Approve / reject workflow bound to the validated commit.',
    '**Deployment & Verification:** GitOps-style deployment of approved fixes and verification on production.',
    '**Dashboard & Audit:** Web dashboard and append-only audit trail of the full incident lifecycle.',
    '**Evaluation:** Measurement of detection, root-cause and patch accuracy on seeded bug scenarios.',
    '**Boundary of the first version:** Python services and stack traces, with local staging and production environments; Kubernetes, GitHub Actions and other languages are planned extensions.',
  ].map(t => bullet(t, { spacing: { line: 360, after: 100 } })),
];

// ---------------------------------------------------------------- requirements
const req = (items) => items.map(t => bullet(t, { ref: 'reqbullets', spacing: { line: 276, after: 40 } }));
const requirements = [
  h1('SOFTWARE & HARDWARE REQUIREMENTS'),
  h2('HARDWARE REQUIREMENTS:'),
  ...req([
    '**Processor:** Intel Core i5 / AMD Ryzen 5 or equivalent',
    '**RAM:** Minimum 8 GB; recommended 16 GB (for running a local LLM)',
    '**Storage:** SSD with at least 20 GB free space for source code, databases and local model files',
    '**GPU (optional):** NVIDIA GPU with 6 GB or more VRAM for running a local LLM',
    '**Internet:** Stable connection for GitHub and cloud LLM API calls',
    '**Display:** Minimum 1920 × 1080 resolution',
  ]),
  h2('SOFTWARE REQUIREMENTS:'),
  group('FRONTEND:'),
  ...req([
    '**React.js:** Component-based incident dashboard',
    '**Vite:** Development server and production build tool',
    '**JavaScript (JSX):** Frontend logic and interaction',
    '**HTML5 / CSS3:** Page structure, layout and styling',
    '**Fetch API:** REST communication with the backend, with periodic polling for live updates',
  ]),
  group('BACKEND:'),
  ...req([
    '**Python 3.10+:** Primary backend programming language',
    '**FastAPI:** REST APIs with request validation and automatic OpenAPI (Swagger) documentation',
    '**Uvicorn:** ASGI server for the FastAPI application',
    '**Pydantic:** Request and response data validation',
    '**SQLAlchemy 2.0:** Object-relational mapping for database access',
    '**httpx:** HTTP client for LLM providers, health checks and request replay',
    '**pytest:** Unit testing and automated patch validation',
  ]),
  group('DATABASE:'),
  ...req([
    '**SQLite (WAL mode):** Storage of services, log events, signatures, incidents, suspect commits, RCA reports, patches, validation runs, approvals, deployments and audit events',
    '**PostgreSQL (planned):** Multi-worker, production-scale deployments',
  ]),
  group('AI & LLM LAYER:'),
  ...req([
    '**Claude API (Anthropic SDK):** Root-cause analysis and patch generation with structured outputs',
    '**Local LLM (Ollama / LM Studio):** OpenAI-compatible local models such as qwen2.5-coder for offline and private use',
    '**Evidence Pack:** Curated, bounded context with evidence IDs instead of raw log dumps',
    '**Grounding Checks:** Verification that every AI claim cites real evidence',
    '**Deterministic Fallback:** Rule-based analyzer and git revert when no LLM is configured',
  ]),
  group('EXTERNAL INTEGRATIONS:'),
  ...req([
    '**Git:** Commit history, blame, worktrees, branches and reverts',
    '**Observability Sources:** Structured JSON log files and HTTP ingest; Elasticsearch / Kibana (ELK) integration planned',
    '**CI/CD:** Local validation runner; GitHub Actions / Jenkins integration planned',
    '**Deployment:** GitOps-style fast-forward deployment; Kubernetes / ArgoCD planned',
    '**Notifications:** Slack / Microsoft Teams bot (planned)',
  ]),
  group('DEVELOPMENT ENVIRONMENT:'),
  ...req([
    '**Operating System:** Windows / Linux',
    '**IDE:** VS Code',
    '**Version Control:** Git and GitHub',
    '**Runtimes:** Python 3.10+, Node.js 18+ and npm',
    '**API Testing:** Swagger UI / Postman',
    '**Documentation:** Markdown documentation and a technical decision log',
  ]),
  group('SECURITY REQUIREMENTS:'),
  ...req([
    '**Human Approval:** No production deployment without an approval bound to the validated commit SHA',
    '**Patch Policy:** Protected test, CI and dependency files; limits on the files and lines a patch may change',
    '**Isolation:** Separate Git worktree and process, with timeouts, for every patch attempt (container sandbox planned)',
    '**Command Safety:** Validation commands defined by the operator and executed without a shell',
    '**Data Protection:** Local LLM option for sensitive logs; secret and PII redaction before prompting (planned)',
    '**Access Control:** Authentication and role-based approver access (planned)',
    '**Auditability:** Append-only audit trail of every action',
  ]),
];

// ---------------------------------------------------------------- outcomes, date, references
const outcomes = [
  ['Automatic Incident Detection', 'Detect production incidents automatically from application logs, grouping repeated errors into a single incident and filtering out harmless noise.'],
  ['Accurate Change Correlation', 'Rank the commits and deployments most likely to have caused an incident, with an explanation for every score.'],
  ['Evidence-Based Root-Cause Analysis', 'Provide a clear, evidence-cited explanation of the root cause that an engineer can verify quickly.'],
  ['Reviewable Code Fixes', 'Generate candidate patches as readable diffs with regression tests, ready for engineer review.'],
  ['Only Validated Changes Reach Approval', 'Only patches that pass automated tests, staging deployment and request replay are presented for approval.'],
  ['Safe, Human-Approved Deployment', 'Deploy fixes to production only after explicit human approval of the exact validated commit, and verify the recovery.'],
  ['Reduced Resolution Time and Effort', 'Reduce the mean time to resolution (MTTR) and the repetitive manual engineering work during incidents.'],
  ['Complete Auditability', 'Keep a full audit trail of every automated and human action for review and accountability.'],
];
const expected = [
  h1('EXPECTED OUTCOMES'),
  ...outcomes.flatMap(([t, d]) => [
    new Paragraph({ numbering: { reference: 'outcomes', level: 0 }, spacing: { before: 160, after: 40 }, keepNext: true,
      children: [new TextRun({ text: t, bold: true })] }),
    body(d, { indent: { left: 360 }, spacing: { line: 312, after: 60 } }),
  ]),
];

const refs = [
  ['P. Notaro, J. Cardoso, and M. Gerndt, “A Survey of AIOps Methods for Failure Management,” ACM Transactions on Intelligent Systems and Technology, vol. 12, no. 6, Art. no. 81, 2021.', 'https://doi.org/10.1145/3483424'],
  ['P. He, J. Zhu, Z. Zheng, and M. R. Lyu, “Drain: An Online Log Parsing Approach with Fixed Depth Tree,” in Proc. IEEE International Conference on Web Services (ICWS), 2017, pp. 33–40.', 'https://doi.org/10.1109/ICWS.2017.13'],
  ['M. Du, F. Li, G. Zheng, and V. Srikumar, “DeepLog: Anomaly Detection and Diagnosis from System Logs through Deep Learning,” in Proc. ACM SIGSAC Conference on Computer and Communications Security (CCS), 2017, pp. 1285–1298.', 'https://doi.org/10.1145/3133956.3134015'],
  ['W. Meng et al., “LogAnomaly: Unsupervised Detection of Sequential and Quantitative Anomalies in Unstructured Logs,” in Proc. International Joint Conference on Artificial Intelligence (IJCAI), 2019, pp. 4739–4745.', 'https://doi.org/10.24963/ijcai.2019/658'],
  ['L. Wu, J. Tordsson, E. Elmroth, and O. Kao, “MicroRCA: Root Cause Localization of Performance Issues in Microservices,” in Proc. IEEE/IFIP Network Operations and Management Symposium (NOMS), 2020.', null],
  ['T. Wittkopp, A. Acker, and O. Kao, “Progressing from Anomaly Detection to Automated Log Labeling and Pioneering Root Cause Analysis,” in Proc. AIOps Workshop, IEEE International Conference on Data Mining (ICDM), 2023.', 'https://arxiv.org/abs/2312.14748'],
  ['Y. Chen et al., “Automatic Root Cause Analysis via Large Language Models for Cloud Incidents,” in Proc. European Conference on Computer Systems (EuroSys), 2024.', null],
  ['I. Bouzenia, P. Devanbu, and M. Pradel, “RepairAgent: An Autonomous, LLM-Based Agent for Program Repair,” in Proc. IEEE/ACM International Conference on Software Engineering (ICSE), 2025.', 'https://arxiv.org/abs/2403.17134'],
  ['Q. Zhang et al., “A Systematic Literature Review on Large Language Models for Automated Program Repair,” arXiv:2405.01466, 2024.', 'https://arxiv.org/abs/2405.01466'],
  ['D. Roy et al., “Exploring LLM-based Agents for Root Cause Analysis,” in Proc. ACM International Conference on the Foundations of Software Engineering (FSE), 2024.', null],
  ['U. Kulsum, H. Zhu, B. Xu, and M. d’Amorim, “A Case Study of LLM for Automated Vulnerability Repair: Assessing Impact of Reasoning and Patch Validation Feedback,” in Proc. 1st ACM International Conference on AI-Powered Software (AIware), 2024.', 'https://arxiv.org/abs/2405.15690'],
  ['L. Zhang, T. Jia, M. Jia, et al., “A Survey of AIOps in the Era of Large Language Models,” ACM Computing Surveys, 2026.', 'https://doi.org/10.1145/3746635'],
  ['Z. Ma, J. Yang, and T.-H. Chen, “LLM4Log: A Systematic Review of Large Language Model-based Log Analysis,” arXiv:2604.16359, 2026.', 'https://arxiv.org/abs/2604.16359'],
  ['M. De la Cruz Cabello, T. P. Sales, and M. R. Machado, “Log Anomaly Detection in AIOps: A Real-World Implementation Using Large Language Models,” Systems and Soft Computing, vol. 8, Art. no. 200475, 2026.', 'https://doi.org/10.1016/j.sasc.2026.200475'],
  ['“Integrating Large Language Models with Cloud-Native Observability for Automated Root Cause Analysis and Remediation,” in Proc. 3rd International Conference on Artificial Intelligence, Systems and Network Security, 2025.', 'https://doi.org/10.1145/3797161.3797213'],
];
const noBorder = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };
const signCell = text => new TableCell({ width: { size: 3120, type: WidthType.DXA }, borders: noBorders,
  children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text, bold: true })] })] });
const closing = [
  h1('PROBABLE DATE OF COMPLETION'),
  new Paragraph({ indent: { left: 450 }, spacing: { before: 120, after: 80 }, children: [new TextRun({ text: 'Academic Year 2026–27', bold: true, size: 28 })] }),
  body('The project is planned for completion within the academic year, covering system design, development, integration, testing, evaluation and final documentation.', { indent: { left: 450 }, spacing: { line: 312, after: 360 } }),
  h1('REFERENCES', { pageBreak: false }),
  ...refs.map(([text, url]) => new Paragraph({
    numbering: { reference: 'refs', level: 0 }, alignment: AlignmentType.LEFT,
    spacing: { line: 288, after: 100 }, keepLines: true,
    children: [new TextRun(text + (url ? ' Available: ' : '')), ...(url ? [link(url)] : [])],
  })),
  new Paragraph({ spacing: { before: 1200 }, keepNext: true, children: [] }),
  new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [3120, 3120, 3120],
    borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder, insideHorizontal: noBorder, insideVertical: noBorder },
    rows: [new TableRow({ cantSplit: true, children: [signCell('Name & Sign of Student'), signCell('Name & Sign of Guide'), signCell('Name & Sign of HoD')] })] }),
];

// ---------------------------------------------------------------- document
const pageBorder = { style: BorderStyle.DOUBLE, size: 4, color: '000000', space: 24 };
const bulletLevel = (left, glyph = '•', font) => ({
  level: 0, format: LevelFormat.BULLET, text: glyph, alignment: AlignmentType.LEFT,
  style: { paragraph: { indent: { left, hanging: 360 } }, run: font ? { font } : undefined },
});

const doc = new Document({
  creator: 'Aditya Bheke, Harshal Bhogawade, Malhar Bhoi',
  title: 'AION – Project Synopsis',
  description: 'Project proposal / synopsis for AION – Autonomous Incident Observation & Navigation',
  styles: {
    default: { document: { run: { font: FONT, size: 24 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 32, bold: true, color: '000000' },
        paragraph: { spacing: { before: 0, after: 240 }, keepNext: true, keepLines: true, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 28, bold: true, color: '000000' },
        paragraph: { spacing: { before: 240, after: 160 }, keepNext: true, keepLines: true, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 26, bold: true, color: '000000' },
        paragraph: { spacing: { before: 200, after: 80 }, keepNext: true, keepLines: true, outlineLevel: 2 } },
    ],
    characterStyles: [
      { id: 'Hyperlink', name: 'Hyperlink', run: { color: '0563C1', underline: { type: UnderlineType.SINGLE } } },
    ],
  },
  numbering: {
    config: [
      { reference: 'info', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 450, hanging: 450 } }, run: { bold: true, size: 28 } } }] },
      { reference: 'sections', levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 450, hanging: 450 } } } },
        { level: 1, format: LevelFormat.LOWER_LETTER, text: '%2)', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 810, hanging: 360 } } } },
      ] },
      { reference: 'bullets', levels: [bulletLevel(810)] },
      { reference: 'modbullets', levels: [bulletLevel(1080)] },
      { reference: 'reqbullets', levels: [bulletLevel(1170)] },
      { reference: 'diamond', levels: [{ ...bulletLevel(810, '❖', 'Segoe UI Symbol') }] },
      { reference: 'outcomes', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1)', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 360, hanging: 360 } }, run: { bold: true } } }] },
      { reference: 'refs', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '[%1]', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 540 } } } }] },
    ],
  },
  sections: [{
    properties: {
      titlePage: true,
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440, header: 720, footer: 720 },
        borders: {
          pageBorders: { display: PageBorderDisplay.ALL_PAGES, offsetFrom: PageBorderOffsetFrom.PAGE, zOrder: PageBorderZOrder.FRONT },
          pageBorderTop: pageBorder, pageBorderRight: pageBorder, pageBorderBottom: pageBorder, pageBorderLeft: pageBorder,
        },
      },
    },
    footers: {
      default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 20 })] })] }),
      first: new Footer({ children: [new Paragraph({ children: [] })] }),
    },
    children: [...cover, ...details, ...abstract, ...section2, ...literature, ...objectives, ...scope, ...requirements, ...expected, ...closing],
  }],
});

Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log('wrote', OUT); });
