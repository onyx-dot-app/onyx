"""Registration retries use one callback and never weaken GitHub transport security."""

import hashlib
import hmac
import io
import json
from collections.abc import Generator
from unittest.mock import Mock, patch

import pytest
import requests

from onyx.db.models import Marketplace
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.github_webhooks import GitHubWebhooks
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from onyx.skills.marketplace.provider import GitHubMarketplaceAdapter
from onyx.utils.sensitive import SensitiveValue

CALLBACK = "https://onyx.example/marketplaces/fixture/github"
SECRET = "fixture-signing-secret"


def response(value: object, status: int = 200) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(value).encode()
    result.raw = io.BytesIO()
    return result


def hook(identifier: int = 17, url: str = CALLBACK) -> dict[str, object]:
    return {"id": identifier, "config": {"url": url}}


def client(ref: str = "main") -> GitHubWebhooks:
    return GitHubWebhooks(
        GitHubMarketplaceConfig(owner="acme", repo="skills", ref=ref), "Bearer fixture"
    )


@pytest.fixture
def transport() -> Generator[Mock, None, None]:
    with patch("onyx.skills.marketplace.github_webhooks.requests.request") as request:
        yield request


@pytest.mark.parametrize(
    "ref", ["main", "feature/skills", "refs/heads/main", "refs/tags/v1"]
)
def test_exact_ref_resolution(transport: Mock, ref: str) -> None:
    expected = ref if ref.startswith("refs/") else "refs/heads/" + ref
    transport.side_effect = [response({"ref": expected}), response({}, 404)]
    assert client(ref).resolve_ref() == expected
    assert transport.call_args_list[0].args == (
        "GET",
        "https://api.github.com/repos/acme/skills/git/ref/"
        + expected.removeprefix("refs/"),
    )


def test_tag_and_default_branch(transport: Mock) -> None:
    transport.side_effect = [response({}, 404), response({"ref": "refs/tags/v1"})]
    assert client("v1").resolve_ref() == "refs/tags/v1"
    transport.side_effect = [
        response({"default_branch": "release/current"}),
        response({"ref": "refs/heads/release/current"}),
    ]
    assert client("HEAD").resolve_ref() == "refs/heads/release/current"


@pytest.mark.parametrize("ref", ["a" * 40, "refs/pull/1/head"])
def test_unsupported_refs_do_not_register(transport: Mock, ref: str) -> None:
    with pytest.raises(OnyxError, match="commits|branch or tag"):
        client(ref).resolve_ref()
    transport.assert_not_called()


@pytest.mark.parametrize("refs", [[], ["refs/heads/main", "refs/tags/main"]])
def test_missing_or_ambiguous_ref(transport: Mock, refs: list[str]) -> None:
    transport.side_effect = [response({"ref": ref}) for ref in refs] or [
        response({}, 404),
        response({}, 404),
    ]
    with pytest.raises(OnyxError, match="unambiguous"):
        client().resolve_ref()


def test_create_uses_signed_json_and_verified_https(transport: Mock) -> None:
    transport.side_effect = [response([]), response(hook(), 201)]
    assert client().ensure(CALLBACK, SECRET) == "17"
    call = transport.call_args
    assert call.args == ("POST", "https://api.github.com/repos/acme/skills/hooks")
    assert call.kwargs["json"] == {
        "name": "web",
        "active": True,
        "events": ["push"],
        "config": {
            "url": CALLBACK,
            "content_type": "json",
            "secret": SECRET,
            "insecure_ssl": "0",
        },
    }
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["timeout"] == 30
    assert call.kwargs["headers"]["Authorization"] == "Bearer fixture"


def test_retry_after_lost_acknowledgement_reuses_hook(transport: Mock) -> None:
    transport.side_effect = [response([]), requests.Timeout()]
    with pytest.raises(OnyxError, match="Retry"):
        client().ensure(CALLBACK, SECRET)
    transport.reset_mock()
    transport.side_effect = [
        response([hook(18, "https://other.example"), hook()]),
        response(hook()),
    ]
    assert client().ensure(CALLBACK, SECRET) == "17"
    assert [c.args[0] for c in transport.call_args_list] == ["GET", "PATCH"]
    assert transport.call_args.args[1].endswith("/hooks/17")


def test_simultaneous_creation_reuses_hook(transport: Mock) -> None:
    transport.side_effect = [
        response([]),
        response({}, 422),
        response([hook()]),
        response(hook()),
    ]
    assert client().ensure(CALLBACK, SECRET) == "17"


def test_hooks_are_paginated_without_following_remote_links(transport: Mock) -> None:
    transport.side_effect = [
        response([hook(n, f"https://other.example/{n}") for n in range(100)]),
        response([hook()]),
        response(hook()),
    ]
    assert client().ensure(CALLBACK, SECRET) == "17"
    assert transport.call_args_list[1].args[1].endswith("page=2")


@pytest.mark.parametrize(
    "status, detail",
    [
        (401, "Reconnect"),
        (403, "repository admin"),
        (404, "repository admin"),
        (429, "rate limit"),
        (500, "Try again"),
        (302, "Try again"),
    ],
)
def test_errors_do_not_forward_provider_bodies(
    transport: Mock, status: int, detail: str
) -> None:
    transport.return_value = response({"message": "PRIVATE PROVIDER BODY"}, status)
    with pytest.raises(OnyxError, match=detail) as raised:
        client().ensure(CALLBACK, SECRET)
    assert "PRIVATE" not in str(raised.value)


@pytest.mark.parametrize("body", [{}, "invalid", [{"config": {"url": CALLBACK}}]])
def test_malformed_hook_list(transport: Mock, body: object) -> None:
    transport.return_value = response(body)
    with pytest.raises(OnyxError, match="invalid webhook"):
        client().ensure(CALLBACK, SECRET)


def test_rejected_creation_and_duplicate_callbacks(transport: Mock) -> None:
    transport.side_effect = [response([]), response({}, 422), response([])]
    with pytest.raises(OnyxError, match="rejected"):
        client().ensure(CALLBACK, SECRET)
    transport.side_effect = [response([hook(1), hook(2)])]
    with pytest.raises(OnyxError, match="Multiple"):
        client().ensure(CALLBACK, SECRET)


@pytest.mark.parametrize("status", [204, 404])
def test_remove_is_idempotent(transport: Mock, status: int) -> None:
    transport.return_value = response({}, status)
    client().remove("17")
    assert transport.call_args.args == (
        "DELETE",
        "https://api.github.com/repos/acme/skills/hooks/17",
    )


def test_default_branch_receiver_matches_registered_branch() -> None:
    marketplace = Marketplace(
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(
            owner="acme", repo="skills", ref="HEAD"
        ),
        webhook_ref="refs/heads/main",
        webhook_id="17",
        webhook_secret=SensitiveValue[str](
            encrypted_bytes=SECRET.encode(), decrypt_fn=lambda value: value.decode()
        ),
    )
    adapter = GitHubMarketplaceAdapter(marketplace, "public")
    for ref, expected in [
        ("refs/heads/main", "sync"),
        ("refs/tags/main", "received"),
        ("refs/heads/other", "received"),
    ]:
        body = json.dumps(
            {"repository": {"full_name": "acme/skills"}, "ref": ref}
        ).encode()
        signature = (
            "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        )
        assert (
            adapter.verify_webhook(
                body, signature=signature, event="push", hook_id="17"
            )
            == expected
        )
