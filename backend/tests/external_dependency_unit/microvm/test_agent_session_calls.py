"""Host agent session saves and managed drive calls against the fake agent:
typed results, and typed errors of both the agent and the guest daemon."""

import hashlib
import io
import zipfile
from collections.abc import Generator
from dataclasses import dataclass

import grpc
import pytest
from pydantic import SecretStr

from onyx.microvm.agent_client import (
    HostAgentClient,
    HostAgentError,
    HostAgentErrorReason,
    InstanceMismatchError,
    new_sandboxd_key,
)
from onyx.microvm.daemon_client import (
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
)
from onyx.microvm.models import FileType, ManagedSlot, PresignedRequest, VmInstance
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
    RunningFakeAgent,
)

SANDBOX_ID = "5d0c7a3e-1b2f-4c6d-8e9a-0f1b2c3d4e5f"
SESSION = "s1"
URL = "https://bucket.example/cap?sig=1"
GET = PresignedRequest(url=SecretStr(URL), method="GET")


def _put(size_bytes: int) -> PresignedRequest:
    return PresignedRequest(
        url=SecretStr(URL),
        method="PUT",
        headers={"Content-Length": str(size_bytes)},
    )


@dataclass
class Node:
    agent: FakeHostAgent
    host: HostAgentClient
    daemon: SandboxDaemonClient
    vm: VmInstance


@pytest.fixture
def node() -> Generator[Node, None, None]:
    running = RunningFakeAgent(FakeHostAgent())
    factory = InsecureClientFactory()
    host = factory.client(running.address)
    key = new_sandboxd_key()
    created = host.create(
        sandbox_id=SANDBOX_ID,
        attempt=1,
        template="tpl-1",
        vcpus=2,
        mem_mib=2048,
        scratch_gib=4,
        tenant_id="public",
        sandboxd_key=key,
    )
    daemon = SandboxDaemonClient(host.channel, sandbox_id=SANDBOX_ID, sandboxd_key=key)
    daemon.init(
        generation=created.vm.generation, scratch_gib=4, env={}, session_ids=[SESSION]
    )
    vm = VmInstance(
        sandbox_id=SANDBOX_ID,
        attempt=1,
        generation=created.vm.generation,
        sandboxd_key=key,
    )
    yield Node(running.agent, host, daemon, vm)
    factory.close()
    running.stop()


def test_capture_upload_and_restore_round_trip(node: Node) -> None:
    node.daemon.write_file(session_id=SESSION, path="attachments/a.txt", data=b"hi")
    node.daemon.write_file(session_id=SESSION, path="outputs/b.txt", data=b"skip")
    node.daemon.write_file(
        session_id=SESSION, path="attachments/node_modules/x.js", data=b"dep"
    )

    capture = node.host.capture_session(
        node.vm, session_id=SESSION, exclude_names=["node_modules"]
    )
    assert capture.files == 1
    assert capture.excluded == 1
    assert capture.roots == ["attachments"]
    assert capture.expires_at is not None

    upload = node.host.upload_capture(
        capture_id=capture.capture_id, request=_put(capture.size_bytes)
    )
    assert (upload.size_bytes, upload.sha256) == (capture.size_bytes, capture.sha256)
    assert upload.http_status == 200
    assert node.agent.upload_headers == [{"Content-Length": str(capture.size_bytes)}]

    # The restore replaces the attachments root: a later file goes away.
    node.daemon.write_file(session_id=SESSION, path="attachments/new.txt", data=b"n")
    restored = node.host.restore_session(
        node.vm,
        session_id=SESSION,
        request=GET,
        size_bytes=capture.size_bytes,
        sha256=capture.sha256,
    )
    assert restored.files == 1
    assert restored.roots == ["attachments"]
    _, data = node.daemon.read_file(session_id=SESSION, path="attachments/a.txt")
    assert b"".join(data) == b"hi"
    listing = node.daemon.list_files(session_id=SESSION, recursive=True)
    assert {e.path for e in listing.entries if e.type is FileType.REGULAR} == {
        "attachments/a.txt",
        "outputs/b.txt",
    }


def test_upload_with_another_content_length_raises_archive_mismatch(
    node: Node,
) -> None:
    capture = node.host.capture_session(node.vm, session_id=SESSION)
    with pytest.raises(HostAgentError) as exc:
        node.host.upload_capture(
            capture_id=capture.capture_id, request=_put(capture.size_bytes + 1)
        )
    assert exc.value.reason is HostAgentErrorReason.ARCHIVE_MISMATCH


def test_capture_with_another_key_raises_the_daemon_error(node: Node) -> None:
    wrong = node.vm.model_copy(update={"sandboxd_key": new_sandboxd_key()})
    with pytest.raises(SandboxDaemonError) as exc:
        node.host.capture_session(wrong, session_id=SESSION)
    assert exc.value.reason is SandboxDaemonErrorReason.UNAUTHENTICATED
    assert exc.value.vm_unusable


def test_capture_of_another_instance_raises_instance_mismatch(node: Node) -> None:
    stale = node.vm.model_copy(update={"generation": node.vm.generation + 1})
    with pytest.raises(InstanceMismatchError):
        node.host.capture_session(stale, session_id=SESSION)


def test_upload_of_an_unknown_capture_raises_capture_not_found(node: Node) -> None:
    with pytest.raises(HostAgentError) as exc:
        node.host.upload_capture(capture_id="cap-404", request=_put(1))
    assert exc.value.reason is HostAgentErrorReason.CAPTURE_NOT_FOUND
    assert exc.value.code is grpc.StatusCode.NOT_FOUND


def test_discard_capture(node: Node) -> None:
    capture = node.host.capture_session(node.vm, session_id=SESSION)
    assert node.host.discard_capture(capture_id=capture.capture_id)
    assert not node.host.discard_capture(capture_id=capture.capture_id)


def test_restore_with_another_sha256_raises_archive_mismatch(node: Node) -> None:
    capture = node.host.capture_session(node.vm, session_id=SESSION)
    node.host.upload_capture(
        capture_id=capture.capture_id, request=_put(capture.size_bytes)
    )
    with pytest.raises(HostAgentError) as exc:
        node.host.restore_session(
            node.vm,
            session_id=SESSION,
            request=GET,
            size_bytes=capture.size_bytes,
            sha256="0" * 64,
        )
    assert exc.value.reason is HostAgentErrorReason.ARCHIVE_MISMATCH


def _bundle(n_bytes: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("skills/a/SKILL.md", b"x" * n_bytes)
    return buf.getvalue()


def test_put_managed_image_then_swap(node: Node) -> None:
    bundle = _bundle(3 << 20)  # several upload chunks

    put = node.host.put_managed_image(bundle)
    assert put.built
    assert put.image.image_id == hashlib.sha256(bundle).hexdigest()
    assert put.image.files == 1
    assert not node.host.put_managed_image(bundle).built

    stale = node.vm.model_copy(update={"attempt": 9, "sandbox_id": "other"})
    wrong_key = node.vm.model_copy(update={"sandboxd_key": new_sandboxd_key()})
    results = node.host.swap_managed(
        image_id=put.image.image_id, targets=[node.vm, stale]
    )
    assert [(r.sandbox_id, r.ok) for r in results] == [
        (SANDBOX_ID, True),
        ("other", False),
    ]
    assert results[0].active is ManagedSlot.B
    assert results[0].reason is None
    assert results[1].reason is HostAgentErrorReason.INSTANCE_MISMATCH

    [rejected] = node.host.swap_managed(
        image_id=put.image.image_id, targets=[wrong_key]
    )
    assert not rejected.ok
    assert rejected.reason is HostAgentErrorReason.GUEST_KEY_REJECTED

    [spaces] = node.host.swap_managed(
        image_id=put.image.image_id, targets=[node.vm], mount="spaces"
    )
    assert spaces.ok
    assert node.agent.swap_mounts == ["skills", "spaces"]


def test_put_of_a_bundle_that_is_not_a_zip_raises_bundle_invalid(node: Node) -> None:
    with pytest.raises(HostAgentError) as exc:
        node.host.put_managed_image(b"not a zip")
    assert exc.value.reason is HostAgentErrorReason.MANAGED_BUNDLE_INVALID
    assert exc.value.code is grpc.StatusCode.INVALID_ARGUMENT
    assert not node.agent.managed_images


def test_swap_of_a_missing_image_raises_managed_image_missing(node: Node) -> None:
    with pytest.raises(HostAgentError) as exc:
        node.host.swap_managed(image_id="f" * 64, targets=[node.vm])
    assert exc.value.reason is HostAgentErrorReason.MANAGED_IMAGE_MISSING


def test_newer_create_reasons_are_typed(node: Node) -> None:
    node.agent.refuse_create = HostAgentErrorReason.EGRESS_CA_UNAVAILABLE
    with pytest.raises(HostAgentError) as exc:
        node.host.create(
            sandbox_id="9c1e2d3f-4a5b-4c6d-8e7f-0a1b2c3d4e5f",
            attempt=1,
            template="tpl-1",
            vcpus=2,
            mem_mib=2048,
            scratch_gib=4,
            tenant_id="public",
            sandboxd_key=new_sandboxd_key(),
        )
    assert exc.value.reason is HostAgentErrorReason.EGRESS_CA_UNAVAILABLE
    assert exc.value.code is grpc.StatusCode.UNAVAILABLE
