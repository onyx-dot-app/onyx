"""A 4xx during attachment CQL pagination must not abort the whole index run.

Confluence Data Center intermittently 400s when offset pagination of an
attachment query advances past the first page. The connector keeps the
attachments retrieved before the error, records a ConnectorFailure for the
page, and continues. 401/403 skip the page's attachments entirely; other
statuses still propagate.
"""

from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest
import requests
from requests.exceptions import HTTPError

from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.connector import (
    ConfluenceConnector,
    _extract_page_id_from_url,
)
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure

_PAGE = {
    "id": "111",
    "title": "Big Page",
    "_links": {"webui": "/spaces/X/pages/111/Page"},
    "space": {"key": "X"},
    "history": {"createdDate": "2023-01-01T12:00:00.000+0000"},
}
_PDF_ATTACHMENT = {
    "id": "222",
    "title": "spec.pdf",
    "metadata": {"mediaType": "application/pdf"},
    "_links": {
        "webui": "/spaces/X/pages/111/Page?preview=spec.pdf",
        "download": "/download/attachments/111/spec.pdf",
    },
    "space": {"key": "X"},
    "history": {"createdDate": "2023-01-02T12:00:00.000+0000"},
    "version": {"when": "2023-01-02T12:00:00.000+0000"},
}


def _http_error(status_code: int, message: str = "") -> HTTPError:
    # A real Response: it is falsy for error statuses, which the handler's
    # `is not None` check must tolerate.
    response = requests.Response()
    response.status_code = status_code
    return HTTPError(message, response=response)


def _fetch_with_pagination_error(
    status_code: int, message: str = ""
) -> tuple[list[Any], list[ConnectorFailure]]:
    """Drive _fetch_page_attachments with a client that yields one attachment
    and then fails pagination with the given status code."""
    connector = ConfluenceConnector(
        wiki_base="https://confluence.example.com",
        is_cloud=False,
        include_attachments=True,
    )
    fake_client = mock.Mock(spec=OnyxConfluence)

    def failing_pagination(**_kwargs: Any) -> Iterator[dict[str, Any]]:
        yield _PDF_ATTACHMENT
        raise _http_error(status_code, message)

    fake_client.paginated_cql_retrieval.side_effect = failing_pagination

    with (
        mock.patch.object(
            ConfluenceConnector,
            "confluence_client",
            new_callable=mock.PropertyMock,
            return_value=fake_client,
        ),
        mock.patch.object(
            connector, "_maybe_yield_page_hierarchy_node", return_value=None
        ),
        mock.patch(
            "onyx.connectors.confluence.connector.convert_attachment_to_content",
            return_value=("extracted text", None),
        ),
    ):
        return connector._fetch_page_attachments(_PAGE)


def test_400_keeps_partial_attachments_and_records_failure() -> None:
    docs, failures = _fetch_with_pagination_error(400)

    assert len(docs) == 1
    assert isinstance(docs[0], Document)
    assert docs[0].semantic_identifier == "spec.pdf"

    assert len(failures) == 1
    failure = failures[0]
    assert "400" in failure.failure_message
    assert failure.failed_document is not None
    # document_id must be the page URL so targeted reindex can recover the page id
    assert _extract_page_id_from_url(failure.failed_document.document_id) == "111"
    assert isinstance(failure.exception, HTTPError)


@pytest.mark.parametrize("status_code", [401, 403])
def test_401_403_skips_page_attachments(status_code: int) -> None:
    docs, failures = _fetch_with_pagination_error(status_code)

    assert docs == []
    assert len(failures) == 1
    assert str(status_code) in failures[0].failure_message


def test_other_http_errors_propagate() -> None:
    with pytest.raises(HTTPError):
        _fetch_with_pagination_error(500)


def test_400_date_error_propagates() -> None:
    """Atlassian date errors are 400s but must reach load_from_checkpoint's
    time-offset retry instead of being skipped as a page failure."""
    with pytest.raises(HTTPError):
        _fetch_with_pagination_error(400, "The field 'updated' is invalid")


_PAGE_URL = "https://confluence.example.com/spaces/X/pages/111/Page"


def _run_reindex(attachment_error_code: int | None) -> list[Any]:
    """Run targeted reindex for _PAGE with a client whose attachment pagination
    yields one attachment and then optionally fails."""
    connector = ConfluenceConnector(
        wiki_base="https://confluence.example.com",
        is_cloud=False,
        include_attachments=True,
    )
    fake_client = mock.Mock(spec=OnyxConfluence)

    def paginate(**kwargs: Any) -> Iterator[dict[str, Any]]:
        if str(kwargs.get("cql", "")).startswith("type=page"):
            yield _PAGE
            return
        yield _PDF_ATTACHMENT
        if attachment_error_code is not None:
            raise _http_error(attachment_error_code)

    fake_client.paginated_cql_retrieval.side_effect = paginate

    error = ConnectorFailure(
        failed_document=DocumentFailure(document_id=_PAGE_URL, document_link=_PAGE_URL),
        failure_message="Bad request (400) while paginating attachments",
    )
    with (
        mock.patch.object(
            ConfluenceConnector,
            "confluence_client",
            new_callable=mock.PropertyMock,
            return_value=fake_client,
        ),
        mock.patch.object(
            connector, "_yield_space_hierarchy_nodes", return_value=iter([])
        ),
        mock.patch.object(
            connector, "_yield_ancestor_hierarchy_nodes", return_value=iter([])
        ),
        mock.patch.object(
            connector, "_maybe_yield_page_hierarchy_node", return_value=None
        ),
        mock.patch.object(
            connector,
            "_convert_page_to_document",
            return_value=Document(
                id=_PAGE_URL,
                sections=[],
                source=DocumentSource.CONFLUENCE,
                semantic_identifier="Big Page",
                metadata={},
            ),
        ),
        mock.patch(
            "onyx.connectors.confluence.connector.convert_attachment_to_content",
            return_value=("extracted text", None),
        ),
    ):
        return list(connector.reindex([error]))


def test_reindex_refetches_attachments() -> None:
    outputs = _run_reindex(attachment_error_code=None)

    assert any(
        isinstance(o, Document) and o.semantic_identifier == "spec.pdf" for o in outputs
    )
    assert not any(isinstance(o, ConnectorFailure) for o in outputs)


def _slim_attachments_with(side_effects: list[Any]) -> tuple[list[Any], mock.Mock]:
    """Drive _retrieve_attachments_for_slim_page with a client whose
    cql_paginate_all_expansions produces the given results/exceptions."""
    connector = ConfluenceConnector(
        wiki_base="https://confluence.example.com",
        is_cloud=False,
        include_attachments=True,
    )
    fake_client = mock.Mock(spec=OnyxConfluence)
    fake_client.cql_paginate_all_expansions.side_effect = side_effects

    with mock.patch.object(
        ConfluenceConnector,
        "confluence_client",
        new_callable=mock.PropertyMock,
        return_value=fake_client,
    ):
        results = connector._retrieve_attachments_for_slim_page(
            "111", "space", None, None
        )
    return results, fake_client


def test_slim_attachment_400_retries_then_succeeds() -> None:
    results, fake_client = _slim_attachments_with(
        [_http_error(400), _http_error(400), iter([_PDF_ATTACHMENT])]
    )

    assert results == [_PDF_ATTACHMENT]
    assert fake_client.cql_paginate_all_expansions.call_count == 3


def test_slim_attachment_persistent_400_raises() -> None:
    """The slim path must never keep partial results (pruning deletes anything
    not enumerated) -- a persistent 400 aborts instead of truncating."""
    with pytest.raises(HTTPError):
        _slim_attachments_with([_http_error(400), _http_error(400), _http_error(400)])


@pytest.mark.parametrize(
    "error",
    [
        _http_error(403),
        _http_error(500),
        _http_error(400, "The field 'updated' is invalid"),
    ],
)
def test_slim_attachment_other_errors_raise_immediately(error: HTTPError) -> None:
    with pytest.raises(HTTPError):
        _slim_attachments_with([error])


def test_reindex_rerecords_attachment_failure() -> None:
    """If the 400 recurs during targeted reindex, the failure must be yielded
    again so the error is not silently cleared."""
    outputs = _run_reindex(attachment_error_code=400)

    assert any(
        isinstance(o, Document) and o.semantic_identifier == "spec.pdf" for o in outputs
    )
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert len(failures) == 1
    assert "400" in failures[0].failure_message
    assert failures[0].failed_document is not None
    assert _extract_page_id_from_url(failures[0].failed_document.document_id) == "111"
