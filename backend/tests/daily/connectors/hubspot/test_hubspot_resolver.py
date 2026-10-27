"""Tests for HubSpotConnector.reindex against the real HubSpot test portal."""

import pytest

from onyx.connectors.hubspot.config import HUBSPOT_OBJECT_SPECS, HubSpotObjectType
from onyx.connectors.hubspot.connector import HubSpotConnector, hubspot_document_id
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
)
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.HUBSPOT_ACCESS_TOKEN)

# Records listed per object type. One listing call each keeps the test fast.
_IDS_PER_TYPE = 3


def _make_connector(
    access_token: str, object_types: list[str] | None = None
) -> HubSpotConnector:
    connector = HubSpotConnector(object_types=object_types)
    connector.load_credentials({"hubspot_access_token": access_token})
    return connector


@pytest.fixture
def access_token(test_secrets: dict[TestSecret, str]) -> str:
    return test_secrets[TestSecret.HUBSPOT_ACCESS_TOKEN]


@pytest.fixture
def hubspot_connector(access_token: str) -> HubSpotConnector:
    return _make_connector(access_token)


@pytest.fixture
def doc_ids_by_type(
    hubspot_connector: HubSpotConnector,
) -> dict[HubSpotObjectType, list[str]]:
    """A few real document ids per object type the portal has records of."""
    doc_ids: dict[HubSpotObjectType, list[str]] = {}
    for object_type in HubSpotObjectType:
        page = hubspot_connector.ops.list_records(
            variant=object_type, properties=["hs_object_id"], limit=_IDS_PER_TYPE
        )
        if page.items:
            doc_ids[object_type] = [
                hubspot_document_id(object_type, record.id) for record in page.items
            ]
    assert doc_ids, "The HubSpot test portal must hold at least one record"
    return doc_ids


def _build_failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id),
            failure_message="Synthetic failure for %s" % doc_id,
        )
        for doc_id in doc_ids
    ]


def _split(
    results: list[Document | ConnectorFailure | HierarchyNode],
) -> tuple[list[Document], list[ConnectorFailure]]:
    """HubSpot has no hierarchy, so only documents and failures come back."""
    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]
    assert len(docs) + len(failures) == len(results)
    return docs, failures


def _failed_ids(failures: list[ConnectorFailure]) -> set[str]:
    ids: set[str] = set()
    for failure in failures:
        assert failure.failed_document is not None
        ids.add(failure.failed_document.document_id)
    return ids


def test_reindex_single_record(
    hubspot_connector: HubSpotConnector,
    doc_ids_by_type: dict[HubSpotObjectType, list[str]],
) -> None:
    target = next(iter(doc_ids_by_type.values()))[0]

    docs, failures = _split(list(hubspot_connector.reindex(_build_failures([target]))))

    assert failures == []
    assert len(docs) == 1
    assert docs[0].id == target
    assert docs[0].sections[0].text is not None
    assert docs[0].external_access is None


def test_reindex_records_of_every_type(
    hubspot_connector: HubSpotConnector,
    doc_ids_by_type: dict[HubSpotObjectType, list[str]],
) -> None:
    targets = [doc_id for ids in doc_ids_by_type.values() for doc_id in ids]

    docs, failures = _split(list(hubspot_connector.reindex(_build_failures(targets))))

    assert failures == []
    assert {d.id for d in docs} == set(targets)
    assert {d.metadata["object_type"] for d in docs} == {
        HUBSPOT_OBJECT_SPECS[object_type].document_noun
        for object_type in doc_ids_by_type
    }


def test_reindex_unknown_record_yields_failure(
    hubspot_connector: HubSpotConnector,
    doc_ids_by_type: dict[HubSpotObjectType, list[str]],
) -> None:
    real = next(iter(doc_ids_by_type.values()))[0]
    bogus = hubspot_document_id(HubSpotObjectType.COMPANIES, "999999999999")

    docs, failures = _split(
        list(hubspot_connector.reindex(_build_failures([real, bogus])))
    )

    assert [d.id for d in docs] == [real]
    assert _failed_ids(failures) == {bogus}


def test_reindex_unparseable_id_yields_failure(
    hubspot_connector: HubSpotConnector,
) -> None:
    weird = ["hubspot_widget_123", "hubspot_company_abc", "not-a-hubspot-id"]

    docs, failures = _split(list(hubspot_connector.reindex(_build_failures(weird))))

    assert docs == []
    assert _failed_ids(failures) == set(weird)


def test_reindex_out_of_scope_type_yields_failure(
    access_token: str,
    doc_ids_by_type: dict[HubSpotObjectType, list[str]],
) -> None:
    in_scope_type, in_scope_ids = next(iter(doc_ids_by_type.items()))
    out_of_scope = hubspot_document_id(
        next(t for t in HubSpotObjectType if t != in_scope_type), "1"
    )
    connector = _make_connector(access_token, object_types=[in_scope_type.value])

    docs, failures = _split(
        list(connector.reindex(_build_failures([in_scope_ids[0], out_of_scope])))
    )

    assert [d.id for d in docs] == [in_scope_ids[0]]
    assert _failed_ids(failures) == {out_of_scope}


def test_reindex_empty_errors(hubspot_connector: HubSpotConnector) -> None:
    assert list(hubspot_connector.reindex([])) == []


def test_reindex_entity_failures_are_skipped(
    hubspot_connector: HubSpotConnector,
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="some_stage"),
        failure_message="retrieval failure",
    )

    assert list(hubspot_connector.reindex([entity])) == []


def test_reindex_with_permissions_sets_external_access(
    hubspot_connector: HubSpotConnector,
    doc_ids_by_type: dict[HubSpotObjectType, list[str]],
) -> None:
    targets = [ids[0] for ids in doc_ids_by_type.values()]

    docs, failures = _split(
        list(
            hubspot_connector.reindex(
                _build_failures(targets), include_permissions=True
            )
        )
    )

    assert failures == []
    assert {d.id for d in docs} == set(targets)
    for doc in docs:
        assert doc.external_access is not None
        assert doc.external_access.is_public is False
        assert doc.external_access.external_user_emails
        assert doc.external_access.external_user_group_ids == set()
