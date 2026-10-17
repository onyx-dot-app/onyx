#!/usr/bin/env python3
"""Report whether project Codex hooks can inspect files for pre-commit."""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVENTS = ("Stop", "UserPromptSubmit")
EVENT_KEYS = {"Stop": "stop", "UserPromptSubmit": "user_prompt_submit"}
GIT_ROOT_PREFIX = "$(git rev-parse --show-toplevel)/"


def git_root(project: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def hook_config_source(project: Path, root: Path) -> Path:
    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
            "--absolute-git-dir",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    git_dirs = result.stdout.splitlines() if result.returncode == 0 else []
    if len(git_dirs) == 2:
        common_dir, git_dir = (Path(path) for path in git_dirs)
        if common_dir != git_dir and common_dir.name == ".git":
            return common_dir.parent / ".codex" / "hooks.json"
    config_root = project
    return config_root / ".codex" / "hooks.json"


def hook_paths(config: Path, root: Path | None) -> tuple[list[Path], list[str]]:
    try:
        payload: Any = json.loads(config.read_text())
    except (OSError, ValueError):
        return [], ["hooks_config_unreadable"]
    if not isinstance(payload, dict) or not isinstance(payload.get("hooks"), dict):
        return [], ["hooks_config_unreadable"]

    paths: list[Path] = []
    reasons: list[str] = []
    hooks: dict[str, Any] = payload["hooks"]
    for event in EVENTS:
        entries: Any = hooks.get(event, [])
        if not isinstance(entries, list):
            reasons.append("hooks_config_unreadable")
            continue
        commands: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                reasons.append("hooks_config_unreadable")
                continue
            for item in entry["hooks"]:
                if not isinstance(item, dict):
                    reasons.append("hooks_config_unreadable")
                elif item.get("type") == "command":
                    command = item.get("command")
                    if isinstance(command, str):
                        commands.append(command)
                    else:
                        reasons.append("hooks_config_unreadable")
        if not commands:
            reasons.append(f"{event.lower()}_hook_missing")
        for command in commands:
            try:
                argv = shlex.split(command)
            except ValueError:
                reasons.append("hook_command_unresolved")
                continue
            if len(argv) != 2 or argv[0] not in ("python", "python3"):
                reasons.append("hook_command_unresolved")
                continue
            raw_path = argv[1]
            if raw_path.startswith(GIT_ROOT_PREFIX) and root is not None:
                relative = Path(raw_path[len(GIT_ROOT_PREFIX) :])
                if relative.is_absolute() or ".." in relative.parts:
                    reasons.append("hook_command_unresolved")
                    continue
                path = root / relative
            else:
                path = Path(raw_path)
            if not path.is_absolute() or "$" in str(path):
                reasons.append("hook_command_unresolved")
                continue
            paths.append(path)
            if not path.is_file():
                reasons.append("hook_file_missing")
    return paths, reasons


def runtime_state(source: Path) -> tuple[str, dict[str, str], list[str]]:
    config = (
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    )
    try:
        payload: Any = tomllib.loads(config.read_text())
    except (OSError, ValueError):
        payload = {}
    hooks = payload.get("hooks", {}) if isinstance(payload, dict) else {}
    states = hooks.get("state", {}) if isinstance(hooks, dict) else {}
    if not isinstance(states, dict):
        states = {}
    events: dict[str, str] = {}
    for event in EVENTS:
        key = f"{source}:{EVENT_KEYS[event]}:0:0"
        state = states.get(key, {})
        events[event] = (
            "disabled"
            if isinstance(state, dict) and state.get("enabled") is False
            else "unverified"
        )
    disabled = [
        f"{EVENT_KEYS[event]}_disabled"
        for event, state in events.items()
        if state == "disabled"
    ]
    if disabled:
        return "disabled", events, disabled
    return "unverified", events, ["runtime_activation_unverified"]


def diagnose(project: Path) -> tuple[int, dict[str, Any]]:
    root = git_root(project)
    config_source = (
        hook_config_source(project, root) if root else project / ".codex" / "hooks.json"
    )
    paths, reasons = hook_paths(config_source, root)
    if root is None:
        reasons.append("not_git_repo")
    else:
        if not (root / ".pre-commit-config.yaml").is_file():
            reasons.append("pre_commit_config_missing_at_git_root")
        if project != root:
            relative = project.relative_to(root)
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", "--", str(relative)],
                cwd=root,
                check=False,
            )
            if ignored.returncode == 0:
                reasons.append("project_ignored_by_git")
        in_venv = root / ".venv" / "bin" / "pre-commit"
        if shutil.which("pre-commit") is None and not (
            in_venv.is_file() and os.access(in_venv, os.X_OK)
        ):
            reasons.append("pre_commit_unavailable")

    failures = {
        "hooks_config_unreadable",
        "hook_command_unresolved",
        "hook_file_missing",
        "not_git_repo",
    }
    static_reasons = reasons.copy()
    if any(
        reason in failures or reason.endswith("_hook_missing")
        for reason in static_reasons
    ):
        static_status = "failed"
        next_action = "Repair the configured hook commands or use a Git checkout."
    elif static_reasons:
        static_status = "degraded"
        next_action = "Use a tracked Git checkout with a pre-commit config at its root."
    else:
        static_status = "ok"
        next_action = "Inspect both project hooks in Codex /hooks and observe a turn."
    runtime_status, event_states, runtime_reasons = runtime_state(config_source)
    reasons.extend(runtime_reasons)
    status = static_status if static_status != "ok" else "degraded"
    exit_code = 2 if status == "failed" else 1
    if runtime_status == "disabled" and static_status == "ok":
        next_action = "Enable the disabled project hook through Codex /hooks."
    report: dict[str, Any] = {
        "status": status,
        "static_status": static_status,
        "runtime_status": runtime_status,
        "event_states": event_states,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "codex-hook-health",
        "project": str(project),
        "git_root": str(root) if root else None,
        "config_source": str(config_source),
        "hook_targets": sorted({str(path) for path in paths}),
        "reasons": sorted(set(reasons)),
        "next_action": next_action,
    }
    return exit_code, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", type=Path, default=Path.cwd())
    project = parser.parse_args().project.expanduser().resolve()
    if not project.is_dir():
        print(
            json.dumps(
                {
                    "status": "failed",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "source": "codex-hook-health",
                    "project": str(project),
                    "git_root": None,
                    "hook_targets": [],
                    "reasons": ["project_not_directory"],
                    "next_action": "Choose an existing project directory.",
                },
                sort_keys=True,
            )
        )
        return 2
    code, report = diagnose(project)
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
