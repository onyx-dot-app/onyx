"""Unit tests for SalesforceConnector.reindex with a faked SOQL layer.

The fake replaces only describe / describe_type / safe_query, so the real
record, child and document-building helpers run."""

import re
from typing import Any

import pytest
from simple_salesforce.exceptions import (
    SalesforceAuthenticationFailed,
    SalesforceMalformedRequest,
)

from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
)
from onyx.connectors.salesforce.connector import SalesforceConnector
from onyx.connectors.salesforce.doc_conversion import ID_PREFIX
from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce

ACCOUNT_ID = "001000000000001AAA"
ACCOUNT_ID_15 = "001000000000004"
MISSING_ACCOUNT_ID = "001000000000002AAA"
BROKEN_ACCOUNT_ID = "001000000000003AAA"
CONTACT_ID = "003000000000001AAA"
USER_ID = "005000000000001AAA"
UNKNOWN_PREFIX_ID = "zzz000000000001AAA"

_WHERE_ID = re.compile(r"WHERE Id = '([A-Za-z0-9]+)'")


def _field(name: str, field_type: str = "string") -> dict[str, Any]:
    return {"name": name, "type": field_type, "sortable": True}


_DESCRIBES: dict[str, dict[str, Any]] = {
    "Account": {
        "queryable": True,
        "fields": [
            _field("Id", "id"),
            _field("Name"),
            _field("LastModifiedDate", "datetime"),
            _field("LastModifiedById", "reference"),
        ],
        "childRelationships": [
            {
                "childSObject": "Contact",
                "relationshipName": "Contacts",
                "field": "AccountId",
            }
        ],
    },
    "Contact": {
        "queryable": True,
        "fields": [
            _field("Id", "id"),
            _field("LastName"),
            _field("LastModifiedDate", "datetime"),
        ],
        "childRelationships": [],
    },
    "User": {
        "queryable": True,
        "fields": [
            _field("Id", "id"),
            _field("FirstName"),
            _field("LastName"),
            _field("Email"),
        ],
        "childRelationships": [],
    },
}


class _FakeSalesforce(OnyxSalesforce):
    def __init__(self, fail_auth: bool = False) -> None:
        # skip the login in Salesforce.__init__
        self.sf_instance = "test.my.salesforce.com"
        self.fail_auth = fail_auth
        self.queries: list[str] = []

    def describe(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "sobjects": [
                {"keyPrefix": "001", "name": "Account"},
                {"keyPrefix": "003", "name": "Contact"},
                {"keyPrefix": "005", "name": "User"},
            ]
        }

    def describe_type(self, name: str) -> Any:
        return _DESCRIBES[name]

    def safe_query(self, query: str, **_kwargs: Any) -> dict[str, Any]:
        self.queries.append(query)
        if self.fail_auth:
            raise SalesforceAuthenticationFailed("INVALID_LOGIN", "bad creds")
        match = _WHERE_ID.search(query)
        if match is None:
            raise AssertionError(f"unexpected query {query}")
        record_id = match.group(1)
        if record_id == BROKEN_ACCOUNT_ID:
            raise SalesforceMalformedRequest("url", 400, "query", b"bad query")
        if record_id == USER_ID:
            return {
                "records": [
                    {
                        "Id": USER_ID,
                        "FirstName": "Ada",
                        "LastName": "Lovelace",
                        "Email": "ada@example.com",
                    }
                ]
            }
        if record_id not in (ACCOUNT_ID, ACCOUNT_ID_15):
            return {"records": []}
        if "FROM Contacts" in query:
            return {
                "records": [
                    {
                        "attributes": {"type": "Account"},
                        "Contacts": {
                            "records": [
                                {
                                    "Id": CONTACT_ID,
                                    "LastName": "Doe",
                                    "LastModifiedDate": "2026-01-01T00:00:00.000+0000",
                                }
                            ]
                        },
                    }
                ]
            }
        return {
            "records": [
                {
                    "attributes": {"type": "Account"},
                    "Id": record_id,
                    "Name": "Acme",
                    "LastModifiedDate": "2026-01-02T00:00:00.000+0000",
                    "LastModifiedById": USER_ID,
                }
            ]
        }


def _connector(fake: _FakeSalesforce) -> SalesforceConnector:
    connector = SalesforceConnector(requested_objects=["Account"])
    connector._sf_client = fake
    return connector


def _failures(document_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=document_id),
            failure_message="synthetic",
        )
        for document_id in document_ids
    ]


def _failed_ids(results: list[Any]) -> set[str]:
    return {
        r.failed_document.document_id
        for r in results
        if isinstance(r, ConnectorFailure) and r.failed_document is not None
    }


def test_reindex_rebuilds_parent_with_children() -> None:
    target = f"{ID_PREFIX}{ACCOUNT_ID}"
    results = list(_connector(_FakeSalesforce()).reindex(_failures([target])))

    assert len(results) == 1
    doc = results[0]
    assert isinstance(doc, Document)
    assert doc.id == target
    assert doc.semantic_identifier == "Acme"
    assert doc.metadata["object_type"] == "Account"
    assert doc.external_access is None
    links = [section.link for section in doc.sections]
    assert links == [
        f"https://test.my.salesforce.com/{ACCOUNT_ID}",
        f"https://test.my.salesforce.com/{CONTACT_ID}",
    ]
    assert doc.primary_owners is not None
    assert doc.primary_owners[0].email == "ada@example.com"


def test_reindex_keeps_input_id_format() -> None:
    target = f"{ID_PREFIX}{ACCOUNT_ID_15}"
    results = list(_connector(_FakeSalesforce()).reindex(_failures([target])))

    assert [r.id for r in results if isinstance(r, Document)] == [target]


def test_reindex_mixed_batch() -> None:
    good = f"{ID_PREFIX}{ACCOUNT_ID}"
    missing = f"{ID_PREFIX}{MISSING_ACCOUNT_ID}"
    broken = f"{ID_PREFIX}{BROKEN_ACCOUNT_ID}"
    out_of_scope = f"{ID_PREFIX}{CONTACT_ID}"
    unknown_prefix = f"{ID_PREFIX}{UNKNOWN_PREFIX_ID}"
    unparseable = "https://example.com/not-salesforce"
    bad_length = f"{ID_PREFIX}001abc"
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="Account"),
        failure_message="entity",
    )

    results = list(
        _connector(_FakeSalesforce()).reindex(
            _failures(
                [
                    good,
                    missing,
                    broken,
                    out_of_scope,
                    unknown_prefix,
                    unparseable,
                    bad_length,
                ]
            )
            + [entity]
        )
    )

    assert [r.id for r in results if isinstance(r, Document)] == [good]
    assert _failed_ids(results) == {
        missing,
        broken,
        out_of_scope,
        unknown_prefix,
        unparseable,
        bad_length,
    }
    assert len(results) == 7


def test_reindex_raises_on_credential_error() -> None:
    connector = _connector(_FakeSalesforce(fail_auth=True))
    with pytest.raises(SalesforceAuthenticationFailed):
        list(connector.reindex(_failures([f"{ID_PREFIX}{ACCOUNT_ID}"])))


def test_reindex_no_document_targets_makes_no_calls() -> None:
    fake = _FakeSalesforce()
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="Account"),
        failure_message="entity",
    )

    assert list(_connector(fake).reindex([])) == []
    assert list(_connector(fake).reindex([entity])) == []
    assert fake.queries == []
