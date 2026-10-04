"""Sandbox: fail-closed behaviour, isolation flags, and (when Docker is up) a real container run."""
from pathlib import Path

import pytest

from aion.config import settings
from aion.validation import runner as runner_mod
from aion.validation.runner import ValidationRunner, ValidationTarget
from aion.validation.sandbox import DockerSandbox, LocalSandbox, SandboxUnavailable, make_sandbox


def _target(tmp_path: Path) -> ValidationTarget:
    return ValidationTarget(repo_path=str(tmp_path), worktree=tmp_path, base_sha="a", commit_sha="b",
                            test_command=["{python}", "-m", "pytest"], run_command=[], health_path="/health",
                            new_test_files=[], failing_requests=[], baseline_requests=[])


def test_unavailable_docker_fails_closed_and_runs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sandbox", "docker")
    monkeypatch.setattr(DockerSandbox, "available", staticmethod(lambda image: (False, "engine not running")))
    executed = []
    monkeypatch.setattr(LocalSandbox, "run", lambda *a, **k: executed.append(a) or (0, ""))
    passed, steps = ValidationRunner(_target(tmp_path)).run()
    assert passed is False
    assert steps[0]["status"] == "failed" and "engine not running" in steps[0]["summary"]
    assert all(s["status"] == "skipped" for s in steps[1:])
    assert executed == []  # no silent fallback to the host


def test_unknown_sandbox_kind_is_an_error():
    with pytest.raises(ValueError):
        make_sandbox("vm", "x")


def test_docker_command_carries_every_isolation_flag(tmp_path):
    cmd = DockerSandbox("aion-sandbox:py310")._base(tmp_path, ["--rm"])
    joined = " ".join(cmd)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--user 1000:1000", "--memory", "--cpus", "--pids-limit"):
        assert flag in joined, flag
    assert f"{tmp_path.resolve()}:/src:ro" in cmd  # source mounted read-only
    shell = DockerSandbox._shell(["{python}", "-m", "pytest", "-q", "x y"])
    assert shell.endswith("exec python -m pytest -q 'x y'")  # arguments are shell-quoted


docker_ok, docker_why = DockerSandbox.available(settings.sandbox_image)


@pytest.mark.skipif(not docker_ok, reason=f"Docker sandbox not available: {docker_why}")
def test_real_container_has_no_network_and_readonly_source(tmp_path):
    (tmp_path / "probe.py").write_text(
        "import socket, pathlib\n"
        "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=3); print('NET=yes')\n"
        "except OSError:\n    print('NET=no')\n"
        "try:\n    pathlib.Path('/src/x').write_text('x'); print('SRC=writable')\n"
        "except OSError:\n    print('SRC=readonly')\n", encoding="utf-8")
    rc, out = DockerSandbox(settings.sandbox_image).run(["{python}", "probe.py"], tmp_path, 120)
    assert rc == 0, out
    assert "NET=no" in out and "SRC=readonly" in out
    assert not (tmp_path / "x").exists()
