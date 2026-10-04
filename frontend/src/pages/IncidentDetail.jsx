import { useState } from "react";
import { api } from "../api.js";
import { fmtTime, usePolling } from "../hooks.js";
import ApprovalPanel from "../components/ApprovalPanel.jsx";
import PipelineStepper from "../components/PipelineStepper.jsx";
import DiffView from "../components/DiffView.jsx";
import { Card, ConfidenceBar, Empty, Pre, Sha, StatusBadge, StepBadge } from "../components/common.jsx";

const TABS = [
  ["rca", "Root cause"],
  ["logs", "Logs"],
  ["correlation", "Git correlation"],
  ["patch", "Patch"],
  ["validation", "Validation"],
  ["evidence", "What the AI saw"],
  ["audit", "Audit trail"],
];

export default function IncidentDetail({ id }) {
  const { data, error, refresh } = usePolling(() => api.incident(id), 2500, [id]);
  const [tab, setTab] = useState("rca");

  if (error && !data) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  const { incident, service } = data;

  return (
    <>
      <a href="#/" className="back">← All incidents</a>
      <div className="incident-head">
        <div>
          <div className="eyebrow">Incident #{incident.id} · {service.name} · severity {incident.severity}</div>
          <h1>{incident.title}</h1>
          <p className="muted small">
            First seen {fmtTime(incident.first_seen)} · last seen {fmtTime(incident.last_seen)} · {incident.event_count} events
          </p>
        </div>
        <StatusBadge status={incident.status} />
      </div>
      <PipelineStepper detail={data} />
      <ApprovalPanel detail={data} onChange={refresh} />

      <div className="tabs">
        {TABS.map(([key, label]) => (
          <button key={key} className={tab === key ? "tab active" : "tab"} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "rca" && <RcaTab data={data} />}
      {tab === "logs" && <LogsTab id={id} incident={incident} />}
      {tab === "correlation" && <CorrelationTab data={data} />}
      {tab === "patch" && <PatchTab data={data} />}
      {tab === "validation" && <ValidationTab data={data} />}
      {tab === "evidence" && <EvidenceTab data={data} />}
      {tab === "audit" && <AuditTab data={data} />}
    </>
  );
}

function RcaTab({ data }) {
  const { rca, incident } = data;
  return (
    <div className="grid-2">
      <Card title="Detection" subtitle="Why AION opened this incident">
        <p>{incident.detection_reason}</p>
        <p className="muted small">Signature <code>{incident.signature}</code></p>
      </Card>
      {!rca ? (
        <Card title="Root-cause analysis"><Empty><span className="spinner" /> Analysis in progress…</Empty></Card>
      ) : (
        <Card title="Probable root cause" subtitle={`Analyzer: ${rca.analyzer}`}>
          <p className="lead">{rca.probable_root_cause}</p>
          <div className="kv">
            <span>Confidence</span><ConfidenceBar value={rca.confidence} />
            <span>Suspected commit</span><Sha sha={rca.suspected_commit} n={10} />
            <span>Affected files</span><span>{rca.affected_files.map((f) => <code key={f} className="chip">{f}</code>)}</span>
          </div>
          {rca.usage?.confidence_rationale && <p className="muted small">{rca.usage.confidence_rationale}</p>}
          <h4>Recommended remediation</h4>
          <p>{rca.remediation}</p>
        </Card>
      )}
      {rca && (
        <>
          <Card title="Observed evidence" subtitle="Facts read directly from the evidence (each cites an evidence ID)">
            <ul className="evidence-list">
              {rca.observed_evidence.map((o, i) => (
                <li key={i}><code className="chip">{o.evidence_id}</code> {o.observation}</li>
              ))}
            </ul>
          </Card>
          <Card title="Inferences" subtitle="Conclusions drawn from the evidence — not direct observations">
            <ul className="evidence-list">
              {rca.inferences.map((inf, i) => (
                <li key={i}>
                  {inf.statement}
                  <div className="muted small">based on {inf.based_on.map((b) => <code key={b} className="chip">{b}</code>)}</div>
                </li>
              ))}
            </ul>
            {rca.usage?.alternative_hypotheses?.length > 0 && (
              <>
                <h4>Alternative hypotheses</h4>
                <ul>{rca.usage.alternative_hypotheses.map((h, i) => <li key={i}>{h}</li>)}</ul>
              </>
            )}
          </Card>
          {rca.grounding_warnings.length > 0 && (
            <Card title="Grounding checks" subtitle="Claims AION could not verify against the evidence or repository" className="span-2">
              <ul>{rca.grounding_warnings.map((w, i) => <li key={i} className="warn-text">{w}</li>)}</ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function LogsTab({ id, incident }) {
  const { data } = usePolling(() => api.incidentLogs(id), 5000, [id]);
  if (!data) return <p className="muted">Loading logs…</p>;
  const sample = data.events.find((e) => e.stack_trace);
  return (
    <>
      <Card
        title="Deduplicated log clusters"
        subtitle={`${data.raw_events_in_window} raw log lines in the incident window collapsed into ${data.clusters.length} templates`}
      >
        <table className="table">
          <thead><tr><th>Level</th><th>Count</th><th>Template</th><th>First ever seen</th></tr></thead>
          <tbody>
            {data.clusters.map((c) => (
              <tr key={c.signature + c.level} className={c.is_incident ? "row-highlight" : ""}>
                <td><span className={`lvl lvl-${c.level}`}>{c.level}</span></td>
                <td>{c.count}</td>
                <td className="mono small">{c.template}{c.is_incident && <span className="badge small tone-warn">incident</span>}</td>
                <td className="muted small">{fmtTime(c.first_ever_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {sample && (
        <Card title="Representative stack trace">
          <Pre>{sample.stack_trace}</Pre>
        </Card>
      )}
      <Card title="Recent events with this signature" subtitle={`signature ${incident.signature}`}>
        <table className="table">
          <thead><tr><th>Time</th><th>Request</th><th>Message</th></tr></thead>
          <tbody>
            {data.events.map((e) => (
              <tr key={e.id}>
                <td className="small">{fmtTime(e.timestamp)}</td>
                <td className="mono small">{e.request ? `${e.request.method} ${e.request.path}${e.request.query ? "?" + e.request.query : ""} → ${e.request.status}` : "—"}</td>
                <td className="small">{e.exception_type}: {e.exception_message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

function CorrelationTab({ data }) {
  const { suspects, rca } = data;
  if (!suspects.length) return <Card><Empty>No correlated commits yet.</Empty></Card>;
  return (
    <Card title="Suspect commits" subtitle="Ranked by git blame on the failing lines, file overlap with the stack trace, deployment timing and keywords">
      {suspects.map((s) => (
        <div key={s.commit_sha} className={`suspect ${rca?.suspected_commit === s.commit_sha ? "chosen" : ""}`}>
          <div className="suspect-head">
            <Sha sha={s.commit_sha} />
            <b>{s.message.split("\n")[0]}</b>
            {s.deployment_version && <span className="badge small tone-info">{s.deployment_version}</span>}
            {rca?.suspected_commit === s.commit_sha && <span className="badge small tone-warn">chosen by RCA</span>}
            <span className="spacer" />
            <ConfidenceBar value={s.score} />
          </div>
          <div className="muted small">{s.author} · {fmtTime(s.authored_at)} · {s.files_changed.join(", ")}</div>
          <ul className="reasons">{s.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
      ))}
    </Card>
  );
}

function PatchTab({ data }) {
  const { patches } = data;
  const [sel, setSel] = useState(null);
  if (!patches.length) return <Card><Empty>No patch generated yet.</Empty></Card>;
  const p = patches.find((x) => x.id === sel) || patches[patches.length - 1];
  return (
    <>
      {patches.length > 1 && (
        <div className="btn-row">
          {patches.map((x) => (
            <button key={x.id} className={`btn small ${x.id === p.id ? "primary" : "ghost"}`} onClick={() => setSel(x.id)}>
              Attempt {x.attempt} · {x.status}
            </button>
          ))}
        </div>
      )}
      <Card
        title={`Attempt ${p.attempt}: ${p.strategy === "revert" ? "revert suspected commit" : "AI-generated edit"}`}
        subtitle={`Generator: ${p.generator} · branch ${p.branch || "—"}`}
        actions={<StepBadge status={p.status === "passed" || p.status === "deployed" ? "passed" : p.status === "failed" ? "failed" : p.status} />}
      >
        {p.error && <p className="error">{p.error}</p>}
        <div className="kv">
          <span>Base commit</span><Sha sha={p.base_sha} n={10} />
          <span>Patch commit</span><Sha sha={p.commit_sha} n={10} />
        </div>
        <h4>Rationale</h4>
        <p className="pre-wrap">{p.rationale || "—"}</p>
        <h4>Diff</h4>
        <DiffView diff={p.diff} />
      </Card>
    </>
  );
}

function ValidationTab({ data }) {
  const { validations } = data;
  const [open, setOpen] = useState({});
  if (!validations.length) return <Card><Empty>Validation has not started.</Empty></Card>;
  return validations.slice().reverse().map((v) => (
    <Card key={v.id} title={`Validation run #${v.id} (patch ${v.patch_id})`} subtitle={`Started ${fmtTime(v.started_at)}`}
      actions={<StepBadge status={v.status} />}>
      {v.steps.map((s) => (
        <div key={s.name} className="vstep">
          <div className="vstep-head" onClick={() => setOpen({ ...open, [v.id + s.name]: !open[v.id + s.name] })}>
            <StepBadge status={s.status} />
            <b>{s.title}</b>{!s.blocking && <span className="muted small"> (advisory)</span>}
            <span className="muted small">{s.summary}</span>
            <span className="spacer" />
            <span className="muted small">{s.duration_ms ? `${(s.duration_ms / 1000).toFixed(1)}s` : ""}</span>
          </div>
          {s.name === "replay_requests" && s.details?.results && (
            <table className="table compact">
              <tbody>
                {s.details.results.map((r, i) => (
                  <tr key={i}>
                    <td>{r.ok ? "✓" : "✕"}</td><td className="small">{r.kind}</td>
                    <td className="mono small">{r.request}</td><td className="small">{r.status}</td>
                    <td className="muted small">{r.expected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {open[v.id + s.name] && s.output && <Pre className="small">{s.output}</Pre>}
        </div>
      ))}
    </Card>
  ));
}

function EvidenceTab({ data }) {
  const pack = data.rca?.evidence_pack;
  if (!pack) return <Card><Empty>No evidence pack yet.</Empty></Card>;
  const redactions = Object.entries(pack.redactions || {});
  return (
    <>
      <Card title="Privacy: redaction before the AI" subtitle="Secrets and personal data are masked before anything is sent to a model">
        {pack.redactions === undefined ? (
          <p className="muted">Redaction was disabled for this analysis (AION_REDACT_PROMPTS=false).</p>
        ) : redactions.length ? (
          <p>Masked before sending: {redactions.map(([kind, n]) => <code key={kind} className="chip">{kind} × {n}</code>)}
            <span className="muted small"> — shown below as <code>[REDACTED:kind]</code>.</span></p>
        ) : (
          <p className="muted">Checked: no secrets or personal data found in this evidence.</p>
        )}
      </Card>
      <Card title="Evidence pack" subtitle={`Exactly what the analyzer received: ${pack.evidence.length} items, built from ${pack.stats.raw_warning_and_error_events_in_window} warning/error log lines`}>
        {pack.evidence.map((e) => (
          <details key={e.id} className="evidence-item">
            <summary><code className="chip">{e.id}</code> {e.kind} {e.classification ? `· ${e.classification}` : ""}{e.message ? `· ${e.message.split("\n")[0]}` : ""}{e.file ? `· ${e.file}` : ""}</summary>
            <Pre className="small">{JSON.stringify(e, null, 2)}</Pre>
          </details>
        ))}
      </Card>
      {data.rca.raw_response && (
        <Card title="Raw model response" subtitle="Before grounding checks">
          <Pre className="small">{data.rca.raw_response}</Pre>
        </Card>
      )}
    </>
  );
}

function AuditTab({ data }) {
  return (
    <Card title="Audit trail" subtitle="Append-only record of every automated and human action on this incident">
      <AuditTable rows={data.audit} />
    </Card>
  );
}

export function AuditTable({ rows, showIncident = false }) {
  return (
    <table className="table">
      <thead><tr><th>Time</th>{showIncident && <th>Incident</th>}<th>Actor</th><th>Action</th><th>Details</th></tr></thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.id}>
            <td className="small nowrap">{fmtTime(a.timestamp)}</td>
            {showIncident && <td>{a.incident_id ? <a href={`#/incidents/${a.incident_id}`}>#{a.incident_id}</a> : "—"}</td>}
            <td><span className={`actor actor-${a.actor.split(":")[0]}`}>{a.actor}</span></td>
            <td className="nowrap">{a.action.replaceAll("_", " ")}</td>
            <td className="mono small details-cell">{summarize(a)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function summarize(a) {
  const d = a.details || {};
  if (a.action === "status_changed") return `${d.from_status} → ${d.to_status}${d.comment ? ` · “${d.comment}”` : ""}${d.reason ? ` · ${d.reason}` : ""}`;
  return Object.entries(d).filter(([, v]) => v !== null && v !== "" && typeof v !== "object")
    .map(([k, v]) => `${k}=${String(v).slice(0, 60)}`).join("  ");
}
