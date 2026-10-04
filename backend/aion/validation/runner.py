"""Automated validation of a candidate patch (a local CI pipeline).

Steps, in order (a blocking failure stops the pipeline):

  1. syntax_check         - every changed Python file compiles.
  2. regression_reproduce - new AION regression tests are run against the
                            *unpatched* code; they should FAIL there, proving
                            they reproduce the incident (non-blocking signal).
  3. unit_tests           - the service's full test suite on the patched code.
  4. staging_deploy       - start the patched service on a free port from the
                            patch's worktree; wait for its health check.
  5. replay_requests      - replay the production requests that failed during
                            the incident (expect no 5xx) plus a sample of
                            requests that used to succeed (expect the same
                            status) against staging.

All commands come from the *service registration* (operator-controlled), never
from the AI, and run without a shell.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from aion.config import settings
from aion.gitops.repo import GitRepo

OUTPUT_LIMIT = 6000


@dataclass
class Step:
    name: str
    title: str
    status: str = "pending"  # pending | running | passed | failed | warning | skipped
    blocking: bool = True
    summary: str = ""
    output: str = ""
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationTarget:
    repo_path: str
    worktree: Path
    base_sha: str
    commit_sha: str
    test_command: list[str]
    run_command: list[str]
    health_path: str
    new_test_files: list[str]
    failing_requests: list[dict[str, Any]]
    baseline_requests: list[dict[str, Any]]


def _expand(cmd: list[str], port: Optional[int] = None) -> list[str]:
    return [a.replace("{python}", sys.executable).replace("{port}", str(port or "")) for a in cmd]


def _tail(text: str) -> str:
    return text if len(text) <= OUTPUT_LIMIT else "... [truncated]\n" + text[-OUTPUT_LIMIT:]


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", AION_ENV="ci")
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env)
        return proc.returncode, _tail((proc.stdout or "") + (proc.stderr or ""))
    except subprocess.TimeoutExpired as exc:
        return -1, f"Timed out after {timeout}s\n{_tail(str(exc.stdout or ''))}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pytest_summary(output: str) -> str:
    for line in reversed(output.strip().splitlines()):
        if any(w in line for w in ("passed", "failed", "error", "no tests ran")):
            return line.strip(" =")
    return output.strip().splitlines()[-1] if output.strip() else ""


def _url(req: dict[str, Any]) -> str:
    return req["path"] + (f"?{req['query']}" if req.get("query") else "")


class ValidationRunner:
    def __init__(self, target: ValidationTarget, on_progress: Callable[[list[dict[str, Any]]], None] = lambda s: None):
        self.t = target
        self.on_progress = on_progress
        self.steps = [
            Step("syntax_check", "Static check: changed files compile"),
            Step("regression_reproduce", "Regression test reproduces the bug on unpatched code", blocking=False),
            Step("unit_tests", "Unit test suite on patched code"),
            Step("staging_deploy", "Deploy patched build to staging"),
            Step("replay_requests", "Replay incident traffic against staging"),
        ]
        self._staging: Optional[subprocess.Popen] = None
        self._staging_out = None

    def _emit(self) -> None:
        self.on_progress([asdict(s) for s in self.steps])

    def run(self) -> tuple[bool, list[dict[str, Any]]]:
        handlers = {
            "syntax_check": self._syntax_check,
            "regression_reproduce": self._regression_reproduce,
            "unit_tests": self._unit_tests,
            "staging_deploy": self._staging_deploy,
            "replay_requests": self._replay,
        }
        ok = True
        try:
            for step in self.steps:
                if not ok:
                    step.status, step.summary = "skipped", "Skipped because an earlier blocking step failed."
                    continue
                step.status = "running"
                self._emit()
                started = time.monotonic()
                try:
                    handlers[step.name](step)
                except Exception as exc:  # a crash inside a step is a failed step, not a crashed pipeline
                    step.status, step.summary = "failed", f"Step crashed: {exc}"
                step.duration_ms = int((time.monotonic() - started) * 1000)
                if step.status == "failed" and step.blocking:
                    ok = False
                self._emit()
        finally:
            self._stop_staging()
        return ok, [asdict(s) for s in self.steps]

    # -- steps ------------------------------------------------------------------
    def _changed_py_files(self) -> list[str]:
        out = GitRepo(self.t.repo_path).git("diff", "--name-only", "--diff-filter=AM",
                                            self.t.base_sha, self.t.commit_sha)
        return [p for p in out.splitlines() if p.endswith(".py")]

    def _syntax_check(self, step: Step) -> None:
        files = self._changed_py_files()
        if not files:
            step.status, step.summary = "passed", "No Python files changed."
            return
        rc, out = _run([sys.executable, "-m", "py_compile", *files], self.t.worktree, 60)
        step.output = out
        step.details = {"files": files}
        step.status = "passed" if rc == 0 else "failed"
        step.summary = f"{len(files)} file(s) compiled" if rc == 0 else "Compilation failed"

    def _regression_reproduce(self, step: Step) -> None:
        if not self.t.new_test_files:
            step.status, step.summary = "skipped", "The patch adds no regression test."
            return
        repo = GitRepo(self.t.repo_path)
        base_wt = self.t.worktree.parent / (self.t.worktree.name + "-basecheck")
        if base_wt.exists():
            repo.remove_worktree(base_wt)
            shutil.rmtree(base_wt, ignore_errors=True)
        repo.git("worktree", "add", "--detach", str(base_wt), self.t.base_sha)
        try:
            for rel in self.t.new_test_files:
                dst = base_wt / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.t.worktree / rel, dst)
            cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *self.t.new_test_files]
            rc, out = _run(cmd, base_wt, settings.test_timeout_seconds)
        finally:
            repo.remove_worktree(base_wt)
            shutil.rmtree(base_wt, ignore_errors=True)
        step.output = out
        step.details = {"exit_code": rc, "tests": self.t.new_test_files}
        if rc == 1:
            step.status = "passed"
            step.summary = f"Regression test fails on the unpatched code as expected ({_pytest_summary(out)})."
        elif rc == 0:
            step.status = "warning"
            step.summary = "Regression test PASSES on unpatched code - it does not reproduce the incident."
        else:
            step.status = "warning"
            step.summary = f"Regression test could not run on unpatched code (pytest exit {rc})."

    def _unit_tests(self, step: Step) -> None:
        cmd = _expand(self.t.test_command)
        rc, out = _run(cmd, self.t.worktree, settings.test_timeout_seconds)
        step.output = out
        step.details = {"command": " ".join(self.t.test_command), "exit_code": rc}
        step.status = "passed" if rc == 0 else "failed"
        step.summary = _pytest_summary(out) or f"exit code {rc}"

    def _staging_deploy(self, step: Step) -> None:
        port = _free_port()
        log_file = self.t.worktree / "staging.log"
        env = dict(os.environ, AION_ENV="staging", SERVICE_LOG_FILE=str(log_file), PYTHONDONTWRITEBYTECODE="1")
        cmd = _expand(self.t.run_command, port)
        self._staging_out = out_file = open(self.t.worktree / "staging.out", "w", encoding="utf-8")
        self._staging = subprocess.Popen(cmd, cwd=str(self.t.worktree), stdout=out_file, stderr=subprocess.STDOUT, env=env)
        self.staging_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        last_err = ""
        while time.monotonic() < deadline:
            if self._staging.poll() is not None:
                break
            try:
                r = httpx.get(self.staging_url + self.t.health_path, timeout=2)
                if r.status_code == 200:
                    step.status = "passed"
                    step.summary = f"Staging instance healthy at {self.staging_url}"
                    step.details = {"url": self.staging_url, "health": r.json() if "json" in
                                    r.headers.get("content-type", "") else r.text[:200]}
                    return
                last_err = f"health returned {r.status_code}"
            except httpx.HTTPError as exc:
                last_err = str(exc)
            time.sleep(0.5)
        out_file.flush()
        step.status = "failed"
        step.summary = f"Staging instance did not become healthy ({last_err or 'process exited'})"
        step.output = _tail((self.t.worktree / "staging.out").read_text(encoding="utf-8", errors="replace"))

    def _replay(self, step: Step) -> None:
        results = []
        failures = 0
        with httpx.Client(base_url=self.staging_url, timeout=10) as client:
            for kind, reqs in (("incident", self.t.failing_requests), ("baseline", self.t.baseline_requests)):
                for req in reqs:
                    # Only idempotent requests are replayed: replaying a POST could change data.
                    if req.get("method", "GET").upper() not in ("GET", "HEAD"):
                        continue
                    try:
                        r = client.request(req.get("method", "GET"), _url(req))
                        status = r.status_code
                    except httpx.HTTPError as exc:
                        status = None
                        results.append({"kind": kind, "request": f"{req.get('method')} {_url(req)}",
                                        "status": None, "ok": False, "error": str(exc)})
                        failures += 1
                        continue
                    if kind == "incident":
                        ok = status < 500
                        expectation = "no 5xx"
                    else:
                        ok = status == req.get("status")
                        expectation = f"same status as production ({req.get('status')})"
                    failures += 0 if ok else 1
                    results.append({"kind": kind, "request": f"{req.get('method', 'GET')} {_url(req)}",
                                    "status": status, "expected": expectation, "ok": ok})
        step.details = {"results": results}
        n_inc = sum(1 for r in results if r["kind"] == "incident")
        n_base = len(results) - n_inc
        if not results:
            step.status, step.summary = "warning", "No recorded requests available to replay."
        elif failures:
            step.status = "failed"
            step.summary = f"{failures} of {len(results)} replayed requests did not meet expectations"
        else:
            step.status = "passed"
            step.summary = (f"{n_inc} incident request(s) no longer fail; {n_base} baseline request(s) "
                            f"unchanged")
        step.output = "\n".join(f"[{'OK' if r['ok'] else 'FAIL'}] {r['kind']:8} {r['request']} -> {r['status']}"
                                for r in results)

    def _stop_staging(self) -> None:
        if self._staging and self._staging.poll() is None:
            self._staging.terminate()
            try:
                self._staging.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._staging.kill()
        if self._staging_out:
            self._staging_out.close()
