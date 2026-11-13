#!/usr/bin/env python3
"""Developer commands for your own Firecracker VM on a shared dev cluster.

    craft_fc_vm.py skills push <dir> [--mount skills] [--wake]
    craft_fc_vm.py vms
    craft_fc_vm.py exec [--wake] [--cwd DIR] -- <command>
    craft_fc_vm.py logs [--guest | --agent] [--since 1h] [--tail N] [-f]
    craft_fc_vm.py reset [--force]

The commands run `craft_fc_pod_helper.py` in an api-server pod with
`kubectl exec`, so they need no Telepresence: the pod has the agent mTLS
files, Postgres, Redis and the network path. The cluster comes from the
profile file (`--profile`, else `CRAFT_DEV_PROFILE`, else the onyx-internal
checkout next to this repo); kubectl always gets its context explicitly.
The commands act only on the sandbox of your user
(`--user`, else `CRAFT_DEV_USER`, else the profile's `user.email`).
"""

import argparse
import collections
import hashlib
import io
import json
import os
import shlex
import stat
import subprocess
import sys
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import remote
from remote import RemoteProfile

ROOT = Path(__file__).resolve().parents[3]
HELPER = Path(__file__).with_name("craft_fc_pod_helper.py")
USER_ENV = "CRAFT_DEV_USER"
RESULT_PREFIX = "@@craft-fc "
# Reads the helper source, then runs it on the rest of stdin.
BOOT = (
    "import sys;b=sys.stdin.buffer;n=int(b.readline());"
    "exec(compile(b.read(n),'craft_fc_pod_helper.py','exec'))"
)
MOUNTS = ("skills", "user-uploads", "spaces")
# The agent's defaults: --managed-max-zip-mib, --managed-max-mib, --managed-max-files.
MAX_ZIP_BYTES = 256 << 20
MAX_CONTENT_BYTES = 512 << 20
MAX_ENTRIES = 50_000
SKIP_NAMES = frozenset({".DS_Store", ".git", "__pycache__"})
# 1980-01-01, the earliest zip time: the same tree gives the same bytes.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class CommandError(Exception):
    """A failure with a message for the developer; exits nonzero."""


@dataclass(frozen=True)
class Target:
    context: str
    user: str
    kubeconfig: str | None = None
    namespace: str = "onyx"
    agent_namespace: str = "onyx-sandbox-runtime"
    agent_selector: str = "app.kubernetes.io/component=craft-fc-host-agent"
    agent_container: str = "host-agent"
    api_deployment: str = "onyx-api-server"
    api_container: str = "api-server"
    tenant_id: str | None = None

    def kubectl(self, namespace: str | None = None) -> list[str]:
        base = ["kubectl"]
        if self.kubeconfig:
            base += ["--kubeconfig", self.kubeconfig]
        return base + ["--context", self.context, "-n", namespace or self.namespace]


# Profile


def target_from(
    profile: RemoteProfile,
    *,
    context: str | None,
    user: str | None,
    tenant_id: str | None,
    env: dict[str, str],
) -> Target:
    """Flags win over the environment, the environment over the profile.
    A context outside the profile's allowed list is refused."""
    try:
        chosen = remote.select_context(profile, context or env.get(remote.CONTEXT_ENV))
    except ValueError as e:
        raise CommandError(str(e)) from e
    email = user or env.get(USER_ENV) or profile.user_email
    if not email or "@" not in email:
        raise CommandError(
            f"no user: pass --user, set {USER_ENV}, or set user.email in the profile"
        )
    return Target(
        context=chosen,
        user=email.strip().lower(),
        kubeconfig=str(profile.kubeconfig) if profile.kubeconfig else None,
        namespace=profile.namespace,
        agent_namespace=profile.agent_namespace,
        agent_selector=profile.agent_selector,
        agent_container=profile.agent_container,
        tenant_id=tenant_id,
    )


def load_profile(path: str | None) -> RemoteProfile:
    """The profile from --profile, else $CRAFT_DEV_PROFILE, else onyx-internal."""
    try:
        return remote.load_profile(ROOT, Path(path) if path else None)
    except (ValueError, OSError) as e:
        raise CommandError(str(e)) from e


# Bundles


@dataclass
class Bundle:
    data: bytes
    files: int
    content_bytes: int
    warnings: list[str] = field(default_factory=list)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _walk(src: Path) -> Iterator[tuple[str, Path]]:
    """Every entry under src in sorted order, as (posix path, path)."""
    for path in sorted(src.rglob("*"), key=lambda p: p.relative_to(src).as_posix()):
        rel = path.relative_to(src)
        if any(part in SKIP_NAMES for part in rel.parts):
            continue
        yield rel.as_posix(), path


def run_hint(name: str, data: bytes, mount_path: str) -> str:
    """How to run a script from the noexec mount: through its interpreter."""
    shebang = data.split(b"\n", 1)[0]
    interpreter = (
        "python3" if b"python" in shebang else "bash" if b"bash" in shebang else "sh"
    )
    return f"{interpreter} {mount_path}/{name}"


def build_bundle(src: Path, mount_path: str = "/mnt/skills") -> Bundle:
    """A zip of src that the agent accepts as a managed bundle. Same tree,
    same bytes: sorted names, fixed times and modes. The agent rejects
    symlinks and special files, so this refuses them first."""
    if not src.is_dir():
        raise CommandError(f"{src} is not a directory")
    buffer = io.BytesIO()
    files = 0
    content = 0
    entries = 0
    warnings: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, path in _walk(src):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise CommandError(f"{name}: symlinks are not allowed in a bundle")
            entries += 1
            if entries > MAX_ENTRIES:
                raise CommandError(f"more than {MAX_ENTRIES} entries")
            if stat.S_ISDIR(mode):
                info = zipfile.ZipInfo(name + "/", ZIP_EPOCH)
                info.external_attr = (stat.S_IFDIR | 0o755) << 16
                zf.writestr(info, b"")
                continue
            if not stat.S_ISREG(mode):
                raise CommandError(f"{name}: only files and directories are allowed")
            data = path.read_bytes()
            content += len(data)
            if content > MAX_CONTENT_BYTES:
                raise CommandError(f"content is over {MAX_CONTENT_BYTES >> 20} MiB")
            executable = bool(mode & 0o111)
            if data.startswith(b"#!"):
                warnings.append(
                    f"{name}: the mount is noexec; run it as "
                    f"`{run_hint(name, data, mount_path)}`"
                )
            info = zipfile.ZipInfo(name, ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
            zf.writestr(info, data)
            files += 1
    data = buffer.getvalue()
    if len(data) > MAX_ZIP_BYTES:
        raise CommandError(f"the zip is over {MAX_ZIP_BYTES >> 20} MiB")
    if files == 0:
        raise CommandError(f"{src} has no files")
    return Bundle(data=data, files=files, content_bytes=content, warnings=warnings)


# Pod helper


def helper_input(request: dict[str, Any], payload: bytes, script: bytes) -> bytes:
    """Stdin for `python -c BOOT`: script length, script, request line, payload."""
    body = dict(request, payload_bytes=len(payload))
    return (
        str(len(script)).encode()
        + b"\n"
        + script
        + json.dumps(body).encode()
        + b"\n"
        + payload
    )


def parse_result(line: str) -> dict[str, Any] | None:
    if not line.startswith(RESULT_PREFIX):
        return None
    value = json.loads(line[len(RESULT_PREFIX) :])
    return value if isinstance(value, dict) else None


def helper_request(target: Target, command_name: str, **fields: Any) -> dict[str, Any]:
    return {
        "command_name": command_name,
        "user": target.user,
        "tenant_id": target.tenant_id,
        **fields,
    }


def helper_argv(target: Target) -> list[str]:
    return target.kubectl() + [
        "exec",
        "-i",
        f"deploy/{target.api_deployment}",
        "-c",
        target.api_container,
        "--",
        "python",
        "-c",
        BOOT,
    ]


def run_helper(
    target: Target, request: dict[str, Any], payload: bytes = b"", verbose: bool = False
) -> Iterator[dict[str, Any]]:
    """Run the pod helper and yield its result lines as they arrive."""
    proc = subprocess.Popen(
        helper_argv(target),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None if verbose else subprocess.DEVNULL,
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(helper_input(request, payload, HELPER.read_bytes()))
    proc.stdin.close()
    seen = False
    for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip("\n")
        result = parse_result(line)
        if result is None:
            if verbose:
                print(line, file=sys.stderr)
            continue
        seen = True
        yield result
    proc.wait()
    if not seen:
        raise CommandError(
            f"the pod helper gave no result (kubectl exit {proc.returncode}); "
            "run again with --verbose"
        )


def single(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The one final result of a command; an error result raises."""
    last: dict[str, Any] = {}
    for result in results:
        last = result
    if last.get("t") == "error":
        raise CommandError(f"{last.get('code')}: {last.get('message')}")
    return last


# Commands


def _age(seconds: object) -> str:
    if not isinstance(seconds, int):
        return "-"
    if seconds < 120:
        return f"{seconds}s"
    if seconds < 7200:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def format_vms(vms: list[dict[str, Any]]) -> str:
    header = ("USER", "SANDBOX", "NODE", "ATTEMPT", "GEN", "STATE", "AGE", "IDLE")
    rows = [header]
    for vm in vms:
        if not vm.get("placed"):
            rows.append(
                (vm["user"], vm["sandbox_id"], "-", "-", "-", "stopped", "-", "-")
            )
            continue
        rows.append(
            (
                vm["user"],
                vm["sandbox_id"],
                str(vm.get("node", "-")),
                str(vm.get("attempt", "-")),
                str(vm.get("generation", "-")),
                str(vm.get("state", "-")) + (" busy" if vm.get("busy_marks") else ""),
                _age(vm.get("age_s")),
                _age(vm.get("idle_s")),
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        for row in rows
    )


def cmd_vms(target: Target, args: argparse.Namespace) -> int:
    result = single(
        run_helper(target, helper_request(target, "vms"), verbose=args.verbose)
    )
    print(format_vms(result.get("vms", [])))
    return 0


def cmd_exec(target: Target, args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise CommandError("give a command after --")
    shell = shlex.join(command) if len(command) > 1 else command[0]
    request = helper_request(
        target, "exec", command=shell, cwd=args.cwd, wake=args.wake
    )
    code = 1
    for result in run_helper(target, request, verbose=args.verbose):
        kind = result.get("t")
        if kind == "out":
            out = sys.stderr if result.get("s") == "stderr" else sys.stdout
            out.write(str(result.get("d", "")))
            out.flush()
        elif kind == "result":
            exit_code = result.get("exit_code")
            code = exit_code if isinstance(exit_code, int) and exit_code >= 0 else 128
            if result.get("completion") != "EXITED":
                print(f"[{result.get('completion')}]", file=sys.stderr)
        elif kind == "error":
            raise CommandError(f"{result.get('code')}: {result.get('message')}")
    return code


def cmd_skills_push(target: Target, args: argparse.Namespace) -> int:
    bundle = build_bundle(Path(args.dir), f"/mnt/{args.mount}")
    for warning in bundle.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(
        f"bundle {bundle.sha256[:12]}: {bundle.files} files, "
        f"{bundle.content_bytes} bytes, zip {len(bundle.data)} bytes",
        file=sys.stderr,
    )
    request = helper_request(target, "skills-push", mount=args.mount, wake=args.wake)
    result = single(run_helper(target, request, bundle.data, verbose=args.verbose))
    print(
        f"image {result['image_id'][:12]} ({'built' if result['built'] else 'cached'}"
        f" {result['build_ms']} ms) -> {result['path']} on {result['sandbox_id']} "
        f"(slot {result['active']}, {'changed' if result['changed'] else 'unchanged'},"
        f" {result['swap_ms']} ms)"
    )
    if result.get("previous_in_use"):
        print(
            "note: a process still has files open on the old image; the next push "
            "waits until they close",
            file=sys.stderr,
        )
    print(f"$ ls -la {result['path']}")
    print(result.get("listing", "").rstrip())
    return 0


def cmd_reset(target: Target, args: argparse.Namespace) -> int:
    request = helper_request(target, "reset", force=args.force)
    result = single(run_helper(target, request, verbose=args.verbose))
    outcome = result.get("outcome")
    print(f"{result.get('sandbox_id')}: {outcome}")
    if outcome in ("stopped", "already_gone", "not_placed"):
        return 0
    if outcome in ("kept_no_checkpoint", "kept_busy"):
        print(
            "the VM is busy or a session save failed; it still runs. "
            "Use --force to stop it without a save.",
            file=sys.stderr,
        )
    return 1


def log_line(raw: str, sandbox_id: str, *, guest: bool, agent: bool) -> str | None:
    """The display form of one agent pod log line for this sandbox, else None."""
    if sandbox_id not in raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw if agent else None
    if not isinstance(data, dict):
        return raw if agent else None
    if data.get("kind") == "guest_log":
        if not guest or data.get("sandbox_id") != sandbox_id:
            return None
        return f"[{data.get('stream', 'guest')}] {data.get('line', '')}"
    if not agent:
        return None
    rest = {k: v for k, v in data.items() if k not in ("time", "level", "msg")}
    extra = " ".join(f"{k}={v}" for k, v in rest.items())
    return f"{data.get('time', '')} {data.get('level', '')} {data.get('msg', '')} {extra}".strip()


def matching_lines(
    lines: Iterable[str],
    sandbox_id: str,
    *,
    guest: bool,
    agent: bool,
    tail: int | None,
) -> Iterator[str]:
    """The display lines of this sandbox; with tail, only the last `tail`."""
    shown = (
        s
        for raw in lines
        if (s := log_line(raw.rstrip("\n"), sandbox_id, guest=guest, agent=agent))
        is not None
    )
    if tail is None:
        yield from shown
    else:
        yield from collections.deque(shown, maxlen=tail)


def agent_pods(target: Target, node: str | None) -> list[str]:
    argv = target.kubectl(target.agent_namespace) + [
        "get",
        "pods",
        "-l",
        target.agent_selector,
        "-o",
        "name",
    ]
    if node:
        argv += ["--field-selector", f"spec.nodeName={node}"]
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=True)
    return [line for line in out.stdout.split() if line]


def cmd_logs(target: Target, args: argparse.Namespace) -> int:
    where = single(
        run_helper(target, helper_request(target, "where"), verbose=args.verbose)
    )
    sandbox_id = str(where["sandbox_id"])
    node = where.get("node") if where.get("placed") else None
    pods = agent_pods(target, node) or (
        [] if node is None else agent_pods(target, None)
    )
    if not pods:
        raise CommandError(f"no host agent pods in {target.agent_namespace}")
    if args.follow and args.tail is not None:
        raise CommandError("-f streams from --since; --tail works only without -f")
    if args.follow and len(pods) > 1:
        raise CommandError(
            "-f needs one agent pod; wake the VM first so its node is known"
        )
    guest = not args.agent
    agent = not args.guest
    for pod in pods:
        # --tail counts this VM's lines, so the filter applies it, not kubectl.
        argv = target.kubectl(target.agent_namespace) + [
            "logs",
            pod,
            "-c",
            target.agent_container,
            f"--since={args.since}",
        ]
        if args.follow:
            argv.append("-f")
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        try:
            for shown in matching_lines(
                proc.stdout, sandbox_id, guest=guest, agent=agent, tail=args.tail
            ):
                print(shown, flush=True)
        except KeyboardInterrupt:
            proc.terminate()
        proc.wait()
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--profile", help=f"profile file (default: ${remote.PROFILE_ENV})")
    p.add_argument(
        "--context",
        help=f"kube context; must be in the profile (default: ${remote.CONTEXT_ENV})",
    )
    p.add_argument("--user", help=f"your Onyx login email (default: ${USER_ENV})")
    p.add_argument("--tenant", help="tenant ID (default: looked up from the email)")
    p.add_argument("--verbose", action="store_true", help="show pod helper output")
    sub = p.add_subparsers(dest="command_name", required=True)

    skills = sub.add_parser("skills", help="managed drive commands")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    push = skills_sub.add_parser(
        "push", help="put a local dir on a managed mount of your VM"
    )
    push.add_argument("dir")
    push.add_argument("--mount", choices=MOUNTS, default="skills")
    push.add_argument(
        "--wake", action="store_true", help="start the VM if it is stopped"
    )
    push.set_defaults(handler=cmd_skills_push)

    sub.add_parser("vms", help="show your VM").set_defaults(handler=cmd_vms)

    run = sub.add_parser("exec", help="run a command in your VM as the sandbox user")
    run.add_argument(
        "--wake", action="store_true", help="start the VM if it is stopped"
    )
    run.add_argument(
        "--cwd", default="", help="working directory in the VM (default /)"
    )
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(handler=cmd_exec)

    logs = sub.add_parser("logs", help="guest and agent log lines of your VM")
    which = logs.add_mutually_exclusive_group()
    which.add_argument("--guest", action="store_true", help="only guest console lines")
    which.add_argument("--agent", action="store_true", help="only agent lines")
    logs.add_argument("--since", default="1h")
    logs.add_argument(
        "--tail", type=int, help="only the last N lines of your VM (not with -f)"
    )
    logs.add_argument("-f", "--follow", action="store_true")
    logs.set_defaults(handler=cmd_logs)

    reset = sub.add_parser("reset", help="save your sessions, then stop your VM")
    reset.add_argument("--force", action="store_true", help="stop without a save")
    reset.set_defaults(handler=cmd_reset)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        target = target_from(
            load_profile(args.profile),
            context=args.context,
            user=args.user,
            tenant_id=args.tenant,
            env=dict(os.environ),
        )
        return int(args.handler(target, args))
    except CommandError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(
            f"error: {' '.join(e.cmd[:6])} ... failed: {e.stderr or e}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
