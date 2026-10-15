"""Literal credential isolation after normal provisioning, without outbound calls.

Coverage excludes unreadable memory, upstream reflection, and active app requests.
The CUSTOM app has no rendered skill. Gateway and OpenCode auth remain allowed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import ExitStack
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.external_app import ExternalAppManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    SandboxHandle,
    kubernetes_runtime,
)


class _Match(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    kind: str
    location: str


class _ScanReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    uid: int
    gid: int
    complete: bool
    gateway_placeholder: bool
    provider_catalog_entry: bool
    roots: list[str]
    absent_roots: list[str]
    file_count: int
    byte_count: int
    process_field_count: int
    opencode_pids: list[int]
    control_pid: int
    matches: list[_Match]
    unreadable: list[str]
    exited_processes: int
    errors: list[str]
    limits: dict[str, int]


_SCAN_SCRIPT = rb"""
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

session_id, model_id, control_path, encoded_hashes = sys.argv[1:]
hashes = json.loads(encoded_hashes)
pattern = re.compile(rb"NONSECRET_CRAFT_(?:PROVIDER|APPORG|APPUSER|CONTROL)_[0-9a-f]{32}")
limits = {"file_bytes": 512 * 1024**2, "total_bytes": 8 * 1024**3,
          "files": 250000, "entries": 300000, "seconds": 180, "locations": 256}
deadline = time.monotonic() + limits["seconds"]
report = {"uid": os.getuid(), "gid": os.getgid(), "complete": False,
          "gateway_placeholder": False, "provider_catalog_entry": False,
          "roots": [], "absent_roots": [], "file_count": 0, "byte_count": 0,
          "process_field_count": 0, "opencode_pids": [], "control_pid": 0,
          "matches": [], "unreadable": [], "exited_processes": 0,
          "errors": [], "limits": limits}
seen_files, seen_dirs, seen_matches = set(), set(), set()
entry_count = 0

def check_time():
    if time.monotonic() >= deadline:
        raise RuntimeError("time bound reached")

def unreadable(path):
    if len(report["unreadable"]) >= limits["locations"]:
        raise RuntimeError("unreadable location bound reached")
    report["unreadable"].append(str(path))

def inspect(source, location):
    size, overlap = 0, b""
    while True:
        check_time()
        chunk = source.read(1024 * 1024)
        if not chunk:
            return
        size += len(chunk)
        report["byte_count"] += len(chunk)
        if size > limits["file_bytes"] or report["byte_count"] > limits["total_bytes"]:
            raise RuntimeError("byte bound reached at " + location)
        data = overlap + chunk
        for candidate in pattern.findall(data):
            kind = hashes.get(hashlib.sha256(candidate).hexdigest())
            if kind is not None and (kind, location) not in seen_matches:
                if len(seen_matches) >= limits["locations"]:
                    raise RuntimeError("match location bound reached")
                seen_matches.add((kind, location))
                report["matches"].append({"kind": kind, "location": location})
        overlap = data[-128:]

def scan_file(path):
    check_time()
    try:
        info = path.stat()
        identity = (info.st_dev, info.st_ino)
        if not stat.S_ISREG(info.st_mode) or identity in seen_files:
            return
        if report["file_count"] >= limits["files"]:
            raise RuntimeError("file count bound reached")
        if info.st_size > limits["file_bytes"]:
            raise RuntimeError("file byte bound reached at " + str(path))
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise RuntimeError("file changed type at " + str(path))
            if (opened.st_dev, opened.st_ino) != identity:
                raise RuntimeError("file changed identity at " + str(path))
            seen_files.add(identity)
            report["file_count"] += 1
            inspect(source, str(path))
    except PermissionError:
        unreadable(path)

def scan_root(root, required):
    global entry_count
    path = Path(root)
    if not path.exists():
        if required:
            raise RuntimeError("required root absent at " + root)
        report["absent_roots"].append(root)
        return
    resolved = path.resolve(strict=True)
    report["roots"].append(root)
    pending = [resolved]
    while pending:
        check_time()
        current = pending.pop()
        if not current.is_dir():
            scan_file(current)
            continue
        info = current.stat()
        identity = (info.st_dev, info.st_ino)
        if identity in seen_dirs:
            continue
        seen_dirs.add(identity)
        with os.scandir(current) as entries:
            for entry in entries:
                check_time()
                entry_count += 1
                if entry_count > limits["entries"]:
                    raise RuntimeError("directory entry bound reached")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif not entry.is_symlink() or not entry.is_dir():
                    scan_file(Path(entry.path))

child = None
try:
    config_path = Path("/workspace/sessions") / session_id / "opencode.json"
    with config_path.open("rb") as source:
        config_bytes = source.read(1024 * 1024 + 1)
    if len(config_bytes) > 1024 * 1024:
        raise RuntimeError("session config byte bound reached")
    config = json.loads(config_bytes)
    provider = config["provider"]["onyx"]
    report["gateway_placeholder"] = provider["options"]["apiKey"] == "replaced_by_egress_proxy"
    report["provider_catalog_entry"] = model_id in provider["models"]
    control = Path(control_path).read_text()
    if hashes.get(hashlib.sha256(control.encode()).hexdigest()) != "CONTROL":
        raise RuntimeError("control attachment hash mismatch")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(210)"],
        env={**os.environ, "CRAFT_SCAN_CONTROL": control},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    report["control_pid"] = child.pid
    for root in ("/workspace", "/home/sandbox", "/tmp"):
        scan_root(root, True)
    for root in ("/etc/environment", "/etc/profile.d", "/run/secrets", "/var/run/secrets"):
        scan_root(root, False)
    for directory in sorted(Path("/proc").iterdir()):
        if not directory.name.isdigit():
            continue
        check_time()
        opencode = False
        for field in ("cmdline", "environ"):
            path = directory / field
            try:
                with path.open("rb") as source:
                    if field == "cmdline":
                        command = source.read(1024 * 1024)
                        if source.read(1):
                            raise RuntimeError("process argument byte bound reached")
                        arguments = command.split(b"\0")
                        opencode = b"serve" in arguments and any(
                            os.path.basename(arg) == b"opencode" for arg in arguments
                        )
                        source.seek(0)
                    inspect(source, str(path))
                    report["process_field_count"] += 1
            except PermissionError:
                unreadable(path)
                if opencode:
                    raise RuntimeError("OpenCode process field unreadable at " + str(path))
            except (FileNotFoundError, ProcessLookupError):
                report["exited_processes"] += 1
                if opencode:
                    raise RuntimeError("OpenCode exited during process scan")
                break
        else:
            if opencode:
                os.kill(int(directory.name), 0)
                report["opencode_pids"].append(int(directory.name))
    if child.poll() is not None:
        raise RuntimeError("control process exited during scan")
    report["complete"] = True
except Exception as error:
    report["errors"].append(type(error).__name__ + ": " + str(error)
                            if isinstance(error, RuntimeError) else type(error).__name__)
finally:
    if child is not None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    print(json.dumps(report, separators=(",", ":")))
"""


def test_model_and_external_app_credentials_absent_from_guest_files_and_processes(
    k8s_admin_user: DATestUser,
    running_sandbox: Callable[..., SandboxHandle],
) -> None:
    subjects = {
        kind: f"NONSECRET_CRAFT_{kind}_{uuid4().hex}"
        for kind in ("PROVIDER", "APPORG", "APPUSER", "CONTROL")
    }
    hashes = {
        hashlib.sha256(value.encode()).hexdigest(): kind
        for kind, value in subjects.items()
    }
    with ExitStack() as cleanup:
        provider = LLMProviderManager.create(
            user_performing_action=k8s_admin_user,
            name=f"craft-credential-isolation-{uuid4().hex}",
            api_key=subjects["PROVIDER"],
            default_model_name="gpt-5-mini",
            set_as_default=False,
        )
        cleanup.callback(LLMProviderManager.delete, provider, k8s_admin_user)
        app = ExternalAppManager.create(
            user_performing_action=k8s_admin_user,
            name=f"craft-credential-isolation-{uuid4().hex}",
            upstream_url_patterns=[f"https://craft-sentinel-{uuid4().hex}.invalid/*"],
            auth_template={
                "X-Craft-Org": "{org_key}",
                "Authorization": "Bearer {user_key}",
            },
            organization_credentials={"org_key": subjects["APPORG"]},
        )
        cleanup.callback(ExternalAppManager.delete, k8s_admin_user, app.id)
        owner = running_sandbox().api_user
        ExternalAppManager.upsert_user_credentials(
            owner, app.id, {"user_key": subjects["APPUSER"]}
        )
        assert ExternalAppManager.get_for_user(owner, app.id).authenticated is True
        metadata = next(
            item
            for item in LLMProviderManager.get_all(k8s_admin_user)
            if item.id == provider.id
        )
        assert metadata.name == provider.name
        assert any(
            model.name == "gpt-5-mini" and model.is_visible
            for model in metadata.model_configurations
        )
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        assert handle.api_user.id == owner.id
        attachment = BuildSessionManager.upload_file(
            owner,
            handle.session_id,
            "credential-scan-control.txt",
            subjects["CONTROL"].encode(),
        )
        control_path = f"/workspace/sessions/{handle.session_id}/{attachment.path}"
        result = kubernetes_runtime(handle.manager).helper(
            handle.sandbox_id,
            "run",
            {
                "argv": [
                    "python3",
                    "-",
                    str(handle.session_id),
                    f"{provider.id}/gpt-5-mini",
                    control_path,
                    json.dumps(hashes),
                ],
                "has_stdin": True,
                "timeout_seconds": 205,
            },
            stdin=_SCAN_SCRIPT,
            timeout=220,
        )
        assert result.returncode == 0, f"credential scan exited {result.returncode}"
        try:
            report = _ScanReport.model_validate_json(result.stdout)
        except ValidationError:
            raise AssertionError(
                "credential scanner did not return its typed report"
            ) from None
        summary = report.model_dump_json()
        assert report.uid == report.gid == 1000, summary
        assert report.complete and not report.errors, summary
        assert report.gateway_placeholder and report.provider_catalog_entry, summary
        assert {"/workspace", "/home/sandbox", "/tmp"} <= set(report.roots), summary
        assert report.opencode_pids and report.process_field_count > 0, summary
        assert report.file_count > 0 and report.byte_count > 0, summary
        assert not [match for match in report.matches if match.kind != "CONTROL"], (
            summary
        )
        controls = {
            match.location for match in report.matches if match.kind == "CONTROL"
        }
        assert control_path in controls, summary
        assert f"/proc/{report.control_pid}/environ" in controls, summary
        print(f"credential isolation scan {summary}")
