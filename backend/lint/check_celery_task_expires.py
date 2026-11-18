#!/usr/bin/env python3
"""Fail when code enqueues a Celery task without an expiration.

A task with no expiry stays in the broker until a worker takes it, so a slow
or dead consumer grows the queue without bound. The check reads the source
only and flags three shapes:

- `x.send_task(...)` and `x.apply_async(...)` with no `expires=` keyword, or
  with `expires=None`. A `**options` argument does not count: the check
  cannot see what it holds.
- `x.delay(...)`, which cannot carry an expiry.
- A beat schedule entry, a dict literal with "task" and "schedule" keys, whose
  "options" is not a dict literal with an "expires" key, or has "expires": None.

It does not follow values. It does not see a task sent through a signature
(`.s()`, `.si()`, `signature()`, `group`, `chain`, `chord`), a `link=`
callback, or a schedule entry built without a dict literal. It does not prove
that a variable passed as `expires=` is set.

Usage, from the repo root:
    python3 backend/lint/check_celery_task_expires.py [<file> ...]
With no files it checks backend/onyx, backend/ee and backend/scripts.
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

# A deliberate exception opts out per statement and must say why:
#     # celery-expires: allow (<reason>)
ALLOW_MARKER = "celery-expires: allow"
_ALLOW_WITH_REASON = re.compile(re.escape(ALLOW_MARKER) + r"\s*\(\s*[^\s)][^)]*\)")
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_ROOTS = ("onyx", "ee", "scripts")
_SEND_CALLS = {"send_task", "apply_async"}

_FIX_SEND = (
    "{name}() has no expires=. Add expires=<seconds>, chosen from how long "
    "the task stays useful in the queue (see the *_EXPIRES constants in "
    "onyx/configs/constants.py and BEAT_EXPIRES_DEFAULT)."
)
_FIX_NONE = "{name}() has expires=None. Pass a number of seconds."
_FIX_DELAY = (
    "delay() cannot set an expiry. Use "
    "apply_async(kwargs={{...}}, expires=<seconds>) or send_task(..., expires=<seconds>)."
)
_FIX_BEAT = (
    'beat schedule entry has no "expires" in a literal "options" dict. Add '
    '"options": {{"expires": BEAT_EXPIRES_DEFAULT}} or a value under the '
    "schedule interval."
)
_FIX_REASON = (
    f"`# {ALLOW_MARKER}` needs a reason. Write `# {ALLOW_MARKER} (<why this "
    "task has no expiry>)`."
)


class _Finder(ast.NodeVisitor):
    def __init__(self, comments: dict[int, str], accepted: set[int] | None) -> None:
        self._comments = comments
        self._accepted = accepted
        self._statement: ast.stmt | None = None
        self.found: dict[int, str] = {}

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.stmt):
            self._statement = node
        super().visit(node)

    def _flag(self, node: ast.expr, message: str) -> None:
        """The marker exempts one node: on its own lines or its statement's first."""
        end = node.end_lineno or node.lineno
        lines = {*range(node.lineno, end + 1)}
        if self._statement is not None:
            lines.add(self._statement.lineno)
        marked = [self._comments[line] for line in lines if line in self._comments]
        if any(_ALLOW_WITH_REASON.search(line) for line in marked):
            if self._accepted is not None:
                self._accepted.add(node.lineno)
            return
        if any(ALLOW_MARKER in line for line in marked):
            message = _FIX_REASON
        self.found[node.lineno] = message

    def visit_Call(self, node: ast.Call) -> None:
        name = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if name in _SEND_CALLS:
            expires = [kw.value for kw in node.keywords if kw.arg == "expires"]
            if not expires:
                self._flag(node, _FIX_SEND.format(name=name))
            elif _is_none(expires[0]):
                self._flag(node, _FIX_NONE.format(name=name))
        elif name == "delay":
            self._flag(node, _FIX_DELAY.format())
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        entry = _literal_keys(node)
        if "task" in entry and "schedule" in entry:
            options = entry.get("options")
            expires = (
                _literal_keys(options).get("expires")
                if isinstance(options, ast.Dict)
                else None
            )
            if expires is None or _is_none(expires):
                self._flag(node, _FIX_BEAT.format())
        self.generic_visit(node)


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _literal_keys(node: ast.Dict) -> dict[str, ast.expr]:
    return {
        key.value: value
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def find_missing_expires(
    source: str, *, accepted: set[int] | None = None
) -> dict[int, str]:
    """One-based line number of each enqueue without an expiry, with its fix."""
    # Comments only, so marker text in a string does not exempt a send.
    comments = {
        token.start[0]: token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    }
    finder = _Finder(comments, accepted)
    finder.visit(ast.parse(source))
    return dict(sorted(finder.found.items()))


def _default_files() -> list[Path]:
    return sorted(
        path for root in _DEFAULT_ROOTS for path in (_BACKEND_DIR / root).rglob("*.py")
    )


def main(paths: list[str]) -> int:
    files = [Path(path) for path in paths] if paths else _default_files()
    failures: list[str] = []
    for path in files:
        if path.suffix != ".py" or not path.is_file():
            continue
        found = find_missing_expires(path.read_text())
        failures.extend(f"{path}:{line}: {fix}" for line, fix in found.items())
    if not failures:
        return 0
    print("Every enqueued Celery task needs an expiration:")
    print("\n".join(f"  {failure}" for failure in failures))
    print(
        f"A deliberate exception may carry `# {ALLOW_MARKER} (<reason>)` on the "
        "line that opens the call."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
