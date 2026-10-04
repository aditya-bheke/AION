import { useState } from "react";
import { api } from "../api.js";
import { Sha } from "./common.jsx";

// Remembering the approver's name is a convenience only; storage may be unavailable.
const storage = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
};

// The human-in-the-loop control. It is the only place in the UI that can move
// an incident towards production, and it always names the exact commit.
export default function ApprovalPanel({ detail, onChange }) {
  const { incident, patches, approvals, deployments, validations } = detail;
  const s = incident.status;
  const patch = [...patches].reverse().find((p) => ["passed", "deployed"].includes(p.status));
  const approval = [...approvals].reverse().find((a) => a.decision === "approved");
  const [name, setName] = useState(() => storage.get("aion.approver") || "");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const act = async (fn) => {
    setErr(null);
    if (name.trim().length < 2) return setErr("Enter your name: approvals are recorded in the audit trail.");
    storage.set("aion.approver", name.trim());
    setBusy(true);
    try {
      await fn(name.trim());
      setComment("");
      onChange();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const nameField = (
    <div className="form-row">
      <input placeholder="Your name (recorded in the audit trail)" value={name} onChange={(e) => setName(e.target.value)} />
      <input placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
    </div>
  );

  if (["detected", "analyzing", "patching", "validating"].includes(s)) {
    return (
      <div className="gate gate-busy">
        <div className="gate-title"><span className="spinner" /> AI pipeline running — production is locked</div>
        <p>AION is investigating and preparing a candidate fix. Nothing will be deployed without explicit human approval.</p>
      </div>
    );
  }

  if (s === "awaiting_approval" && patch) {
    const lastVal = validations[validations.length - 1];
    return (
      <div className="gate gate-warn">
        <div className="gate-title">🔒 Human approval required</div>
        <p>
          Patch <b>attempt {patch.attempt}</b> (<Sha sha={patch.commit_sha} n={10} /> on <code>{patch.branch}</code>)
          passed all {lastVal?.steps?.filter((x) => x.status === "passed").length ?? 0} blocking validation checks.
          Review the root cause, the diff and the validation results below. Approving binds your decision to this exact commit.
        </p>
        {nameField}
        <div className="btn-row">
          <button className="btn primary" disabled={busy} onClick={() => act((n) => api.approve(incident.id, n, comment))}>
            Approve patch
          </button>
          <button className="btn danger" disabled={busy} onClick={() => act((n) => api.reject(incident.id, n, comment))}>
            Reject
          </button>
        </div>
        {err && <p className="error">{err}</p>}
      </div>
    );
  }

  if (s === "approved") {
    return (
      <div className="gate gate-good">
        <div className="gate-title">✓ Approved by {approval?.approver} — ready to deploy</div>
        <p>
          Deploying fast-forwards the production branch to <Sha sha={approval?.commit_sha} n={10} />, then AION verifies
          production health and replays the requests that failed during the incident.
        </p>
        {nameField}
        <div className="btn-row">
          <button className="btn primary" disabled={busy} onClick={() => act((n) => api.deploy(incident.id, n))}>
            Deploy to production
          </button>
          <button className="btn ghost" disabled={busy} onClick={() => act((n) => api.reject(incident.id, n, comment || "withdrawn before deploy"))}>
            Withdraw approval
          </button>
        </div>
        {err && <p className="error">{err}</p>}
      </div>
    );
  }

  if (s === "deploying") {
    return (
      <div className="gate gate-busy">
        <div className="gate-title"><span className="spinner" /> Deploying approved fix and verifying production…</div>
      </div>
    );
  }

  if (s === "resolved") {
    const dep = deployments[deployments.length - 1];
    return (
      <div className="gate gate-good">
        <div className="gate-title">✓ Resolved — fix deployed and verified in production</div>
        <p>
          Deployment <b>{dep?.version}</b> (<Sha sha={dep?.commit_sha} />) by <b>{dep?.deployed_by}</b>.
          Approved by <b>{approval?.approver}</b>{approval?.comment ? ` — “${approval.comment}”` : ""}.
        </p>
      </div>
    );
  }

  if (s === "rejected") {
    const rej = [...approvals].reverse().find((a) => a.decision === "rejected");
    return (
      <div className="gate gate-muted">
        <div className="gate-title">Rejected{rej ? ` by ${rej.approver}` : ""}</div>
        {rej?.comment && <p>“{rej.comment}”</p>}
      </div>
    );
  }

  // validation_failed, error, deploy_failed
  const title = { validation_failed: "No patch passed validation", error: "The pipeline stopped with an error",
    deploy_failed: "Deployment failed or was blocked" }[s] || s;
  return (
    <div className="gate gate-bad">
      <div className="gate-title">✕ {title} — human investigation needed</div>
      {incident.pipeline_error && <pre className="pre small">{incident.pipeline_error}</pre>}
      <p>Nothing was deployed. You can re-run the investigation (for example after configuring an LLM) or reject the incident.</p>
      {nameField}
      <div className="btn-row">
        <button className="btn" disabled={busy} onClick={() => act((n) => api.rerun(incident.id, n))}>Re-run investigation</button>
        <button className="btn danger" disabled={busy} onClick={() => act((n) => api.reject(incident.id, n, comment))}>Reject</button>
      </div>
      {err && <p className="error">{err}</p>}
    </div>
  );
}
