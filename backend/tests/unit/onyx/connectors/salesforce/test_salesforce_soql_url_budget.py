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
    get_object_by_id_queries,
    pinned_child_queries,
    plan_child_queries,
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
    r"\(SELECT (?P<fields>[^()]+) FROM (?P<rel>\w+) "
    r"(?P<selection>ORDER BY [^()]+? LIMIT 10|WHERE Id IN \((?P<ids>[^()]*)\))\)"
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


def _subquery_ids(match: re.Match[str]) -> list[str]:
    if match["ids"] is None:
        return ["c1", "c2"]
    return [child_id.strip("'") for child_id in match["ids"].split(",")]


def _fake_children_result(query: str) -> dict[str, Any]:
    record: dict[str, Any] = {"attributes": {"type": "Account"}}
    for match in _SUBQUERY.finditer(query):
        fields = match["fields"].split(SOQL_FIELD_SEPARATOR)
        assert ID_FIELD in fields, query
        rows = []
        for child_id in _subquery_ids(match):
            row: dict[str, Any] = {f: f"{child_id}:{f}" for f in fields}
            row[ID_FIELD] = child_id
            row["attributes"] = {"type": match["rel"]}
            rows.append(row)
        record[match["rel"]] = {"totalSize": len(rows), "records": rows}
    return {"totalSize": 1, "records": [record]}


def _assert_query_shape(query: str) -> list[re.Match[str]]:
    assert _url_encoded_length(query) <= SOQL_MAX_URL_ENCODED_LENGTH
    subqueries = list(_SUBQUERY.finditer(query))
    assert 0 < len(subqueries) <= SOQL_MAX_SUBQUERIES
    relationships = [match["rel"] for match in subqueries]
    assert len(relationships) == len(set(relationships)), query
    return subqueries


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


class TestChildQueryPlanning:
    # 1000 fields need three chunks, 400 need two, so both have pinned rounds
    _RELATIONSHIPS = {
        "Opportunities": _wide_fields(1000, "Opp") | {ID_FIELD},
        "Contacts": {ID_FIELD, "Email"},
        "Cases": _wide_fields(400, "Case"),
    }

    def test_window_queries_cover_each_relationship_once(self) -> None:
        plan = plan_child_queries(
            _ACCOUNT_ID, "Account", list(self._RELATIONSHIPS), self._RELATIONSHIPS
        )
        windowed: dict[str, set[str]] = {}
        for query in plan.window_queries:
            for match in _assert_query_shape(query):
                assert match["selection"].startswith("ORDER BY")
                windowed[match["rel"]] = set(
                    match["fields"].split(SOQL_FIELD_SEPARATOR)
                )
        assert set(windowed) == set(self._RELATIONSHIPS)
        assert set(plan.remaining_chunks) == {"Opportunities", "Cases"}
        for relationship, fields in self._RELATIONSHIPS.items():
            remaining = {
                f
                for chunk in plan.remaining_chunks.get(relationship, [])
                for f in chunk
            }
            assert windowed[relationship] | remaining == fields | {ID_FIELD}

    def test_pinned_queries_pin_the_window_ids(self) -> None:
        plan = plan_child_queries(
            _ACCOUNT_ID, "Account", list(self._RELATIONSHIPS), self._RELATIONSHIPS
        )
        queries = pinned_child_queries(
            _ACCOUNT_ID,
            "Account",
            plan.remaining_chunks,
            {"Opportunities": ["c1", "c2"], "Contacts": ["c9"]},
        )
        remaining = plan.remaining_chunks["Opportunities"]
        assert len(queries) == len(remaining) >= 2, "one pinned query per chunk"
        pinned_fields: set[str] = set()
        for query in queries:
            for match in _assert_query_shape(query):
                assert match["rel"] == "Opportunities"
                assert match["selection"] == "WHERE Id IN ('c1','c2')"
                pinned_fields.update(match["fields"].split(SOQL_FIELD_SEPARATOR))
        assert "Cases" not in "".join(queries), "no window rows means no pinned query"
        assert pinned_fields == {f for chunk in remaining for f in chunk} | {ID_FIELD}

    def test_id_only_relationship(self) -> None:
        plan = plan_child_queries(
            _ACCOUNT_ID, "Account", ["Notes"], {"Notes": {ID_FIELD}}
        )
        assert plan.window_queries == [
            "SELECT (SELECT Id FROM Notes ORDER BY Id DESC LIMIT 10) "
            f"FROM Account WHERE Id = '{_ACCOUNT_ID}'"
        ]
        assert plan.remaining_chunks == {}

    @pytest.mark.parametrize(
        ("fields", "selection"),
        [
            (
                {ID_FIELD, "Name", CREATED_FIELD, MODIFIED_FIELD},
                f"ORDER BY {MODIFIED_FIELD} DESC, {ID_FIELD} DESC LIMIT 10",
            ),
            (
                {ID_FIELD, CREATED_FIELD},
                f"ORDER BY {CREATED_FIELD} DESC, {ID_FIELD} DESC LIMIT 10",
            ),
            ({ID_FIELD, "Name"}, f"ORDER BY {ID_FIELD} DESC LIMIT 10"),
        ],
    )
    def test_window_orders_by_recency_with_id_tiebreaker(
        self, fields: set[str], selection: str
    ) -> None:
        plan = plan_child_queries(
            _ACCOUNT_ID, "Account", ["Contacts"], {"Contacts": fields}
        )
        match = _SUBQUERY.search(plan.window_queries[0])
        assert match, plan.window_queries[0]
        assert match["selection"] == selection


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
    _WIDE = _wide_fields(600, "Opp") | {ID_FIELD}
    _NARROW = {ID_FIELD, "Email"}
    _RELATIONSHIPS = {
        "Opportunities": _WIDE,
        "Contacts": _NARROW,
        "Attachments": {ID_FIELD, "Body"},
    }

    def _fetch(self, side_effect: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
        with patch.object(OnyxSalesforce, "safe_query", side_effect=side_effect) as m:
            children = _client().get_child_objects_by_id(
                _ACCOUNT_ID, "Account", list(self._RELATIONSHIPS), self._RELATIONSHIPS
            )
        return children, [call.args[0] for call in m.call_args_list]

    def test_wide_child_splits_and_merges_by_id(self) -> None:
        children, issued = self._fetch(_fake_children_result)
        assert len(issued) > 1
        for query in issued:
            assert _url_encoded_length(query) <= SOQL_MAX_URL_ENCODED_LENGTH
            assert "Attachments" not in query
        assert any("WHERE Id IN ('c1','c2')" in query for query in issued)

        assert set(children) == {
            "Opportunities:c1",
            "Opportunities:c2",
            "Contacts:c1",
            "Contacts:c2",
        }
        assert set(children["Opportunities:c1"]) - {"attributes"} == self._WIDE
        assert set(children["Contacts:c2"]) - {"attributes"} == self._NARROW

    def test_child_missing_from_a_pinned_chunk_is_dropped(self) -> None:
        def lose_c2_in_pinned_chunks(query: str) -> dict[str, Any]:
            result = _fake_children_result(query)
            if "WHERE Id IN" in query:
                for child_result in result["records"][0].values():
                    if isinstance(child_result, dict) and "records" in child_result:
                        child_result["records"] = [
                            row
                            for row in child_result["records"]
                            if row[ID_FIELD] != "c2"
                        ]
            return result

        children, _ = self._fetch(lose_c2_in_pinned_chunks)
        assert set(children) == {"Opportunities:c1", "Contacts:c1", "Contacts:c2"}
        assert set(children["Opportunities:c1"]) - {"attributes"} == self._WIDE

    def test_empty_window_skips_pinned_queries(self) -> None:
        def no_opportunities(query: str) -> dict[str, Any]:
            result = _fake_children_result(query)
            if "Opportunities" in result["records"][0]:
                result["records"][0]["Opportunities"] = None
            return result

        children, issued = self._fetch(no_opportunities)
        assert set(children) == {"Contacts:c1", "Contacts:c2"}
        assert not any("WHERE Id IN" in query for query in issued)

    def test_failed_query_propagates(self) -> None:
        def fail_pinned(query: str) -> dict[str, Any]:
            if "WHERE Id IN" in query:
                raise RuntimeError("boom")
            return _fake_children_result(query)

        with pytest.raises(RuntimeError):
            self._fetch(fail_pinned)
