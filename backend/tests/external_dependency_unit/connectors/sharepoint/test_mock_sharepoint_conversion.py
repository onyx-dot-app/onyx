"""The SharePoint conversion from the listing payload against the mock
server: every entry point makes the same documents with the same access, and
conversion makes only the calls it needs."""

import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.load_all import load_all_from_connector
from onyx.connectors.microsoft_utils.request_pacer import GRAPH_LIMITER_API
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
    ResolveTarget,
    SlimDocument,
    SlimDocumentStub,
)
from onyx.connectors.sharepoint import connector as sharepoint_connector
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.listing import (
    DOWNLOAD_URL_MAX_AGE,
    SharepointListedKind,
    SharepointListingPayload,
)
from onyx.connectors.source_api_limiter import (
    RedisSourceApiLimiter,
    build_source_api_limiter,
)
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
    list_stubs,
)


def _targets(stubs: list[SlimDocumentStub]) -> list[ResolveTarget]:
    """The targets as the conversion stage builds them from stored stubs."""
    return [
        ResolveTarget(document_id=stub.id, listing_payload=stub.listing_payload)
        for stub in stubs
    ]


def _convert(
    connector: SharepointConnector,
    stubs: list[SlimDocumentStub],
    include_permissions: bool = False,
) -> dict[str, Document]:
    converted = list(connector.resolve_targets(_targets(stubs), include_permissions))
    failures = [item for item in converted if isinstance(item, ConnectorFailure)]
    assert not failures, failures[0].failure_message
    assert not [item for item in converted if isinstance(item, HierarchyNode)]
    documents = [item for item in converted if isinstance(item, Document)]
    assert len(documents) == len({document.id for document in documents})
    return {document.id: document for document in documents}


def _comparable(document: Document) -> dict[str, Any]:
    return document.model_dump(exclude={"file_id"})


def test_conversion_makes_the_documents_of_the_fetching_path(
    mock_sharepoint: MockSharepoint,
) -> None:
    end = time.time()
    fetched = {
        document.id: document
        for document in load_all_from_connector(
            mock_sharepoint.build_connector(), 0, end
        ).documents
    }
    connector = mock_sharepoint.build_connector()
    listing = list_stubs(connector, end=end)
    mock_sharepoint.reset_stats()

    converted = _convert(connector, listing.stubs)

    assert set(converted) == set(fetched) == mock_sharepoint.document_ids()
    for document_id, document in converted.items():
        assert _comparable(document) == _comparable(fetched[document_id])

    # One download for each file from its fresh listed link, which is no
    # Graph call, one read for each page, and no metadata call, listing call
    # or permission read.
    stats = mock_sharepoint.stats()
    files = mock_sharepoint.supported_file_ids()
    assert stats["item_downloads"] == dict.fromkeys(files, 1)
    assert stats["ops"]["download_url.get"]["count"] == len(files)
    assert stats["ops"]["graph.site.page.get"]["count"] == len(
        mock_sharepoint.page_ids()
    )
    allowed = {"graph.site.page.get", "download_url.get"}
    assert {op for op in stats["ops"] if not op.startswith("login.")} <= allowed, stats[
        "ops"
    ].keys()
    assert stats["unmatched_requests"] == []


def _file_stubs(stubs: list[SlimDocumentStub]) -> list[SlimDocumentStub]:
    return [
        stub
        for stub in stubs
        if stub.listing_payload is not None
        and stub.listing_payload.as_type(SharepointListingPayload).kind
        == SharepointListedKind.DRIVE_ITEM
    ]


def test_an_old_listed_link_downloads_by_item_id(
    mock_sharepoint: MockSharepoint,
) -> None:
    """A link older than DOWNLOAD_URL_MAX_AGE is not tried: conversion
    downloads by Graph /content, as for a stub with no link."""
    connector = mock_sharepoint.build_connector()
    stubs = _file_stubs(list_stubs(connector).stubs)
    for stub in stubs:
        payload = stub.listing_payload
        assert isinstance(payload, SharepointListingPayload)
        assert payload.encrypted_download_url
        assert payload.download_url_listed_at is not None
        payload.download_url_listed_at -= DOWNLOAD_URL_MAX_AGE + timedelta(minutes=1)
    mock_sharepoint.reset_stats()

    converted = _convert(connector, stubs)

    files = mock_sharepoint.supported_file_ids()
    assert set(converted) == files
    stats = mock_sharepoint.stats()
    assert stats["item_downloads"] == dict.fromkeys(files, 1)
    assert stats["ops"]["graph.item.content"]["count"] == len(files)
    # Only the redirects of /content, and none of them refused.
    assert stats["ops"]["download_url.get"]["count"] == len(files)
    assert stats["ops"]["download_url.get"].get("errors", 0) == 0


@pytest.mark.parametrize("refused_status", [401, 403])
def test_a_refused_listed_link_falls_back_to_content(
    own_mock_sharepoint: MockSharepoint, refused_status: int
) -> None:
    """A fresh link that SharePoint refuses (here: it expired early) costs one
    try, then conversion downloads by Graph /content."""
    own_mock_sharepoint.patch_config(
        {
            "faults": {
                "download_url_ttl_seconds": 0,
                "download_url_expired_status": refused_status,
            }
        }
    )
    connector = own_mock_sharepoint.build_connector(include_site_pages=False)
    stubs = list_stubs(connector).stubs
    own_mock_sharepoint.reset_stats()

    converted = _convert(connector, stubs)

    files = own_mock_sharepoint.supported_file_ids()
    assert set(converted) == files
    stats = own_mock_sharepoint.stats()
    assert stats["item_downloads"] == dict.fromkeys(files, 1)
    assert stats["ops"]["graph.item.content"]["count"] == len(files)
    # Each file: one refused listed link, then the redirect of /content.
    assert stats["ops"]["download_url.get"]["errors"] == len(files)
    assert stats["ops"]["download_url.get"]["count"] == 2 * len(files)


_LINK_RETRY_AFTER_SECONDS = 1


@pytest.fixture
def limiter_tenant(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The limiter on, in a tenant of its own, so runs cannot collide."""
    monkeypatch.setattr(source_api_limiter, "ENABLE_SOURCE_API_LIMITER", True)
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
    yield tenant
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    client = get_redis_client(tenant_id=tenant)
    for key in client.scan_iter("*"):
        client.delete(key)


def _with_shared_limiter(
    mock: MockSharepoint,
    connector: SharepointConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> list[float]:
    """Gives the connector the limiter of its app, as the factory does, and
    returns the list of the Retry-After waits that it reports."""
    limiter = build_source_api_limiter(
        DocumentSource.SHAREPOINT,
        credential_id=int(uuid4().int % 1_000_000_000),
        load_credential_json=mock.credentials,
    )
    assert isinstance(limiter, RedisSourceApiLimiter)
    reported: list[float] = []
    report = limiter.report_retry_after

    def record(api: str, seconds: float) -> None:
        if api == GRAPH_LIMITER_API:
            reported.append(seconds)
        report(api, seconds)

    monkeypatch.setattr(limiter, "report_retry_after", record)
    connector.set_source_api_limiter(limiter)
    return reported


@pytest.mark.usefixtures("limiter_tenant")
def test_a_throttled_listed_link_pauses_and_is_tried_again(
    own_mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The download host answers 429 with Retry-After. /content redirects to
    the same host, so conversion does not fall back: the shared limiter gets
    the pause, and the fresh link is tried again."""
    mock = own_mock_sharepoint
    connector = mock.build_connector(include_site_pages=False)
    stubs = list_stubs(connector).stubs
    reported = _with_shared_limiter(mock, connector, monkeypatch)
    mock.patch_config(
        {
            "faults": {
                "download_url_throttled_calls": 2,
                "download_url_retry_after_seconds": _LINK_RETRY_AFTER_SECONDS,
            }
        }
    )
    mock.reset_stats()

    converted = _convert(connector, stubs)

    files = mock.supported_file_ids()
    assert set(converted) == files
    stats = mock.stats()
    assert "graph.item.content" not in stats["ops"]
    assert stats["item_downloads"] == dict.fromkeys(files, 1)
    assert stats["ops"]["download_url.get"]["errors"] == 2
    assert stats["ops"]["download_url.get"]["count"] == len(files) + 2
    assert reported == [_LINK_RETRY_AFTER_SECONDS] * 2


@pytest.mark.usefixtures("limiter_tenant")
def test_a_throttled_redirect_of_content_pauses_the_app(
    own_mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an old link, conversion reads /content, which redirects to the
    download host. A 429 there reaches the shared limiter too, and /content
    is read again."""
    mock = own_mock_sharepoint
    connector = mock.build_connector(include_site_pages=False)
    stubs = _file_stubs(list_stubs(connector).stubs)
    for stub in stubs:
        payload = stub.listing_payload
        assert isinstance(payload, SharepointListingPayload)
        assert payload.download_url_listed_at is not None
        payload.download_url_listed_at -= DOWNLOAD_URL_MAX_AGE + timedelta(minutes=1)
    reported = _with_shared_limiter(mock, connector, monkeypatch)
    mock.patch_config(
        {
            "faults": {
                "download_url_throttled_calls": 1,
                "download_url_retry_after_seconds": _LINK_RETRY_AFTER_SECONDS,
            }
        }
    )
    mock.reset_stats()

    converted = _convert(connector, stubs)

    files = mock.supported_file_ids()
    assert set(converted) == files
    stats = mock.stats()
    assert stats["ops"]["graph.item.content"]["count"] == len(files) + 1
    assert stats["ops"]["download_url.get"]["errors"] == 1
    assert reported == [_LINK_RETRY_AFTER_SECONDS]


@pytest.mark.usefixtures("ee_permission_sync")
def test_every_entry_point_gives_the_same_documents_and_access(
    mock_sharepoint: MockSharepoint,
) -> None:
    """The fetching path, the stub listing with conversion, the slim listing
    and ``reindex`` agree on the documents and on who can read each one."""
    end = time.time()
    expected: dict[str, ExternalAccess] = {}
    for file_id in mock_sharepoint.supported_file_ids():
        effective = mock_sharepoint.describe_file(file_id)["effective_access"]
        expected[file_id] = ExternalAccess(
            external_user_emails=set(effective["user_emails"]),
            external_user_group_ids=set(effective["group_ids"]),
            is_public=effective["is_public"],
        )
    for page_id in mock_sharepoint.page_ids():
        effective = mock_sharepoint.describe_page(page_id)["effective_access"]
        expected[page_id] = ExternalAccess(
            external_user_emails=set(effective["user_emails"]),
            external_user_group_ids=set(effective["group_ids"]),
            is_public=effective["is_public"],
        )

    fetching = load_all_from_connector(
        mock_sharepoint.build_connector(certificate=True),
        0,
        end,
        include_permissions=True,
    )
    fetched = {document.id: document for document in fetching.documents}
    assert {doc_id: doc.external_access for doc_id, doc in fetched.items()} == expected

    connector = mock_sharepoint.build_connector(certificate=True)
    listing = list_stubs(connector, end=end, include_permissions=True)
    converted = _convert(connector, listing.stubs, include_permissions=True)
    assert {
        doc_id: doc.external_access for doc_id, doc in converted.items()
    } == expected
    # The listing yields the same hierarchy nodes with the same access.
    assert {node.raw_node_id: node.external_access for node in listing.nodes} == {
        node.raw_node_id: node.external_access for node in fetching.hierarchy_nodes
    }

    slim = {
        item.id: item.external_access
        for batch in mock_sharepoint.build_connector(
            certificate=True
        ).retrieve_all_slim_docs_perm_sync(0, end)
        for item in batch
        if isinstance(item, SlimDocument)
    }
    assert {doc_id: slim[doc_id] for doc_id in expected} == expected

    reindexed = [
        item
        for item in mock_sharepoint.build_connector(certificate=True).reindex(
            [
                ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=document.id,
                        document_link=document.sections[0].link,
                    ),
                    failure_message="again",
                )
                for document in fetched.values()
            ],
            include_permissions=True,
        )
        if isinstance(item, Document)
    ]
    assert {document.id: document.external_access for document in reindexed} == (
        expected
    )


def test_a_second_run_downloads_only_the_changed_files(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """Docfetching drops a stub whose document is in the index with the same
    modified time and size (``drop_unchanged_stubs``). The stubs of a second
    listing give it what it needs, so only a changed file is downloaded and
    only a changed page is read."""
    connector = own_mock_sharepoint.build_connector()
    indexed = _convert(connector, list_stubs(connector).stubs)
    changed = sorted(own_mock_sharepoint.supported_file_ids())[:2]
    own_mock_sharepoint.touch(changed)
    own_mock_sharepoint.reset_stats()

    connector = own_mock_sharepoint.build_connector()
    second = list_stubs(connector)
    assert {stub.id for stub in second.stubs} == set(indexed)
    to_convert = [
        stub
        for stub in second.stubs
        if (stub.doc_updated_at, stub.size_bytes)
        != (indexed[stub.id].doc_updated_at, indexed[stub.id].source_size_bytes)
    ]
    converted = _convert(connector, to_convert)

    assert set(converted) == set(changed)
    stats = own_mock_sharepoint.stats()
    assert set(stats["item_downloads"]) == set(changed)
    # The listing read no canvas, and no page changed.
    assert stats["ops"]["graph.site.pages.list"]["canvas_expanded"] == 0
    assert "graph.site.page.get" not in stats["ops"]


def test_conversion_runs_in_a_thread_pool(
    mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_sharepoint.patch_config({"latency": {"enabled": True, "content_ms": 150}})
    try:
        connector = mock_sharepoint.build_connector()
        stubs = list_stubs(connector).stubs
        mock_sharepoint.reset_stats()
        monkeypatch.setattr(sharepoint_connector, "SHAREPOINT_CONVERSION_WORKERS", 8)

        _convert(connector, stubs)

        assert 2 <= mock_sharepoint.stats()["max_inflight"] <= 8
    finally:
        mock_sharepoint.patch_config({"latency": {"enabled": False}})


def test_a_target_with_no_payload_goes_through_reindex(
    mock_sharepoint: MockSharepoint,
) -> None:
    file_id = min(mock_sharepoint.supported_file_ids())
    target = ResolveTarget(
        document_id=file_id,
        document_link=mock_sharepoint.describe_file(file_id)["web_url"],
    )

    converted = list(mock_sharepoint.build_connector().resolve_targets([target]))

    assert [item.id for item in converted if isinstance(item, Document)] == [file_id]
    # `reindex` reads the item's metadata to find it. Conversion does not.
    assert mock_sharepoint.op_count("graph.item.get") >= 1


_GROUP_EXPANSION_OPS = (
    "rest.site_group_users",
    "graph.group.members",
    "graph.group.transitive_members",
)


def _group_expansion_reads(mock: MockSharepoint) -> int:
    return sum(mock.op_count(op) for op in _GROUP_EXPANSION_OPS)


@pytest.mark.usefixtures("ee_permission_sync")
def test_a_new_listing_run_reads_the_groups_again(
    mock_sharepoint: MockSharepoint,
) -> None:
    """Conversion shares the group expansions in Redis for one listing run
    only. A later run, which can be for another credential, reads them
    again, as a run did before the conversion stage. Other paths keep them
    in the process."""
    first = mock_sharepoint.build_connector(certificate=True)
    _convert(first, list_stubs(first, include_permissions=True).stubs, True)
    assert _group_expansion_reads(mock_sharepoint) > 0

    second = mock_sharepoint.build_connector(certificate=True)
    listing = list_stubs(second, include_permissions=True)
    mock_sharepoint.reset_stats()
    _convert(second, listing.stubs, include_permissions=True)
    assert _group_expansion_reads(mock_sharepoint) > 0

    mock_sharepoint.reset_stats()
    for _ in mock_sharepoint.build_connector(
        certificate=True
    ).retrieve_all_slim_docs_perm_sync(0, time.time()):
        pass
    assert _group_expansion_reads(mock_sharepoint) > 0
