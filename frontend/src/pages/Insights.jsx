import { api } from "../api.js";
import { usePolling } from "../hooks.js";
import { Card, Empty, StatusBadge } from "../components/common.jsx";

export function fmtDur(s) {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}

const METRICS = [
  ["mttd_s", "MTTD", "first error → incident opened"],
  ["time_to_fix_s", "Time to validated fix", "incident → fix ready for approval (automated)"],
  ["decision_s", "Human decision time", "fix ready → approved"],
  ["deploy_s", "Deploy + verify", "approved → resolved"],
  ["mttr_s", "MTTR", "first error → resolved"],
];

export default function Insights() {
  const { data } = usePolling(() => api.insights(), 10000);
  if (!data) return <p className="muted">Loading…</p>;
  const counts = (obj) => Object.entries(obj || {}).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—";
  return (
    <>
      <div className="page-head"><h1>Insights</h1></div>
      <p className="muted">Computed from recorded timestamps and the audit trail — medians across incidents (mean in brackets).</p>
      <div className="kpis wrap">
        {METRICS.map(([k, label, hint]) => (
          <div className="kpi metric" key={k} title={hint}>
            <b>{fmtDur(data.timings[k].median)}</b>
            <span>{label}</span>
            <small className="muted">{data.timings[k].count ? `n=${data.timings[k].count} (mean ${fmtDur(data.timings[k].mean)})` : "no data yet"}</small>
          </div>
        ))}
      </div>
      <div className="grid-2">
        <Card title="Outcomes">
          <div className="kv">
            <span>Incidents</span><span>{counts(data.incidents_by_status)}</span>
            <span>Rollbacks</span><span>{data.rollbacks}</span>
            <span>Validation runs</span><span>{counts(data.validation_runs)}</span>
          </div>
        </Card>
        <Card title="AI & CI">
          <div className="kv">
            <span>Root-cause analyzer</span><span>{counts(data.rca_analyzers)}</span>
            <span>Patches</span><span>{Object.entries(data.patches_by_strategy).map(([s, st]) => `${s === "llm_edit" ? "AI fix" : s}: ${counts(st)}`).join(" | ") || "—"}</span>
            <span>GitHub Actions</span><span>{counts(data.github_ci)}</span>
          </div>
        </Card>
      </div>
      <Card title="Recent incidents">
        {data.incidents.length === 0 ? <Empty>No incidents yet.</Empty> : (
          <table className="table clickable">
            <thead><tr><th>#</th><th>Status</th><th>Incident</th><th>MTTD</th><th>To fix</th><th>Decision</th><th>Deploy</th><th>MTTR</th></tr></thead>
            <tbody>
              {data.incidents.map((r) => (
                <tr key={r.id} onClick={() => (window.location.hash = `#/incidents/${r.id}`)}>
                  <td className="muted">{r.id}</td><td><StatusBadge status={r.status} /></td>
                  <td className="title-cell">{r.title}</td><td>{fmtDur(r.mttd_s)}</td><td>{fmtDur(r.time_to_fix_s)}</td>
                  <td>{fmtDur(r.decision_s)}</td><td>{fmtDur(r.deploy_s)}</td><td><b>{fmtDur(r.mttr_s)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
