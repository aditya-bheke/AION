// Renders a unified diff with added/removed lines highlighted.
export default function DiffView({ diff }) {
  if (!diff) return <p className="muted">No diff.</p>;
  return (
    <pre className="diff">
      {diff.split("\n").map((line, i) => {
        let cls = "";
        if (line.startsWith("diff --git")) cls = "d-file";
        else if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("index ")) cls = "d-meta";
        else if (line.startsWith("@@")) cls = "d-hunk";
        else if (line.startsWith("+")) cls = "d-add";
        else if (line.startsWith("-")) cls = "d-del";
        return <div key={i} className={cls}>{line || " "}</div>;
      })}
    </pre>
  );
}
