"""Regression invariants for the CONFCLOUD-77618 / CONFCLOUD-76424
fallback: the offending 404 surfaces as a typed exception, perm-sync
restarts in per-page mode on it, the per-page lookup hits the dedicated
`restriction/byOperation` endpoint, and the EE walker skips unreadable
ancestors while caching shared ones."""

from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest
import requests
from requests import HTTPError

from ee.onyx.external_permissions.confluence.page_access import (
    get_page_restrictions_with_per_ancestor_fetch,
)
from onyx.connectors.confluence.access import (
    get_page_restrictions_with_per_ancestor_fetch as get_page_restrictions_with_per_ancestor_fetch_shim,
)
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.confluence.onyx_confluence import _is_confcloud_77618_response
from onyx.connectors.confluence.onyx_confluence import Confcloud77618Error
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.interfaces import CredentialsProviderInterface

_CONFCLOUD_77618_BODY = (
    '{"statusCode":404,"data":{"authorized":false,"valid":false,'
    '"errors":[{"message":{"translation":'
    '"No content with id <ContentId{id=12345}> can be found"}}],'
    '"successful":false}}'
)
_CONFCLOUD_76424_BODY = (
    '{"message":"Cannot find content. Outdated version/old_draft/trashed?'
    ' Please provide valid ContentId."}'
)


def _make_response(
    status_code: int,
    json_data: dict[str, Any] | None = None,
    body_text: str | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    if json_data is not None:
        response.json = mock.Mock(  # ty: ignore[invalid-assignment]
            return_value=json_data
        )
    if body_text is not None:
        response._content = body_text.encode()
    if status_code >= 400:
        response.reason = "Mock Error"
        response.raise_for_status = mock.Mock(  # ty: ignore[invalid-assignment]
            side_effect=HTTPError(response=response)
        )
    return response


@pytest.fixture
def mock_credentials_provider() -> mock.Mock:
    provider = mock.Mock(spec=CredentialsProviderInterface)
    provider.is_dynamic.return_value = False
    provider.get_credentials.return_value = {"confluence_access_token": "dummy_token"}
    provider.get_tenant_id.return_value = "test_tenant"
    provider.get_provider_key.return_value = "test_key"
    provider.__enter__ = mock.Mock(return_value=None)
    provider.__exit__ = mock.Mock(return_value=None)
    return provider


@pytest.fixture
def cloud_client(mock_credentials_provider: mock.Mock) -> OnyxConfluence:
    client = OnyxConfluence(
        is_cloud=True,
        url="https://fake-cloud.atlassian.net",
        credentials_provider=mock_credentials_provider,
        timeout=10,
    )
    mock_internal = mock.Mock()
    mock_internal.url = client._url
    client._confluence = mock_internal
    client._kwargs = client.shared_base_kwargs
    return client


# ---------------------------------------------------------------------------
# 404 body signature predicate
# ---------------------------------------------------------------------------


def test_is_confcloud_77618_response_matches_canonical_body() -> None:
    response = _make_response(404, body_text=_CONFCLOUD_77618_BODY)
    assert _is_confcloud_77618_response(response) is True


def test_is_confcloud_77618_response_matches_outdated_sibling() -> None:
    response = _make_response(404, body_text=_CONFCLOUD_76424_BODY)
    assert _is_confcloud_77618_response(response) is True


def test_is_confcloud_77618_response_rejects_unrelated_404() -> None:
    response = _make_response(404, body_text='{"message": "Not found"}')
    assert _is_confcloud_77618_response(response) is False


def test_is_confcloud_77618_response_rejects_non_404() -> None:
    response = _make_response(500, body_text="No content with id <ContentId{id=1}>")
    assert _is_confcloud_77618_response(response) is False


# ---------------------------------------------------------------------------
# _paginate_url: raises Confcloud77618Error on the offending 404
# ---------------------------------------------------------------------------


def test_paginate_url_raises_confcloud_77618_on_signature_match(
    cloud_client: OnyxConfluence,
) -> None:
    """77618 404 + ancestor-restrictions expand -> typed exception."""

    def get_side_effect(
        path: str,  # noqa: ARG001
        params: dict[str, Any] | None = None,  # noqa: ARG001
        advanced_mode: bool = False,  # noqa: ARG001
    ) -> requests.Response:
        return _make_response(404, body_text=_CONFCLOUD_77618_BODY)

    cloud_client._confluence.get.side_effect = (  # ty: ignore[unresolved-attribute]
        get_side_effect
    )

    with pytest.raises(Confcloud77618Error):
        list(
            cloud_client.paginated_cql_retrieval(
                cql="type=page",
                expand=(
                    "ancestors.restrictions.read.restrictions.user,"
                    "ancestors.restrictions.read.restrictions.group"
                ),
                limit=50,
            )
        )


def test_paginate_url_propagates_unrelated_404(
    cloud_client: OnyxConfluence,
) -> None:
    """Body-signature gate: unrelated 404s propagate as HTTPError so
    real auth/scope errors don't disguise as 77618 fallbacks."""

    def get_side_effect(
        path: str,  # noqa: ARG001
        params: dict[str, Any] | None = None,  # noqa: ARG001
        advanced_mode: bool = False,  # noqa: ARG001
    ) -> requests.Response:
        return _make_response(404, body_text='{"message": "Some other 404"}')

    cloud_client._confluence.get.side_effect = (  # ty: ignore[unresolved-attribute]
        get_side_effect
    )

    with pytest.raises(HTTPError):
        list(
            cloud_client.paginated_cql_retrieval(
                cql="type=page",
                expand="ancestors.restrictions.read.restrictions.user",
                limit=50,
            )
        )


def test_paginate_url_does_not_raise_77618_without_ancestor_expand(
    cloud_client: OnyxConfluence,
) -> None:
    """URL gate: 77618 only fires when the request URL carried the
    ancestor-restrictions expand."""

    def get_side_effect(
        path: str,  # noqa: ARG001
        params: dict[str, Any] | None = None,  # noqa: ARG001
        advanced_mode: bool = False,  # noqa: ARG001
    ) -> requests.Response:
        return _make_response(404, body_text=_CONFCLOUD_77618_BODY)

    cloud_client._confluence.get.side_effect = (  # ty: ignore[unresolved-attribute]
        get_side_effect
    )

    with pytest.raises(HTTPError) as exc_info:
        list(
            cloud_client.paginated_cql_retrieval(
                cql="type=page",
                expand="space,restrictions.read.restrictions.user",
                limit=50,
            )
        )
    assert not isinstance(exc_info.value, Confcloud77618Error)


# ---------------------------------------------------------------------------
# OnyxConfluence.fetch_content_read_restrictions (byOperation endpoint)
# ---------------------------------------------------------------------------


def test_fetch_content_read_restrictions_hits_byoperation_endpoint(
    cloud_client: OnyxConfluence,
) -> None:
    """Dedicated `restriction/byOperation` URL, SDK-aligned."""
    captured: dict[str, str] = {}

    def get_side_effect(
        path: str,
        advanced_mode: bool = False,  # noqa: ARG001
    ) -> requests.Response:
        captured["path"] = path
        return _make_response(
            200,
            {
                "read": {
                    "operation": "read",
                    "restrictions": {
                        "user": {"results": [{"email": "u@example.com"}]},
                        "group": {"results": []},
                    },
                },
                "update": {
                    "operation": "update",
                    "restrictions": {
                        "user": {"results": []},
                        "group": {"results": []},
                    },
                },
            },
        )

    cloud_client._confluence.get = mock.Mock(  # ty: ignore[invalid-assignment]
        side_effect=get_side_effect
    )

    result = cloud_client.fetch_content_read_restrictions("999")
    assert result is not None
    assert "/restriction/byOperation" in captured["path"]
    assert result["read"]["restrictions"]["user"]["results"][0]["email"] == (
        "u@example.com"
    )


def test_fetch_content_read_restrictions_returns_none_on_403(
    cloud_client: OnyxConfluence,
) -> None:
    """403 = draft permission reply; silent skip."""
    cloud_client._confluence.get = mock.Mock(  # ty: ignore[invalid-assignment]
        return_value=_make_response(
            403, body_text="confluence.user.view.draft.permission"
        )
    )
    assert cloud_client.fetch_content_read_restrictions("draft-id") is None


def test_fetch_content_read_restrictions_returns_none_on_404(
    cloud_client: OnyxConfluence,
) -> None:
    """404 = ancestor deleted between search and follow-up."""
    cloud_client._confluence.get = mock.Mock(  # ty: ignore[invalid-assignment]
        return_value=_make_response(404, body_text="not found")
    )
    assert cloud_client.fetch_content_read_restrictions("missing-id") is None


def test_fetch_content_read_restrictions_raises_on_500(
    cloud_client: OnyxConfluence,
) -> None:
    """5xx must propagate; can't silently mask as "no restriction"."""
    cloud_client._confluence.get = mock.Mock(  # ty: ignore[invalid-assignment]
        return_value=_make_response(500, body_text="boom")
    )
    with pytest.raises(HTTPError):
        cloud_client.fetch_content_read_restrictions("any-id")


# ---------------------------------------------------------------------------
# retrieve_all_slim_docs_perm_sync: try-then-retry on Confcloud77618Error
# ---------------------------------------------------------------------------


@pytest.fixture
def confluence_connector() -> ConfluenceConnector:
    return ConfluenceConnector(
        wiki_base="https://fake-cloud.atlassian.net/wiki",
        is_cloud=True,
    )


def test_perm_sync_retries_in_per_page_mode_on_77618(
    confluence_connector: ConfluenceConnector,
) -> None:
    """On 77618 mid-stream, restart with expand_per_page=True. Pre-raise
    yields are re-yielded; idempotent DB writes make this safe."""
    call_kwargs: list[dict[str, Any]] = []

    def fake_inner(**kwargs: Any) -> Iterator[list[Any]]:
        call_kwargs.append(kwargs)
        if not kwargs["expand_per_page"]:
            yield ["doc-from-attempt-1"]
            raise Confcloud77618Error(url="fake", body=_CONFCLOUD_77618_BODY)
        yield ["doc-from-attempt-2-a"]
        yield ["doc-from-attempt-2-b"]

    with mock.patch.object(
        confluence_connector,
        "_retrieve_all_slim_docs",
        side_effect=fake_inner,
    ):
        out = list(confluence_connector.retrieve_all_slim_docs_perm_sync())

    assert out == [
        ["doc-from-attempt-1"],
        ["doc-from-attempt-2-a"],
        ["doc-from-attempt-2-b"],
    ]
    assert len(call_kwargs) == 2
    assert call_kwargs[0]["expand_per_page"] is False
    assert call_kwargs[1]["expand_per_page"] is True
    assert call_kwargs[0]["include_permissions"] is True
    assert call_kwargs[1]["include_permissions"] is True


def test_perm_sync_no_retry_when_first_attempt_succeeds(
    confluence_connector: ConfluenceConnector,
) -> None:
    """Unaffected runs never enter the per-page branch."""
    call_kwargs: list[dict[str, Any]] = []

    def fake_inner(**kwargs: Any) -> Iterator[list[Any]]:
        call_kwargs.append(kwargs)
        yield ["doc"]

    with mock.patch.object(
        confluence_connector,
        "_retrieve_all_slim_docs",
        side_effect=fake_inner,
    ):
        out = list(confluence_connector.retrieve_all_slim_docs_perm_sync())

    assert out == [["doc"]]
    assert len(call_kwargs) == 1
    assert call_kwargs[0]["expand_per_page"] is False


def test_pruning_expand_skips_restrictions_but_keeps_hierarchy(
    confluence_connector: ConfluenceConnector,
) -> None:
    """Pruning must drop the `restrictions.read.restrictions.*` expand
    (the 77618 trigger) but keep `space` and `ancestors` so the
    hierarchy graph isn't flattened."""
    captured_expands: list[str | None] = []

    def fake_paginate(**kwargs: Any) -> Iterator[Any]:
        captured_expands.append(kwargs.get("expand"))
        return iter([])

    fake_client = mock.Mock(spec=OnyxConfluence)
    fake_client.cql_paginate_all_expansions.side_effect = fake_paginate

    with mock.patch.object(
        ConfluenceConnector,
        "confluence_client",
        new_callable=mock.PropertyMock,
        return_value=fake_client,
    ):
        with mock.patch.object(
            confluence_connector,
            "_yield_space_hierarchy_nodes",
            return_value=iter([]),
        ):
            list(confluence_connector.retrieve_all_slim_docs())

    assert captured_expands, "expected at least one CQL paginated call"
    for expand in captured_expands:
        assert expand is not None
        fields = set(expand.split(","))
        assert "space" in fields
        assert "ancestors" in fields
        assert not any(f.startswith("restrictions.read.restrictions.") for f in fields)
        assert not any(
            f.startswith("ancestors.restrictions.read.restrictions.") for f in fields
        )


# ---------------------------------------------------------------------------
# EE: get_page_restrictions_with_per_ancestor_fetch
# ---------------------------------------------------------------------------


def _restriction_dict(user_emails: list[str]) -> dict[str, Any]:
    return {
        "read": {
            "restrictions": {
                "user": {"results": [{"email": e} for e in user_emails]},
                "group": {"results": []},
            }
        }
    }


def test_per_ancestor_fetch_short_circuits_on_page_level_restriction() -> None:
    """Page-level restriction wins outright -- never fetch ancestors."""
    client = mock.Mock(spec=OnyxConfluence)
    cache: dict[str, dict[str, Any] | None] = {}

    result = get_page_restrictions_with_per_ancestor_fetch(
        confluence_client=client,
        page_id="doc/1",
        page_restrictions=_restriction_dict(["page-restricted@example.com"]),
        ancestors=[{"id": "anc-1"}, {"id": "anc-2"}],
        ancestor_restrictions_cache=cache,
    )
    assert result is not None
    assert result.external_user_emails == {"page-restricted@example.com"}
    client.fetch_content_read_restrictions.assert_not_called()
    assert cache == {}


def test_per_ancestor_fetch_walks_ancestors_immediate_parent_first() -> None:
    """Ancestors arrive root-first; closest restricted ancestor wins."""
    client = mock.Mock(spec=OnyxConfluence)
    fetch_results = {
        "root": _restriction_dict(["root@example.com"]),
        "parent": _restriction_dict(["parent@example.com"]),
    }
    client.fetch_content_read_restrictions.side_effect = lambda cid: fetch_results.get(
        cid, {}
    )

    cache: dict[str, dict[str, Any] | None] = {}
    result = get_page_restrictions_with_per_ancestor_fetch(
        confluence_client=client,
        page_id="doc/leaf",
        page_restrictions={},
        ancestors=[{"id": "root"}, {"id": "parent"}],
        ancestor_restrictions_cache=cache,
    )
    assert result is not None
    assert result.external_user_emails == {"parent@example.com"}


def test_per_ancestor_fetch_skips_drafts_and_continues_up() -> None:
    """Unreadable ancestor doesn't terminate the walk; closest visible
    restriction wins."""
    client = mock.Mock(spec=OnyxConfluence)
    fetch_results: dict[str, dict[str, Any] | None] = {
        "grandparent": _restriction_dict(["gp@example.com"]),
        "parent-draft": None,
    }
    client.fetch_content_read_restrictions.side_effect = lambda cid: fetch_results[cid]

    cache: dict[str, dict[str, Any] | None] = {}
    result = get_page_restrictions_with_per_ancestor_fetch(
        confluence_client=client,
        page_id="doc/leaf",
        page_restrictions={},
        ancestors=[{"id": "grandparent"}, {"id": "parent-draft"}],
        ancestor_restrictions_cache=cache,
    )
    assert result is not None
    assert result.external_user_emails == {"gp@example.com"}


def test_per_ancestor_fetch_returns_none_when_no_restrictions_anywhere() -> None:
    """All ancestors unrestricted -> caller falls back to space-level."""
    client = mock.Mock(spec=OnyxConfluence)
    client.fetch_content_read_restrictions.return_value = {}

    result = get_page_restrictions_with_per_ancestor_fetch(
        confluence_client=client,
        page_id="doc/leaf",
        page_restrictions={},
        ancestors=[{"id": "anc-1"}, {"id": "anc-2"}],
        ancestor_restrictions_cache={},
    )
    assert result is None


def test_per_ancestor_fetch_caches_shared_ancestors_across_calls() -> None:
    """Cache collapses shared ancestors so a tainted batch doesn't
    multiply API calls per sibling."""
    client = mock.Mock(spec=OnyxConfluence)
    client.fetch_content_read_restrictions.return_value = {}
    cache: dict[str, dict[str, Any] | None] = {}

    shared_ancestors = [{"id": "shared-1"}, {"id": "shared-2"}]

    for page_num in range(5):
        get_page_restrictions_with_per_ancestor_fetch(
            confluence_client=client,
            page_id=f"doc/{page_num}",
            page_restrictions={},
            ancestors=shared_ancestors,
            ancestor_restrictions_cache=cache,
        )

    assert client.fetch_content_read_restrictions.call_count == 2


def test_per_ancestor_fetch_caches_none_for_drafts() -> None:
    """None results are cached -- no re-fetch for sibling pages."""
    client = mock.Mock(spec=OnyxConfluence)
    client.fetch_content_read_restrictions.return_value = None
    cache: dict[str, dict[str, Any] | None] = {}

    shared_ancestors = [{"id": "draft-anc"}]

    for page_num in range(3):
        get_page_restrictions_with_per_ancestor_fetch(
            confluence_client=client,
            page_id=f"doc/{page_num}",
            page_restrictions={},
            ancestors=shared_ancestors,
            ancestor_restrictions_cache=cache,
        )

    assert client.fetch_content_read_restrictions.call_count == 1
    assert cache == {"draft-anc": None}


# ---------------------------------------------------------------------------
# Shim resolution: `fetch_versioned_implementation` reaches the EE function
# ---------------------------------------------------------------------------


def test_per_ancestor_shim_resolves_to_ee_implementation(
    enable_ee: None,  # noqa: ARG001 -- fixture sets EE mode for this test
) -> None:
    """End-to-end through the connector-side shim: with EE on, the shim's
    `fetch_versioned_implementation` lookup must reach the EE function and
    actually run it. Catches drift between the shim's module/attr strings
    and the EE module path."""
    client = mock.Mock(spec=OnyxConfluence)

    result = get_page_restrictions_with_per_ancestor_fetch_shim(
        confluence_client=client,
        page_id="doc/1",
        page_restrictions=_restriction_dict(["page-restricted@example.com"]),
        ancestors=[],
        ancestor_restrictions_cache={},
    )

    assert result is not None
    assert result.external_user_emails == {"page-restricted@example.com"}
    client.fetch_content_read_restrictions.assert_not_called()
