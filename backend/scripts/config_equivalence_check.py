"""Equivalence checker for config-module migrations (TOML settings service).

Compares a config module's exported constants BEFORE a migration (at a git
ref) vs the current working tree, under the environment states whose
semantics the migration touches: every relevant env var unset, then each var
set to the empty string one at a time. Set-value coercion is covered
generically by the loader unit tests; vars with bespoke parse shapes are
hand-checked per the migration plan.

Usage (from the repo root):
    uv run python backend/scripts/config_equivalence_check.py \
        --module onyx.configs.app_configs [--ref main] [--names A,B,...]

Classification per scenario:
- REGRESSION  (exit 1): values differ while both versions succeeded, or the
  new version crashed where the old succeeded, or an old export vanished.
- EXPECTED    (logged): the old version crashed (e.g. int("") on a blank env
  var) and the new version imported cleanly with defaults.
- BOTH-CRASH  (logged): both versions raised — same fail-loud behavior.

Temporary migration tooling — delete once all config modules are migrated.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"

# The new facade must never read a real config file during comparison.
_PINNED_ENV = {"ONYX_CONFIG_FILE": "disabled"}


def discover_env_names(source: str) -> set[str]:
    """Collect env var names read by the OLD module source via the known
    idioms: os.environ.get / os.getenv / os.environ[...] / the
    _non_negative_int_env helper."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            first_arg = (
                node.args[0].value
                if node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                else None
            )
            if first_arg is None:
                continue
            if isinstance(func, ast.Attribute) and (
                func.attr == "getenv"
                or (
                    func.attr == "get"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "environ"
                )
            ):
                names.add(first_arg)
            elif isinstance(func, ast.Name) and func.id == "_non_negative_int_env":
                names.add(first_arg)
        elif isinstance(node, ast.Subscript):
            if (
                isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                names.add(node.slice.value)
    return names


@contextmanager
def env_state(cleared: set[str], overrides: dict[str, str]) -> Iterator[None]:
    touched = cleared | set(overrides) | set(_PINNED_ENV)
    saved = {name: os.environ.get(name) for name in touched}
    try:
        for name in cleared:
            os.environ.pop(name, None)
        os.environ.update(_PINNED_ENV)
        os.environ.update(overrides)
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _canonical_repr(value: object) -> str:
    if isinstance(value, (set, frozenset)):
        inner = ", ".join(sorted(repr(item) for item in value))
        return f"{type(value).__name__}({{{inner}}})"
    return repr(value)


def snapshot(module: types.ModuleType) -> dict[str, tuple[str, str]]:
    """{NAME: (type_name, repr)} for every value-like UPPER_SNAKE export."""
    out: dict[str, tuple[str, str]] = {}
    for name, value in vars(module).items():
        if name.startswith("_") or name != name.upper():
            continue
        if isinstance(value, types.ModuleType) or callable(value):
            continue
        out[name] = (type(value).__name__, _canonical_repr(value))
    return out


class OldModuleLoader:
    """Executes the pre-migration source fresh for each scenario."""

    _counter = 0

    def __init__(self, source: str, tmp_dir: Path) -> None:
        self._path = tmp_dir / "old_module.py"
        self._path.write_text(source)

    def load(self) -> tuple[dict[str, tuple[str, str]] | None, BaseException | None]:
        OldModuleLoader._counter += 1
        spec = importlib.util.spec_from_file_location(
            f"_config_equiv_old_{OldModuleLoader._counter}", self._path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not build import spec for {self._path}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:  # noqa: BLE001 — classification, not handling
            return None, e
        return snapshot(module), None


def load_new(
    dotted: str,
) -> tuple[dict[str, tuple[str, str]] | None, BaseException | None]:
    try:
        if dotted in sys.modules:
            module = importlib.reload(sys.modules[dotted])
        else:
            module = importlib.import_module(dotted)
    except Exception as e:  # noqa: BLE001 — classification, not handling
        return None, e
    return snapshot(module), None


def diff_snapshots(
    old: dict[str, tuple[str, str]], new: dict[str, tuple[str, str]]
) -> list[str]:
    problems: list[str] = []
    for name, old_value in sorted(old.items()):
        if name not in new:
            problems.append(f"{name}: exported by old module, missing from new")
        elif new[name] != old_value:
            problems.append(f"{name}: old={old_value} new={new[name]}")
    return problems


def run_scenario(
    cleared: set[str],
    overrides: dict[str, str],
    old_loader: OldModuleLoader,
    dotted: str,
) -> tuple[str, list[str]]:
    """Returns (classification, problem lines)."""
    with env_state(cleared, overrides):
        old_snap, old_exc = old_loader.load()
        new_snap, new_exc = load_new(dotted)

    if old_exc is None and new_exc is None:
        assert old_snap is not None and new_snap is not None
        problems = diff_snapshots(old_snap, new_snap)
        return ("REGRESSION" if problems else "OK", problems)
    if old_exc is not None and new_exc is not None:
        return ("BOTH-CRASH", [f"old: {old_exc!r}", f"new: {new_exc!r}"])
    if old_exc is not None:
        return ("EXPECTED", [f"old crashed ({old_exc!r}); new imported with defaults"])
    return ("REGRESSION", [f"new crashed where old succeeded: {new_exc!r}"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--module", required=True, help="dotted module, e.g. onyx.configs.app_configs"
    )
    parser.add_argument(
        "--ref", default="main", help="git ref holding the pre-migration module"
    )
    parser.add_argument(
        "--names",
        default="",
        help="comma-separated env var subset for the empty-string scenarios",
    )
    args = parser.parse_args()

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    rel_path = "backend/" + args.module.replace(".", "/") + ".py"
    old_source = subprocess.run(
        ["git", "show", f"{args.ref}:{rel_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    env_names = discover_env_names(old_source)
    scenario_names = (
        {name.strip() for name in args.names.split(",") if name.strip()}
        if args.names
        else env_names
    )
    unknown = scenario_names - env_names
    if unknown:
        print(f"WARNING: --names not read by the old module: {sorted(unknown)}")

    regressions: list[str] = []
    counts = {"OK": 0, "EXPECTED": 0, "BOTH-CRASH": 0, "REGRESSION": 0}

    with tempfile.TemporaryDirectory() as tmp:
        old_loader = OldModuleLoader(old_source, Path(tmp))

        scenarios: list[tuple[str, dict[str, str]]] = [("all-unset", {})]
        scenarios += [(f"{name}=''", {name: ""}) for name in sorted(scenario_names)]
        for label, overrides in scenarios:
            classification, problems = run_scenario(
                env_names, overrides, old_loader, args.module
            )
            counts[classification] += 1
            if classification == "REGRESSION":
                regressions.append(label)
                print(f"[REGRESSION] {label}")
                for line in problems:
                    print(f"    {line}")
            elif classification in ("EXPECTED", "BOTH-CRASH"):
                print(f"[{classification}] {label}: {problems[0]}")

    print(
        f"\n{args.module} vs {args.ref}: {counts['OK']} ok, "
        f"{counts['EXPECTED']} expected, {counts['BOTH-CRASH']} both-crash, "
        f"{counts['REGRESSION']} regressions "
        f"({len(env_names)} env vars, {len(scenario_names)} tested)"
    )
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
