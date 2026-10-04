import pytest

from aion.ai.patcher import FileEdit, NewFile
from aion.remediation.apply import PatchApplyError, apply_edits
from aion.remediation.policy import PolicyViolation, check_diff_size


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "a.py").write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_a.py").write_text("def test(): assert True\n", encoding="utf-8")
    return tmp_path, {"app/a.py", "app/b.py", "tests/test_a.py"}


def test_applies_unique_edit_and_new_test(tree):
    root, files = tree
    changed = apply_edits(root, [FileEdit(path="app/b.py", search="    return 1", replace="    return 2")],
                          [NewFile(path="tests/test_aion_regression.py", content="def test_x(): pass")], files)
    assert changed == ["app/b.py", "tests/test_aion_regression.py"]
    assert "return 2" in (root / "app/b.py").read_text()


def test_missing_search_text_fails_without_writing(tree):
    root, files = tree
    with pytest.raises(PatchApplyError, match="not found"):
        apply_edits(root, [FileEdit(path="app/b.py", search="    return 1", replace="    return 9"),
                           FileEdit(path="app/a.py", search="z = 3", replace="z = 4")], [], files)
    assert "return 1" in (root / "app/b.py").read_text()  # all-or-nothing


def test_ambiguous_search_text_fails(tree):
    root, files = tree
    with pytest.raises(PatchApplyError, match="ambiguous"):
        apply_edits(root, [FileEdit(path="app/a.py", search="x = 1", replace="x = 3")], [], files)


@pytest.mark.parametrize("path", ["tests/test_a.py", "../outside.py", "/etc/passwd", "C:/Windows/x.py", ".github/ci.yml"])
def test_protected_or_unsafe_paths_rejected(tree, path):
    root, files = tree
    with pytest.raises(PolicyViolation):
        apply_edits(root, [FileEdit(path=path, search="x", replace="y")], [], files | {path})


def test_new_files_must_be_aion_regression_tests(tree):
    root, files = tree
    with pytest.raises(PolicyViolation):
        apply_edits(root, [], [NewFile(path="app/backdoor.py", content="import os")], files)


def test_diff_size_limit():
    big = "+++ b/app/a.py\n" + "\n".join(f"+line {i}" for i in range(500))
    with pytest.raises(PolicyViolation):
        check_diff_size(big)
