import { useState } from "react";
import { api } from "../api.js";
import { hasRole, useUser } from "../auth.js";
import { Sha } from "./common.jsx";

// The human-in-the-loop control. It is the only place in the UI that can move
// an incident towards production, and it always names the exact commit.
// Identity comes from the signed-in session; the backend enforces the roles.
export default function ApprovalPanel({ detail, onChange }) {
  const user = useUser();
  const { incident, patches, approvals, deployments, validations } = detail;
  const s = incident.status;
  const patch = [...patches].reverse().find((p) => ["passed", "deployed"].includes(p.status));
  const approvedBy = patch ? approvals.filter((a) => a.decision === "approved" && a.commit_sha === patch.commit_sha) : [];
  const required = user.required_approvals || 1;
  const canDecide = hasRole(user, "approver");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const act = async (fn) => {
    setErr(null);
    setBusy(true);
    try {
      await fn();
      setComment("");
      onChange();
    } catch (e) {
      setErr(e.message.replace(/^\d+: /, ""));
    } finally {
      setBusy(false);
    }
  };

  const identity = (
    <p className="muted small">
      Acting as <b>{user.display_name}</b> ({user.role}). Your decision is recorded in the audit trail under your account.
    </p>
  );
  const commentField = (
    <div className="form-row">
      <input placeholder="Comment (optional, recorded in the audit trail)" value={comment}
             onChange={(e) => setComment(e.target.value)} />
    </div>
  );
  const notAllowed = !canDecide && (
    <p className="muted small">Your role (<b>{user.role}</b>) can view this incident; an <b>approver</b> must decide.</p>
  );

  if (["detected", "analyzing", "patching", "validating"].includes(s)) {
    const waiting = (detail.ai_tasks || []).filter((t) => ["pending", "claimed"].includes(t.status));
    return (
      <div className="gate gate-busy">
        <div className="gate-title"><span className="spinner" /> AI pipeline running — production is locked</div>
        <p>AION is investigating and preparing a candidate fix. Nothing will be deployed without explicit human approval.</p>
        {waiting.map((t) => (
          <p key={t.task_id} className="small">
            ⏳ Waiting for the AI agent connected over <b>MCP</b>: task #{t.task_id} ({t.purpose === "RCAOutput" ? "root-cause analysis" : t.purpose === "PatchOutput" ? "code fix" : t.purpose}) is <b>{t.status}</b>.
            {t.status === "pending" && " Ask your AI app (e.g. Claude Code) to check AION for pending tasks."}
          </p>
        ))}
      </div>
    );
  }

  if (s === "awaiting_approval" && patch) {
    const lastVal = validations[validations.length - 1];
    const iApproved = approvedBy.some((a) => a.approver === user.username);
    return (
      <div className="gate gate-warn">
        <div className="gate-title">🔒 Human approval required</div>
        <p>
          Patch <b>attempt {patch.attempt}</b> (<Sha sha={patch.commit_sha} n={10} /> on <code>{patch.branch}</code>)
          passed all {lastVal?.steps?.filter((x) => x.status === "passed").length ?? 0} blocking validation checks.
          Review the root cause, the diff and the validation results below. Approving binds your decision to this exact commit.
        </p>
        {required > 1 && (
          <p><b>Two-person rule:</b> {approvedBy.length} of {required} approvals
            {approvedBy.length > 0 && <> ({approvedBy.map((a) => a.approver).join(", ")})</>}.</p>
        )}
        {canDecide ? (
          <>
            {identity}
            {commentField}
            <div className="btn-row">
              <button className="btn primary" disabled={busy || iApproved} onClick={() => act(() => api.approve(incident.id, comment))}>
                {iApproved ? "You approved — waiting for another approver" : "Approve patch"}
              </button>
              <button className="btn danger" disabled={busy} onClick={() => act(() => api.reject(incident.id, comment))}>Reject</button>
            </div>
          </>
        ) : notAllowed}
        {err && <p className="error">{err}</p>}
      </div>
    );
  }

  if (s === "approved") {
    return (
      <div className="gate gate-good">
        <div className="gate-title">✓ Approved by {approvedBy.map((a) => a.approver).join(" and ")} — ready to deploy</div>
        <p>
          Deploying fast-forwards the production branch to <Sha sha={patch?.commit_sha} n={10} />, then AION verifies
          production health and replays the requests that failed during the incident.
        </p>
        {canDecide ? (
          <>
            {identity}
            <div className="btn-row">
              <button className="btn primary" disabled={busy} onClick={() => act(() => api.deploy(incident.id))}>Deploy to production</button>
              <button className="btn ghost" disabled={busy} onClick={() => act(() => api.reject(incident.id, comment || "withdrawn before deploy"))}>
                Withdraw approval
              </button>
            </div>
          </>
        ) : notAllowed}
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
          Approved by <b>{approvedBy.map((a) => a.approver + (a.comment ? ` (“${a.comment}”)` : "")).join(", ")}</b>.
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
      {hasRole(user, "engineer") ? (
        <>
          {canDecide && commentField}
          <div className="btn-row">
            <button className="btn" disabled={busy} onClick={() => act(() => api.rerun(incident.id))}>Re-run investigation</button>
            {canDecide && <button className="btn danger" disabled={busy} onClick={() => act(() => api.reject(incident.id, comment))}>Reject</button>}
          </div>
        </>
      ) : notAllowed}
      {err && <p className="error">{err}</p>}
    </div>
  );
}
