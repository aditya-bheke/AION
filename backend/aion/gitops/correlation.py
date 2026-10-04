"""Git / deployment correlation: which recent change most likely caused this?

Signals (each one is recorded as a human-readable reason):

1. Blame on the failing line   - `git blame` the exact line of the innermost
                                 application stack frame at the deployed
                                 revision. The commit that last touched it is
                                 a very strong suspect.
2. Blame on the failing function - lines of the enclosing function (found with
                                 Python's `ast`) last modified by the commit.
3. File overlap                - the commit touched a file in the stack trace.
3b. Dependency overlap         - the commit touched a module *imported by* a file
                                 in the stack trace (data/helpers the failing code
                                 reads) - catches causes that are not on the stack.
4. Deployment timing          - the commit shipped in the deployment that went
                                 live right before the errors started.
5. Keyword overlap             - identifiers from the error (function names,
                                 exception text) appear in the commit message.

Each signal counts once per commit (its strongest instance). Commits that
were already running in an earlier deployment, before the errors appeared,
are multiplied by STABLE_CODE_FACTOR. The weighted sum is capped at 1.0. It
is a ranking heuristic, not a probability; the LLM later reasons over the top candidates *and* their diffs.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from aion.gitops.repo import Commit, GitError, GitRepo
from aion.logs.normalize import app_frames

W_BLAME_LINE = 0.40
W_BLAME_FUNCTION = 0.20
W_FILE_OVERLAP = 0.15
W_DEPENDENCY = 0.15
W_DEPLOYMENT = 0.20
W_KEYWORDS = 0.05
STABLE_CODE_FACTOR = 0.5

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_STOP = {"self", "none", "nonetype", "object", "error", "file", "line", "return", "true", "false",
         "with", "from", "that", "this", "subscriptable", "traceback", "most", "recent", "call", "last"}


@dataclass
class DeploymentInfo:
    version: str
    commit_sha: str
    deployed_at: datetime


@dataclass
class MappedFrame:
    repo_path: str
    line: int
    function: str
    function_start: Optional[int] = None
    function_end: Optional[int] = None


@dataclass
class Suspect:
    commit: Commit
    score: float
    reasons: list[str] = field(default_factory=list)
    deployment_version: Optional[str] = None


@dataclass
class CorrelationResult:
    analysed_revision: str
    frames: list[MappedFrame]
    suspects: list[Suspect]
    suspect_deployment: Optional[DeploymentInfo]
    previous_deployment: Optional[DeploymentInfo]
    notes: list[str] = field(default_factory=list)


def map_frames_to_repo(frames: list[dict[str, Any]], repo_files: list[str]) -> list[MappedFrame]:
    """Translate absolute paths from a stack trace into repository-relative paths."""
    mapped = []
    for f in app_frames(frames):
        path = f["file"].replace("\\", "/")
        best = None
        for rf in repo_files:
            if path == rf or path.endswith("/" + rf):
                if best is None or len(rf) > len(best):
                    best = rf
        if best:
            mapped.append(MappedFrame(repo_path=best, line=int(f["line"]), function=f["function"]))
    return mapped


def _function_range(source: str, line: int) -> tuple[Optional[int], Optional[int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, None
    best: tuple[Optional[int], Optional[int]] = (None, None)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None)
            if end and node.lineno <= line <= end:
                if best[0] is None or node.lineno > best[0]:  # innermost function wins
                    best = (node.lineno, end)
    return best


def _blame(repo: GitRepo, rev: str, path: str, start: int, end: int) -> dict[int, str]:
    """Map line number -> sha of the commit that last changed it."""
    try:
        out = repo.git("blame", "--porcelain", "-L", f"{start},{end}", rev, "--", path)
    except GitError:
        return {}
    result: dict[int, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]):
            result[int(parts[2])] = parts[0]
    return result


def _imported_repo_files(repo: GitRepo, rev: str, files: set[str], repo_files: set[str]) -> set[str]:
    """Repository files imported by `files` (Python `import` / `from ... import`), at `rev`."""
    found: set[str] = set()

    def resolve(module: str) -> None:
        base = module.replace(".", "/")
        for candidate in (f"{base}.py", f"{base}/__init__.py"):
            if candidate in repo_files:
                found.add(candidate)

    for path in files:
        try:
            tree = ast.parse(repo.file_at(rev, path) or "")
        except SyntaxError:
            continue
        package = path.rsplit("/", 1)[0].replace("/", ".") if "/" in path else ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolve(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:  # relative import: from . import x / from .x import y
                    parts = package.split(".") if package else []
                    parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                    module = ".".join(p for p in parts + ([module] if module else []) if p)
                resolve(module)
                for alias in node.names:  # from app import catalog -> app/catalog.py
                    resolve(f"{module}.{alias.name}" if module else alias.name)
    return found


def _keywords(texts: list[str]) -> set[str]:
    words = set()
    for t in texts:
        for w in _TOKEN_RE.findall(t or ""):
            w = w.lower()
            if w not in _STOP:
                words.add(w)
                words.update(p for p in w.split("_") if len(p) > 3 and p not in _STOP)
    return words


def correlate(
    repo: GitRepo,
    production_branch: str,
    frames: list[dict[str, Any]],
    error_texts: list[str],
    first_seen: datetime,
    deployments: list[DeploymentInfo],
    max_candidates: int = 15,
) -> CorrelationResult:
    notes: list[str] = []
    # Deployment records can outlive their commits (history rewritten, repo rebuilt).
    known = [d for d in deployments if repo.has_commit(d.commit_sha)]
    if len(known) < len(deployments):
        notes.append(f"Ignored {len(deployments) - len(known)} deployment record(s) whose commit is not in the repository.")
    deployments = sorted(known, key=lambda d: d.deployed_at)
    before = [d for d in deployments if d.deployed_at <= first_seen]
    suspect_dep = before[-1] if before else None
    previous_dep = before[-2] if len(before) >= 2 else None

    # The revision that was actually running when the errors happened.
    rev = suspect_dep.commit_sha if suspect_dep else repo.rev_parse(production_branch)
    if not suspect_dep:
        notes.append("No deployment history before the incident; analysing the production branch head.")

    repo_files = repo.ls_files(rev)
    mapped = map_frames_to_repo(frames, repo_files)
    if not mapped:
        notes.append("No stack frame could be mapped to a file in the repository.")

    # Function ranges for each mapped frame (from the deployed source).
    for mf in mapped:
        source = repo.file_at(rev, mf.repo_path) or ""
        mf.function_start, mf.function_end = _function_range(source, mf.line)

    shipped: set[str] = set()
    if suspect_dep and previous_dep:
        shipped = {c.sha for c in repo.commits(f"{previous_dep.commit_sha}..{suspect_dep.commit_sha}", 200)}
    elif suspect_dep:
        shipped = {suspect_dep.commit_sha}

    candidates = repo.commits(rev, max_candidates)
    by_sha = {c.sha: c for c in candidates}
    # signals[sha][signal] = (weight, reason). Each signal counts ONCE per commit
    # (its strongest instance), so touching several stack frames cannot inflate a score.
    signals: dict[str, dict[str, tuple[float, str]]] = {c.sha: {} for c in candidates}

    def add(sha: str, signal: str, weight: float, reason: str) -> None:
        if sha in signals and weight > signals[sha].get(signal, (0.0, ""))[0]:
            signals[sha][signal] = (weight, reason)

    # (1) + (2): blame, innermost frames first (they are closest to the failure).
    for depth, mf in enumerate(reversed(mapped[-3:])):
        damp = 1.0 if depth == 0 else 0.5
        exact = _blame(repo, rev, mf.repo_path, mf.line, mf.line)
        for sha in exact.values():
            add(sha, "blame_line", W_BLAME_LINE * damp,
                f"Last modified the {'failing' if depth == 0 else 'calling'} line {mf.repo_path}:{mf.line} "
                f"(in {mf.function}) [git blame]")
        if mf.function_start and mf.function_end:
            fn = _blame(repo, rev, mf.repo_path, mf.function_start, mf.function_end)
            touched: dict[str, list[int]] = {}
            for ln, sha in fn.items():
                touched.setdefault(sha, []).append(ln)
            for sha, lines in touched.items():
                add(sha, "blame_function", W_BLAME_FUNCTION * damp,
                    f"Modified {len(lines)} line(s) of function {mf.function}() in {mf.repo_path} [git blame]")

    # (3) file overlap
    trace_files = {mf.repo_path for mf in mapped}
    for c in candidates:
        overlap = trace_files.intersection(c.files)
        if overlap:
            add(c.sha, "file_overlap", W_FILE_OVERLAP, f"Touched file(s) in the stack trace: {', '.join(sorted(overlap))}")

    # (3b) dependency overlap: the commit changed a module that the failing code imports
    # (e.g. data or helpers it reads). Catches causes that are not on the stack itself.
    deps = _imported_repo_files(repo, rev, trace_files, set(repo_files)) - trace_files
    for c in candidates:
        overlap = deps.intersection(c.files)
        if overlap:
            add(c.sha, "dependency", W_DEPENDENCY,
                f"Changed {', '.join(sorted(overlap))}, imported by the failing code ({', '.join(sorted(trace_files))})")

    # (4) deployment timing
    for sha in shipped:
        if sha in by_sha and suspect_dep:
            add(sha, "deployment", W_DEPLOYMENT,
                f"Shipped in deployment {suspect_dep.version} at {suspect_dep.deployed_at:%Y-%m-%d %H:%M} UTC, "
                f"the last deployment before errors began ({first_seen:%H:%M:%S} UTC)")

    # (5) keyword overlap
    # Only the specific error and the innermost failing functions - not generic wrapper
    # text ("Unhandled exception while processing request") or outer middleware frames.
    kw = _keywords(error_texts + [mf.function for mf in mapped[-3:]])
    for c in candidates:
        hits = sorted(kw.intersection(_keywords([c.message])))
        if hits:
            add(c.sha, "keywords", W_KEYWORDS, f"Commit message mentions: {', '.join(hits[:5])}")

    suspects = []
    for sha, sigs in signals.items():
        if not sigs:
            continue
        score = sum(w for w, _ in sigs.values())
        reasons = [r for _, r in sorted(sigs.values(), key=lambda x: -x[0])]
        # Code that was already running in an earlier deployment (before the errors
        # appeared) is less likely to be the trigger than code that just shipped.
        if suspect_dep and shipped and sha not in shipped:
            score *= STABLE_CODE_FACTOR
            reasons.append(f"Already in production before {suspect_dep.version} while this error did not occur "
                           f"(score x{STABLE_CODE_FACTOR})")
        suspects.append(Suspect(commit=by_sha[sha], score=round(min(score, 1.0), 3), reasons=reasons,
                                deployment_version=suspect_dep.version if sha in shipped and suspect_dep else None))
    suspects.sort(key=lambda s: (-s.score, -s.commit.authored_at.timestamp()))
    return CorrelationResult(analysed_revision=rev, frames=mapped, suspects=suspects,
                             suspect_deployment=suspect_dep, previous_deployment=previous_dep, notes=notes)
