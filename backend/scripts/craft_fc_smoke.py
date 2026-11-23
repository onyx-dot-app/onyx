"""End-to-end smoke test for Craft on Firecracker.

Runs in an api-server pod, through the same harness calls that Craft
sessions use. It makes a test user that cannot log in and takes no license
seat, with its own sandbox, then checks:

    create        a microVM starts and gets a placement
    exec-uid      a command runs as uid 1000
    file          a written file reads back with the same SHA-256, in and out of the VM
    egress        an HTTPS request from the VM goes out through the sandbox proxy
    save-stop     the session is saved to the file store and the VM stops
    resume        a new VM restores the session with its files intact
    purge         a session purge deletes the save record and the archive object

A cleanup step always runs: it purges the sandbox and deletes the test user.
Exit code 0 when every step passes, 1 when a step fails.

Usage (kubernetes):
    kubectl -n onyx exec deploy/onyx-api-server -c api-server -- \
        python -m scripts.craft_fc_smoke

`ods craft-fc smoke` sends this file from a checkout to the pod and runs it.
"""

import argparse
import hashlib
import logging
import os
import shlex
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from uuid import UUID, uuid4

import requests

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.db.enums import AccountType
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.sandbox import (
    create_sandbox__no_commit,
    get_sandbox_by_user_id,
)
from onyx.db.users import (
    batch_add_ext_perm_user_if_not_exists,
    delete_user_from_db__no_commit,
    fetch_user_by_id,
    get_all_users,
)
from onyx.file_store.file_store import PresignableFileStore, get_default_file_store
from onyx.file_store.models import PresignedRequest
from onyx.microvm.agent_client import MtlsHostAgentClientFactory
from onyx.microvm.configs import FIRECRACKER_ENABLED, SANDBOX_FC_TEMPLATE
from onyx.microvm.lifecycle import VmStopOutcome, stop_sandbox_vm
from onyx.microvm.placement import PLACEMENT_LOCK_WAIT_SECONDS
from onyx.microvm.registry import get_sandbox_placement
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    get_session_save,
)
from onyx.server.features.build.sandbox.harness_base import collect_exec_result
from onyx.server.features.build.sandbox.harness_factory import (
    get_firecracker_sandbox,
)
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    HarnessSandboxRef,
)
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

SMOKE_EMAIL_PREFIX = "craft-fc-smoke-"
SMOKE_EMAIL_DOMAIN = "example.com"
DEFAULT_EGRESS_URL = "https://pypi.org/simple/"
SANDBOX_UID = 1000
PAYLOAD_BYTES = 256 * 1024
DATA_PATH = "smoke/data.bin"
NOTE_PATH = "smoke/note.txt"
NOTE_TEXT = "hello-from-the-vm"
HTTP_TIMEOUT_SECONDS = 30


class StepStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class StepResult:
    name: str
    status: StepStatus
    detail: str
    seconds: float


class StepFailedError(Exception):
    """A check failed; the message is the report detail."""


def require(ok: bool, detail: str) -> None:
    if not ok:
        raise StepFailedError(detail)


Step = tuple[str, Callable[[], str]]


def run_steps(
    steps: list[Step],
    cleanup: Step,
    on_result: Callable[[StepResult], None] = lambda _: None,
) -> list[StepResult]:
    """Run the steps in order. After a failure the remaining steps are
    skipped; the cleanup step always runs."""
    results: list[StepResult] = []
    failed = False
    for name, fn in [*steps, cleanup]:
        if failed and name != cleanup[0]:
            result = StepResult(name, StepStatus.SKIP, "an earlier step failed", 0.0)
        else:
            result = _run_step(name, fn)
            failed = failed or result.status is StepStatus.FAIL
        results.append(result)
        on_result(result)
    return results


def _run_step(name: str, fn: Callable[[], str]) -> StepResult:
    start = time.monotonic()
    try:
        detail = fn()
        status = StepStatus.PASS
    except StepFailedError as e:
        detail, status = str(e), StepStatus.FAIL
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        detail, status = f"{type(e).__name__}: {e}", StepStatus.FAIL
    return StepResult(name, status, detail, round(time.monotonic() - start, 2))


def format_result(result: StepResult) -> str:
    detail = " ".join(result.detail.split())
    return (
        f"{result.status.value:<4} {result.name:<10} {result.seconds:>7.2f}s  {detail}"
    )


def exit_code(results: list[StepResult]) -> int:
    return 1 if any(r.status is StepStatus.FAIL for r in results) else 0


def summary(results: list[StepResult]) -> str:
    passed = sum(r.status is StepStatus.PASS for r in results)
    verdict = "FAIL" if exit_code(results) else "PASS"
    return f"RESULT {verdict} ({passed}/{len(results)} steps passed)"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_http_code(output: str) -> int | None:
    """The status code that `curl -w '%{http_code}'` printed last."""
    tail = output.strip()[-3:]
    return int(tail) if tail.isdigit() else None


def smoke_email() -> str:
    return f"{SMOKE_EMAIL_PREFIX}{uuid4().hex[:12]}@{SMOKE_EMAIL_DOMAIN}"


class ArchiveProbe:
    """Looks at one session archive in the file store: its file record and,
    through a signed GET, the object itself."""

    def __init__(self, tenant_id: str, file_id: str) -> None:
        store = get_default_file_store()
        if not isinstance(store, PresignableFileStore):
            raise StepFailedError("the file store cannot sign URLs")
        self._tenant_id = tenant_id
        self._file_id = file_id
        # Signed while the record exists: the URL still names the object after.
        self._download: PresignedRequest = store.presign_download(file_id)

    def record_exists(self) -> bool:
        with get_session_with_tenant(tenant_id=self._tenant_id) as db:
            return get_filerecord_by_file_id_optional(self._file_id, db) is not None

    def object_status(self) -> int:
        response = requests.request(
            self._download.method,
            self._download.url,
            headers=self._download.headers,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        return response.status_code


def wait_for_idle() -> None:
    """A stop gives way to any call in the last PLACEMENT_LOCK_WAIT_SECONDS."""
    wait = PLACEMENT_LOCK_WAIT_SECONDS + 2
    print(f"     save-stop: waiting {wait}s until the VM counts as idle", flush=True)
    time.sleep(wait)


def _output(result: ExecCommandResult) -> str:
    """The output of a smoke command, which is short enough to keep whole."""
    return result.head + result.tail


class FirecrackerSmoke:
    """The steps, in order, on one test user and one chat session."""

    def __init__(self, tenant_id: str, egress_url: str | None) -> None:
        self.tenant_id = tenant_id
        self.egress_url = egress_url
        self.tenant_cache = get_cache_backend(tenant_id=tenant_id)
        self.payload = os.urandom(PAYLOAD_BYTES)
        self.user_id: UUID | None = None
        self.sandbox_id: UUID | None = None
        self.file_id: str | None = None
        self._sandbox: FirecrackerHarnessSandbox | None = None
        self._ref: HarnessSandboxRef | None = None

    @property
    def sandbox(self) -> FirecrackerHarnessSandbox:
        if self._sandbox is None:
            raise StepFailedError("no harness sandbox")
        return self._sandbox

    @property
    def ref(self) -> HarnessSandboxRef:
        if self._ref is None:
            raise StepFailedError("no sandbox")
        return self._ref

    def steps(self) -> list[Step]:
        steps: list[Step] = [
            ("create", self.create),
            ("exec-uid", self.exec_uid),
            ("file", self.file_round_trip),
        ]
        if self.egress_url is not None:
            steps.append(("egress", self.egress))
        steps += [
            ("save-stop", self.save_stop),
            ("resume", self.resume),
            ("purge", self.purge),
        ]
        return steps

    def _exec(self, cmd: str) -> ExecCommandResult:
        return collect_exec_result(self.sandbox.exec_command(self.ref, cmd))

    def create(self) -> str:
        require(FIRECRACKER_ENABLED, "SANDBOX_RUNTIME is not firecracker")
        require(bool(SANDBOX_FC_TEMPLATE), "SANDBOX_FC_TEMPLATE is not set")
        self._sandbox = get_firecracker_sandbox()
        email = smoke_email()
        with get_session_with_tenant(tenant_id=self.tenant_id) as db:
            (user,) = batch_add_ext_perm_user_if_not_exists(db, [email])
            self.user_id = user.id
            self.sandbox_id = create_sandbox__no_commit(db, user.id).id
            db.commit()
        self._ref = HarnessSandboxRef(
            tenant_id=self.tenant_id, sandbox_id=self.sandbox_id, session_id=uuid4()
        )
        self.sandbox.ensure_running(self.ref)
        placement = get_sandbox_placement(self.tenant_cache, self.sandbox_id)
        if placement is None:
            raise StepFailedError("the VM has no placement")
        return f"user={email} sandbox={self.sandbox_id} node={placement.node_id}"

    def exec_uid(self) -> str:
        result = self._exec("id -u; id -un")
        output = _output(result)
        lines = output.split()
        require(
            result.exit_code == 0 and lines[:1] == [str(SANDBOX_UID)],
            f"exit={result.exit_code} output={output.strip()!r}",
        )
        return f"uid={lines[0]} user={' '.join(lines[1:2])}"

    def file_round_trip(self) -> str:
        want = sha256_hex(self.payload)
        self.sandbox.write_file(self.ref, DATA_PATH, self.payload)
        result = self._exec(
            f"sha256sum {DATA_PATH} && stat -c %u {DATA_PATH} "
            f"&& printf %s {NOTE_TEXT} > {NOTE_PATH}"
        )
        output = _output(result)
        require(result.exit_code == 0, f"exit={result.exit_code} {output}")
        fields = output.split()
        require(fields[:1] == [want], f"sha256 in the VM {fields[:1]} != {want}")
        require(fields[2:3] == [str(SANDBOX_UID)], f"file owner {fields[2:3]}")
        got = self.sandbox.read_file(self.ref, DATA_PATH, max_bytes=2 * PAYLOAD_BYTES)
        require(sha256_hex(got) == want, f"read back {len(got)} bytes, sha256 differs")
        return f"{len(got)} bytes sha256={want[:16]} owner={SANDBOX_UID}"

    def egress(self) -> str:
        url = self.egress_url or DEFAULT_EGRESS_URL
        # The VM has no network card: a response can only come through the proxy.
        result = self._exec(
            "curl -sS -o /dev/null --max-time 20 -w '%{http_code}' "
            f"{shlex.quote(url)} 2>&1 || true"
        )
        output = _output(result)
        code = parse_http_code(output)
        require(
            code is not None and 200 <= code < 400,
            f"{url}: {' '.join(output.split())}",
        )
        return f"{url} http={code}"

    def save_stop(self) -> str:
        checkpointer = self.sandbox.session_checkpointer()
        if checkpointer is None:
            raise StepFailedError("no session saves: the file store cannot sign URLs")
        wait_for_idle()
        outcome = stop_sandbox_vm(
            get_shared_cache_backend(),
            self.tenant_cache,
            MtlsHostAgentClientFactory(),
            checkpointer,
            tenant_id=self.tenant_id,
            sandbox_id=self.ref.sandbox_id,
        )
        require(outcome is VmStopOutcome.STOPPED, f"outcome={outcome.value}")
        save = get_session_save(self.tenant_cache, self.ref.session_id)
        if save is None or save.file_id is None:
            raise StepFailedError("no save record after the stop")
        self.file_id = save.file_id
        require(
            get_sandbox_placement(self.tenant_cache, self.ref.sandbox_id) is None,
            "the placement is still there after the stop",
        )
        return f"archive={save.size_bytes} bytes roots={','.join(save.roots)}"

    def resume(self) -> str:
        self.sandbox.ensure_running(self.ref)
        got = self.sandbox.read_file(self.ref, DATA_PATH, max_bytes=2 * PAYLOAD_BYTES)
        require(
            sha256_hex(got) == sha256_hex(self.payload),
            f"{DATA_PATH} after resume: {len(got)} bytes, sha256 differs",
        )
        note = _output(self._exec(f"cat {NOTE_PATH}"))
        require(note.strip() == NOTE_TEXT, f"{NOTE_PATH}: {note!r}")
        placement = get_sandbox_placement(self.tenant_cache, self.ref.sandbox_id)
        node = placement.node_id if placement else ""
        return f"files intact node={node}"

    def purge(self) -> str:
        if self.file_id is None:
            raise StepFailedError("no archive to purge")
        probe = ArchiveProbe(self.tenant_id, self.file_id)
        before = probe.object_status()
        require(before == 200, f"archive GET before the purge: http={before}")
        self.sandbox.purge_session(
            tenant_id=self.tenant_id,
            sandbox_id=self.ref.sandbox_id,
            session_id=self.ref.session_id,
        )
        require(
            get_session_save(self.tenant_cache, self.ref.session_id) is None,
            "the save record is still there",
        )
        require(not probe.record_exists(), f"file record {self.file_id} is still there")
        after = probe.object_status()
        require(after != 200, "the archive object is still readable")
        # 404, or 403 when the signer may not list the bucket: any other status
        # does not show that the object is gone.
        require(after in (403, 404), f"archive GET after the purge: http={after}")
        return f"save record, file record and object gone (GET http={after})"

    def cleanup(self) -> str:
        if self.user_id is None:
            return "nothing to clean up"
        problems: list[str] = []
        if self.sandbox_id is not None and self._sandbox is not None:
            try:
                self._sandbox.purge_sandbox(
                    tenant_id=self.tenant_id, sandbox_id=self.sandbox_id
                )
                if get_sandbox_placement(self.tenant_cache, self.sandbox_id):
                    problems.append("the VM placement is still there")
            except Exception as e:
                problems.append(f"sandbox purge: {type(e).__name__}: {e}")
        if problems:
            # --cleanup-leaked finds the sandbox through its user.
            raise StepFailedError(
                "; ".join(problems) + "; test user kept, run with --cleanup-leaked"
            )
        delete_smoke_user(self.tenant_id, self.user_id)
        return "sandbox purged, test user deleted"


def delete_smoke_user(tenant_id: str, user_id: UUID) -> None:
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        user = fetch_user_by_id(db, user_id)
        if user is not None:
            delete_user_from_db__no_commit(user, db)
            db.commit()


def cleanup_leaked(tenant_id: str) -> str:
    """Purge the sandboxes and users that an interrupted run left."""
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        users = [
            user
            for user in get_all_users(
                db, email_filter_string=SMOKE_EMAIL_PREFIX, include_external=True
            )
            if user.account_type == AccountType.EXT_PERM_USER
            and user.email.startswith(SMOKE_EMAIL_PREFIX)
            and user.email.endswith("@" + SMOKE_EMAIL_DOMAIN)
        ]
        leaked = [
            (user.id, user.email, get_sandbox_by_user_id(db, user.id)) for user in users
        ]
        targets = [(uid, email, sb.id if sb else None) for uid, email, sb in leaked]
    for user_id, email, sandbox_id in targets:
        if sandbox_id is not None:
            get_firecracker_sandbox().purge_sandbox(
                tenant_id=tenant_id, sandbox_id=sandbox_id
            )
        delete_smoke_user(tenant_id, user_id)
        print(f"     removed {email}", flush=True)
    return f"{len(targets)} leaked test users removed"


def resolve_tenant(requested: str | None) -> str:
    if requested:
        return requested
    if MULTI_TENANT:
        raise SystemExit("--tenant-id is required on a multi-tenant deployment")
    return POSTGRES_DEFAULT_SCHEMA


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test for Craft on Firecracker")
    parser.add_argument("--tenant-id", help="Tenant (required when multi-tenant)")
    parser.add_argument(
        "--egress-url",
        default=DEFAULT_EGRESS_URL,
        help="HTTPS URL that the VM must reach through the sandbox proxy",
    )
    parser.add_argument(
        "--skip-egress", action="store_true", help="Do not check egress"
    )
    parser.add_argument(
        "--cleanup-leaked",
        action="store_true",
        help="Only remove test users and sandboxes left by an interrupted run",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show the server INFO log lines"
    )
    return parser.parse_args(argv)


def print_result(result: StepResult) -> None:
    print(format_result(result), flush=True)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.verbose:
        logging.disable(logging.INFO)
    tenant_id = resolve_tenant(args.tenant_id)
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    SqlEngine.init_engine(pool_size=2, max_overflow=2)
    print(
        f"Craft on Firecracker smoke test: tenant={tenant_id} "
        f"template={SANDBOX_FC_TEMPLATE or '-'}",
        flush=True,
    )
    if args.cleanup_leaked:
        results = run_steps(
            [], ("cleanup", lambda: cleanup_leaked(tenant_id)), print_result
        )
    else:
        smoke = FirecrackerSmoke(
            tenant_id, None if args.skip_egress else args.egress_url
        )
        results = run_steps(smoke.steps(), ("cleanup", smoke.cleanup), print_result)
    print(summary(results), flush=True)
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
