import { useEffect, useState } from "react";
import { api } from "../api.js";
import { hasRole, useUser } from "../auth.js";
import { Card } from "./common.jsx";
import { fmtTime } from "../hooks.js";

// Slack / Discord / webhook notifications. The URL is sent once and stored encrypted.
export default function NotificationsCard() {
  const isAdmin = hasRole(useUser(), "admin");
  const [channels, setChannels] = useState([]);
  const [events, setEvents] = useState([]);
  const [deliveries, setDeliveries] = useState([]);
  const [form, setForm] = useState({ name: "", kind: "slack", url: "", events: ["awaiting_approval", "validation_failed", "deploy_failed", "resolved", "rolled_back"] });
  const [msg, setMsg] = useState(null);

  const load = async () => {
    const [c, e, d] = await Promise.all([api.channels(), api.notifEvents(), api.deliveries()]);
    setChannels(c); setEvents(e); setDeliveries(d);
  };
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: e.message })); }, []);

  const run = async (fn) => {
    setMsg(null);
    try { const r = await fn(); if (r?.message) setMsg({ ok: r.ok, text: r.message }); await load(); }
    catch (e) { setMsg({ ok: false, text: e.message.replace(/^\d+: /, "") }); }
  };
  const toggle = (id) => setForm({ ...form, events: form.events.includes(id) ? form.events.filter((x) => x !== id) : [...form.events, id] });
  const nameOf = (id) => channels.find((c) => c.id === id)?.name || `#${id}`;

  return (
    <Card title="Notifications" subtitle="Tell people when an incident needs them (Slack, Discord or any webhook)" className="span-2">
      {channels.length === 0 && <p className="muted small">No channels yet.</p>}
      {channels.map((c) => (
        <div key={c.id} className="channel-row">
          <b>{c.name}</b> <span className="muted small">{c.kind} · {c.url_hint} · {c.enabled ? c.events.join(", ") : "disabled"}</span>
          {isAdmin && c.enabled && (
            <span className="btn-row inline">
              <button className="btn small" onClick={() => run(() => api.testChannel(c.id))}>Send test</button>
              <button className="btn small ghost" onClick={() => run(() => api.disableChannel(c.id))}>Disable</button>
            </span>
          )}
        </div>
      ))}
      {isAdmin && (
        <div className="channel-form">
          <div className="ai-form">
            <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. on-call" /></label>
            <label>Type
              <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                <option value="slack">Slack incoming webhook</option>
                <option value="discord">Discord webhook</option>
                <option value="webhook">Generic JSON webhook</option>
              </select>
            </label>
            <label>Webhook URL<input type="password" autoComplete="off" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://hooks.slack.com/services/…" /></label>
          </div>
          <div className="checks">
            {events.map((e) => (
              <label key={e.id}><input type="checkbox" checked={form.events.includes(e.id)} onChange={() => toggle(e.id)} /> {e.label}</label>
            ))}
          </div>
          <button className="btn primary" disabled={!form.name || !form.url}
                  onClick={() => run(async () => { await api.addChannel(form); setForm({ ...form, name: "", url: "" }); return { ok: true, message: "Channel added." }; })}>
            Add channel
          </button>
        </div>
      )}
      {msg && <p className={msg.ok ? "ok-text" : "error"}>{msg.text}</p>}
      {deliveries.length > 0 && (
        <details className="evidence-item">
          <summary>Recent deliveries ({deliveries.length})</summary>
          <table className="table compact"><tbody>
            {deliveries.map((d) => (
              <tr key={d.id}><td className="small">{fmtTime(d.created_at)}</td><td>{d.status === "sent" ? "✓" : "✕"}</td>
                <td className="small">{nameOf(d.channel_id)}</td><td className="small">{d.event}</td>
                <td className="small">{d.incident_id ? <a href={`#/incidents/${d.incident_id}`}>#{d.incident_id}</a> : ""}</td>
                <td className="small error">{d.error || ""}</td></tr>
            ))}
          </tbody></table>
        </details>
      )}
    </Card>
  );
}
