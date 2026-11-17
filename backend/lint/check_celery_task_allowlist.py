#!/usr/bin/env python3
"""Fail when code adds a Celery task or beat entry that is not on the list.

A Celery task is for work that runs again: a periodic check, a step of a
pipeline, or a user-started job that is heavy, long, or must survive an API
restart. A run-once backfill or migration is not a task. A script cannot see
that difference, so every task and beat entry must be on
`celery_task_allowlist.txt` with a one-line reason, and a reviewer sees the new
line. The check reads the source only and flags:

- A `@shared_task` or `@<app>.task` function that is not on the list, is
  outside the task directories, or is not named with an `OnyxCeleryTask`
  constant.
- A beat schedule entry, a dict literal with "task", "schedule" and "name"
  keys, whose name is not on the list, or whose task is a raw string.
- A call to `add_periodic_task`, which schedules outside `beat_schedule.py`.
- A list line that no code uses, has no reason, or appears twice.

It does not see a task registered without a decorator, a `Task` subclass, or a
schedule entry whose task is not a literal, such as the copies the scheduler
makes in `apps/beat.py`.

Usage, from the repo root:
    python3 backend/lint/check_celery_task_allowlist.py
It always checks backend/onyx and backend/ee, so file arguments are ignored.
"""

import ast
import re
from pathlib import Path
from typing import NamedTuple

_BACKEND_DIR = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = Path(__file__).resolve().with_name("celery_task_allowlist.txt")
_SOURCE_ROOTS = ("onyx", "ee")
_TASK_DIRS = ("onyx/background/celery/tasks/", "ee/onyx/background/celery/tasks/")
# Only files with one of these strings can define a task or a beat entry.
_HINTS = ("shared_task", ".task", "schedule", "add_periodic_task")
_LINE = re.compile(r"^(task|beat) (\S.*?): (.*)$")
_ONE_OFF = " # one-off:"

_WHAT_IS_A_TASK = (
    "A Celery task is for work that runs again: a periodic check, a step of a "
    "pipeline, or a user-started job that is heavy, long, or must survive an API "
    "restart. A run-once backfill or migration is not a task: decide case by case "
    "where it runs, for example an Alembic migration or a script."
)


class Usage(NamedTuple):
    kind: str
    name: str
    location: str


class Problem(NamedTuple):
    location: str
    message: str


class Allowlist(NamedTuple):
    entries: set[tuple[str, str]]
    problems: list[Problem]


def _attribute_of(node: ast.expr | None, owner: str) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == owner
    ):
        return node.attr
    return None


def _beat_names(node: ast.expr) -> list[str] | None:
    """The literal name of a beat entry. An f-string keeps `{EXPR}` for each
    value, and a conditional gives the names of both branches."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append("{" + ast.unparse(value.value) + "}")
        return ["".join(parts)]
    if isinstance(node, ast.IfExp):
        body = _beat_names(node.body)
        orelse = _beat_names(node.orelse)
        return body + orelse if body is not None and orelse is not None else None
    return None


def _is_task_decorator(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id == "shared_task"
    return isinstance(target, ast.Attribute) and target.attr in ("shared_task", "task")


def find_usages(source: str, relative_path: str) -> tuple[list[Usage], list[Problem]]:
    """Tasks and beat entries that `source` defines, and the shapes that break
    the rule whatever the list says."""
    usages: list[Usage] = []
    problems: list[Problem] = []
    in_task_dir = relative_path.startswith(_TASK_DIRS)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                if not _is_task_decorator(decorator):
                    continue
                location = f"{relative_path}:{decorator.lineno}"
                keywords = decorator.keywords if isinstance(decorator, ast.Call) else []
                name_node = next((k.value for k in keywords if k.arg == "name"), None)
                name = _attribute_of(name_node, "OnyxCeleryTask")
                if not in_task_dir:
                    problems.append(
                        Problem(
                            location=location,
                            message=f"task {node.name} is outside the task "
                            f"directories. Move it under {' or '.join(_TASK_DIRS)}.",
                        )
                    )
                if name is None:
                    problems.append(
                        Problem(
                            location=location,
                            message=f"task {node.name} has no OnyxCeleryTask name. "
                            "Pass name=OnyxCeleryTask.<NAME> and add the constant "
                            "to onyx/configs/constants.py.",
                        )
                    )
                else:
                    usages.append(Usage(kind="task", name=name, location=location))
        elif isinstance(node, ast.Dict):
            location = f"{relative_path}:{node.lineno}"
            keys = {
                key.value: value
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if not ("task" in keys and "schedule" in keys and "name" in keys):
                continue
            task = keys["task"]
            if isinstance(task, ast.Constant):
                problems.append(
                    Problem(
                        location=location,
                        message="beat entry names its task with a string. Use "
                        "OnyxCeleryTask.<NAME>.",
                    )
                )
            names = _beat_names(keys["name"])
            if names is None:
                problems.append(
                    Problem(
                        location=location,
                        message="beat entry has no literal name. Give it a string "
                        "or f-string name.",
                    )
                )
                continue
            usages.extend(Usage(kind="beat", name=n, location=location) for n in names)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_periodic_task"
        ):
            problems.append(
                Problem(
                    location=f"{relative_path}:{node.lineno}",
                    message="add_periodic_task schedules outside the beat "
                    "schedule. Add an entry to beat_schedule.py.",
                )
            )
    return usages, problems


def parse_allowlist(text: str, label: str) -> Allowlist:
    entries: set[tuple[str, str]] = set()
    problems: list[Problem] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        location = f"{label}:{number}"
        match = _LINE.match(line)
        reason = match.group(3).split(_ONE_OFF)[0].strip() if match else ""
        if match is None or not reason:
            problems.append(
                Problem(
                    location=location,
                    message="write `task <NAME>: <reason>` or "
                    "`beat <name>: <reason>`. The reason cannot be empty.",
                )
            )
            continue
        entry = (match.group(1), match.group(2))
        if entry in entries:
            problems.append(
                Problem(
                    location=location,
                    message=f"{entry[0]} {entry[1]} is on the list twice.",
                )
            )
        entries.add(entry)
    return Allowlist(entries=entries, problems=problems)


def check(
    sources: dict[str, str], allowlist_text: str, allowlist_label: str
) -> list[Problem]:
    """`sources` maps a path relative to backend/ to its source."""
    allowlist = parse_allowlist(allowlist_text, allowlist_label)
    problems = list(allowlist.problems)
    used: set[tuple[str, str]] = set()
    for relative_path, source in sorted(sources.items()):
        usages, shape_problems = find_usages(source, relative_path)
        problems.extend(shape_problems)
        for usage in usages:
            used.add((usage.kind, usage.name))
            if (usage.kind, usage.name) not in allowlist.entries:
                problems.append(
                    Problem(
                        location=usage.location,
                        message=f"{usage.kind} {usage.name} is not on the list. "
                        f"{_WHAT_IS_A_TASK} If it is a task, add "
                        f"`{usage.kind} {usage.name}: <reason>` to "
                        f"backend/lint/{ALLOWLIST_PATH.name}.",
                    )
                )
    for kind, name in sorted(allowlist.entries - used):
        problems.append(
            Problem(
                location=allowlist_label,
                message=f"`{kind} {name}` is on the list but no code defines it. "
                "Remove the line.",
            )
        )
    return problems


def _read_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for root in _SOURCE_ROOTS:
        for path in (_BACKEND_DIR / root).rglob("*.py"):
            text = path.read_text()
            if any(hint in text for hint in _HINTS):
                sources[path.relative_to(_BACKEND_DIR).as_posix()] = text
    return sources


def main() -> int:
    label = f"backend/lint/{ALLOWLIST_PATH.name}"
    problems = check(_read_sources(), ALLOWLIST_PATH.read_text(), label)
    if not problems:
        return 0
    print("Celery tasks and beat entries must be on the approved list:")
    for problem in problems:
        location = problem.location
        if not location.startswith("backend/"):
            location = f"backend/{location}"
        print(f"  {location}: {problem.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
