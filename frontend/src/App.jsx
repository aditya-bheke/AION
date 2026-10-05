import { useEffect, useState } from "react";
import { api, session } from "./api.js";
import { useHashRoute, usePolling } from "./hooks.js";
import IncidentList from "./pages/IncidentList.jsx";
import IncidentDetail from "./pages/IncidentDetail.jsx";
import AuditLog from "./pages/AuditLog.jsx";
import SystemPage from "./pages/SystemPage.jsx";
import Insights from "./pages/Insights.jsx";
import Login from "./pages/Login.jsx";
import { UserContext } from "./auth.js";

export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(!!session.token);

  useEffect(() => {
    if (session.token) api.me().then(setUser).catch(() => session.set(null)).finally(() => setChecking(false));
    return session.onChange((token) => { if (!token) setUser(null); });
  }, []);

  if (checking) return <div className="center muted">Loading…</div>;
  if (!user) return <Login onLogin={setUser} />;
  return (
    <UserContext.Provider value={user}>
      <Shell user={user} />
    </UserContext.Provider>
  );
}

function Shell({ user }) {
  const route = useHashRoute();
  const { data: system } = usePolling(api.system, 5000);
  const incidentMatch = route.match(/^\/incidents\/(\d+)/);

  let page;
  if (incidentMatch) page = <IncidentDetail id={Number(incidentMatch[1])} />;
  else if (route.startsWith("/audit")) page = <AuditLog />;
  else if (route.startsWith("/system")) page = <SystemPage system={system} />;
  else if (route.startsWith("/insights")) page = <Insights />;
  else page = <IncidentList />;

  const active = (prefix) => (route === prefix || (prefix !== "/" && route.startsWith(prefix)) ? "active" : "");
  const signOut = () => api.logout().catch(() => {}).finally(() => session.set(null));

  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">
          <span className="brand-mark">◆</span> AION
          <span className="brand-sub">Autonomous Incident Observation &amp; Navigation</span>
        </a>
        <nav>
          <a href="#/" className={active("/") || (incidentMatch ? "active" : "")}>Incidents</a>
          <a href="#/insights" className={active("/insights")}>Insights</a>
          <a href="#/audit" className={active("/audit")}>Audit trail</a>
          <a href="#/system" className={active("/system")}>System</a>
        </nav>
        <div className="mode-pill" title="Which analyzer AION is using">
          {system ? (
            system.llm.provider ? <>AI: <b>{system.llm.provider}</b></> : <>AI: <b>heuristic mode (no LLM)</b></>
          ) : "connecting…"}
        </div>
        <div className="user-pill">
          <span title={`role: ${user.role}`}>{user.display_name} · <b>{user.role}</b></span>
          <button className="btn small ghost" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <main className="content">{page}</main>
    </div>
  );
}
