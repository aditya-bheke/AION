// Thin wrapper around fetch() for the AION REST API.

async function request(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    throw new Error(`${res.status}: ${detail}`);
  }
  return data;
}

export const api = {
  system: () => request("GET", "/api/system"),
  incidents: () => request("GET", "/api/incidents"),
  incident: (id) => request("GET", `/api/incidents/${id}`),
  incidentLogs: (id) => request("GET", `/api/incidents/${id}/logs?limit=30`),
  audit: () => request("GET", "/api/audit?limit=300"),
  deployments: () => request("GET", "/api/deployments"),
  approve: (id, approver, comment) => request("POST", `/api/incidents/${id}/approve`, { approver, comment }),
  reject: (id, approver, comment) => request("POST", `/api/incidents/${id}/reject`, { approver, comment }),
  deploy: (id, actor) => request("POST", `/api/incidents/${id}/deploy`, { actor }),
  rerun: (id, actor) => request("POST", `/api/incidents/${id}/rerun`, { actor }),
};
