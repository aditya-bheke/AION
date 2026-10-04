// Thin wrapper around fetch() for the AION REST API.
//
// The session token lives in sessionStorage: it survives page reloads but is
// dropped when the tab closes. (Trade-off: any script running on the page can
// read it, so the dashboard loads no third-party scripts.)

const TOKEN_KEY = "aion.token";
const listeners = new Set();

export const session = {
  get token() {
    try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set(token) {
    try { token ? sessionStorage.setItem(TOKEN_KEY, token) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
    listeners.forEach((fn) => fn(token));
  },
  onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};

async function request(method, path, body) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !path.endsWith("/auth/login")) session.set(null); // expired or revoked: back to login
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    throw new Error(`${res.status}: ${detail}`);
  }
  return data;
}

export const api = {
  login: (username, password) => request("POST", "/api/auth/login", { username, password }),
  logout: () => request("POST", "/api/auth/logout"),
  me: () => request("GET", "/api/auth/me"),
  system: () => request("GET", "/api/system"),
  incidents: () => request("GET", "/api/incidents"),
  incident: (id) => request("GET", `/api/incidents/${id}`),
  incidentLogs: (id) => request("GET", `/api/incidents/${id}/logs?limit=30`),
  audit: () => request("GET", "/api/audit?limit=300"),
  deployments: () => request("GET", "/api/deployments"),
  approve: (id, comment) => request("POST", `/api/incidents/${id}/approve`, { comment }),
  reject: (id, comment) => request("POST", `/api/incidents/${id}/reject`, { comment }),
  deploy: (id) => request("POST", `/api/incidents/${id}/deploy`),
  rerun: (id) => request("POST", `/api/incidents/${id}/rerun`),
};
