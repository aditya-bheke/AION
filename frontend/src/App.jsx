import { api } from "./api.js";
import { useHashRoute, usePolling } from "./hooks.js";
import IncidentList from "./pages/IncidentList.jsx";
import IncidentDetail from "./pages/IncidentDetail.jsx";
import AuditLog from "./pages/AuditLog.jsx";
import SystemPage from "./pages/SystemPage.jsx";

export default function App() {
  const route = useHashRoute();
  const { data: system } = usePolling(api.system, 5000);
  const incidentMatch = route.match(/^\/incidents\/(\d+)/);

  let page;
  if (incidentMatch) page = <IncidentDetail id={Number(incidentMatch[1])} />;
  else if (route.startsWith("/audit")) page = <AuditLog />;
  else if (route.startsWith("/system")) page = <SystemPage system={system} />;
  else page = <IncidentList />;

  const active = (prefix) => (route === prefix || (prefix !== "/" && route.startsWith(prefix)) ? "active" : "");

  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">
          <span className="brand-mark">◆</span> AION
          <span className="brand-sub">Autonomous Incident Observation &amp; Navigation</span>
        </a>
        <nav>
          <a href="#/" className={active("/") || (incidentMatch ? "active" : "")}>Incidents</a>
          <a href="#/audit" className={active("/audit")}>Audit trail</a>
          <a href="#/system" className={active("/system")}>System</a>
        </nav>
        <div className="mode-pill" title="Which analyzer AION is using">
          {system ? (
            system.llm.provider ? <>AI: <b>{system.llm.provider}</b></> : <>AI: <b>heuristic mode (no LLM)</b></>
          ) : "connecting…"}
        </div>
      </header>
      <main className="content">{page}</main>
    </div>
  );
}
