import { useEffect, useState } from "react";
import { api } from "../api.js";
import { hasRole, useUser } from "../auth.js";
import { Card } from "./common.jsx";

// Choose how AION gets its AI: API key providers, a local LLM, or the MCP connector.
// The API key is sent once and stored encrypted; the server only ever returns its last 4 characters.
export default function AiProviderCard() {
  const user = useUser();
  const isAdmin = hasRole(user, "admin");
  const [presets, setPresets] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const [p, c] = await Promise.all([api.aiPresets(), api.aiConfig()]);
    setPresets(p);
    setCfg(c);
    setForm({ preset: c.preset || "none", model: c.model || "", base_url: c.base_url || "", api_key: "", effort: c.effort || "high" });
  };
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: e.message })); }, []);
  if (!cfg || !form) return <Card title="AI provider">Loading…</Card>;

  const preset = presets.find((p) => p.id === form.preset) || {};
  const kind = preset.kind;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const run = async (fn, okText) => {
    setBusy(true); setMsg(null);
    try { const r = await fn(); setMsg({ ok: r?.ok ?? true, text: r?.message || okText }); await load(); }
    catch (e) { setMsg({ ok: false, text: e.message.replace(/^\d+: /, "") }); }
    finally { setBusy(false); }
  };
  const save = () => run(() => api.saveAiConfig({
    preset: form.preset, model: form.model, base_url: form.base_url, effort: form.effort,
    // empty field = keep the stored key (the server never reuses a key for a different provider)
    api_key: form.api_key || null,
  }), "Saved. New incidents will use this provider.");

  return (
    <Card title="AI provider" subtitle={`Active: ${cfg.label || cfg.preset}${cfg.model ? " · " + cfg.model : ""} (configured in ${cfg.source === "dashboard" ? "the dashboard" : "backend/.env"})`} className="span-2">
      {cfg.error && <p className="error">{cfg.error}</p>}
      {!isAdmin && <p className="muted small">Only an admin can change the AI provider.</p>}
      <div className="ai-form">
        <label>Provider
          <select value={form.preset} disabled={!isAdmin} onChange={(e) => {
            const p = presets.find((x) => x.id === e.target.value) || {};
            setForm({ ...form, preset: e.target.value, model: p.default_model || "", base_url: p.base_url || "", api_key: "" });
          }}>
            {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        {(kind === "anthropic" || kind === "openai_compat") && (
          <label>Model id<input value={form.model} disabled={!isAdmin} onChange={set("model")}
                                placeholder={preset.default_model || "e.g. the model name from the provider's docs"} /></label>
        )}
        {kind === "openai_compat" && (
          <label>Endpoint URL<input value={form.base_url} disabled={!isAdmin} onChange={set("base_url")}
                                    placeholder="https://…/v1" /></label>
        )}
        {(preset.needs_key || form.preset === "custom") && (
          <label>API key
            <input type="password" autoComplete="off" value={form.api_key} disabled={!isAdmin} onChange={set("api_key")}
                   placeholder={cfg.api_key_set && form.preset === cfg.preset ? `stored (${cfg.api_key_hint}) — leave empty to keep` : "paste the key"} />
          </label>
        )}
        {kind === "anthropic" && (
          <label>Effort
            <select value={form.effort} disabled={!isAdmin} onChange={set("effort")}>
              {["low", "medium", "high", "xhigh", "max"].map((e) => <option key={e}>{e}</option>)}
            </select>
          </label>
        )}
      </div>

      {kind === "mcp" && (
        <div className="mcp-help">
          <p><b>MCP connector:</b> an AI app you already use answers AION's analysis tasks through MCP — no API key in AION.
            The app reads the evidence and submits a root cause / patch; AION validates, grounds and tests it. The app cannot approve or deploy.</p>
          <p className="small">Connected agent: {cfg.mcp.last_agent_seen_seconds_ago == null ? "not seen yet" : `seen ${cfg.mcp.last_agent_seen_seconds_ago}s ago`}
            {" · "}pending tasks: <b>{cfg.mcp.pending_tasks}</b>{!cfg.mcp.agent_token_configured && <span className="error"> · AION_AGENT_TOKEN missing (python -m aion.cli agent-token --write)</span>}</p>
          <pre className="pre small">{`# Claude Code (run once):
claude mcp add aion -- D:\\projects\\AION\\backend\\.venv\\Scripts\\python.exe -m aion.mcp_server
# then ask:  "Check AION for pending tasks and complete them."`}</pre>
        </div>
      )}
      {!cfg.secret_key_configured && <p className="muted small">AION_SECRET_KEY is not set, so API keys cannot be stored from the dashboard (python -m aion.cli secret-key --write).</p>}

      {isAdmin && (
        <div className="btn-row">
          <button className="btn primary" disabled={busy} onClick={save}>Save</button>
          <button className="btn" disabled={busy} onClick={() => run(api.testAi)}>Test connection</button>
          {cfg.source === "dashboard" && <button className="btn ghost" disabled={busy} onClick={() => run(api.resetAiConfig, "Reverted to backend/.env settings.")}>Use .env settings</button>}
        </div>
      )}
      {msg && <p className={msg.ok ? "ok-text" : "error"}>{msg.text}</p>}
    </Card>
  );
}
