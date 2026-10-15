"""Tests for SalesforceConnector.reindex against the real Salesforce test org.

Doc ids come from small SOQL listings, not a crawl: the full crawl bulk
downloads the whole org and is too slow for this test."""

import os

import pytest

from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
)
from onyx.connectors.salesforce.connector import SalesforceConnector
from onyx.connectors.salesforce.doc_conversion import ID_PREFIX
from onyx.connectors.salesforce.utils import ACCOUNT_OBJECT_TYPE, USER_OBJECT_TYPE
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.SF_PASSWORD,
    TestSecret.SF_SECURITY_TOKEN,
)

_PARENT_TYPES = [ACCOUNT_OBJECT_TYPE, "Contact", "Opportunity"]


@pytest.fixture(scope="module")
def salesforce_connector(
    test_secrets: dict[TestSecret, str],
) -> SalesforceConnector:
    connector = SalesforceConnector(requested_objects=_PARENT_TYPES)
    connector.load_credentials(
        {
            "sf_username": os.environ["SF_USERNAME"],
            "sf_password": test_secrets[TestSecret.SF_PASSWORD],
            "sf_security_token": test_secrets[TestSecret.SF_SECURITY_TOKEN],
        }
    )
    return connector


def _list_doc_ids(
    connector: SalesforceConnector, object_type: str, limit: int
) -> list[str]:
    result = connector.sf_client.safe_query(
        f"SELECT Id FROM {object_type} ORDER BY LastModifiedDate DESC LIMIT {limit}"  # noqa: S608
    )
    return [f"{ID_PREFIX}{record['Id']}" for record in result["records"]]


def _build_failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id),
            failure_message="Synthetic failure for %s" % doc_id,
        )
        for doc_id in doc_ids
    ]


def _split(
    results: list[object],
) -> tuple[list[Document], list[ConnectorFailure]]:
    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]
    return docs, failures


def test_reindex_single_record(salesforce_connector: SalesforceConnector) -> None:
    doc_ids = _list_doc_ids(salesforce_connector, ACCOUNT_OBJECT_TYPE, 1)
    assert doc_ids, "Test org must contain at least one Account"
    target = doc_ids[0]

    docs, failures = _split(
        list(salesforce_connector.reindex(_build_failures([target])))
    )

    assert failures == []
    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == target
    assert doc.metadata["object_type"] == ACCOUNT_OBJECT_TYPE
    assert doc.sections
    assert doc.external_access is None


def test_reindex_multiple_records_of_each_type(
    salesforce_connector: SalesforceConnector,
) -> None:
    doc_ids: list[str] = []
    for object_type in _PARENT_TYPES:
        type_ids = _list_doc_ids(salesforce_connector, object_type, 2)
        assert type_ids, "Test org must contain at least one %s" % object_type
        doc_ids.extend(type_ids)

    docs, failures = _split(
        list(salesforce_connector.reindex(_build_failures(doc_ids)))
    )

    assert failures == []
    assert {d.id for d in docs} == set(doc_ids)
    assert {d.metadata["object_type"] for d in docs} == set(_PARENT_TYPES)


def test_reindex_include_permissions_leaves_access_unset(
    salesforce_connector: SalesforceConnector,
) -> None:
    # Salesforce access is enforced by query-time censoring, not doc sync
    target = _list_doc_ids(salesforce_connector, ACCOUNT_OBJECT_TYPE, 1)[0]

    docs, failures = _split(
        list(
            salesforce_connector.reindex(
                _build_failures([target]), include_permissions=True
            )
        )
    )

    assert failures == []
    assert [d.id for d in docs] == [target]
    assert docs[0].external_access is None


def test_reindex_unknown_record_yields_failure(
    salesforce_connector: SalesforceConnector,
) -> None:
    # well-formed Account id that does not exist
    bogus = f"{ID_PREFIX}001000000000000AAA"

    docs, failures = _split(
        list(salesforce_connector.reindex(_build_failures([bogus])))
    )

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == bogus


def test_reindex_out_of_scope_type_yields_failure(
    salesforce_connector: SalesforceConnector,
) -> None:
    user_ids = _list_doc_ids(salesforce_connector, USER_OBJECT_TYPE, 1)
    assert user_ids

    docs, failures = _split(
        list(salesforce_connector.reindex(_build_failures(user_ids)))
    )

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == user_ids[0]


def test_reindex_unparseable_id_yields_failure(
    salesforce_connector: SalesforceConnector,
) -> None:
    weird = "https://example.my.salesforce.com/lightning/r/Account/view"

    docs, failures = _split(
        list(salesforce_connector.reindex(_build_failures([weird])))
    )

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == weird


def test_reindex_empty_errors(salesforce_connector: SalesforceConnector) -> None:
    assert list(salesforce_connector.reindex([])) == []


def test_reindex_entity_failures_are_skipped(
    salesforce_connector: SalesforceConnector,
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="Account"),
        failure_message="retrieval failure",
    )

    assert list(salesforce_connector.reindex([entity])) == []
