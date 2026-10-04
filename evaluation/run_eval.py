"""AION evaluation harness.

Runs every demo scenario through the *real* AION pipeline (detection ->
correlation -> RCA -> patch -> validation) and scores the outcome against the
scenario's known answer (demo/scenarios/*/scenario.json -> "expected").

Each scenario runs in its own temporary workspace and database, so results
are independent and the real workspace/ is untouched. Logs are produced by
running the scenario's real service code (normal traffic + trigger requests).

Usage (from the repository root, with the backend virtualenv):

    backend\\.venv\\Scripts\\python evaluation\\run_eval.py                 # deterministic mode (no LLM)
    backend\\.venv\\Scripts\\python evaluation\\run_eval.py --mode llm      # the LLM configured in backend/.env
    backend\\.venv\\Scripts\\python evaluation\\run_eval.py --scenario supplier-feed --mode llm

Results are written to evaluation/results/<timestamp>-<mode>.{md,json}.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "demo"))
os.environ["AION_ENABLE_BACKGROUND"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from aion.ai.providers.factory import get_provider, set_provider_override  # noqa: E402
from aion.config import settings  # noqa: E402
from aion.db import init_engine  # noqa: E402
from aion.main import create_app  # noqa: E402
from aion.pipeline import orchestrator  # noqa: E402
from demo_repo import build_repo, list_scenarios, load_scenario  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def generate_logs(repo: Path, log_file: Path, trigger: list[list], trigger_count: int = 8) -> list[dict]:
    """Run the scenario's real service in a subprocess: normal traffic, then trigger requests."""
    triggers = [(m, p) for m, p, _ in trigger]
    script = textwrap.dedent(f"""
        import os
        os.environ["SERVICE_LOG_FILE"] = {str(log_file)!r}
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app, raise_server_exceptions=False)
        for i in range(3):
            c.get("/products"); c.get("/products/SKU-1003"); c.get(f"/orders/{{1001 + i}}")
            c.get(f"/orders/{{1002 + i}}/total"); c.get("/orders/1002/total?coupon=WELCOME10")
            c.get("/orders/9999"); c.post(f"/orders/{{1003 + i}}/pay")
        triggers = {triggers!r}
        for i in range({trigger_count} if triggers else 0):
            method, path = triggers[i % len(triggers)]
            c.request(method, path.format(order=1001 + i % 8))
    """)
    subprocess.run([sys.executable, "-c", script], cwd=str(repo), check=True, capture_output=True)
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def _viewer(client) -> dict:
    """Create a throw-away viewer account in the temporary database and sign in."""
    from aion.db import session_scope
    from aion.security import create_user

    password = secrets.token_urlsafe(16)
    with session_scope() as s:
        create_user(s, "eval-viewer", password, "viewer")
    token = client.post("/api/auth/login", json={"username": "eval-viewer", "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def run_scenario(name: str, mode: str) -> dict:
    sc = load_scenario(name)
    work = Path(tempfile.mkdtemp(prefix=f"aion-eval-{name}-"))
    settings.workspace_dir = work / "workspace"
    settings.database_url = f"sqlite:///{(work / 'aion.db').as_posix()}"
    settings.auto_pipeline = False
    settings.service_token = secrets.token_urlsafe(24)  # the harness acts as the machine client
    service = {"Authorization": f"Bearer {settings.service_token}"}
    settings.worktrees_dir.mkdir(parents=True, exist_ok=True)
    init_engine(settings.database_url)
    set_provider_override(None)  # reset the provider cache for this run
    provider = get_provider(settings)
    result: dict = {"scenario": name, "title": sc.title, "mode": mode,
                    "analyzer": provider.name if provider else "heuristic (no LLM)"}
    try:
        repo = work / "orders-service"
        commits = build_repo(repo, scenario=name)
        culprit = next((c.sha for c in commits if c.message.splitlines()[0] == sc.expected.get("culprit")), None)
        with TestClient(create_app(start_background=False)) as client:
            client.post("/api/services", headers=service, json={
                "name": "orders-service", "repo_path": str(repo),
                "test_command": ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                "run_command": ["{python}", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "{port}"],
            }).raise_for_status()
            for c in commits:
                if c.deploy_version:
                    client.post("/api/deployments", headers=service, json={"service": "orders-service",
                                                                          "version": c.deploy_version,
                                                          "commit_sha": c.sha,
                                                          "deployed_at": c.deployed_at.isoformat()}).raise_for_status()
            events = generate_logs(repo, work / "prod.log", sc.trigger)
            ingest = client.post("/api/ingest/orders-service", headers=service, json={"events": events}).json()
            incidents = ingest["new_incidents"]
            result["log_events"] = len(events)
            result["incidents_opened"] = len(incidents)
            result["expected_incident"] = sc.expected.get("incident", True)
            result["detection_correct"] = bool(incidents) == result["expected_incident"]
            if not incidents:
                result["final_status"] = "no incident"
                result["automated_success"] = not result["expected_incident"]
                return result

            started = time.monotonic()
            orchestrator.run_pipeline(incidents[0])
            result["pipeline_seconds"] = round(time.monotonic() - started, 1)
            d = client.get(f"/api/incidents/{incidents[0]}", headers=_viewer(client)).json()

        inc, rca = d["incident"], d["rca"]
        suspects = [s["commit_sha"] for s in d["suspects"]]
        result["title_detected"] = inc["title"]
        result["exception_correct"] = inc["title"].startswith(sc.expected.get("exception_type", ""))
        result["culprit_rank"] = (suspects.index(culprit) + 1) if culprit in suspects else None
        result["top_suspects"] = [{"commit": s["commit_sha"][:7], "score": s["score"],
                                   "message": s["message"].splitlines()[0], "reasons": s["reasons"],
                                   "is_culprit": s["commit_sha"] == culprit} for s in d["suspects"][:3]]
        result["rca_suspected_correct"] = bool(rca and culprit and rca["suspected_commit"] == culprit)
        result["rca_suspected_commit"] = next((s["message"].splitlines()[0] for s in d["suspects"]
                                               if rca and s["commit_sha"] == rca["suspected_commit"]),
                                              "(none named)" if rca else None)
        result["rca_confidence"] = rca["confidence"] if rca else None
        result["rca_root_cause"] = rca["probable_root_cause"] if rca else None
        result["grounding_warnings"] = len(rca["grounding_warnings"]) if rca else None
        patches = d["patches"]
        result["patch_attempts"] = len(patches)
        result["patch_sequence"] = [{"strategy": p["strategy"], "status": p["status"]} for p in patches]
        result["patch_strategy"] = patches[-1]["strategy"] if patches else None
        result["patch_status"] = patches[-1]["status"] if patches else None
        result["patch_error"] = patches[-1]["error"] if patches else None
        steps = d["validations"][-1]["steps"] if d["validations"] else []
        result["validation"] = {s["name"]: s["status"] for s in steps}
        result["patch_diff"] = patches[-1]["diff"][:4000] if patches else None
        failed = next((s for s in steps if s["status"] == "failed"), None)
        result["failed_step"] = ({"name": failed["name"], "summary": failed["summary"],
                                  "output": failed["output"][-2000:]} if failed else None)
        result["final_status"] = inc["status"]
        result["automated_success"] = inc["status"] == "awaiting_approval"
        usage = [rca["usage"] if rca else {}] + [p.get("usage") or {} for p in patches]
        result["input_tokens"] = sum(int(u.get("input_tokens", 0) or 0) for u in usage)
        result["output_tokens"] = sum(int(u.get("output_tokens", 0) or 0) for u in usage)
        return result
    except Exception as exc:  # a crash is a result, not a reason to stop the whole evaluation
        result["final_status"] = "harness error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["automated_success"] = False
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _mark(v) -> str:
    return "—" if v is None else ("✅" if v is True else "❌" if v is False else str(v))


def to_markdown(results: list[dict], mode: str) -> str:
    lines = [
        f"# AION evaluation — {datetime.now():%Y-%m-%d %H:%M} — mode: {mode}",
        "",
        f"Analyzer: `{results[0]['analyzer'] if results else '-'}` · max patch attempts: {settings.max_patch_attempts}",
        "",
        "| Scenario | Detection | Culprit rank (correlation) | RCA names culprit | Confidence | Patch | Regression test | Validation | Final status | Time (s) | Tokens in/out |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        val = r.get("validation") or {}
        blocking_ok = all(val.get(k) == "passed" for k in ("syntax_check", "unit_tests", "staging_deploy", "replay_requests")) if val else None
        lines.append("| {s} | {det} | {rank} | {rca} | {conf} | {patch} | {reg} | {val} | {final} | {t} | {tok} |".format(
            s=r["scenario"], det=_mark(r.get("detection_correct")), rank=_mark(r.get("culprit_rank")),
            rca=_mark(r.get("rca_suspected_correct")) if r.get("incidents_opened") else "—",
            conf=r.get("rca_confidence", "—") if r.get("rca_confidence") is not None else "—",
            patch=" → ".join(("AI" if p["strategy"] == "llm_edit" else "revert")
                             + (" ✓" if p["status"] in ("passed", "deployed") else " ✗")
                             for p in r.get("patch_sequence") or []) or "—",
            reg=val.get("regression_reproduce", "—"), val=_mark(blocking_ok), final=r.get("final_status"),
            t=r.get("pipeline_seconds", "—"),
            tok=f"{r.get('input_tokens', 0)}/{r.get('output_tokens', 0)}" if r.get("input_tokens") else "—"))
    n = len(results)
    lines += [
        "",
        f"**Summary:** detection correct {sum(1 for r in results if r.get('detection_correct'))}/{n} · "
        f"automated pipeline reached the approval gate (or correctly stayed silent) "
        f"{sum(1 for r in results if r.get('automated_success'))}/{n} · "
        f"RCA named the true culprit {sum(1 for r in results if r.get('rca_suspected_correct'))}/"
        f"{sum(1 for r in results if r.get('incidents_opened'))}",
        "",
        "## Details",
    ]
    for r in results:
        lines += ["", f"### {r['scenario']} — {r['title']}", ""]
        if r.get("error"):
            lines.append(f"- **Harness error:** `{r['error']}`")
        if r.get("title_detected"):
            lines.append(f"- Incident: `{r['title_detected']}`")
        if r.get("rca_root_cause"):
            lines.append(f"- Root cause given: {r['rca_root_cause']}")
        if r.get("patch_error"):
            lines.append(f"- Last patch error: `{r['patch_error'][:300]}`")
        if r.get("validation"):
            lines.append("- Validation: " + ", ".join(f"{k}={v}" for k, v in r["validation"].items()))
        lines.append(f"- Final status: `{r.get('final_status')}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["heuristic", "llm"], default="heuristic")
    ap.add_argument("--scenario", action="append", choices=list_scenarios(),
                    help="run only this scenario (repeatable); default: all")
    args = ap.parse_args()

    if args.mode == "heuristic":
        settings.llm_provider = "none"
    set_provider_override(None)
    if args.mode == "llm" and get_provider(settings) is None:
        sys.exit("No LLM configured. Set ANTHROPIC_API_KEY or AION_OPENAI_BASE_URL + AION_OPENAI_MODEL in backend/.env")

    results = []
    for name in args.scenario or list_scenarios():
        print(f"[eval] {name} ({args.mode}) ...", flush=True)
        r = run_scenario(name, args.mode)
        print(f"[eval]   -> {r.get('final_status')}  culprit_rank={r.get('culprit_rank')}  "
              f"rca_correct={r.get('rca_suspected_correct')}  {r.get('error', '')}", flush=True)
        results.append(r)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    (RESULTS_DIR / f"{stamp}-{args.mode}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    md = to_markdown(results, args.mode)
    (RESULTS_DIR / f"{stamp}-{args.mode}.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"[eval] written to {RESULTS_DIR / (stamp + '-' + args.mode)}.md/.json")


if __name__ == "__main__":
    main()
