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


def test_indentation_only_repair_when_model_drops_relative_indentation(tmp_path):
    (tmp_path / "app").mkdir()
    src = "def apply_discount(subtotal, coupon):\n    discount = subtotal * coupon['percent'] / 100\n    return discount\n"
    (tmp_path / "app" / "p.py").write_text(src, encoding="utf-8")
    # What a small model actually produced: first line indented, the rest at the wrong level.
    bad = "    if coupon is None:\n    discount = 0.0\nelse:\n    discount = subtotal * coupon['percent'] / 100\n"
    notes = []
    apply_edits(tmp_path, [FileEdit(path="app/p.py", search="    discount = subtotal * coupon['percent'] / 100\n",
                                    replace=bad)], [], {"app/p.py"}, notes)
    fixed = (tmp_path / "app" / "p.py").read_text(encoding="utf-8")
    namespace = {}
    exec(fixed, namespace)  # parses and runs
    assert namespace["apply_discount"](100, None) == 0.0
    assert namespace["apply_discount"](100, {"percent": 10}) == 10
    assert notes and "indentation-only repair" in notes[0]


def test_correct_edits_are_never_reindented(tree):
    root, files = tree
    notes = []
    apply_edits(root, [FileEdit(path="app/b.py", search="    return 1", replace="    if True:\n        return 1")],
                [], files, notes)
    assert notes == []
    assert "    if True:\n        return 1" in (root / "app/b.py").read_text()


@pytest.mark.parametrize("search", [
    'discount = subtotal * coupon["percent"] / 100\n',       # model omitted the line's indentation
    '    discount = subtotal * coupon["percent"] / 100\n',   # model included it
])
def test_indentation_repair_matches_real_model_output(tmp_path, search):
    """Exact replacement text produced by qwen2.5-coder:7b during the evaluation."""
    (tmp_path / "app").mkdir()
    src = ('def apply_discount(subtotal, coupon):\n    """Doc."""\n'
           '    discount = subtotal * coupon["percent"] / 100\n    return round(discount, 2)\n')
    (tmp_path / "app" / "p.py").write_text(src, encoding="utf-8")
    model_replace = ('if coupon is None:\n    discount = 0.0\nelse:\n'
                     '    discount = subtotal * coupon["percent"] / 100\n')
    if search.startswith("    "):
        model_replace = "    " + model_replace
    notes = []
    apply_edits(tmp_path, [FileEdit(path="app/p.py", search=search, replace=model_replace)], [], {"app/p.py"}, notes)
    namespace = {}
    exec((tmp_path / "app" / "p.py").read_text(encoding="utf-8"), namespace)
    assert namespace["apply_discount"](100, None) == 0.0
    assert namespace["apply_discount"](100, {"percent": 10}) == 10.0
    assert notes
