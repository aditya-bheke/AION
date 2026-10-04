"""End-to-end AION demo driver.

    1. builds the demo `orders-service` git repository for a scenario
       (workspace/orders-service; scenarios live in demo/scenarios/)
    2. registers it with AION and records its deployment history
    3. starts the service in "production" on port 8101 and redeploys it whenever
       the main branch moves (a minimal GitOps controller)
    4. sends realistic traffic; after a warm-up period the scenario's trigger
       requests start (e.g. an expired coupon), which hit the latent bug

Then watch the incident in the dashboard: http://127.0.0.1:8000

Run with the backend virtualenv's Python while AION is running:

    backend\\.venv\\Scripts\\python demo\\run_demo.py --fresh [--scenario supplier-feed]
    backend\\.venv\\Scripts\\python demo\\run_demo.py --list
"""
from __future__ import annotations

import argparse
import itertools
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_repo import DEFAULT_SCENARIO, build_repo, list_scenarios, load_scenario  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
REPO = WORKSPACE / "orders-service"
LOG_FILE = WORKSPACE / "logs" / "orders-service.log"
PROD_PORT = 8101
PROD_URL = f"http://127.0.0.1:{PROD_PORT}"


def setup(aion: str, fresh: bool, scenario: str) -> None:
    if fresh or not (REPO / ".git").exists():
        print(f"[demo] scenario '{scenario}': {load_scenario(scenario).title}")
        print(f"[demo] building git repository at {REPO}")
        commits = build_repo(REPO, scenario=scenario)
        for c in commits:
            print(f"        {c.sha[:7]}  {c.message.splitlines()[0]}" + (f"   <- deployed as {c.deploy_version}" if c.deploy_version else ""))
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        register(aion)
        for c in commits:
            if c.deploy_version:
                r = httpx.post(f"{aion}/api/deployments", json={
                    "service": "orders-service", "version": c.deploy_version, "commit_sha": c.sha,
                    "deployed_at": c.deployed_at.isoformat(), "deployed_by": "ci-pipeline"})
                r.raise_for_status()
                print(f"[demo] recorded deployment {c.deploy_version} ({c.sha[:7]}) at {c.deployed_at:%Y-%m-%d %H:%M} UTC")
    else:
        print(f"[demo] reusing existing repository at {REPO} (use --fresh to rebuild)")
        register(aion)


def register(aion: str) -> None:
    r = httpx.post(f"{aion}/api/services", json={
        "name": "orders-service",
        "repo_path": str(REPO),
        "production_branch": "main",
        "log_path": str(LOG_FILE),
        "test_command": ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        "run_command": ["{python}", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "{port}"],
        "health_path": "/health",
        "production_url": PROD_URL,
    })
    if r.status_code >= 400:
        sys.exit(f"[demo] could not register service: {r.status_code} {r.text}")
    print("[demo] registered service orders-service with AION")


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "main"], cwd=str(REPO), capture_output=True, text=True).stdout.strip()


class ProductionRuntime:
    """Runs the service in "production" and acts as a tiny GitOps controller.

    A background thread watches the production branch (main). When it moves -
    e.g. because AION fast-forwarded it to a human-approved fix - the service
    is restarted on the new commit, like Argo CD / Flux syncing a cluster to Git.
    """

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.commit = ""
        self._stop = threading.Event()

    def start(self) -> None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, SERVICE_LOG_FILE=str(LOG_FILE), AION_ENV="production", PYTHONDONTWRITEBYTECODE="1")
        self.commit = _head()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PROD_PORT),
             "--log-level", "warning"], cwd=str(REPO), env=env)
        for _ in range(60):
            try:
                if httpx.get(PROD_URL + "/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.stop()
        sys.exit("[demo] production service failed to start")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def watch(self) -> None:
        def loop() -> None:
            while not self._stop.wait(2.0):
                head = _head()
                if head and head != self.commit:
                    print(f"\n[controller] production branch moved {self.commit[:7]} -> {head[:7]}; redeploying")
                    self.stop()
                    self.start()
                    print(f"[controller] production now running {self.commit[:7]}")
        threading.Thread(target=loop, name="gitops-controller", daemon=True).start()

    def shutdown(self) -> None:
        self._stop.set()
        self.stop()


NORMAL = [
    ("GET", "/products", 3), ("GET", "/products/{sku}", 3), ("GET", "/orders/{order}", 4),
    ("GET", "/orders/{order}/total", 4), ("GET", "/orders/{order}/total?coupon=WELCOME10", 2),
    ("GET", "/orders/{order}/total?coupon=DIWALI25", 2), ("GET", "/orders/9999", 1),
]
def traffic(incident_after: float, rate: float, duration: float | None, broken: list[tuple]) -> None:
    rng = random.Random(7)
    started = time.monotonic()
    counts = {"ok": 0, "4xx": 0, "5xx": 0}
    last_pay = 0.0
    announced = False
    with httpx.Client(base_url=PROD_URL, timeout=5) as client:
        for i in itertools.count():
            elapsed = time.monotonic() - started
            if duration and elapsed > duration:
                break
            pool = NORMAL + (broken if elapsed >= incident_after else [])
            if elapsed >= incident_after and broken and not announced:
                print(f"\n[demo] t={elapsed:.0f}s: trigger traffic starts: {', '.join(p for _, p, _ in broken)} ...")
                announced = True
            method, template, _ = rng.choices(pool, weights=[w for *_, w in pool])[0]
            path = template.format(sku=rng.choice(["SKU-1001", "SKU-1002", "SKU-1003", "SKU-1004", "SKU-1005"]),
                                   order=rng.randint(1001, 1008))
            if elapsed - last_pay >= 5:  # a checkout every ~5 seconds
                method, path, last_pay = "POST", f"/orders/{rng.randint(1001, 1008)}/pay", elapsed
            try:
                status = client.request(method, path).status_code
                counts["ok" if status < 400 else "4xx" if status < 500 else "5xx"] += 1
            except httpx.HTTPError:
                counts["5xx"] += 1  # e.g. during a reload
            if i % 20 == 0:
                print(f"\r[demo] t={elapsed:5.0f}s requests ok={counts['ok']} 4xx={counts['4xx']} 5xx={counts['5xx']}   ",
                      end="", flush=True)
            time.sleep(1.0 / rate)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aion", default="http://127.0.0.1:8000", help="AION base URL")
    ap.add_argument("--fresh", action="store_true", help="rebuild the demo repository from scratch")
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO, choices=list_scenarios(),
                    help=f"which bug scenario to build (default: {DEFAULT_SCENARIO}); applies with --fresh")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    ap.add_argument("--incident-after", type=float, default=45, help="seconds of normal traffic before the bug is hit")
    ap.add_argument("--rate", type=float, default=4.0, help="requests per second")
    ap.add_argument("--duration", type=float, default=None, help="stop after N seconds (default: run until Ctrl+C)")
    args = ap.parse_args()
    if args.list:
        for name in list_scenarios():
            sc = load_scenario(name)
            print(f"{name:20} {sc.title}\n{'':20} {sc.description}\n")
        return
    try:
        httpx.get(f"{args.aion}/api/health", timeout=3).raise_for_status()
    except httpx.HTTPError:
        sys.exit(f"[demo] AION is not reachable at {args.aion}. Start it first: backend\\.venv\\Scripts\\python -m aion")

    setup(args.aion, args.fresh, args.scenario)
    broken = [tuple(t) for t in load_scenario(args.scenario).trigger]
    runtime = ProductionRuntime()
    runtime.start()
    runtime.watch()
    print(f"[demo] production service up at {PROD_URL} on commit {runtime.commit[:7]}; "
          "a controller redeploys it whenever the main branch moves")
    print(f"[demo] sending traffic at {args.rate}/s; the bug is triggered after {args.incident_after:.0f}s. Ctrl+C to stop.")
    try:
        traffic(args.incident_after, args.rate, args.duration, broken)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[demo] stopping production service")
        runtime.shutdown()

if __name__ == "__main__":
    main()
