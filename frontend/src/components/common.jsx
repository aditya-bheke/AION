const STATUS_LABEL = {
  detected: "Detected",
  analyzing: "Analyzing",
  patching: "Generating patch",
  validating: "Validating",
  awaiting_approval: "Awaiting human approval",
  validation_failed: "Validation failed",
  approved: "Approved",
  deploying: "Deploying",
  resolved: "Resolved",
  deploy_failed: "Deploy failed",
  rejected: "Rejected",
  error: "Pipeline error",
};

const STATUS_TONE = {
  detected: "info", analyzing: "busy", patching: "busy", validating: "busy",
  awaiting_approval: "warn", validation_failed: "bad", approved: "good", deploying: "busy",
  resolved: "good", deploy_failed: "bad", rejected: "muted", error: "bad",
};

export function StatusBadge({ status }) {
  return <span className={`badge tone-${STATUS_TONE[status] || "muted"}`}>{STATUS_LABEL[status] || status}</span>;
}

export function StepBadge({ status }) {
  const tone = { passed: "good", failed: "bad", warning: "warn", running: "busy", skipped: "muted", pending: "muted" }[status];
  return <span className={`badge small tone-${tone || "muted"}`}>{status}</span>;
}

export function Card({ title, subtitle, children, actions, className = "" }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            <h3>{title}</h3>
            {subtitle && <p className="muted small">{subtitle}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Sha({ sha, n = 7 }) {
  if (!sha) return <span className="muted">—</span>;
  return <code className="sha" title={sha}>{sha.slice(0, n)}</code>;
}

export function ConfidenceBar({ value }) {
  const pct = Math.round((value || 0) * 100);
  const tone = pct >= 75 ? "good" : pct >= 45 ? "warn" : "bad";
  return (
    <div className="confidence">
      <div className="bar"><div className={`fill tone-bg-${tone}`} style={{ width: `${pct}%` }} /></div>
      <span>{pct}%</span>
    </div>
  );
}

export function Pre({ children, className = "" }) {
  return <pre className={`pre ${className}`}>{children}</pre>;
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}
