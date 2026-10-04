import { api } from "../api.js";
import { usePolling } from "../hooks.js";
import { Card } from "../components/common.jsx";
import { AuditTable } from "./IncidentDetail.jsx";

export default function AuditLog() {
  const { data } = usePolling(api.audit, 4000);
  return (
    <>
      <div className="page-head"><h1>Audit trail</h1></div>
      <p className="muted">
        Every action is recorded with its actor: <span className="actor actor-system">system:*</span> for deterministic AION
        components, <span className="actor actor-ai">ai:*</span> for language-model output and{" "}
        <span className="actor actor-human">human:*</span> for people. Records are append-only.
      </p>
      <Card>{data ? <AuditTable rows={data} showIncident /> : "Loading…"}</Card>
    </>
  );
}
