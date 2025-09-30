#!/usr/bin/env python3
"""
Onyx CLI

Commands:
  onyx doctor
  onyx install [--dir PATH] [--stable | --beta] [--all]
  onyx up [--build-from-source] [-f COMPOSE_FILE] [-n PROJECT_NAME]
  onyx update
  onyx uninstall [-n PROJECT_NAME] [--dir PATH]
  onyx dev [--dir PATH]

Defaults:
  - Install directory: ~/onyx-dot-app
  - Repo path: ~/onyx-dot-app/onyx
  - Default branch/ref for install: main (unless --stable or --beta)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional
from typing import Tuple

# ---------- Constants ----------

DEFAULT_HOME = Path.home() / "onyx-dot-app"
REPO_DIRNAME = "onyx"
REPO_URL = "https://github.com/onyx-dot-app/onyx.git"
VERSIONS_URL = "https://app.danswer.ai/api/versions" # TODO: change to cloud.onyx.app when ready

# Requirements thresholds
MIN_CPUS = 4
MIN_RAM_GB_HARD = 10  # must meet or exit
MIN_RAM_GB_WARN = 16  # warn if below

# Docker compose defaults
DEFAULT_PROJECT = "onyx-stack"
DEFAULT_COMPOSE_REL = "deployment/docker_compose/docker-compose.dev.yml"

# ---------- Utilities ----------


def run(
    cmd: list[str], cwd: Optional[Path] = None, check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess:
    """
    Run a shell command.
    """
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=check,
            capture_output=capture,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        if e.stdout:
            print(e.stdout, file=sys.stdout)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        raise


def which(prog: str) -> Optional[str]:
    return shutil.which(prog)


def human_gb(bytes_val: int) -> float:
    return round(bytes_val / (1024**3), 2)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def print_header(txt: str) -> None:
    print(f"\n=== {txt} ===")


def docker_compose_cmd() -> list[str]:
    """
    Prefer 'docker compose' (new) but fall back to 'docker-compose' if needed.
    Returns the command prefix as a list, e.g. ["docker", "compose"].
    """
    if which("docker"):
        # Check if 'docker compose' is supported
        try:
            run(["docker", "compose", "version"], check=True)
            return ["docker", "compose"]
        except Exception:
            pass
    if which("docker-compose"):
        return ["docker-compose"]
    # If neither available, we'll fail in doctor
    return ["docker", "compose"]  # best default; doctor will catch errors


def get_versions() -> dict:
    req = urllib.request.Request(VERSIONS_URL, headers={"User-Agent": "onyx-cli"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def resolve_ref(stable: bool, beta: bool) -> str:
    """
    Returns a git ref to checkout based on flags:
      - --stable -> versions['stable']['onyx']
      - --beta   -> versions['dev']['onyx']
      - default  -> 'main'
    """
    if stable:
        v = get_versions()
        return v["stable"]["danswer"] # TODO: change to onyx when ready
    if beta:
        v = get_versions()
        return v["dev"]["danswer"] # TODO: change to onyx when ready
    return "main"


def docker_info() -> Tuple[Optional[int], Optional[float]]:
    """
    Returns (cpus, mem_gb_available_to_docker)
    """
    if not which("docker"):
        return None, None
    # Use Go template fields so we don't have to parse free-form text
    try:
        cp = run(
            ["docker", "info", "--format", "{{.NCPU}}|{{.MemTotal}}"], capture=True
        )
        out = (cp.stdout or "").strip()
        parts = out.split("|")
        if len(parts) != 2:
            return None, None
        cpus = int(parts[0])
        mem_bytes = int(parts[1])
        mem_gb = mem_bytes / (1024**3)
        return cpus, mem_gb
    except Exception:
        return None, None


def check_python_version(required_major=3, required_minor=11) -> bool:
    return (sys.version_info.major, sys.version_info.minor) >= (
        required_major,
        required_minor,
    )


def has_git() -> bool:
    return which("git") is not None


def is_git_repo(p: Path) -> bool:
    return (p / ".git").exists()


def is_sparse_checkout(repo: Path) -> bool:
    """
    Returns True if the repo has sparse-checkout enabled.
    Works for both cone and non-cone modes.
    """
    try:
        # Newer git: config flag
        cp = run(["git", "config", "--bool", "core.sparseCheckout"], cwd=repo, capture=True)
        if (cp.stdout or "").strip().lower() == "true":
            return True
    except Exception:
        pass

    # Fallback: presence of sparse-checkout file often indicates sparse mode
    if (repo / ".git" / "info" / "sparse-checkout").exists():
        return True

    # Last resort: try a harmless list call (returns 0 even when disabled on some versions)
    try:
        cp = run(["git", "sparse-checkout", "list"], cwd=repo, capture=True, check=False)
        # If it prints patterns, it's active; if empty, it might still be disabled.
        if (cp.stdout or "").strip():
            return True
    except Exception:
        pass

    return False


def disable_sparse_checkout(repo: Path) -> None:
    """
    Disable sparse-checkout and expand working tree.
    Also unsets cone mode if present.
    """
    print("→ Disabling sparse-checkout to expand to full repository")
    # Disable sparse mode
    run(["git", "sparse-checkout", "disable"], cwd=repo, check=False)
    # Unset cone flag if it exists (harmless if missing)
    run(["git", "config", "--unset", "core.sparseCheckoutCone"], cwd=repo, check=False)
    # Ensure working tree fully repopulates
    run(["git", "checkout", "."], cwd=repo, check=False)


def repo_path(base_dir: Path) -> Path:
    """
    If --dir points directly to a repo (contains .git or deployment/),
    return it as-is. Otherwise, append 'onyx'.
    """
    if (base_dir / ".git").exists() or (base_dir / "deployment").exists():
        return base_dir
    return base_dir / REPO_DIRNAME


def path_exists(p: Path) -> bool:
    return p.exists()


def repo_has_entire_source(repo: Path) -> bool:
    """Heuristic: full repo should include backend + web directories."""
    return (repo / "backend").exists() and (repo / "web").exists()


def deployment_exists(repo: Path) -> bool:
    return (repo / "deployment").exists()


def compose_file_from_repo(repo: Path) -> Path:
    return repo / DEFAULT_COMPOSE_REL


def resolve_compose_file(repo: Path, compose_file: Optional[str]) -> Path:
    """
    Resolve compose file path.
    - If compose_file is absolute, return it.
    - If relative, assume it's inside repo/deployment/docker_compose.
    - If None, return default dev compose.
    """
    if compose_file:
        p = Path(compose_file).expanduser()
        if not p.is_absolute():
            return repo / "deployment" / "docker_compose" / p
        return p
    # default
    return repo / "deployment" / "docker_compose" / "docker-compose.dev.yml"


# ---------- Help ----------


def cmd_help() -> int:
    print(
        """
Onyx CLI - Available Commands

  onyx doctor
    Check environment requirements:
      - Docker & Docker Compose installed
      - Docker resources (>=4 CPUs, >=10 GiB RAM)
      - Warn if RAM < 16 GiB
    Prevents continuation if requirements are not met.

  onyx install [--dir PATH] [--stable | --beta] [--all]
    Install Onyx into ~/onyx-dot-app/ by default.
      --dir PATH   Set custom install location.
      --stable     Install latest stable release.
      --beta       Install latest beta release.
      --all        Clone full repo (not just deployment/).
    Default: sparse checkout of deployment/ on main.

  onyx up [--dir PATH] [--build-from-source] [-f COMPOSE_FILE] [-n PROJECT]
    Start Onyx stack via Docker Compose.
      --dir PATH          Base directory (default: ~/onyx-dot-app).
      --build-from-source Build images locally instead of pulling.
      -f COMPOSE_FILE     Use a specific docker-compose file.
      -n PROJECT          Docker project name (default: onyx-stack).
    Runs `onyx doctor` first and checks repo/deployment presence.

  onyx update [--dir PATH]
    Show current version and interactively switch to:
      - stable
      - beta
      - main

  onyx uninstall [--dir PATH] [-n PROJECT]
    Remove Onyx installation and associated Docker containers/volumes.
      --dir PATH   Base directory (default: ~/onyx-dot-app).
      -n PROJECT   Docker project name (default: onyx-stack).

  onyx dev [--dir PATH]
    Set up a development environment:
      - Creates ~/onyx-dot-app/.onyx-venv
      - Installs Python requirements
      - Sets up pre-commit in backend/
      - Runs npm install in web/
      - Requires Python 3.11+, Docker, and Docker Compose.

Tips:
  - 'onyx --help' also shows argparse help.
  - Most commands accept --dir PATH to control installation root.
    """.strip()
    )
    return 0


# ---------- Doctor ----------


def cmd_doctor() -> int:
    print_header("Onyx Doctor")
    ok = True

    # Check docker
    if not which("docker"):
        print(
            "✖ Docker not found in PATH. Please install Docker Desktop / Docker engine.",
            file=sys.stderr,
        )
        ok = False
    else:
        print("✔ Docker found")

    # Check docker compose
    dc_cmd = docker_compose_cmd()
    try:
        run(dc_cmd + ["version"])
        print("✔ Docker Compose found")
    except Exception:
        print(
            "✖ Docker Compose not found. Install Docker Compose (or update Docker Desktop).",
            file=sys.stderr,
        )
        ok = False

    # Resource checks
    cpus, mem_gb = docker_info()
    if cpus is None or mem_gb is None:
        print(
            "✖ Could not determine Docker CPU/RAM. Is Docker running?", file=sys.stderr
        )
        ok = False
    else:
        print(f"ℹ Docker resources: CPUs={cpus}, RAM={mem_gb:.2f} GiB")
        if cpus < MIN_CPUS:
            print(
                f"✖ CPU < {MIN_CPUS}. Please allocate at least {MIN_CPUS} CPUs to Docker.",
                file=sys.stderr,
            )
            ok = False
        if mem_gb < MIN_RAM_GB_HARD:
            print(
                f"✖ RAM < {MIN_RAM_GB_HARD} GiB. Please allocate at least {MIN_RAM_GB_HARD} GiB to Docker.",
                file=sys.stderr,
            )
            ok = False
        elif mem_gb < MIN_RAM_GB_WARN:
            print(
                f"⚠ Warning: RAM < {MIN_RAM_GB_WARN} GiB. Onyx may run, but performance could be limited."
            )

    return 0 if ok else 1


# ---------- Install ----------


def sparse_checkout_deployment(dst: Path, ref: str) -> None:
    """
    Clone only the 'deployment' folder (sparse checkout).
    If dst already exists, just fetch + checkout.
    """
    ensure_dir(dst.parent)

    if dst.exists() and (dst / ".git").exists():
        print(f"✔ Repo already exists at {dst}")
        # Only update and checkout ref
        run(["git", "fetch", "--all", "--tags"], cwd=dst)
        run(["git", "checkout", ref], cwd=dst)
        print(f"✔ Checked out {ref}")
        return

    # Fresh clone with sparse-checkout
    print(f"→ Cloning (sparse) into {dst} ...")
    run(
        [
            "git",
            "clone",
            "--no-checkout",
            "--filter=blob:none",
            "--depth=1",
            REPO_URL,
            str(dst),
        ]
    )

    print("→ Configuring sparse checkout (deployment/)")
    run(["git", "sparse-checkout", "init", "--cone"], cwd=dst)
    run(["git", "sparse-checkout", "set", "deployment"], cwd=dst)

    run(["git", "fetch", "--all", "--tags"], cwd=dst)
    run(["git", "checkout", ref], cwd=dst)
    print(f"✔ Checked out {ref}")


def clone_or_update_full_repo(dst: Path, ref: str) -> None:
    """
    Ensure we have a full (non-sparse) working tree at the requested ref.
    If a repo already exists and is sparse, convert it to full.
    Protects .env* files during the ref switch.
    """
    ensure_dir(dst.parent)

    if dst.exists() and is_git_repo(dst):
        print(f"→ Using existing repo at {dst}")
        # Convert sparse -> full if needed
        if is_sparse_checkout(dst):
            disable_sparse_checkout(dst)

        # Fetch what we need (depth=1 is fine; we don't need full history)
        run(["git", "fetch", "--all", "--tags", "--depth=1"], cwd=dst)
    elif dst.exists() and not is_git_repo(dst):
        raise RuntimeError(f"Target path exists but is not a git repo: {dst}")
    else:
        print(f"→ Cloning full repo into {dst}")
        run(["git", "clone", "--filter=blob:none", "--depth=1", REPO_URL, str(dst)])
        # Make sure we have tags for versioned refs
        run(["git", "fetch", "--tags", "--depth=1"], cwd=dst)

    # Protect .env* while switching refs
    env_backups: list[tuple[Path, Path]] = []
    for env in dst.rglob(".env*"):
        tmp = Path(tempfile.mkdtemp()) / env.name
        try:
            shutil.copy2(env, tmp)
            env_backups.append((env, tmp))
        except Exception:
            pass

    try:
        run(["git", "checkout", ref], cwd=dst)
        print(f"✔ Checked out {ref}")
        # After disabling sparse on a blobless clone, ensure blobs get materialized as needed
        run(["git", "checkout", "."], cwd=dst, check=False)
    finally:
        for original, backup in env_backups:
            if backup.exists():
                ensure_dir(original.parent)
                shutil.copy2(backup, original)


def cmd_install(base_dir: Path, stable: bool, beta: bool, install_all: bool) -> int:
    print_header("Onyx Install")
    if not has_git():
        print("✖ git is required to install Onyx.", file=sys.stderr)
        return 1

    ref = resolve_ref(stable, beta)
    repo = repo_path(base_dir)

    if install_all:
        clone_or_update_full_repo(repo, ref)
        print("✔ Full repository installed.")
    else:
        sparse_checkout_deployment(repo, ref)
        print("✔ Deployment-only checkout installed.")

    print(f"→ Location: {repo}")
    return 0


# ---------- Up ----------


def cmd_up(
    base_dir: Path,
    build_from_source: bool,
    compose_file: Optional[str],
    project_name: str,
) -> int:
    print_header("Onyx Up")

    # Doctor first
    if cmd_doctor() != 0:
        return 1

    repo = repo_path(base_dir)
    if build_from_source or compose_file:
        # Needs entire repo
        if not repo_has_entire_source(repo):
            print("✖ Full repo not found. Run: onyx install --all", file=sys.stderr)
            return 1
    else:
        # Default 'up' requires at least deployment/
        if not deployment_exists(repo):
            print("✖ deployment/ not found. Run: onyx install", file=sys.stderr)
            return 1

    dc_cmd = docker_compose_cmd()

    if compose_file:
        compose_path = resolve_compose_file(repo, compose_file)
        if not compose_path.exists():
            print(f"✖ Compose file not found: {compose_path}", file=sys.stderr)
            return 1
    else:
        compose_path = compose_file_from_repo(repo)
        if not compose_path.exists():
            print(f"✖ Default compose file not found: {compose_path}", file=sys.stderr)
            return 1

    # Build vs pull choice
    if build_from_source:
        args = dc_cmd + [
            "-f",
            str(compose_path),
            "-p",
            project_name,
            "up",
            "-d",
            "--build",
            "--force-recreate",
        ]
    else:
        args = dc_cmd + [
            "-f",
            str(compose_path),
            "-p",
            project_name,
            "up",
            "-d",
            "--pull",
            "always",
            "--force-recreate",
        ]

    print(f"→ Running: {' '.join(args)}")
    try:
        run(args, cwd=compose_path.parent, capture=False)
    except subprocess.CalledProcessError:
        return 1

    print("✔ Stack is starting.")
    return 0


# ---------- Down ----------


def cmd_down(
    base_dir: Path, compose_file: Optional[str], project_name: str, volumes: bool
) -> int:
    print_header("Onyx Down")

    repo = repo_path(base_dir)

    # Default compose path
    if compose_file:
        compose_path = resolve_compose_file(repo, compose_file)
    else:
        compose_path = compose_file_from_repo(repo)

    if not compose_path.exists():
        print(f"✖ Compose file not found: {compose_path}", file=sys.stderr)
        return 1

    dc_cmd = docker_compose_cmd()
    args = dc_cmd + ["-f", str(compose_path), "-p", project_name, "down"]

    if volumes:
        args.append("-v")

    print(f"→ Running: {' '.join(args)}")
    try:
        run(args, cwd=compose_path.parent, capture=False)
    except subprocess.CalledProcessError:
        return 1

    print("✔ Stack has been stopped.")
    return 0


# ---------- Update ----------


def current_ref(repo: Path) -> str:
    try:
        cp = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
        branch = (cp.stdout or "").strip()
        if branch != "HEAD":
            return branch
        cp2 = run(["git", "describe", "--tags", "--always"], cwd=repo)
        return (cp2.stdout or "").strip()
    except Exception:
        return "unknown"


def cmd_update(base_dir: Path) -> int:
    print_header("Onyx Update")
    repo = repo_path(base_dir)
    if not (repo.exists() and (repo / ".git").exists()):
        print("✖ Onyx repo not found. Run: onyx install", file=sys.stderr)
        return 1

    print(f"Current ref: {current_ref(repo)}")
    choice = None
    # Simple prompt without external deps
    print("Select channel: [s]table / [b]eta / [m]ain")
    while choice not in {"s", "b", "m"}:
        choice = input("Enter s/b/m: ").strip().lower()

    ref = {"s": resolve_ref(True, False), "b": resolve_ref(False, True), "m": "main"}[
        choice
    ]
    try:
        run(["git", "fetch", "--all", "--tags"], cwd=repo)
        run(["git", "checkout", ref], cwd=repo)
    except subprocess.CalledProcessError:
        return 1

    print(f"✔ Updated to {ref}")
    return 0


# ---------- Uninstall ----------


def cmd_uninstall(base_dir: Path, project_name: str) -> int:
    print_header("Onyx Uninstall")
    repo = repo_path(base_dir)
    dc_cmd = docker_compose_cmd()

    # Try to bring down with volumes if we have a compose file
    default_compose = compose_file_from_repo(repo)
    if default_compose.exists():
        try:
            print("→ Stopping containers and removing volumes ...")
            run(
                dc_cmd
                + [
                    "-f",
                    str(default_compose),
                    "-p",
                    project_name,
                    "down",
                    "-v",
                    "--remove-orphans",
                ],
                cwd=default_compose.parent,
                check=False,
            )
        except Exception:
            pass
    else:
        # Fallback: try by project only (works with v2 in some contexts)
        try:
            print("→ Stopping containers by project ...")
            run(
                dc_cmd + ["-p", project_name, "down", "-v", "--remove-orphans"],
                check=False,
            )
        except Exception:
            pass

    # Delete repo directory
    if repo.exists():
        print(f"→ Deleting {repo}")
        shutil.rmtree(repo, ignore_errors=True)

    print("✔ Uninstalled Onyx repo and attempted to remove containers/volumes.")
    print(
        "ℹ If any images remain, you can remove them via Docker Desktop or 'docker image rm <image>'."
    )
    return 0


# ---------- Dev ----------


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def python_in_venv(venv: Path) -> Path:
    return venv_bin(venv) / ("python.exe" if os.name == "nt" else "python")


def pip_in_venv(venv: Path) -> Path:
    return venv_bin(venv) / ("pip.exe" if os.name == "nt" else "pip")


def npm_cmd() -> str:
    return which("npm") or "npm"


def cmd_dev(base_dir: Path) -> int:
    print_header("Onyx Dev Setup")

    # Check basic tooling first
    errors = []
    if not which("docker"):
        errors.append("Docker is required.")
    if not docker_compose_cmd():
        errors.append("Docker Compose is required.")
    if not check_python_version(3, 11):
        errors.append("Python 3.11+ is required for development.")
    if errors:
        for e in errors:
            print(f"✖ {e}", file=sys.stderr)
        return 1

    repo = repo_path(base_dir)

    # If no repo (or only sparse deployment checkout), fetch/expand to FULL repo automatically
    try:
        needs_full = (not is_git_repo(repo)) or (not repo_has_entire_source(repo))
        if needs_full:
            if not has_git():
                print("✖ git is required to fetch the Onyx repository for development.", file=sys.stderr)
                return 1
            print("ℹ Full repository required for dev. Fetching/upgrading repository (main)...")
            # clone_or_update_full_repo should convert sparse → full if already present
            clone_or_update_full_repo(repo, "main")
    except Exception as e:
        print(f"✖ Failed to prepare full repository: {e}", file=sys.stderr)
        return 1

    # --- create venv and install dependencies ---
    venv_dir = base_dir / ".onyx-venv"
    if not venv_dir.exists():
        print(f"→ Creating virtual environment at {venv_dir}")
        run(["python3.11", "-m", "venv", str(venv_dir)])
    else:
        print(f"✔ Using existing venv at {venv_dir}")

    py = str(python_in_venv(venv_dir))
    pip = str(pip_in_venv(venv_dir))

    run([py, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    reqs = [
        "backend/requirements/default.txt",
        "backend/requirements/dev.txt",
        "backend/requirements/ee.txt",
        "backend/requirements/model_server.txt",
    ]
    for req in reqs:
        req_path = repo / req
        if req_path.exists():
            print(f"→ pip install -r {req}")
            run([pip, "install", "-r", str(req_path)], capture=False)
        else:
            print(f"⚠ Skipping missing file: {req}")

    print("→ Installing pre-commit")
    run([pip, "install", "pre-commit"], capture=False)
    backend_dir = repo / "backend"
    if backend_dir.exists():
        print("→ Running 'pre-commit install' in backend/")
        run([py, "-m", "pre-commit", "install"], cwd=backend_dir, capture=False)
    else:
        print("⚠ backend/ directory not found; skipping pre-commit install")

    web_dir = repo / "web"
    if web_dir.exists():
        print("→ Running 'npm i' in web/")
        run([npm_cmd(), "i"], cwd=web_dir, capture=False)
    else:
        print("⚠ web/ directory not found; skipping npm install")

    print("✔ Dev environment setup complete.")
    print(f"ℹ To activate the venv: source {venv_bin(venv_dir) / 'activate'}")
    return 0


# ---------- Main / Argument parsing ----------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="onyx", description="Onyx CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # help
    sub.add_parser("help", help="Show list of commands and their usage")

    # doctor
    p_doctor = sub.add_parser(  # noqa: F841
        "doctor", help="Check environment requirements"
    )

    # install
    p_install = sub.add_parser("install", help="Install Onyx")
    p_install.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_HOME,
        help="Base directory (default: ~/.onyx)",
    )
    chan = p_install.add_mutually_exclusive_group()
    chan.add_argument(
        "--stable", action="store_true", help="Install latest stable release"
    )
    chan.add_argument(
        "--beta", action="store_true", help="Install latest beta (dev) release"
    )
    p_install.add_argument(
        "--all",
        action="store_true",
        help="Get full repository instead of deployment-only",
    )

    # up
    p_up = sub.add_parser("up", help="Start Onyx stack with Docker Compose")
    p_up.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_HOME,
        help="Base directory (default: ~/.onyx)",
    )
    p_up.add_argument(
        "--build-from-source",
        action="store_true",
        help="Build images from local source",
    )
    p_up.add_argument(
        "-f",
        "--file",
        dest="compose_file",
        type=str,
        help="Path to a specific docker compose file",
    )
    p_up.add_argument(
        "-n",
        "--name",
        dest="project_name",
        type=str,
        default=DEFAULT_PROJECT,
        help=f"Docker project name (default: {DEFAULT_PROJECT})",
    )

    # down
    p_down = sub.add_parser("down", help="Stop Onyx stack with Docker Compose")
    p_down.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_HOME,
        help="Base directory (default: ~/onyx-dot-app)",
    )
    p_down.add_argument(
        "-f",
        "--file",
        dest="compose_file",
        type=str,
        help="Path to a specific docker compose file",
    )
    p_down.add_argument(
        "-n",
        "--name",
        dest="project_name",
        type=str,
        default=DEFAULT_PROJECT,
        help=f"Docker project name (default: {DEFAULT_PROJECT})",
    )
    p_down.add_argument(
        "-v", "--volumes", action="store_true", help="Remove named volumes as well"
    )

    # update
    p_update = sub.add_parser("update", help="Switch to stable/beta/main")
    p_update.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_HOME,
        help="Base directory (default: ~/.onyx)",
    )

    # uninstall
    p_uninstall = sub.add_parser(
        "uninstall", help="Remove Onyx and its Docker resources"
    )
    p_uninstall.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_HOME,
        help="Base directory (default: ~/onyx-dot-app)",
    )
    p_uninstall.add_argument(
        "-n",
        "--name",
        dest="project_name",
        type=str,
        default=DEFAULT_PROJECT,
        help=f"Docker project name (default: {DEFAULT_PROJECT})",
    )

    # dev
    p_dev = sub.add_parser("dev", help="Set up local development environment")
    p_dev.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_HOME,
        help="Base directory (default: ~/onyx-dot-app)",
    )

    args = parser.parse_args(argv)

    if args.command == "help":
        return cmd_help()
    elif args.command == "doctor":
        return cmd_doctor()
    elif args.command == "install":
        return cmd_install(args.dir.expanduser(), args.stable, args.beta, args.all)
    elif args.command == "up":
        return cmd_up(
            args.dir.expanduser(),
            args.build_from_source,
            args.compose_file,
            args.project_name,
        )
    elif args.command == "down":
        return cmd_down(
            args.dir.expanduser(), args.compose_file, args.project_name, args.volumes
        )
    elif args.command == "update":
        return cmd_update(args.dir.expanduser())
    elif args.command == "uninstall":
        return cmd_uninstall(args.dir.expanduser(), args.project_name)
    elif args.command == "dev":
        return cmd_dev(args.dir.expanduser())
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
