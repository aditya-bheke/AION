// Visual summary of where the incident is in the AION workflow.

function stages(d) {
  const s = d.incident.status;
  const lastVal = d.validations[d.validations.length - 1];
  const after = (list) => list.includes(s);
  return [
    { key: "detect", label: "Detected", state: "done" },
    {
      key: "rca", label: "Root cause",
      state: d.rca ? "done" : s === "analyzing" ? "active" : s === "error" ? "failed" : "todo",
    },
    {
      key: "patch", label: "Patch",
      state: d.patches.some((p) => ["ready", "passed", "failed", "deployed"].includes(p.status)) && s !== "patching"
        ? "done" : s === "patching" ? "active" : s === "validation_failed" && !lastVal ? "failed" : "todo",
    },
    {
      key: "validate", label: "Validation",
      state: s === "validating" ? "active" : lastVal?.status === "passed" ? "done"
        : lastVal?.status === "failed" ? "failed" : "todo",
    },
    {
      key: "approve", label: "Human approval",
      state: after(["approved", "deploying", "resolved", "deploy_failed"]) ? "done"
        : s === "awaiting_approval" ? "waiting" : s === "rejected" ? "failed" : "todo",
    },
    {
      key: "deploy", label: "Production",
      state: s === "resolved" ? "done" : s === "deploying" ? "active" : s === "deploy_failed" ? "failed" : "todo",
    },
  ];
}

export default function PipelineStepper({ detail }) {
  return (
    <ol className="stepper">
      {stages(detail).map((st, i) => (
        <li key={st.key} className={`step ${st.state}`}>
          <span className="dot">{st.state === "done" ? "✓" : st.state === "failed" ? "✕" : i + 1}</span>
          <span className="label">{st.label}</span>
          {st.key === "approve" && <span className="lock" title="Production deployment requires a human">🔒</span>}
        </li>
      ))}
    </ol>
  );
}
