"""Automated validation of a candidate patch (a local CI pipeline).

Steps, in order (a blocking failure stops the pipeline):

  1. syntax_check         - every changed Python file compiles.
  2. regression_reproduce - new AION regression tests are run against the
                            *unpatched* code; they should FAIL there, proving
                            they reproduce the incident (non-blocking signal).
  3. unit_tests           - the service's full test suite on the patched code.
  4. staging_deploy       - start the patched service; wait for its health check.
  5. replay_requests      - replay the production requests that failed during
                            the incident (expect no 5xx) plus a sample of
                            requests that used to succeed (expect the same
                            status) against staging.

Every command that executes the patched code goes through a Sandbox
(validation/sandbox.py): host subprocesses ("local") or locked-down Docker
containers ("docker", AION_SANDBOX). Commands come from the *service
registration* (operator-controlled), never from the AI, and run without a shell
on the host.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from aion.config import settings
from aion.gitops.repo import GitRepo
from aion.validation.sandbox import Sandbox, SandboxUnavailable, _url, make_sandbox


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


def _pytest_summary(output: str) -> str:
    for line in reversed(output.strip().splitlines()):
        if any(w in line for w in ("passed", "failed", "error", "no tests ran")):
            return line.strip(" =")
    return output.strip().splitlines()[-1] if output.strip() else ""


class ValidationRunner:
    def __init__(self, target: ValidationTarget, on_progress: Callable[[list[dict[str, Any]]], None] = lambda s: None,
                 sandbox: Optional[Sandbox] = None):
        self.t = target
        self.on_progress = on_progress
        self._sandbox = sandbox
        self.steps = [
            Step("syntax_check", "Static check: changed files compile"),
            Step("regression_reproduce", "Regression test reproduces the bug on unpatched code", blocking=False),
            Step("unit_tests", "Unit test suite on patched code"),
            Step("staging_deploy", "Deploy patched build to staging"),
            Step("replay_requests", "Replay incident traffic against staging"),
        ]

    def _emit(self) -> None:
        self.on_progress([asdict(s) for s in self.steps])

    @property
    def sandbox(self) -> Sandbox:
        if self._sandbox is None:
            self._sandbox = make_sandbox(settings.sandbox, settings.sandbox_image)
        return self._sandbox

    def run(self) -> tuple[bool, list[dict[str, Any]]]:
        try:
            sandbox_name = self.sandbox.name
        except SandboxUnavailable as exc:
            # Never fall back to running untrusted code on the host.
            for step in self.steps:
                step.status, step.summary = "skipped", "Skipped: sandbox unavailable."
            self.steps[0].status = "failed"
            self.steps[0].summary = f"Sandbox '{settings.sandbox}' unavailable: {exc}"
            self._emit()
            return False, [asdict(s) for s in self.steps]

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
                step.details["sandbox"] = sandbox_name
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
            self.sandbox.stop()
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
        rc, out = self.sandbox.run(["{python}", "-m", "py_compile", *files], self.t.worktree, 120)
        step.output = out
        step.details.update(files=files)
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
            cmd = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", *self.t.new_test_files]
            rc, out = self.sandbox.run(cmd, base_wt, settings.test_timeout_seconds)
        finally:
            repo.remove_worktree(base_wt)
            shutil.rmtree(base_wt, ignore_errors=True)
        step.output = out
        step.details.update(exit_code=rc, tests=self.t.new_test_files)
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
        rc, out = self.sandbox.run(self.t.test_command, self.t.worktree, settings.test_timeout_seconds)
        step.output = out
        step.details.update(command=" ".join(self.t.test_command), exit_code=rc)
        step.status = "passed" if rc == 0 else "failed"
        step.summary = _pytest_summary(out) or f"exit code {rc}"

    def _staging_deploy(self, step: Step) -> None:
        where = self.sandbox.start_service(self.t.run_command, self.t.worktree)
        healthy, detail = self.sandbox.wait_healthy(self.t.health_path, timeout=45)
        step.details.update(where=where, health=detail[:300])
        if healthy:
            step.status, step.summary = "passed", f"Staging instance healthy ({where})"
        else:
            step.status = "failed"
            step.summary = f"Staging instance did not become healthy ({detail or 'no response'})"
            step.output = self.sandbox.service_output()

    def _replay(self, step: Step) -> None:
        # Only idempotent requests are replayed: replaying a POST could change data.
        planned = [(kind, req) for kind, reqs in (("incident", self.t.failing_requests),
                                                  ("baseline", self.t.baseline_requests))
                   for req in reqs if req.get("method", "GET").upper() in ("GET", "HEAD")]
        responses = self.sandbox.replay([req for _, req in planned])
        results, failures = [], 0
        for (kind, req), resp in zip(planned, responses):
            status = resp.get("status")
            if status is None:
                ok, expectation = False, "a response"
            elif kind == "incident":
                ok, expectation = status < 500, "no 5xx"
            else:
                ok, expectation = status == req.get("status"), f"same status as production ({req.get('status')})"
            failures += 0 if ok else 1
            results.append({"kind": kind, "request": f"{req.get('method', 'GET')} {_url(req)}",
                            "status": status, "expected": expectation, "ok": ok,
                            **({"error": resp["error"]} if resp.get("error") else {})})
        step.details.update(results=results)
        n_inc = sum(1 for r in results if r["kind"] == "incident")
        n_base = len(results) - n_inc
        if not results:
            step.status, step.summary = "warning", "No recorded requests available to replay."
        elif failures:
            step.status = "failed"
            step.summary = f"{failures} of {len(results)} replayed requests did not meet expectations"
        else:
            step.status = "passed"
            step.summary = f"{n_inc} incident request(s) no longer fail; {n_base} baseline request(s) unchanged"
        step.output = "\n".join(f"[{'OK' if r['ok'] else 'FAIL'}] {r['kind']:8} {r['request']} -> {r['status']}"
                                for r in results)
