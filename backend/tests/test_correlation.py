from datetime import timedelta

from aion.gitops.correlation import DeploymentInfo, correlate
from aion.gitops.repo import GitRepo


def _line_of(repo_dir, rel, needle):
    for i, line in enumerate((repo_dir / rel).read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return i
    raise AssertionError(needle)


def test_blame_and_deployment_point_at_the_campaign_commit(demo_repo):
    repo_dir, commits = demo_repo
    buggy = next(c for c in commits if c.message.startswith("Support seasonal campaigns"))
    timing = next(c for c in commits if c.message.startswith("Add request duration"))
    deps = [DeploymentInfo(c.deploy_version, c.sha, c.deployed_at) for c in commits if c.deploy_version]
    # A stale record whose commit no longer exists (e.g. history rewritten) must be ignored, not crash.
    stale = DeploymentInfo("v0.9-stale", "0" * 40, deps[0].deployed_at)
    abs_prefix = "C:/somewhere/else/orders-service/"
    frames = [
        {"file": "C:/venv/Lib/site-packages/starlette/routing.py", "line": 70, "function": "app"},
        {"file": abs_prefix + "app/main.py", "line": _line_of(repo_dir, "app/main.py", "pricing.compute_total(order, coupon)"),
         "function": "order_total"},
        {"file": abs_prefix + "app/pricing.py", "line": _line_of(repo_dir, "app/pricing.py", "apply_discount(subtotal, coupon)"),
         "function": "compute_total"},
        {"file": abs_prefix + "app/pricing.py", "line": _line_of(repo_dir, "app/pricing.py", 'coupon["percent"]'),
         "function": "apply_discount"},
    ]
    first_seen = deps[-1].deployed_at + timedelta(hours=2)
    result = correlate(GitRepo(repo_dir), "main", frames, ["TypeError: 'NoneType' object is not subscriptable"],
                       first_seen, deps + [stale])

    assert result.suspect_deployment.version == "v1.4.0"
    assert any("Ignored 1 deployment record" in n for n in result.notes)
    assert [f.repo_path for f in result.frames] == ["app/main.py", "app/pricing.py", "app/pricing.py"]
    top = result.suspects[0]
    assert top.commit.sha == buggy.sha
    assert any("failing line" in r for r in top.reasons)
    assert any("v1.4.0" in r for r in top.reasons)
    timing_suspect = next(s for s in result.suspects if s.commit.sha == timing.sha)
    assert timing_suspect.score < top.score
    # The commit that originally added coupons wrote the calling lines too, but it
    # ran in production for days without this error: it must rank clearly lower.
    older = next(s for s in result.suspects if s.commit.message.startswith("Add coupon support"))
    assert older.score < 0.5 < top.score
    assert any("Already in production" in r for r in older.reasons)
    assert top.score == 1.0


def test_dependency_signal_finds_data_change_off_the_stack(tmp_path):
    """supplier-feed: the culprit changed catalog.py (imported by pricing.py), not the crashing line."""
    from demo_repo import build_repo

    repo_dir = tmp_path / "repo"
    commits = build_repo(repo_dir, scenario="supplier-feed")
    culprit = next(c for c in commits if c.message.startswith("Import DockCo"))
    deps = [DeploymentInfo(c.deploy_version, c.sha, c.deployed_at) for c in commits if c.deploy_version]
    p = "C:/x/orders-service/"
    frames = [
        {"file": p + "app/main.py", "line": _line_of(repo_dir, "app/main.py", "pricing.compute_total(order, coupon)"),
         "function": "order_total"},
        {"file": p + "app/pricing.py", "line": _line_of(repo_dir, "app/pricing.py", "subtotal = order_subtotal(order)"),
         "function": "compute_total"},
        {"file": p + "app/pricing.py", "line": _line_of(repo_dir, "app/pricing.py", 'product["price"]'),
         "function": "order_subtotal"},
    ]
    result = correlate(GitRepo(repo_dir), "main", frames, ["KeyError: 'price'"],
                       deps[-1].deployed_at + timedelta(hours=1), deps)
    top = result.suspects[0]
    assert top.commit.sha == culprit.sha
    assert any("imported by the failing code" in r for r in top.reasons)
