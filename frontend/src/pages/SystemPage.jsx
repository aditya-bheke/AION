import { api } from "../api.js";
import { fmtTime, usePolling } from "../hooks.js";
import { Card, Sha } from "../components/common.jsx";

export default function SystemPage({ system }) {
  const { data: deployments } = usePolling(api.deployments, 5000);
  if (!system) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="page-head"><h1>System</h1></div>
      <div className="grid-2">
        <Card title="AI provider">
          <div className="kv">
            <span>Mode</span><b>{system.llm.mode}</b>
            <span>Provider</span><span>{system.llm.provider || "—"}</span>
            <span>Configured as</span><code>{system.llm.kind}</code>
          </div>
          {system.llm.error && <p className="error">{system.llm.error}</p>}
          {!system.llm.provider && (
            <p className="muted small">
              Without an LLM, AION uses the deterministic analyzer (correlation-ranked root cause) and proposes a
              revert of the suspected commit. Configure <code>ANTHROPIC_API_KEY</code> or an OpenAI-compatible endpoint
              in <code>backend/.env</code> to enable AI analysis and AI-written fixes.
            </p>
          )}
        </Card>
        <Card title="Incident detection">
          <div className="kv">
            <span>Window</span><span>{system.detection.window_seconds}s</span>
            <span>Minimum errors in window</span><span>{system.detection.min_count}</span>
            <span>Baseline period</span><span>{system.detection.baseline_seconds}s</span>
            <span>Spike ratio</span><span>{system.detection.spike_ratio}×</span>
          </div>
        </Card>
        <Card title="Pipeline">
          <div className="kv">
            <span>Automatic investigation</span><span>{system.pipeline.auto_pipeline ? "on" : "off"}</span>
            <span>Max patch attempts</span><span>{system.pipeline.max_patch_attempts}</span>
            <span>Running jobs</span><span>{system.pipeline.running_jobs.join(", ") || "none"}</span>
          </div>
        </Card>
        <Card title="Data">
          <div className="kv">
            <span>Services</span><span>{system.counts.services}</span>
            <span>Log events stored</span><span>{system.counts.log_events}</span>
            <span>Incidents</span><span>{Object.entries(system.counts.incidents).map(([k, v]) => `${k}: ${v}`).join(", ") || "0"}</span>
          </div>
        </Card>
      </div>
      <Card title="Deployment history" subtitle="Recorded by CI/CD (and by AION after human-approved fixes)">
        <table className="table">
          <thead><tr><th>Version</th><th>Commit</th><th>Environment</th><th>Deployed</th><th>By</th><th>Status</th></tr></thead>
          <tbody>
            {(deployments || []).map((d) => (
              <tr key={d.id}>
                <td>{d.version}{d.incident_id && <> · <a href={`#/incidents/${d.incident_id}`}>incident #{d.incident_id}</a></>}</td>
                <td><Sha sha={d.commit_sha} /></td><td>{d.environment}</td><td>{fmtTime(d.deployed_at)}</td>
                <td>{d.deployed_by}</td><td>{d.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
