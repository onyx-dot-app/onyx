#!/usr/bin/env python3
"""Manage the local Onyx dev stack without opening an editor."""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_COMPOUND = "Run All Onyx Services"
# The Slack bot binds its metrics server to this port with no override.
SLACK_METRICS_PORT = 8000
INFRA_CONTAINER_PORT = ("code-interpreter", 8000)
PLACEHOLDER_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]*)=<REPLACE(?: THIS|_THIS)>$")
WORKSPACE_PATTERN = re.compile(r"\$\{(?:workspaceFolder|workspaceRoot)\}")


class DevStackError(RuntimeError):
    """A user-actionable dev stack error."""


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str]


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def find_repo_root() -> Path:
    try:
        root = Path(git_output(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    except (OSError, subprocess.CalledProcessError) as error:
        raise DevStackError("Run this helper from an Onyx Git worktree.") from error

    if not (root / ".vscode" / "launch.json").is_file():
        raise DevStackError(f"{root} does not contain .vscode/launch.json.")
    return root


def state_dir(root: Path) -> Path:
    path = Path(git_output(root, "rev-parse", "--git-path", "onyx-dev-stack"))
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def project_name(root: Path) -> str:
    name = re.sub(r"[^a-z0-9_-]+", "-", root.name.lower()).strip("-_") or "onyx"
    identity = hashlib.sha256(str(root).encode()).hexdigest()[:8]
    return f"{name[:40]}-{identity}"


def python_executable(root: Path) -> Path:
    candidates = (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise DevStackError("Missing .venv. Run uv sync --frozen first.")


def ods_command(root: Path, *args: str) -> list[str]:
    return [
        "uv",
        "run",
        "--frozen",
        "--only-group",
        "ods",
        "ods",
        "--project",
        project_name(root),
        *args,
    ]


def run_checked(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    print(f"Running: {format_command(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def strip_jsonc(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue

        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(text):
                if text[index] == "*" and text[index + 1] == "/":
                    index += 2
                    break
                index += 1
            continue

        output.append(char)
        index += 1

    return re.sub(r",\s*([}\]])", r"\1", "".join(output))


def load_jsonc(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(strip_jsonc(path.read_text()))
    except (OSError, json.JSONDecodeError) as error:
        raise DevStackError(f"Cannot parse {path}: {error}") from error
    if not isinstance(parsed, dict):
        raise DevStackError(f"Expected an object in {path}.")
    return parsed


def expand_workspace(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        expanded = WORKSPACE_PATTERN.sub(str(root), value)
        if "${" in expanded:
            raise DevStackError(f"Unsupported launch variable in {value!r}.")
        return expanded
    if isinstance(value, list):
        return [expand_workspace(item, root) for item in value]
    if isinstance(value, dict):
        return {key: expand_workspace(item, root) for key, item in value.items()}
    return value


def parse_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
        return str(parsed)
    return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()


def load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise DevStackError(f"Missing environment file: {path}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise DevStackError(f"Invalid environment entry at {path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise DevStackError(f"Invalid environment key at {path}:{line_number}")
        values[key] = parse_env_value(value)
    return values


def environment_for(config: dict[str, Any], root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env_file = config.get("envFile")
    if env_file:
        env.update(load_env_file(Path(expand_workspace(env_file, root))))
    env.update(
        {
            key: str(expand_workspace(value, root))
            for key, value in config.get("env", {}).items()
        }
    )
    return env


def process_spec(
    config: dict[str, Any],
    root: Path,
    *,
    load_environment: bool = True,
) -> ProcessSpec:
    name = config.get("name")
    if not isinstance(name, str):
        raise DevStackError("A launch configuration has no name.")

    if config.get("request") != "launch":
        raise DevStackError(f"{name} does not use a launch request.")

    env = environment_for(config, root) if load_environment else os.environ.copy()
    ports = read_ports(root) if load_environment else {}
    web_port = ports.get("web", 3000)
    api_port = ports.get("api", 8080)
    model_port = ports.get("model", 9000)
    mcp_port = ports.get("mcp", 8090)
    if load_environment:
        env.update(
            {
                "PORT": str(web_port),
                "MODEL_SERVER_PORT": str(model_port),
                "INTERNAL_URL": f"http://localhost:{api_port}",
                "MCP_INTERNAL_URL": f"http://localhost:{mcp_port}",
                "MCP_SERVER_PORT": str(mcp_port),
                "WEB_DOMAIN": f"http://localhost:{web_port}",
            }
        )
    if name == "Web Server":
        return ProcessSpec(name, ods_command(root, "web", "dev"), root, env)

    cwd = Path(expand_workspace(config.get("cwd", str(root)), root))
    args = [str(item) for item in expand_workspace(config.get("args", []), root)]
    if load_environment and "--port" in args:
        port_by_name = {
            "API Server": api_port,
            "Model Server": model_port,
            "MCP Server": mcp_port,
        }
        if name in port_by_name:
            args[args.index("--port") + 1] = str(port_by_name[name])
    config_type = config.get("type")

    if config_type == "debugpy":
        python = str(python_executable(root))
        if module := config.get("module"):
            command = [python, "-m", str(module), *args]
        elif program := config.get("program"):
            command = [python, str(expand_workspace(program, root)), *args]
        else:
            raise DevStackError(f"{name} has no module or program.")
    elif config_type == "node":
        executable = config.get("runtimeExecutable")
        if not executable:
            raise DevStackError(f"{name} has no runtimeExecutable.")
        runtime_args = [
            str(item) for item in expand_workspace(config.get("runtimeArgs", []), root)
        ]
        command = [str(executable), *runtime_args]
    else:
        raise DevStackError(f"{name} uses unsupported launch type {config_type!r}.")

    return ProcessSpec(name=name, command=command, cwd=cwd, env=env)


def compound_configs(
    launch: dict[str, Any],
    compound_name: str,
) -> list[dict[str, Any]]:
    compounds = {
        item.get("name"): item
        for item in launch.get("compounds", [])
        if isinstance(item, dict)
    }
    compound = compounds.get(compound_name)
    if compound is None:
        raise DevStackError(f"Unknown launch compound: {compound_name}")

    configs = {
        item.get("name"): item
        for item in launch.get("configurations", [])
        if isinstance(item, dict)
    }
    resolved: list[dict[str, Any]] = []
    for name in compound.get("configurations", []):
        config = configs.get(name)
        if config is None:
            raise DevStackError(f"Compound references missing configuration: {name}")
        resolved.append(config)
    return resolved


def format_command(command: list[str]) -> str:
    return shlex.join(command)


def process_start_marker(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        capture_output=True,
        text=True,
        check=False,
    )
    marker = result.stdout.strip()
    return marker or None


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def process_is_current(record: dict[str, Any]) -> bool:
    pid = int(record["pid"])
    if not pid_exists(pid):
        return False
    expected_marker = record.get("start_marker")
    if expected_marker and process_start_marker(pid) != expected_marker:
        return False
    try:
        if os.getpgid(pid) != int(record["pgid"]):
            return False
    except OSError:
        return False
    return True


@contextmanager
def operation_lock(root: Path, command: str) -> Iterator[None]:
    user_id = str(os.getuid())
    lock_path = Path(tempfile.gettempdir()) / f"onyx-dev-stack-{user_id}.lock"
    lock_file = lock_path.open("a+", encoding="utf-8")
    acquired = False

    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            lock_file.seek(0)
            owner_description = lock_file.read().strip() or "another process"
            raise DevStackError(
                f"Another agent owns the dev stack lock: {owner_description}"
            ) from error
        acquired = True

        owner_metadata = {
            "pid": os.getpid(),
            "root": str(root),
            "command": command,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(json.dumps(owner_metadata))
        lock_file.flush()
        os.fsync(lock_file.fileno())
        yield
    finally:
        if acquired:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def read_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise DevStackError(f"Cannot read state file {path}: {error}") from error
    if not isinstance(state, dict):
        raise DevStackError(f"Invalid state file: {path}")
    return state


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def localize_symlink(path: Path) -> None:
    if not path.is_symlink():
        return
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        path.unlink()
        return
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary_file:
        temporary_file.write(content)
        temporary = Path(temporary_file.name)
    temporary.chmod(0o600)
    temporary.replace(path)
    print(f"Converted {path} into a worktree-local file.")


def prepare_env(root: Path) -> None:
    vscode_dir = root / ".vscode"
    env_path = vscode_dir / ".env"
    web_env_path = vscode_dir / ".env.web"
    localize_symlink(env_path)
    localize_symlink(web_env_path)

    if env_path.exists():
        print(f"Keeping existing {env_path}")
    else:
        template_path = vscode_dir / "env_template.txt"
        lines: list[str] = []
        for line in template_path.read_text().splitlines():
            match = PLACEHOLDER_PATTERN.match(line)
            if match:
                key = match.group(1)
                value = (
                    "StrongPassword123!"
                    if key == "OPENSEARCH_INITIAL_ADMIN_PASSWORD"
                    else ""
                )
                lines.append(f"{key}={value}")
                continue
            if line.startswith("SAML_CONF_DIR=/<ABSOLUTE PATH TO ONYX>/onyx/"):
                saml_dir = root / "backend" / "ee" / "onyx" / "configs" / "saml_config"
                lines.append(f"SAML_CONF_DIR={saml_dir}")
                continue
            if line == 'LANGSMITH_TRACING="true"':
                lines.append("LANGSMITH_TRACING=false")
                continue
            lines.append(line)
        env_path.write_text("\n".join(lines) + "\n")
        env_path.chmod(0o600)
        print(f"Created {env_path} from {template_path.name}")

    if web_env_path.exists():
        print(f"Keeping existing {web_env_path}")
    else:
        template_path = vscode_dir / "env.web_template.txt"
        shutil.copyfile(template_path, web_env_path)
        web_env_path.chmod(0o600)
        print(f"Created {web_env_path} from {template_path.name}")

    print("Add GEN_AI_API_KEY only if model-backed behavior is needed.")


def ensure_dependencies(root: Path) -> None:
    for command in ("uv", "bun", "docker"):
        if not shutil.which(command):
            raise DevStackError(f"Missing required command: {command}")
    run_checked(["docker", "info"], cwd=root)
    run_checked(["uv", "sync", "--frozen"], cwd=root)
    python_executable(root)


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(("127.0.0.1", port)) == 0


@contextmanager
def reserve_port(port: int) -> Iterator[None]:
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        reservation.bind(("127.0.0.1", port))
        reservation.listen(1)
    except OSError as error:
        reservation.close()
        raise DevStackError(
            f"Cannot reserve application port {port}: {error}"
        ) from error
    try:
        yield
    finally:
        reservation.close()


def project_service_uses_host_port(
    root: Path,
    service: str,
    container_port: int,
    host_port: int,
) -> bool:
    container = f"{project_name(root)}-{service}-1"
    result = subprocess.run(
        ["docker", "port", container, f"{container_port}/tcp"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return any(
        line.rsplit(":", 1)[-1] == str(host_port) for line in result.stdout.splitlines()
    )


def start_infrastructure(root: Path) -> None:
    service, container_port = INFRA_CONTAINER_PORT
    if project_service_uses_host_port(
        root, service, container_port, SLACK_METRICS_PORT
    ):
        print("Recreating infrastructure to reserve application ports.")
        run_checked(ods_command(root, "compose", "dev", "--infra", "--down"), cwd=root)
    with ExitStack() as reservations:
        if not port_is_open(SLACK_METRICS_PORT):
            reservations.enter_context(reserve_port(SLACK_METRICS_PORT))
        run_checked(ods_command(root, "compose", "dev", "--infra"), cwd=root)


def tail_text(path: Path, lines: int) -> str:
    try:
        content = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def stop_records(records: list[dict[str, Any]], timeout: float) -> None:
    active = [record for record in records if process_is_current(record)]
    for record in active:
        try:
            os.killpg(int(record["pgid"]), signal.SIGTERM)
        except ProcessLookupError:
            continue

    deadline = time.monotonic() + timeout
    while active and time.monotonic() < deadline:
        active = [record for record in active if process_is_current(record)]
        if active:
            time.sleep(0.2)

    for record in active:
        try:
            os.killpg(int(record["pgid"]), signal.SIGKILL)
        except ProcessLookupError:
            continue


def start_processes(root: Path, compound_name: str) -> int:
    stack_dir = state_dir(root)
    state_path = stack_dir / "state.json"
    last_state_path = stack_dir / "last-state.json"
    old_state = read_state(state_path)
    if old_state:
        active = [
            record
            for record in old_state.get("processes", [])
            if process_is_current(record)
        ]
        if active:
            names = ", ".join(record["name"] for record in active)
            raise DevStackError(f"Dev stack already has running processes: {names}")
        write_state(last_state_path, old_state)
        state_path.unlink(missing_ok=True)

    allocated: dict[str, int] = {}
    claimed: set[int] = {SLACK_METRICS_PORT}
    for service, preferred in (
        ("web", 3000),
        ("api", 8080),
        ("mcp", 8090),
        ("model", 9000),
    ):
        for port in range(preferred, 65536):
            if port in claimed:
                continue
            try:
                with socket.socket() as probe:
                    probe.bind(("", port))
            except OSError:
                continue
            allocated[service] = port
            claimed.add(port)
            break
        else:
            raise DevStackError(f"No available port for {service}.")
    write_state(stack_dir / "ports.json", allocated)
    run_checked(ods_command(root, "env"), cwd=root)
    launch = load_jsonc(root / ".vscode" / "launch.json")
    configs = compound_configs(launch, compound_name)
    if port_is_open(SLACK_METRICS_PORT):
        print(
            f"Skipping optional Slack Bot: its metrics port {SLACK_METRICS_PORT} is occupied."
        )
        configs = [config for config in configs if config.get("name") != "Slack Bot"]
    specs = [process_spec(config, root) for config in configs]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_dir = stack_dir / "logs" / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    state = {
        "schema_version": 1,
        "root": str(root),
        "project": project_name(root),
        "compound": compound_name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "log_dir": str(log_dir),
        "processes": records,
    }
    write_state(state_path, state)

    try:
        for position, spec in enumerate(specs, start=1):
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", spec.name).strip("-")
            log_path = log_dir / f"{position:02d}-{safe_name}.log"
            with log_path.open("w") as log_handle:
                log_handle.write(f"cwd: {spec.cwd}\n")
                log_handle.write(f"command: {format_command(spec.command)}\n\n")
                log_handle.flush()
                process = subprocess.Popen(
                    spec.command,
                    cwd=spec.cwd,
                    env=spec.env,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            records.append(
                {
                    "name": spec.name,
                    "pid": process.pid,
                    "pgid": os.getpgid(process.pid),
                    "start_marker": process_start_marker(process.pid),
                    "command": spec.command,
                    "cwd": str(spec.cwd),
                    "log": str(log_path),
                }
            )
            write_state(state_path, state)
            print(f"Started {spec.name} as PID {process.pid}; log: {log_path}")
    except BaseException:
        stop_records(records, timeout=5)
        state_path.unlink(missing_ok=True)
        raise

    time.sleep(1)
    failed = [record for record in records if not process_is_current(record)]
    for record in failed:
        print(
            f"warning: {record['name']} exited during startup.\n"
            f"{tail_text(Path(record['log']), 30)}",
            file=sys.stderr,
        )
    return 2 if failed else 0


def stop_processes(root: Path, timeout: float) -> None:
    stack_dir = state_dir(root)
    state_path = stack_dir / "state.json"
    state = read_state(state_path)
    if not state:
        print("No managed application processes are running.")
        return
    stop_records(state.get("processes", []), timeout)
    write_state(stack_dir / "last-state.json", state)
    state_path.unlink(missing_ok=True)
    print("Stopped managed application processes.")


def read_ports(root: Path) -> dict[str, int]:
    ports_path = state_dir(root) / "ports.json"
    if not ports_path.exists():
        return {}
    ports = json.loads(ports_path.read_text())
    if not isinstance(ports, dict):
        raise DevStackError(f"Invalid ports file: {ports_path}")
    return {str(key): int(value) for key, value in ports.items()}


def readiness_url() -> str:
    ports = read_ports(find_repo_root())
    return f"http://localhost:{ports.get('web', 3000)}/api/auth/type"


def readiness_status() -> bool:
    try:
        with urllib.request.urlopen(readiness_url(), timeout=2) as response:  # noqa: S310 - constructed localhost HTTP URL
            return int(response.status) == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_for_readiness(root: Path, timeout: float) -> bool:
    state = read_state(state_dir(root) / "state.json")
    if not state:
        raise DevStackError("Application state disappeared during startup.")

    required_names = {"Web Server", "API Server"}
    present_names = {record["name"] for record in state.get("processes", [])}
    missing_names = required_names - present_names
    if missing_names:
        missing = ", ".join(sorted(missing_names))
        raise DevStackError(f"Launch compound is missing readiness services: {missing}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        required = [
            record
            for record in state.get("processes", [])
            if record["name"] in required_names
        ]
        if any(not process_is_current(record) for record in required):
            return False
        if readiness_status():
            print(f"Ready: {readiness_url()}")
            return True
        time.sleep(2)
    return False


def status(root: Path) -> int:
    state = read_state(state_dir(root) / "state.json")
    if not state:
        print("No managed dev stack state exists.")
        return 1

    records = state.get("processes", [])
    all_running = bool(records)
    print(f"Project: {state.get('project')}")
    print(f"Compound: {state.get('compound')}")
    print(f"Started: {state.get('started_at')}")
    for record in records:
        running = process_is_current(record)
        all_running = all_running and running
        state_label = "running" if running else "exited"
        print(
            f"{state_label:7}  {record['name']}  PID {record['pid']}  {record['log']}"
        )
    print(f"ready    {readiness_url()}: {'yes' if readiness_status() else 'no'}")
    return 0 if all_running and readiness_status() else 2


def show_logs(
    root: Path,
    *,
    service: str | None,
    lines: int,
    follow: bool,
) -> None:
    stack_dir = state_dir(root)
    state = read_state(stack_dir / "state.json")
    if not state:
        state = read_state(stack_dir / "last-state.json")
    if not state:
        raise DevStackError("No managed dev stack logs exist.")

    records = state.get("processes", [])
    if service:
        records = [record for record in records if record["name"] == service]
        if not records:
            names = ", ".join(record["name"] for record in state["processes"])
            raise DevStackError(f"Unknown service {service!r}. Available: {names}")

    paths = [Path(record["log"]) for record in records]
    if follow:
        if not shutil.which("tail"):
            raise DevStackError("Following logs requires the tail command.")
        subprocess.run(
            ["tail", "-n", str(lines), "-F", *(str(path) for path in paths)],
            check=False,
        )
        return

    for record, path in zip(records, paths, strict=True):
        print(f"\n==> {record['name']} ({path}) <==")
        text = tail_text(path, lines)
        if text:
            print(text)


def print_commands(root: Path, compound_name: str) -> None:
    launch = load_jsonc(root / ".vscode" / "launch.json")
    for config in compound_configs(launch, compound_name):
        spec = process_spec(config, root, load_environment=False)
        print(f"{spec.name}: cd {spec.cwd} && {format_command(spec.command)}")


def up(root: Path, compound_name: str, timeout: float) -> int:
    prepare_env(root)
    ensure_dependencies(root)
    current_state = read_state(state_dir(root) / "state.json")
    if current_state:
        records = current_state.get("processes", [])
        if records and all(process_is_current(record) for record in records):
            if readiness_status():
                print("The managed dev stack is already running.")
                return status(root)
        print("Replacing an incomplete managed application start.")
        stop_processes(root, timeout=20)

    start_infrastructure(root)
    run_checked(ods_command(root, "env"), cwd=root)
    migration_env = os.environ.copy()
    migration_env.update(load_env_file(root / ".vscode" / ".env"))
    migration_env.setdefault("POSTGRES_HOST", "localhost")
    run_checked(ods_command(root, "db", "upgrade"), cwd=root, env=migration_env)
    start_status = start_processes(root, compound_name)
    if not wait_for_readiness(root, timeout):
        print(
            f"error: stack did not become ready within {timeout:g} seconds. Inspect logs.",
            file=sys.stderr,
        )
        return 2
    final_status = status(root)
    return max(start_status, final_status)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("prepare-env", help="Create or localize env files")

    up_parser = subparsers.add_parser("up", help="Prepare and start the full stack")
    up_parser.add_argument("--compound", default=DEFAULT_COMPOUND)
    up_parser.add_argument("--timeout", type=float, default=120.0)

    start_parser = subparsers.add_parser("start", help="Start application processes")
    start_parser.add_argument("--compound", default=DEFAULT_COMPOUND)

    stop_parser = subparsers.add_parser("stop", help="Stop application processes")
    stop_parser.add_argument("--timeout", type=float, default=20.0)

    restart_parser = subparsers.add_parser(
        "restart", help="Restart application processes"
    )
    restart_parser.add_argument("--compound", default=DEFAULT_COMPOUND)
    restart_parser.add_argument("--timeout", type=float, default=20.0)

    down_parser = subparsers.add_parser(
        "down", help="Stop applications and infrastructure"
    )
    down_parser.add_argument("--timeout", type=float, default=20.0)

    subparsers.add_parser("status", help="Show process and readiness state")

    logs_parser = subparsers.add_parser("logs", help="Show application logs")
    logs_parser.add_argument("--service")
    logs_parser.add_argument("--lines", type=int, default=80)
    logs_parser.add_argument("--follow", action="store_true")

    commands_parser = subparsers.add_parser(
        "print-commands", help="Print the resolved background commands"
    )
    commands_parser.add_argument("--compound", default=DEFAULT_COMPOUND)

    return parser.parse_args()


def main() -> int:
    if os.name != "posix":
        print("error: this helper supports macOS and Linux only.", file=sys.stderr)
        return 1
    args = parse_args()
    root = find_repo_root()
    mutating_commands = {"prepare-env", "up", "start", "stop", "restart", "down"}

    try:
        context = (
            operation_lock(root, args.command)
            if args.command in mutating_commands
            else _null_context()
        )
        with context:
            if args.command == "prepare-env":
                prepare_env(root)
            elif args.command == "up":
                return up(root, args.compound, args.timeout)
            elif args.command == "start":
                prepare_env(root)
                ensure_dependencies(root)
                return start_processes(root, args.compound)
            elif args.command == "stop":
                stop_processes(root, args.timeout)
            elif args.command == "restart":
                stop_processes(root, args.timeout)
                return start_processes(root, args.compound)
            elif args.command == "down":
                stop_processes(root, args.timeout)
                run_checked(ods_command(root, "compose", "dev", "--down"), cwd=root)
            elif args.command == "status":
                return status(root)
            elif args.command == "logs":
                show_logs(
                    root, service=args.service, lines=args.lines, follow=args.follow
                )
            elif args.command == "print-commands":
                print_commands(root, args.compound)
            else:
                raise AssertionError(f"Unhandled command: {args.command}")
    except DevStackError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(
            f"error: command failed with exit code {error.returncode}", file=sys.stderr
        )
        return error.returncode or 1
    return 0


@contextmanager
def _null_context() -> Iterator[None]:
    yield


if __name__ == "__main__":
    raise SystemExit(main())
