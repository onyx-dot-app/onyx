"""Signed VM identity against real Postgres and cache: registration, placement,
replay, rotation, and the gate binding (`SANDBOX_RUNTIME=firecracker` paths)."""

import base64
import time
from collections.abc import Generator
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.requests import Request

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.models import Sandbox
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm import registry
from onyx.microvm.models import RegisteredNode
from onyx.microvm.registry import (
    SandboxPlacement,
    clear_sandbox_placement,
    get_node_signing_key,
    get_registered_node,
    list_registered_nodes,
    set_node_agent_address,
    write_sandbox_placement,
)
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import parse_destination_policy
from onyx.sandbox_proxy.request_evaluator import CompositeRequestEvaluator
from onyx.sandbox_proxy.sandbox_identity.signed import (
    SignedIdentityError,
    SignedIdentityRejection,
    SignedIdentityVerifier,
)
from onyx.sandbox_proxy.sandbox_identity.signed_lookups import (
    CachedNodeSigningKeyLookup,
    CacheReplayGuard,
    CacheSandboxPlacementLookup,
)
from onyx.server.features.microvm import api as microvm_api
from onyx.server.features.microvm.api import (
    SandboxNodeSigningKeyRegistration,
    register_sandbox_node_signing_key,
    verify_sandbox_node_registration,
)
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user
from tests.unit.sandbox_proxy.conftest import StubResolver, make_flow


def _public_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _register(node_id: str, key_id: str, private_key: Ed25519PrivateKey) -> None:
    register_sandbox_node_signing_key(
        SandboxNodeSigningKeyRegistration(
            node_id=node_id, key_id=key_id, public_key=_public_b64(private_key)
        )
    )


def _token(
    private_key: Ed25519PrivateKey,
    *,
    key_id: str,
    node_id: str,
    sandbox_id: UUID,
    generation: int,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": f"spiffe://onyx/tenant/{POSTGRES_DEFAULT_SCHEMA}/sandbox/{sandbox_id}",
            "gen": generation,
            "node": node_id,
            "iat": now,
            "exp": now + 60,
            "jti": str(uuid4()),
            "aud": "sandbox-proxy",
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": key_id},
    )


def _tenant_cache(tenant_id: str = POSTGRES_DEFAULT_SCHEMA) -> CacheBackend:
    return get_cache_backend(tenant_id=tenant_id)


def _verifier() -> SignedIdentityVerifier:
    return SignedIdentityVerifier(
        signing_keys=CachedNodeSigningKeyLookup(get_shared_cache_backend),
        placement=CacheSandboxPlacementLookup(_tenant_cache),
        replay_guard=CacheReplayGuard(_tenant_cache),
    )


@pytest.fixture
def placed_vm(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[UUID, UUID, str, str, Ed25519PrivateKey], None, None]:
    """A sandbox placed on a fresh node at generation 2, with the node's key registered.

    Yields (sandbox_id, user_id, node_id, key_id, private_key).
    """
    user = create_test_user(db_session, "signed_identity")
    node_id = f"node-{uuid4().hex[:12]}"
    key_id = f"{node_id}-1"
    sandbox = Sandbox(id=uuid4(), user_id=user.id)
    db_session.add(sandbox)
    db_session.commit()
    write_sandbox_placement(
        _tenant_cache(),
        sandbox.id,
        SandboxPlacement(node_id=node_id, attempt=1, generation=2, last_active=0),
    )
    private_key = Ed25519PrivateKey.generate()
    _register(node_id, key_id, private_key)

    yield sandbox.id, user.id, node_id, key_id, private_key

    clear_sandbox_placement(_tenant_cache(), sandbox.id)


def test_verifier_accepts_placed_sandbox_and_rejects_replay(
    placed_vm: tuple[UUID, UUID, str, str, Ed25519PrivateKey],
) -> None:
    sandbox_id, user_id, node_id, key_id, private_key = placed_vm
    verifier = _verifier()
    token = _token(
        private_key, key_id=key_id, node_id=node_id, sandbox_id=sandbox_id, generation=2
    )

    claims, owner = verifier.verify(token)
    assert (claims.sandbox_id, owner) == (sandbox_id, user_id)

    with pytest.raises(SignedIdentityError) as replayed:
        verifier.verify(token)
    assert replayed.value.reason is SignedIdentityRejection.REPLAYED


def test_verifier_rejects_stale_generation_and_moved_sandbox(
    placed_vm: tuple[UUID, UUID, str, str, Ed25519PrivateKey],
) -> None:
    sandbox_id, _, node_id, key_id, private_key = placed_vm
    verifier = _verifier()

    stale = _token(
        private_key, key_id=key_id, node_id=node_id, sandbox_id=sandbox_id, generation=1
    )
    with pytest.raises(SignedIdentityError) as stale_error:
        verifier.verify(stale)
    assert stale_error.value.reason is SignedIdentityRejection.NOT_PLACED

    # The sandbox moved to another node: the old node can no longer vouch for it.
    write_sandbox_placement(
        _tenant_cache(),
        sandbox_id,
        SandboxPlacement(node_id="node-other", attempt=1, generation=2, last_active=0),
    )
    moved = _token(
        private_key, key_id=key_id, node_id=node_id, sandbox_id=sandbox_id, generation=2
    )
    with pytest.raises(SignedIdentityError) as moved_error:
        verifier.verify(moved)
    assert moved_error.value.reason is SignedIdentityRejection.NOT_PLACED


def test_rotation_expires_old_key_after_overlap(
    placed_vm: tuple[UUID, UUID, str, str, Ed25519PrivateKey],
) -> None:
    sandbox_id, _, node_id, key_id, old_key = placed_vm
    new_key = Ed25519PrivateKey.generate()
    _register(node_id, f"{node_id}-2", new_key)

    shared = get_shared_cache_backend()
    old_record = f"sandbox_fc:signing_key:{key_id}"
    assert 0 < shared.ttl(old_record) <= 300
    # Jump past the overlap window.
    shared.delete(old_record)

    old_token = _token(
        old_key, key_id=key_id, node_id=node_id, sandbox_id=sandbox_id, generation=2
    )
    with pytest.raises(SignedIdentityError) as old_error:
        _verifier().verify(old_token)
    assert old_error.value.reason is SignedIdentityRejection.UNKNOWN_SIGNING_KEY

    new_token = _token(
        new_key,
        key_id=f"{node_id}-2",
        node_id=node_id,
        sandbox_id=sandbox_id,
        generation=2,
    )
    assert _verifier().verify(new_token)[0].sandbox_id == sandbox_id


def test_registration_rejects_key_id_reuse_with_other_key(
    placed_vm: tuple[UUID, UUID, str, str, Ed25519PrivateKey],
) -> None:
    _, _, node_id, key_id, private_key = placed_vm
    # Same key again (agent restart) is accepted.
    _register(node_id, key_id, private_key)
    with pytest.raises(OnyxError) as conflict:
        _register(node_id, key_id, Ed25519PrivateKey.generate())
    assert conflict.value.error_code is OnyxErrorCode.CONFLICT


@pytest.mark.parametrize(
    "configured, header, allowed",
    [
        ("cluster-cred", "Bearer cluster-cred", True),
        ("cluster-cred", "Bearer wrong", False),
        ("cluster-cred", None, False),
        ("caf\u00e9", "Bearer caf\u00e9", True),
        ("voil\u00e0", "Bearer voil\u00e0", True),
        ("cluster-cred", "Bearer \u00ff\u00fe", False),
        (None, "Bearer anything", False),
    ],
)
def test_registration_requires_cluster_credential(
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
    header: str | None,
    allowed: bool,
) -> None:
    monkeypatch.setattr(microvm_api, "SANDBOX_NODE_REGISTRATION_SECRET", configured)
    raw_headers = [] if header is None else [(b"authorization", header.encode("utf-8"))]
    request = Request({"type": "http", "headers": raw_headers})
    if allowed:
        verify_sandbox_node_registration(request)
        return
    with pytest.raises(OnyxError) as error:
        verify_sandbox_node_registration(request)
    assert error.value.error_code is OnyxErrorCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_gate_binds_signed_connect_with_real_verifier(
    monkeypatch: pytest.MonkeyPatch,
    placed_vm: tuple[UUID, UUID, str, str, Ed25519PrivateKey],
) -> None:
    sandbox_id, user_id, node_id, key_id, private_key = placed_vm
    monkeypatch.setattr(
        "onyx.sandbox_proxy.addons.gate.resolve_destination",
        lambda *_args, **_kwargs: ("8.8.8.8",),
    )
    ip_resolver = StubResolver(sandbox=None)
    addon = GateAddon(
        identity=ip_resolver,
        request_evaluator=CompositeRequestEvaluator([]),
        destination_policy=parse_destination_policy(""),
        cache_factory=_tenant_cache,
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
        signed_identity=_verifier(),
    )
    token = _token(
        private_key, key_id=key_id, node_id=node_id, sandbox_id=sandbox_id, generation=2
    )
    connect = make_flow(
        conn_id=f"conn-{uuid4().hex}",
        method="CONNECT",
        proxy_auth=f"Bearer {token}",
    )

    await addon.http_connect(connect)

    assert connect.response is None
    inner = make_flow(conn_id=connect.client_conn.id, method="GET")
    resolved = addon._resolve_sandbox(inner)
    assert resolved is not None
    assert (resolved.sandbox_id, resolved.user_id) == (sandbox_id, user_id)
    assert ip_resolver.resolve_sandbox_calls == 0

    # The same token on a new connection is a replay.
    replay = make_flow(
        conn_id=f"conn-{uuid4().hex}", method="CONNECT", proxy_auth=f"Bearer {token}"
    )
    await addon.http_connect(replay)
    assert replay.response is not None and replay.response.status_code == 403


def test_registration_route_over_http(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from onyx.error_handling.exceptions import register_onyx_exception_handlers
    from onyx.server.auth_check import check_router_auth

    monkeypatch.setattr(microvm_api, "SANDBOX_NODE_REGISTRATION_SECRET", "cred")
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(microvm_api.router)
    check_router_auth(app)
    client = TestClient(app)
    node_id = f"node-{uuid4().hex[:12]}"
    body = {
        "node_id": node_id,
        "key_id": f"{node_id}-1",
        "public_key": _public_b64(Ed25519PrivateKey.generate()),
    }

    try:
        assert (
            client.put(microvm_api.SANDBOX_NODE_SIGNING_KEY_PATH, json=body).status_code
            == 401
        )
        bad_key = {**body, "public_key": base64.b64encode(b"short").decode()}
        assert (
            client.put(
                microvm_api.SANDBOX_NODE_SIGNING_KEY_PATH,
                json=bad_key,
                headers={"Authorization": "Bearer cred"},
            ).status_code
            == 400
        )
        ok = client.put(
            microvm_api.SANDBOX_NODE_SIGNING_KEY_PATH,
            json=body,
            headers={"Authorization": "Bearer cred"},
        )
        assert ok.status_code == 200
        registered = get_node_signing_key(get_shared_cache_backend(), body["key_id"])
        assert registered is not None and registered.node_id == node_id
    finally:
        get_shared_cache_backend().delete(f"sandbox_fc:signing_key:{body['key_id']}")


def test_registration_rejects_key_id_claimed_by_other_node(
    placed_vm: tuple[UUID, UUID, str, str, Ed25519PrivateKey],
) -> None:
    _, _, node_id, key_id, private_key = placed_vm
    with pytest.raises(OnyxError) as conflict:
        _register(f"{node_id}-other", key_id, private_key)
    assert conflict.value.error_code is OnyxErrorCode.CONFLICT
    registered = get_node_signing_key(get_shared_cache_backend(), key_id)
    assert registered is not None and registered.node_id == node_id


def _cleanup_node(node_id: str, key_ids: list[str]) -> None:
    cache = get_shared_cache_backend()
    for key_id in key_ids:
        cache.delete(f"sandbox_fc:signing_key:{key_id}")
    cache.delete(f"sandbox_fc:node_kids:{node_id}")
    cache.delete(f"sandbox_fc:node_address:{node_id}")
    cache.delete(f"sandbox_fc:node_address_key:{node_id}")
    cache.set_remove("sandbox_fc:nodes", node_id)


def test_registration_records_agent_address() -> None:
    """The agent sends its listener with the key; older agents send none."""
    cache = get_shared_cache_backend()
    node_id = f"node-{uuid4().hex[:12]}"
    other_id = f"{node_id}-old"
    private_key = Ed25519PrivateKey.generate()
    try:
        register_sandbox_node_signing_key(
            SandboxNodeSigningKeyRegistration(
                node_id=node_id,
                key_id=f"{node_id}-1",
                public_key=_public_b64(private_key),
                agent_address="10.0.3.7:7443",
            )
        )
        _register(other_id, f"{other_id}-1", Ed25519PrivateKey.generate())

        node = RegisteredNode(node_id=node_id, address="10.0.3.7:7443")
        assert get_registered_node(cache, node_id) == node
        assert node in list_registered_nodes(cache)
        assert get_registered_node(cache, other_id) is None
        # The address names the registration that sent it.
        assert cache.get(registry._NODE_ADDRESS_KEY_PREFIX + node_id) == (
            f"{node_id}-1".encode()
        )

        # A rejected registration does not move the node.
        with pytest.raises(OnyxError):
            register_sandbox_node_signing_key(
                SandboxNodeSigningKeyRegistration(
                    node_id=node_id,
                    key_id=f"{node_id}-1",
                    public_key=_public_b64(Ed25519PrivateKey.generate()),
                    agent_address="10.0.9.9:7443",
                )
            )
        assert get_registered_node(cache, node_id) == node

        # An agent restarted without an address does not keep the old one.
        _register(node_id, f"{node_id}-1", private_key)
        assert get_registered_node(cache, node_id) is None
        assert node_id not in {n.node_id for n in list_registered_nodes(cache)}
    finally:
        _cleanup_node(node_id, [f"{node_id}-1"])
        _cleanup_node(other_id, [f"{other_id}-1"])


def test_list_keeps_node_that_registers_during_prune(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A list that saw the address expire does not drop a fresh registration."""
    cache = get_shared_cache_backend()
    node_id = f"node-{uuid4().hex[:12]}"
    real_get = registry.get_registered_node

    def get_then_reregister(
        shared_cache: CacheBackend, member: str
    ) -> RegisteredNode | None:
        node = real_get(shared_cache, member)
        if member == node_id and node is None:
            set_node_agent_address(
                shared_cache, node_id=node_id, address="10.0.3.8:7443"
            )
        return node

    try:
        set_node_agent_address(cache, node_id=node_id, address="10.0.3.7:7443")
        cache.delete(f"sandbox_fc:node_address:{node_id}")
        monkeypatch.setattr(registry, "get_registered_node", get_then_reregister)

        assert node_id not in {n.node_id for n in list_registered_nodes(cache)}
        monkeypatch.undo()
        assert RegisteredNode(node_id=node_id, address="10.0.3.8:7443") in (
            list_registered_nodes(cache)
        )
    finally:
        _cleanup_node(node_id, [])


@pytest.mark.parametrize(
    "address, valid",
    [
        ("10.0.3.7:7443", True),
        ("[fd00::7]:7443", True),
        ("agent-0.onyx.svc:7443", True),
        ("10.0.3.7:65535", True),
        ("10.0.3.7", False),
        ("fd00::7:7443", False),
        ("http://10.0.3.7:7443/", False),
        (":7443", False),
        ("10.0.3.7:0", False),
        ("10.0.3.7:65536", False),
        ("agent_0.local:7443", False),
    ],
)
def test_registration_validates_agent_address(address: str, valid: bool) -> None:
    def build() -> SandboxNodeSigningKeyRegistration:
        return SandboxNodeSigningKeyRegistration(
            node_id="node-a",
            key_id="node-a-1",
            public_key=_public_b64(Ed25519PrivateKey.generate()),
            agent_address=address,
        )

    if valid:
        assert build().agent_address == address
        return
    with pytest.raises(ValidationError):
        build()
