"""External-dependency-unit tests for the mobile SSO one-time code store.

Runs against a real Redis. Pins the security contract that protects the
custom-scheme deep link: single-use redemption, a short TTL, and PKCE (S256)
binding so a hijacked code is useless without the matching verifier.
"""

import asyncio
import json

import pytest

from onyx.auth.mobile_sso.code_store import consume_sso_code
from onyx.auth.mobile_sso.code_store import store_sso_code
from onyx.auth.pkce import compute_s256_challenge
from onyx.auth.users import generate_pkce_pair
from onyx.configs.app_configs import MOBILE_SSO_CODE_PREFIX
from onyx.configs.app_configs import MOBILE_SSO_CODE_TTL_SECONDS
from onyx.redis.redis_pool import get_async_redis_connection


@pytest.mark.asyncio
async def test_store_then_consume_round_trip() -> None:
    verifier, challenge = generate_pkce_pair()
    code = await store_sso_code("tok_round_trip", challenge)
    assert code
    assert await consume_sso_code(code, verifier) == "tok_round_trip"


@pytest.mark.asyncio
async def test_code_is_single_use() -> None:
    verifier, challenge = generate_pkce_pair()
    code = await store_sso_code("tok_single_use", challenge)

    assert await consume_sso_code(code, verifier) == "tok_single_use"
    # The atomic GETDEL burned the code on first read.
    assert await consume_sso_code(code, verifier) is None


@pytest.mark.asyncio
async def test_wrong_verifier_rejected_and_burns_code() -> None:
    verifier, challenge = generate_pkce_pair()
    wrong_verifier, _ = generate_pkce_pair()
    code = await store_sso_code("tok_wrong_verifier", challenge)

    # A code without the matching verifier is useless (PKCE) ...
    assert await consume_sso_code(code, wrong_verifier) is None
    # ... and the failed attempt still burned the code, so even the correct
    # verifier cannot redeem it afterwards (no retry oracle).
    assert await consume_sso_code(code, verifier) is None


@pytest.mark.asyncio
async def test_unknown_code_returns_none() -> None:
    verifier, _ = generate_pkce_pair()
    assert await consume_sso_code("this-code-was-never-stored", verifier) is None


@pytest.mark.asyncio
async def test_store_sets_bounded_ttl() -> None:
    _, challenge = generate_pkce_pair()
    code = await store_sso_code("tok_ttl", challenge)

    redis = await get_async_redis_connection()
    ttl = await redis.ttl(f"{MOBILE_SSO_CODE_PREFIX}{code}")
    # Positive TTL that never exceeds the configured ceiling -> the code self-
    # expires even if it is never redeemed.
    assert 0 < ttl <= MOBILE_SSO_CODE_TTL_SECONDS


@pytest.mark.asyncio
async def test_code_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.auth.mobile_sso.code_store.MOBILE_SSO_CODE_TTL_SECONDS", 1
    )
    verifier, challenge = generate_pkce_pair()
    code = await store_sso_code("tok_expiry", challenge)

    await asyncio.sleep(1.5)
    assert await consume_sso_code(code, verifier) is None


def test_s256_matches_generate_pkce_pair() -> None:
    # The store's S256 transform must agree with the app-facing PKCE generator,
    # otherwise a verifier produced by the client would never validate.
    verifier, challenge = generate_pkce_pair()
    assert compute_s256_challenge(verifier) == challenge


def test_s256_matches_rfc7636_fixed_vector() -> None:
    # Pin the transform against the canonical RFC 7636 Appendix B vector so it is
    # locked independently of generate_pkce_pair.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert (
        compute_s256_challenge(verifier)
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


@pytest.mark.asyncio
async def test_non_ascii_verifier_fails_closed_as_generic_miss() -> None:
    # A malformed (non-ascii) verifier must redeem to None — the same generic
    # miss as any other failure — never raise / leak a distinct error.
    _, challenge = generate_pkce_pair()
    code = await store_sso_code("tok_non_ascii", challenge)
    assert await consume_sso_code(code, "naïve-vérifier-✗") is None


@pytest.mark.asyncio
async def test_malformed_record_fails_closed_as_generic_miss() -> None:
    # A record with a non-str challenge would make compare_digest raise; it must
    # instead fail closed as the same generic miss (fail-closed contract).
    verifier, _ = generate_pkce_pair()
    code = "manually-planted-malformed-code"
    redis = await get_async_redis_connection()
    await redis.set(
        f"{MOBILE_SSO_CODE_PREFIX}{code}",
        json.dumps({"token": "tok", "code_challenge": 12345}),
        ex=MOBILE_SSO_CODE_TTL_SECONDS,
    )
    assert await consume_sso_code(code, verifier) is None
