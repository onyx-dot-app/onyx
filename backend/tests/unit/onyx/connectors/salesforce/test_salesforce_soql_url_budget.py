import re
from typing import Any
from unittest.mock import patch

import pytest

from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce
from onyx.connectors.salesforce.salesforce_calls import (
    SOQL_FIELD_SEPARATOR,
    SOQL_MAX_SUBQUERIES,
    SOQL_MAX_URL_ENCODED_LENGTH,
    _pack_for_url,
    _url_encoded_length,
    get_child_objects_by_id_queries,
    get_object_by_id_queries,
)
from onyx.connectors.salesforce.utils import (
    CREATED_FIELD,
    ID_FIELD,
    MODIFIED_FIELD,
)

_ACCOUNT_ID = "001bm00000fd9Z3AAI"
_RECORD_QUERY = re.compile(
    r"^SELECT (?P<fields>.+) FROM (?P<type>\w+) WHERE Id = '(?P<id>\w+)'$"
)
_SUBQUERY = re.compile(
    r"\(SELECT (?P<fields>[^()]+) FROM (?P<rel>\w+) (?P<order>ORDER BY [^()]+?) LIMIT 10\)"
)


def _wide_fields(count: int, prefix: str = "Field") -> set[str]:
    # ~30 chars each, like the custom fields of a heavily customized org
    return {f"{prefix}_{i:04d}_Long_Custom_Name__c" for i in range(count)}


def _client() -> OnyxSalesforce:
    # __init__ logs in, and the methods under test only need safe_query
    return OnyxSalesforce.__new__(OnyxSalesforce)


def _fake_record_result(query: str) -> dict[str, Any]:
    match = _RECORD_QUERY.match(query)
    assert match, query
    fields = match["fields"].split(SOQL_FIELD_SEPARATOR)
    record = {"attributes": {"type": match["type"]}}
    record.update({f: f"v:{f}" for f in fields})
    return {"totalSize": 1, "records": [record]}


def _fake_children_result(query: str) -> dict[str, Any]:
    record: dict[str, Any] = {"attributes": {"type": "Account"}}
    for match in _SUBQUERY.finditer(query):
        fields = match["fields"].split(SOQL_FIELD_SEPARATOR)
        assert ID_FIELD in fields, query
        rows = []
        for child_id in ("c1", "c2"):
            row: dict[str, Any] = {f: f"{child_id}:{f}" for f in fields}
            row[ID_FIELD] = child_id
            row["attributes"] = {"type": match["rel"]}
            rows.append(row)
        record[match["rel"]] = {"totalSize": len(rows), "records": rows}
    return {"totalSize": 1, "records": [record]}


class TestPackForUrl:
    def test_small_input_is_one_group(self) -> None:
        assert _pack_for_url(["a", "b", "c"], ", ", 100) == [["a", "b", "c"]]

    def test_groups_fit_budget_and_keep_order(self) -> None:
        items = [f"item{i:03d}" for i in range(50)]
        groups = _pack_for_url(items, ", ", 60)
        assert [item for group in groups for item in group] == items
        assert len(groups) > 1
        for group in groups:
            assert _url_encoded_length(", ".join(group)) <= 60

    def test_max_items(self) -> None:
        groups = _pack_for_url([str(i) for i in range(7)], ", ", 1000, max_items=3)
        assert [len(group) for group in groups] == [3, 3, 1]

    def test_oversized_item_passes_alone(self) -> None:
        assert _pack_for_url(["x" * 50, "y"], ", ", 10) == [["x" * 50], ["y"]]


class TestGetObjectByIdQueries:
    def test_narrow_object_is_one_query(self) -> None:
        queries = get_object_by_id_queries(_ACCOUNT_ID, "Account", {"Name", "Id"})
        assert queries == [f"SELECT Id, Name FROM Account WHERE Id = '{_ACCOUNT_ID}'"]

    def test_wide_object_splits_under_budget(self) -> None:
        fields = _wide_fields(800)
        queries = get_object_by_id_queries(_ACCOUNT_ID, "Account", fields)
        assert len(queries) > 1
        seen: set[str] = set()
        for query in queries:
            assert _url_encoded_length(query) <= SOQL_MAX_URL_ENCODED_LENGTH
            match = _RECORD_QUERY.match(query)
            assert match, query
            assert match["id"] == _ACCOUNT_ID
            seen.update(match["fields"].split(SOQL_FIELD_SEPARATOR))
        assert seen == fields


class TestGetChildObjectsByIdQueries:
    def test_relationship_appears_once_per_query(self) -> None:
        relationships_to_fields = {
            "Opportunities": _wide_fields(600, "Opp") | {ID_FIELD},
            "Contacts": {ID_FIELD, "Email"},
            "Cases": _wide_fields(300, "Case"),
        }
        queries = get_child_objects_by_id_queries(
            _ACCOUNT_ID,
            "Account",
            list(relationships_to_fields),
            relationships_to_fields,
        )
        assert len(queries) > 1
        covered: dict[str, set[str]] = {}
        for query in queries:
            assert _url_encoded_length(query) <= SOQL_MAX_URL_ENCODED_LENGTH
            subqueries = list(_SUBQUERY.finditer(query))
            assert 0 < len(subqueries) <= SOQL_MAX_SUBQUERIES
            relationships = [match["rel"] for match in subqueries]
            assert len(relationships) == len(set(relationships)), query
            for match in subqueries:
                assert match["order"] == f"ORDER BY {ID_FIELD} DESC"
                covered.setdefault(match["rel"], set()).update(
                    match["fields"].split(SOQL_FIELD_SEPARATOR)
                )
        assert covered == {
            relationship: fields | {ID_FIELD}
            for relationship, fields in relationships_to_fields.items()
        }

    def test_id_only_relationship(self) -> None:
        queries = get_child_objects_by_id_queries(
            _ACCOUNT_ID, "Account", ["Notes"], {"Notes": {ID_FIELD}}
        )
        assert queries == [
            "SELECT (SELECT Id FROM Notes ORDER BY Id DESC LIMIT 10) "
            f"FROM Account WHERE Id = '{_ACCOUNT_ID}'"
        ]

    @pytest.mark.parametrize(
        ("fields", "order"),
        [
            (
                {ID_FIELD, "Name", CREATED_FIELD, MODIFIED_FIELD},
                f"ORDER BY {MODIFIED_FIELD} DESC, {ID_FIELD} DESC",
            ),
            (
                {ID_FIELD, CREATED_FIELD},
                f"ORDER BY {CREATED_FIELD} DESC, {ID_FIELD} DESC",
            ),
            ({ID_FIELD, "Name"}, f"ORDER BY {ID_FIELD} DESC"),
        ],
    )
    def test_orders_by_recency_with_id_tiebreaker(
        self, fields: set[str], order: str
    ) -> None:
        queries = get_child_objects_by_id_queries(
            _ACCOUNT_ID, "Account", ["Contacts"], {"Contacts": fields}
        )
        match = _SUBQUERY.search(queries[0])
        assert match, queries[0]
        assert match["order"] == order


class TestQueryObject:
    def test_merges_field_chunks(self) -> None:
        fields = _wide_fields(800)
        with patch.object(
            OnyxSalesforce, "safe_query", side_effect=_fake_record_result
        ) as mocked:
            record = _client().query_object("Account", _ACCOUNT_ID, {"Account": fields})
        assert mocked.call_count > 1
        assert record == {f: f"v:{f}" for f in fields}

    def test_missing_record_returns_none(self) -> None:
        with patch.object(
            OnyxSalesforce, "safe_query", return_value={"totalSize": 0, "records": []}
        ):
            record = _client().query_object("Account", _ACCOUNT_ID, {"Account": {"Id"}})
        assert record is None

    def test_no_queryable_fields_returns_none(self) -> None:
        with patch.object(OnyxSalesforce, "safe_query") as mocked:
            record = _client().query_object("Account", _ACCOUNT_ID, {"Account": set()})
        assert record is None
        mocked.assert_not_called()


class TestGetChildObjectsById:
    def test_wide_child_splits_and_merges_by_id(self) -> None:
        wide = _wide_fields(600, "Opp") | {ID_FIELD}
        narrow = {ID_FIELD, "Email"}
        relationships_to_fields = {
            "Opportunities": wide,
            "Contacts": narrow,
            "Attachments": {ID_FIELD, "Body"},
        }
        with patch.object(
            OnyxSalesforce, "safe_query", side_effect=_fake_children_result
        ) as mocked:
            children = _client().get_child_objects_by_id(
                _ACCOUNT_ID,
                "Account",
                list(relationships_to_fields),
                relationships_to_fields,
            )

        issued = [call.args[0] for call in mocked.call_args_list]
        assert len(issued) > 1
        for query in issued:
            assert _url_encoded_length(query) <= SOQL_MAX_URL_ENCODED_LENGTH
            assert "Attachments" not in query

        assert set(children) == {
            "Opportunities:c1",
            "Opportunities:c2",
            "Contacts:c1",
            "Contacts:c2",
        }
        assert set(children["Opportunities:c1"]) - {"attributes"} == wide
        assert set(children["Contacts:c2"]) - {"attributes"} == narrow

    def test_failed_chunk_propagates(self) -> None:
        wide = _wide_fields(600, "Opp") | {ID_FIELD}
        relationships_to_fields = {"Opportunities": wide, "Contacts": {ID_FIELD}}
        first_field = min(wide - {ID_FIELD})

        def fail_later_opportunity_chunks(query: str) -> dict[str, Any]:
            # the first chunk holds the lowest field name, later rounds hold only
            # Opportunities chunks
            if "Contacts" not in query and first_field not in query:
                raise RuntimeError("boom")
            return _fake_children_result(query)

        with (
            patch.object(
                OnyxSalesforce, "safe_query", side_effect=fail_later_opportunity_chunks
            ),
            pytest.raises(RuntimeError),
        ):
            _client().get_child_objects_by_id(
                _ACCOUNT_ID,
                "Account",
                list(relationships_to_fields),
                relationships_to_fields,
            )
