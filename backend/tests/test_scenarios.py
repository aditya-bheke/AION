"""The evaluation scenarios must stay valid: buildable, latent bug, known culprit."""
import subprocess
import sys

import pytest

from demo_repo import build_repo, list_scenarios, load_scenario


def test_all_expected_scenarios_exist():
    assert {"expired-coupon", "supplier-feed", "empty-cart-average", "healthy-release"} <= set(list_scenarios())


@pytest.mark.parametrize("name", list_scenarios())
def test_scenario_builds_with_latent_bug_and_known_culprit(name, tmp_path):
    sc = load_scenario(name)
    commits = build_repo(tmp_path / "repo", scenario=name)
    messages = [c.message.splitlines()[0] for c in commits]
    if sc.expected.get("incident", True):
        assert sc.expected["culprit"] in messages
        assert sc.trigger, "an incident scenario needs trigger requests"
    else:
        assert not sc.trigger
    assert any(c.deploy_version for c in commits)
    # The service's own test suite passes at HEAD: the bug is latent, as in real life.
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           cwd=tmp_path / "repo", capture_output=True, text=True)
    assert tests.returncode == 0, tests.stdout[-1500:]
