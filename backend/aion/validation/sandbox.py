"""Where AI-generated code is executed during validation.

The validation runner never runs commands itself; it asks a Sandbox to:
  run(cmd, src)              - run a command against a copy of a source tree
  start_service(cmd, src)    - start the patched service ("staging")
  wait_healthy(path)         - poll its health endpoint
  replay(requests)           - send HTTP requests to it, return statuses
  stop()                     - tear it down

LocalSandbox  - subprocesses on this machine (development; the MVP behaviour).
DockerSandbox - a throwaway container per command / per staging instance with:
                --network none (no internet, no LAN), the source mounted
                read-only and copied into a tmpfs, a read-only root filesystem,
                a non-root user, all Linux capabilities dropped,
                no-new-privileges, and CPU / memory / process limits.
                Health checks and the replay run *inside* the container, so
                the staging service needs no network at all.

If Docker is selected but unusable, validation fails loudly - it never falls
back to running untrusted code on the host.
"""
from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Protocol

import httpx

OUTPUT_LIMIT = 6000
CONTAINER_PORT = 8000


def tail(text: str) -> str:
    return text if len(text) <= OUTPUT_LIMIT else "... [truncated]\n" + text[-OUTPUT_LIMIT:]


def _url(req: dict[str, Any]) -> str:
    return req["path"] + (f"?{req['query']}" if req.get("query") else "")


class SandboxUnavailable(RuntimeError):
    pass


class Sandbox(Protocol):
    name: str

    def run(self, cmd: list[str], src: Path, timeout: int) -> tuple[int, str]: ...
    def start_service(self, cmd: list[str], src: Path) -> str: ...
    def wait_healthy(self, health_path: str, timeout: float) -> tuple[bool, str]: ...
    def replay(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
    def service_output(self) -> str: ...
    def stop(self) -> None: ...


# ---------------------------------------------------------------------------------------
class LocalSandbox:
    """Subprocesses on the host. Fast and simple; NOT isolated - development only."""

    name = "local (host subprocess, not isolated)"

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._out = None
        self._out_path: Optional[Path] = None
        self.url = ""

    @staticmethod
    def expand(cmd: list[str], port: Optional[int] = None) -> list[str]:
        return [a.replace("{python}", sys.executable).replace("{port}", str(port or "")) for a in cmd]

    def run(self, cmd: list[str], src: Path, timeout: int) -> tuple[int, str]:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", AION_ENV="ci")
        try:
            proc = subprocess.run(self.expand(cmd), cwd=str(src), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, env=env)
            return proc.returncode, tail((proc.stdout or "") + (proc.stderr or ""))
        except subprocess.TimeoutExpired as exc:
            return -1, f"Timed out after {timeout}s\n{tail(str(exc.stdout or ''))}"

    def start_service(self, cmd: list[str], src: Path) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = dict(os.environ, AION_ENV="staging", SERVICE_LOG_FILE=str(src / "staging.log"),
                   PYTHONDONTWRITEBYTECODE="1")
        self._out_path = src / "staging.out"
        self._out = open(self._out_path, "w", encoding="utf-8")
        self._proc = subprocess.Popen(self.expand(cmd, port), cwd=str(src), stdout=self._out,
                                      stderr=subprocess.STDOUT, env=env)
        self.url = f"http://127.0.0.1:{port}"
        return self.url

    def wait_healthy(self, health_path: str, timeout: float) -> tuple[bool, str]:
        deadline, last = time.monotonic() + timeout, ""
        while time.monotonic() < deadline:
            if self._proc and self._proc.poll() is not None:
                return False, "process exited"
            try:
                r = httpx.get(self.url + health_path, timeout=2)
                if r.status_code == 200:
                    return True, r.text[:300]
                last = f"health returned {r.status_code}"
            except httpx.HTTPError as exc:
                last = str(exc)
            time.sleep(0.5)
        return False, last

    def replay(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        with httpx.Client(base_url=self.url, timeout=10) as client:
            for req in requests:
                try:
                    out.append({"status": client.request(req.get("method", "GET"), _url(req)).status_code})
                except httpx.HTTPError as exc:
                    out.append({"status": None, "error": str(exc)})
        return out

    def service_output(self) -> str:
        if self._out:
            self._out.flush()
        return tail(self._out_path.read_text(encoding="utf-8", errors="replace")) if self._out_path else ""

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._out:
            self._out.close()


# ---------------------------------------------------------------------------------------
# Runs inside the container: health-check or replay against the staging service on localhost.
_IN_CONTAINER_CLIENT = r'''
import json, sys, urllib.request, urllib.error
mode, payload = sys.argv[1], json.loads(sys.argv[2])
def call(method, path):
    req = urllib.request.Request("http://127.0.0.1:%d" + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return {"status": r.status, "body": r.read(300).decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        return {"status": e.code}
    except Exception as e:
        return {"status": None, "error": str(e)}
if mode == "health":
    print(json.dumps(call("GET", payload)))
else:
    print(json.dumps([call(r.get("method", "GET"), r["path"] + ("?" + r["query"] if r.get("query") else ""))
                      for r in payload]))
''' % CONTAINER_PORT


class DockerSandbox:
    """One container per command, and one for staging. Untrusted code never touches the host."""

    def __init__(self, image: str, memory: str = "512m", cpus: str = "1", pids: int = 256):
        self.image = image
        self.name = f"docker ({image}, no network, read-only, non-root)"
        self.limits = ["--memory", memory, "--cpus", cpus, "--pids-limit", str(pids)]
        self._container: Optional[str] = None

    @staticmethod
    def available(image: str) -> tuple[bool, str]:
        try:
            info = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True,
                                  text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"docker CLI not usable: {exc}"
        if info.returncode != 0:
            return False, "Docker engine is not running (start Docker Desktop)"
        img = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=20)
        if img.returncode != 0:
            return False, f"Sandbox image {image!r} not found (build it: scripts\\build-sandbox.ps1)"
        return True, f"Docker {info.stdout.strip()}"

    def _base(self, src: Path, extra: list[str]) -> list[str]:
        return ["docker", "run", "--network", "none", "--read-only",
                "--tmpfs", "/tmp:rw,size=128m", "--tmpfs", "/work:rw,exec,mode=1777,size=256m",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "1000:1000",
                *self.limits, "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-v", f"{src.resolve()}:/src:ro", *extra, self.image]

    @staticmethod
    def _shell(cmd: list[str], port: Optional[int] = None) -> str:
        argv = [a.replace("{python}", "python").replace("{port}", str(port or "")) for a in cmd]
        # Copy the read-only source into the writable tmpfs, then run there.
        return f"cp -a /src/. /work/ && cd /work && exec {shlex.join(argv)}"

    def run(self, cmd: list[str], src: Path, timeout: int) -> tuple[int, str]:
        name = f"aion-run-{uuid.uuid4().hex[:10]}"
        full = self._base(src, ["--rm", "--name", name, "-e", "AION_ENV=ci"]) + ["sh", "-c", self._shell(cmd)]
        try:
            proc = subprocess.run(full, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout)
            return proc.returncode, tail((proc.stdout or "") + (proc.stderr or ""))
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            return -1, f"Timed out after {timeout}s (container killed)"

    def start_service(self, cmd: list[str], src: Path) -> str:
        self._container = f"aion-staging-{uuid.uuid4().hex[:10]}"
        full = self._base(src, ["-d", "--name", self._container, "-e", "AION_ENV=staging",
                                "-e", "SERVICE_LOG_FILE=/tmp/staging.log"])
        full += ["sh", "-c", self._shell(cmd, CONTAINER_PORT)]
        proc = subprocess.run(full, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise SandboxUnavailable(f"could not start staging container: {proc.stderr.strip()}")
        return f"container {self._container} (no network; checked from inside)"

    def _exec_client(self, mode: str, payload: Any) -> Any:
        proc = subprocess.run(["docker", "exec", self._container, "python", "-c", _IN_CONTAINER_CLIENT, mode,
                               json.dumps(payload)], capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "in-container client failed")
        return json.loads(proc.stdout)

    def wait_healthy(self, health_path: str, timeout: float) -> tuple[bool, str]:
        deadline, last = time.monotonic() + timeout, ""
        while time.monotonic() < deadline:
            state = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", self._container],
                                   capture_output=True, text=True)
            if state.stdout.strip() != "true":
                return False, "container exited"
            try:
                res = self._exec_client("health", health_path)
                if res.get("status") == 200:
                    return True, res.get("body", "")
                last = res.get("error") or f"health returned {res.get('status')}"
            except (RuntimeError, ValueError) as exc:
                last = str(exc)
            time.sleep(1.0)
        return False, last

    def replay(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._exec_client("replay", requests) if requests else []

    def service_output(self) -> str:
        if not self._container:
            return ""
        proc = subprocess.run(["docker", "logs", self._container], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        return tail(proc.stdout + proc.stderr)

    def stop(self) -> None:
        if self._container:
            subprocess.run(["docker", "rm", "-f", self._container], capture_output=True)


def make_sandbox(kind: str, image: str) -> Sandbox:
    if kind == "docker":
        ok, why = DockerSandbox.available(image)
        if not ok:
            raise SandboxUnavailable(why)
        return DockerSandbox(image)
    if kind == "local":
        return LocalSandbox()
    raise ValueError(f"Unknown AION_SANDBOX {kind!r} (use 'local' or 'docker')")
