"""Targeted reindex yields only records the crawl would index: configured
object types, unarchived records, and the exact id that was asked for. It
never yields a document with sections it could not read."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.connector import HubSpotConnector
from onyx.connectors.hubspot.models import (
    HubSpotAssociationIds,
    HubSpotRecord,
)
from onyx.connectors.hubspot.source_operations import (
    HubSpotApiError,
    HubSpotSourceOperations,
)
from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure

MOMENT = datetime(2024, 6, 6, tzinfo=timezone.utc)


def _connector(
    object_types: list[str] | None = None,
) -> tuple[HubSpotConnector, MagicMock]:
    connector = HubSpotConnector(object_types=object_types)
    ops = create_autospec(HubSpotSourceOperations, instance=True)
    connector._ops = ops
    connector._portal_id = "portal"
    return connector, ops


def _record(record_id: str, archived: bool = False) -> HubSpotRecord:
    # Empty inline associations, so only the notes listing is called.
    return HubSpotRecord(
        id=record_id,
        properties={"name": f"Company {record_id}"},
        created_at=MOMENT,
        updated_at=MOMENT,
        archived=archived,
        associations={},
    )


def _failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id),
            failure_message="synthetic",
        )
        for doc_id in doc_ids
    ]


def _failed_ids(results: list[Document | ConnectorFailure]) -> set[str]:
    return {
        r.failed_document.document_id
        for r in results
        if isinstance(r, ConnectorFailure) and r.failed_document is not None
    }


def _run(
    connector: HubSpotConnector, doc_ids: list[str]
) -> list[Document | ConnectorFailure]:
    results = list(connector.reindex(_failures(doc_ids)))
    return [r for r in results if isinstance(r, (Document, ConnectorFailure))]


def test_archived_record_yields_failure() -> None:
    connector, ops = _connector()
    ops.read_records.return_value = [_record("1"), _record("2", archived=True)]
    ops.read_associations.return_value = {}

    results = _run(connector, ["hubspot_company_1", "hubspot_company_2"])

    assert [r.id for r in results if isinstance(r, Document)] == ["hubspot_company_1"]
    assert _failed_ids(results) == {"hubspot_company_2"}
    assert ops.read_records.call_args.kwargs["variant"] == "companies"


def test_merged_record_under_another_id_yields_failure() -> None:
    connector, ops = _connector()
    ops.read_records.return_value = [_record("99")]

    results = _run(connector, ["hubspot_company_1"])

    assert not any(isinstance(r, Document) for r in results)
    assert _failed_ids(results) == {"hubspot_company_1"}


def test_unconfigured_object_type_is_not_read() -> None:
    connector, ops = _connector(object_types=[HubSpotObjectType.COMPANIES.value])

    results = _run(connector, ["hubspot_deal_1"])

    assert _failed_ids(results) == {"hubspot_deal_1"}
    ops.read_records.assert_not_called()


def test_rejected_token_ends_the_run() -> None:
    connector, ops = _connector()
    ops.read_records.side_effect = HubSpotApiError("batch read", 401, {}, "nope")

    with pytest.raises(HubSpotApiError):
        _run(connector, ["hubspot_company_1"])


def test_other_read_error_fails_only_its_targets() -> None:
    connector, ops = _connector()
    ops.read_records.side_effect = HubSpotApiError("batch read", 500, {}, "boom")

    results = _run(connector, ["hubspot_company_1", "hubspot_company_2"])

    assert _failed_ids(results) == {"hubspot_company_1", "hubspot_company_2"}


def test_failed_note_read_fails_the_target() -> None:
    connector, ops = _connector()
    ops.read_records.return_value = [_record("1")]
    ops.read_associations.side_effect = HubSpotApiError("notes", 500, {}, "boom")

    results = _run(connector, ["hubspot_company_1"])

    assert not any(isinstance(r, Document) for r in results)
    assert _failed_ids(results) == {"hubspot_company_1"}


def test_failed_association_record_read_fails_the_target() -> None:
    connector, ops = _connector()
    company = _record("1")
    company.associations = {
        "contacts": HubSpotAssociationIds(ids=["7"], has_more=False)
    }
    # The company reads; the associated contact read fails on both attempts.
    ops.read_records.side_effect = [
        [company],
        HubSpotApiError("contacts batch read", 500, {}, "boom"),
        HubSpotApiError("contacts batch read", 500, {}, "boom"),
    ]

    with patch("onyx.connectors.hubspot.connector.time.sleep"):
        results = _run(connector, ["hubspot_company_1"])

    assert not any(isinstance(r, Document) for r in results)
    assert _failed_ids(results) == {"hubspot_company_1"}


def test_rejected_token_on_a_note_read_ends_the_run() -> None:
    connector, ops = _connector()
    ops.read_records.return_value = [_record("1")]
    ops.read_associations.side_effect = HubSpotApiError("notes", 401, {}, "nope")

    with pytest.raises(HubSpotApiError):
        _run(connector, ["hubspot_company_1"])


def test_failed_portal_id_read_fails_every_target() -> None:
    connector, ops = _connector()
    connector._portal_id = None
    ops.get_portal_id.side_effect = HubSpotApiError("portal info", 500, {}, "boom")

    results = list(
        connector.reindex(
            _failures(["hubspot_company_1", "hubspot_deal_2"]),
            include_permissions=True,
        )
    )

    assert _failed_ids(
        [r for r in results if isinstance(r, (Document, ConnectorFailure))]
    ) == {"hubspot_company_1", "hubspot_deal_2"}
    ops.read_records.assert_not_called()


def test_rejected_token_on_the_portal_id_read_ends_the_run() -> None:
    connector, ops = _connector()
    connector._portal_id = None
    ops.get_portal_id.side_effect = HubSpotApiError("portal info", 401, {}, "nope")

    with pytest.raises(HubSpotApiError):
        _run(connector, ["hubspot_company_1"])
