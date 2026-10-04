import { useState } from "react";
import { api, session } from "../api.js";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.login(username.trim(), password);
      session.set(res.token);
      onLogin({ ...res.user, required_approvals: (await api.me()).required_approvals });
    } catch (err) {
      setError(err.message.replace(/^\d+: /, ""));
    } finally {
      setBusy(false);
      setPassword("");
    }
  };

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand login-brand"><span className="brand-mark">◆</span> AION</div>
        <p className="muted small">Sign in to review incidents. Approving and deploying fixes requires the <b>approver</b> role.</p>
        <label>Username<input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <p className="error">{error}</p>}
        <button className="btn primary" disabled={busy || !username || !password}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="muted small">No account? An admin creates one with <code>python -m aion.cli users add</code>.</p>
      </form>
    </div>
  );
}
