from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from onyx.connectors.jira_service_management.connector import (
    DOCUMENT_ID_PREFIX as JSM_DOCUMENT_ID_PREFIX,
)
from onyx.tools.tool_implementations.open_url import open_url_tool
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    IndexedDocumentRequest,
    _pick_readable_document_ids,
    _resolve_urls_to_document_ids,
)
from onyx.tools.tool_implementations.open_url.url_normalization import (
    normalize_url_candidates,
)

_URL = "https://example.atlassian.net/browse/PROJ-123"


def _patch_existing(
    monkeypatch: pytest.MonkeyPatch, existing: Callable[[list[str]], set[str]]
) -> None:
    monkeypatch.setattr(
        open_url_tool,
        "filter_existing_document_ids",
        lambda _session, ids: existing(ids),
    )


def test_resolve_requests_every_existing_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = normalize_url_candidates(_URL)
    assert len(candidates) == 2
    _patch_existing(monkeypatch, lambda _ids: set(candidates))

    matches, unresolved = _resolve_urls_to_document_ids([_URL], MagicMock())

    assert unresolved == []
    assert [m.document_id for m in matches] == candidates
    assert {m.original_url for m in matches} == {_URL}


def test_resolve_only_jsm_candidate_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    jsm_id = next(
        c
        for c in normalize_url_candidates(_URL)
        if c.startswith(JSM_DOCUMENT_ID_PREFIX)
    )
    _patch_existing(monkeypatch, lambda _ids: {jsm_id})

    matches, unresolved = _resolve_urls_to_document_ids([_URL], MagicMock())

    assert unresolved == []
    assert [m.document_id for m in matches] == [jsm_id]


def test_resolve_no_candidate_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_existing(monkeypatch, lambda _ids: set())

    matches, unresolved = _resolve_urls_to_document_ids([_URL], MagicMock())

    assert matches == []
    assert unresolved == [_URL]


def _requests(url: str, *ids: str) -> list[IndexedDocumentRequest]:
    return [IndexedDocumentRequest(document_id=i, original_url=url) for i in ids]


def test_pick_prefers_first_readable() -> None:
    reqs = _requests(_URL, "plain", "jsm")
    assert _pick_readable_document_ids(reqs, {"plain", "jsm"}) == {_URL: "plain"}


def test_pick_falls_through_to_readable_alternate() -> None:
    reqs = _requests(_URL, "plain", "jsm")
    assert _pick_readable_document_ids(reqs, {"jsm"}) == {_URL: "jsm"}


def test_pick_none_readable_uses_first() -> None:
    reqs = _requests(_URL, "plain", "jsm")
    assert _pick_readable_document_ids(reqs, set()) == {_URL: "plain"}


def test_pick_handles_urls_independently() -> None:
    other = "https://example.com/other"
    reqs = _requests(_URL, "plain", "jsm") + _requests(other, "a", "b")
    assert _pick_readable_document_ids(reqs, {"jsm", "a"}) == {
        _URL: "jsm",
        other: "a",
    }
