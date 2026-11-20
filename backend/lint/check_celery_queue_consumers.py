#!/usr/bin/env python3
"""Fail when code sends a Celery task to a queue that no worker consumes.

A task sent to a queue with no consumer waits in the broker until it expires.
Nothing logs an error. The check reads the source only:

- A queue is used when a `send_task`, `apply_async` or `signature` call has a
  `queue=` keyword, or a dict literal has a "queue" key (beat schedule
  `options`). The value must be an `OnyxCeleryQueues` constant or a string.
- A queue is consumed when a worker in each deployment lists it in `-Q`:
  `backend/supervisord.conf` (Docker Compose runs it) and the Helm
  `celery-worker-*.yaml` templates.

A call without `queue=` goes to the default queue, which the primary worker
consumes. A queue value the check cannot resolve is skipped.

`# celery-queue: allow <reason>` on the line that names the queue marks a
deliberate exception, for example a queue that only an optional worker reads.

Usage, from the repo root:
    python3 backend/lint/check_celery_queue_consumers.py
It always checks backend/onyx and backend/ee, so file arguments are ignored.
"""

import ast
import re
import sys
from pathlib import Path

ALLOW_MARKER = "celery-queue: allow"
_MARKER_WITH_REASON = re.compile(re.escape(ALLOW_MARKER) + r"\s*\S*\w")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_DIRS = ("backend/onyx", "backend/ee")
_CONSTANTS = _REPO_ROOT / "backend/onyx/configs/constants.py"
_SUPERVISORD = _REPO_ROOT / "backend/supervisord.conf"
_HELM_TEMPLATES = _REPO_ROOT / "deployment/helm/charts/onyx/templates"
_SEND_METHODS = {"send_task", "apply_async", "signature"}
_SUPERVISORD_QUEUES = re.compile(r"-Q\s+([\w,-]+)")
_HELM_QUEUES = re.compile(r'"-Q",\s*"([\w,-]+)"')


def queue_constants(source: str) -> dict[str, str]:
    """The `OnyxCeleryQueues` attribute names and their string values."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "OnyxCeleryQueues":
            return {
                stmt.targets[0].id: stmt.value.value
                for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            }
    raise RuntimeError("Bug: OnyxCeleryQueues is not in configs/constants.py")


def _queue_value(node: ast.expr, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "OnyxCeleryQueues"
    ):
        return constants.get(node.attr)
    return None


def find_used_queues(source: str, constants: dict[str, str]) -> list[tuple[int, str]]:
    """`(line, queue)` for each queue the source sends to, unless allowed."""
    lines = source.splitlines()
    used: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        values: list[ast.expr] = []
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _SEND_METHODS
        ):
            values = [k.value for k in node.keywords if k.arg == "queue"]
        elif isinstance(node, ast.Dict):
            values = [
                v
                for k, v in zip(node.keys, node.values, strict=True)
                if isinstance(k, ast.Constant) and k.value == "queue"
            ]
        for value in values:
            queue = _queue_value(value, constants)
            if queue is None:
                continue
            if ALLOW_MARKER in lines[value.lineno - 1]:
                continue
            used.append((value.lineno, queue))
    return used


def bad_markers(source: str) -> list[int]:
    return [
        i
        for i, line in enumerate(source.splitlines(), start=1)
        if ALLOW_MARKER in line and not _MARKER_WITH_REASON.search(line)
    ]


def consumed_queues(text: str, pattern: re.Pattern[str]) -> set[str]:
    return {q for match in pattern.findall(text) for q in match.split(",") if q}


def main() -> int:
    constants = queue_constants(_CONSTANTS.read_text())
    deployments = {
        "backend/supervisord.conf": consumed_queues(
            _SUPERVISORD.read_text(), _SUPERVISORD_QUEUES
        ),
        "Helm celery-worker-*.yaml": consumed_queues(
            "\n".join(
                p.read_text()
                for p in sorted(_HELM_TEMPLATES.glob("celery-worker-*.yaml"))
            ),
            _HELM_QUEUES,
        ),
    }
    errors: list[str] = []
    for scanned in _SCANNED_DIRS:
        root = _REPO_ROOT / scanned
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            source = path.read_text()
            rel = path.relative_to(_REPO_ROOT)
            errors.extend(
                f"{rel}:{line}: `{ALLOW_MARKER}` needs a reason"
                for line in bad_markers(source)
            )
            errors.extend(
                f"{rel}:{line}: queue '{queue}' has no worker in {name}. "
                "Add it to a worker's -Q list."
                for line, queue in find_used_queues(source, constants)
                for name, consumed in deployments.items()
                if queue not in consumed
            )
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
