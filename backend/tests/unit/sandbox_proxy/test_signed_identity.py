"""Signed sandbox identity verification.

`signed_identity_vectors.json` is shared with the Go host-agent relay. Regenerate
it with `UPDATE_SIGNED_IDENTITY_VECTORS=1 uv run pytest <this file>`.
"""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from onyx.sandbox_proxy.sandbox_identity import signed
from onyx.sandbox_proxy.sandbox_identity.signed import (
    NodeSigningKey,
    NodeSigningKeyLookup,
    ReplayGuard,
    SandboxClaims,
    SandboxPlacementLookup,
    SignedIdentityError,
    SignedIdentityRejection,
    SignedIdentityVerifier,
    parse_signed_identity_header,
)

_VECTORS_PATH = Path(__file__).parent / "signed_identity_vectors.json"

# Test-only seeds; low entropy on purpose.
_NODE_SEED = bytes(range(32))
_OTHER_SEED = bytes(range(32, 64))
_NOW = 1_800_000_000
_NODE = "node-a"
_KID = "node-a-1"
_TENANT = "public"
_SANDBOX = UUID("0b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69")
_OWNER = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _compact(header: dict[str, Any], claims: dict[str, Any]) -> tuple[str, str]:
    return (
        json.dumps(header, separators=(",", ":")),
        json.dumps(claims, separators=(",", ":")),
    )


def _token_from_vector(header_json: str, claims_json: str, signer: str) -> str:
    """Builds the JWS exactly as the Go relay must: sign the given JSON bytes."""
    signing_input = f"{_b64url(header_json.encode())}.{_b64url(claims_json.encode())}"
    if signer == "hs256":
        signature = hmac.new(b"x" * 32, signing_input.encode(), hashlib.sha256).digest()
    else:
        seed = _NODE_SEED if signer == "node" else _OTHER_SEED
        signature = Ed25519PrivateKey.from_private_bytes(seed).sign(
            signing_input.encode()
        )
    return f"{signing_input}.{_b64url(signature)}"


def _sign(
    claims: dict[str, Any],
    seed: bytes = _NODE_SEED,
    kid: str = _KID,
) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    return jwt.encode(claims, private_key, algorithm="EdDSA", headers={"kid": kid})


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "sub": f"spiffe://onyx/tenant/{_TENANT}/sandbox/{_SANDBOX}",
        "gen": 3,
        "node": _NODE,
        "iat": _NOW,
        "exp": _NOW + 60,
        "jti": "jti-0001",
        # Last, matching the Go relay's claim order.
        "aud": "sandbox-proxy",
    }
    claims.update(overrides)
    return claims


def _build_vectors() -> dict[str, Any]:
    eddsa = {"alg": "EdDSA", "typ": "JWT", "kid": _KID}
    no_jti = {k: v for k, v in _claims().items() if k != "jti"}
    no_aud = {k: v for k, v in _claims().items() if k != "aud"}
    cases: list[tuple[str, dict[str, Any], dict[str, Any], str, str | None]] = [
        ("valid", eddsa, _claims(), "node", None),
        ("wrong_signing_key", eddsa, _claims(), "other", "bad_signature"),
        (
            "unknown_kid",
            {**eddsa, "kid": "node-z-1"},
            _claims(),
            "node",
            "unknown_signing_key",
        ),
        ("expired", eddsa, _claims(iat=_NOW - 120, exp=_NOW - 60), "node", "expired"),
        (
            "lifetime_too_long",
            eddsa,
            _claims(exp=_NOW + 3600),
            "node",
            "lifetime_too_long",
        ),
        ("node_mismatch", eddsa, _claims(node="node-b"), "node", "node_mismatch"),
        ("hs256_alg", {**eddsa, "alg": "HS256"}, _claims(), "hs256", "malformed"),
        (
            "bad_subject",
            eddsa,
            _claims(sub="spiffe://onyx/sandbox/x"),
            "node",
            "malformed",
        ),
        ("missing_jti", eddsa, no_jti, "node", "malformed"),
        ("exp_before_iat", eddsa, _claims(iat=_NOW, exp=_NOW - 1), "node", "malformed"),
        ("wrong_audience", eddsa, _claims(aud="onyx-api"), "node", "malformed"),
        ("missing_aud", eddsa, no_aud, "node", "malformed"),
    ]
    vectors: list[dict[str, Any]] = []
    for name, header, claims, signer, rejection in cases:
        header_json, claims_json = _compact(header, claims)
        vectors.append(
            {
                "name": name,
                "header_json": header_json,
                "claims_json": claims_json,
                "signer": signer,
                "rejection": rejection,
            }
        )
    return {
        "now": _NOW,
        "node": _NODE,
        "kid": _KID,
        "node_seed_hex": _NODE_SEED.hex(),
        "other_seed_hex": _OTHER_SEED.hex(),
        "hs256_secret": "x" * 32,
        "cases": vectors,
    }


class _Keys(NodeSigningKeyLookup):
    def __init__(self) -> None:
        public_key = Ed25519PrivateKey.from_private_bytes(_NODE_SEED).public_key()
        self.keys = {
            _KID: NodeSigningKey(key_id=_KID, node_id=_NODE, public_key=public_key)
        }

    def get(self, key_id: str) -> NodeSigningKey | None:
        return self.keys.get(key_id)


class _Placement(SandboxPlacementLookup):
    def __init__(self) -> None:
        self.placed: dict[tuple[UUID, str, int], UUID] = {(_SANDBOX, _NODE, 3): _OWNER}

    def owner_if_placed(self, claims: SandboxClaims) -> UUID | None:
        return self.placed.get((claims.sandbox_id, claims.node_id, claims.generation))


class _Replay(ReplayGuard):
    def __init__(self) -> None:
        self.seen: set[str] = set()

    def first_use(self, claims: SandboxClaims) -> bool:
        if claims.jti in self.seen:
            return False
        self.seen.add(claims.jti)
        return True


def _verifier() -> SignedIdentityVerifier:
    return SignedIdentityVerifier(_Keys(), _Placement(), _Replay(), clock=lambda: _NOW)


def _rejection(verifier: SignedIdentityVerifier, token: str) -> SignedIdentityRejection:
    with pytest.raises(SignedIdentityError) as exc_info:
        verifier.verify(token)
    return exc_info.value.reason


def test_vectors_file_is_current() -> None:
    if os.environ.get("UPDATE_SIGNED_IDENTITY_VECTORS") == "1":
        _VECTORS_PATH.write_text(json.dumps(_build_vectors(), indent=2) + "\n")
    assert json.loads(_VECTORS_PATH.read_text()) == _build_vectors()


@pytest.mark.parametrize(
    "case", _build_vectors()["cases"], ids=lambda case: case["name"]
)
def test_shared_vectors(case: dict[str, Any]) -> None:
    verifier = _verifier()
    token = _token_from_vector(case["header_json"], case["claims_json"], case["signer"])
    if case["rejection"] is None:
        claims, owner = verifier.verify(token)
        assert (claims.sandbox_id, claims.tenant_id, owner) == (
            _SANDBOX,
            _TENANT,
            _OWNER,
        )
        assert (claims.node_id, claims.generation) == (_NODE, 3)
    else:
        assert _rejection(verifier, token).value == case["rejection"]


def test_replayed_jti_rejected() -> None:
    verifier = _verifier()
    token = _sign(_claims())
    verifier.verify(token)
    assert _rejection(verifier, token) is SignedIdentityRejection.REPLAYED


def test_wrong_generation_not_placed() -> None:
    token = _sign(_claims(gen=2))
    assert _rejection(_verifier(), token) is SignedIdentityRejection.NOT_PLACED


def test_issued_in_future_rejected() -> None:
    token = _sign(_claims(iat=_NOW + 30, exp=_NOW + 60))
    assert _rejection(_verifier(), token) is SignedIdentityRejection.MALFORMED


def test_audience_list_rejected() -> None:
    token = _sign(_claims(aud=["sandbox-proxy"]))
    assert _rejection(_verifier(), token) is SignedIdentityRejection.MALFORMED


def test_multi_tenant_requires_tenant_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(signed, "MULTI_TENANT", True)
    tenant = "tenant_" + str(UUID(int=5))
    good = _sign(_claims(sub=f"spiffe://onyx/tenant/{tenant}/sandbox/{_SANDBOX}"))
    assert _verifier().verify_claims(good).tenant_id == tenant
    public = _sign(_claims(sub=f"spiffe://onyx/tenant/public/sandbox/{_SANDBOX}"))
    assert _rejection(_verifier(), public) is SignedIdentityRejection.MALFORMED


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, None),
        ("Basic dXNlcjp4", None),
        ("Bearer abc.def.ghi", "abc.def.ghi"),
        ("bearer   abc", "abc"),
        ("Bearer", ""),
    ],
)
def test_parse_signed_identity_header(header: str | None, expected: str | None) -> None:
    assert parse_signed_identity_header(header) == expected
