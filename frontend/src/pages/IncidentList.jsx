import { api } from "../api.js";
import { ago, fmtTime, usePolling } from "../hooks.js";
import { Card, Empty, StatusBadge } from "../components/common.jsx";

export default function IncidentList() {
  const { data, error } = usePolling(api.incidents, 3000);
  const waiting = (data || []).filter((i) => i.status === "awaiting_approval").length;
  const active = (data || []).filter((i) => !["resolved", "rejected"].includes(i.status)).length;

  return (
    <>
      <div className="page-head">
        <h1>Incidents</h1>
        <div className="kpis">
          <div className="kpi"><b>{active}</b><span>open</span></div>
          <div className={`kpi ${waiting ? "kpi-warn" : ""}`}><b>{waiting}</b><span>awaiting approval</span></div>
          <div className="kpi"><b>{(data || []).filter((i) => i.status === "resolved").length}</b><span>resolved</span></div>
        </div>
      </div>
      {error && <p className="error">Cannot reach the AION API: {error}</p>}
      <Card>
        {data && data.length === 0 ? (
          <Empty>
            <p><b>No incidents yet.</b> AION is watching registered services' logs.</p>
            <p className="muted">Start the demo in another terminal: <code>backend\.venv\Scripts\python demo\run_demo.py --fresh</code></p>
          </Empty>
        ) : (
          <table className="table clickable">
            <thead>
              <tr><th>#</th><th>Status</th><th>Incident</th><th>Service</th><th>Events</th><th>First seen</th><th>Updated</th></tr>
            </thead>
            <tbody>
              {(data || []).map((i) => (
                <tr key={i.id} onClick={() => (window.location.hash = `#/incidents/${i.id}`)}>
                  <td className="muted">{i.id}</td>
                  <td><StatusBadge status={i.status} /></td>
                  <td className="title-cell">{i.title}</td>
                  <td>{i.service}</td>
                  <td>{i.event_count}</td>
                  <td>{fmtTime(i.first_seen)}</td>
                  <td className="muted">{ago(i.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
