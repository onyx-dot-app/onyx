"""Test the OData filtering for MS Teams with special character handling."""

import json
from functools import partial
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from office365.graph_client import GraphClient

from onyx.connectors.teams.listing import collect_all_teams


def test_special_characters_in_team_names() -> None:
    """Test that team names with special characters use client-side filtering."""
    mock_graph_client = MagicMock()

    # Mock team with special characters
    mock_team = MagicMock()
    mock_team.id = "test-id"
    mock_team.display_name = "Research & Development (R&D) Team"
    mock_team.properties = {}

    # Mock successful responses for client-side filtering
    mock_team_collection = MagicMock()
    mock_team_collection.has_next = False
    mock_team_collection.__iter__ = lambda self: iter([mock_team])  # noqa: ARG005

    mock_get_query = MagicMock()
    mock_top_query = MagicMock()
    mock_top_query.execute_query.return_value = mock_team_collection
    mock_get_query.top.return_value = mock_top_query
    mock_graph_client.teams.get = MagicMock(return_value=mock_get_query)

    # Test with team name containing special characters (has &, parentheses)
    # This should use client-side filtering (get().top()) instead of OData filtering
    result = collect_all_teams(mock_graph_client, ["Research & Development (R&D) Team"])

    # Verify that get().top() was called for client-side filtering
    mock_graph_client.teams.get.assert_called()
    mock_get_query.top.assert_called_with(50)

    # Verify the team was found through client-side filtering
    assert len(result) == 1
    assert result[0].display_name == "Research & Development (R&D) Team"


def test_single_quote_escaping() -> None:
    """Test that team names with single quotes use OData filtering with proper escaping."""
    mock_graph_client = MagicMock()

    # Mock successful responses
    mock_team_collection = MagicMock()
    mock_team_collection.has_next = False
    mock_team_collection.__iter__ = lambda self: iter([])  # noqa: ARG005

    mock_get_query = MagicMock()
    mock_filter_query = MagicMock()
    mock_filter_query.before_execute = MagicMock(return_value=mock_filter_query)
    mock_filter_query.execute_query.return_value = mock_team_collection
    mock_get_query.filter.return_value = mock_filter_query
    mock_graph_client.teams.get = MagicMock(return_value=mock_get_query)

    # Test with a team name containing a single quote (no &, (, ) so uses OData)
    collect_all_teams(mock_graph_client, ["Team's Group"])

    # Verify OData filter was used (since no special characters)
    mock_graph_client.teams.get.assert_called()
    mock_get_query.filter.assert_called_once()

    # Verify the filter: single quote should be escaped to '' for OData syntax
    filter_arg = mock_get_query.filter.call_args[0][0]
    expected_filter = "displayName eq 'Team''s Group'"
    assert filter_arg == expected_filter, (
        f"Expected: {expected_filter}, Got: {filter_arg}"
    )


def test_helper_functions() -> None:
    """Test the helper functions for team name processing."""
    from onyx.connectors.teams.listing import (
        _can_use_odata_filter,
        _escape_odata_string,
        has_odata_incompatible_chars,
    )

    # Test OData string escaping
    assert _escape_odata_string("Team's Group") == "Team''s Group"
    assert _escape_odata_string("Normal Team") == "Normal Team"

    # Test special character detection
    assert has_odata_incompatible_chars(["R&D Team"])
    assert has_odata_incompatible_chars(["Team (Alpha)"])
    assert not has_odata_incompatible_chars(["Normal Team"])
    assert not has_odata_incompatible_chars([])
    assert not has_odata_incompatible_chars(None)

    # Test filtering strategy determination
    can_use, safe, problematic = _can_use_odata_filter(["Normal Team", "R&D Team"])
    assert can_use
    assert "Normal Team" in safe
    assert "R&D Team" in problematic


def _team(team_id: str, name: str, properties: dict | None = None) -> MagicMock:
    team = MagicMock()
    team.id = team_id
    team.display_name = name
    team.properties = properties or {}
    return team


def _page(teams: list[MagicMock], next_url: str | None) -> MagicMock:
    page = MagicMock()
    page.has_next = next_url is not None
    page._next_request_url = next_url
    page.__iter__ = lambda self: iter(teams)  # noqa: ARG005
    return page


def test_no_configured_teams_lists_every_team_to_the_last_page() -> None:
    # The connector form promises that an empty Teams list indexes every team.
    pages = [
        _page([_team("t1", "Support")], "https://graph.example/teams?$skiptoken=2"),
        _page(
            [
                _team("t2", "Research & Development"),
                _team("t3", "Gone", {"deletedDateTime": "2026-01-01T00:00:00Z"}),
            ],
            None,
        ),
    ]
    query = MagicMock()
    graph_client = MagicMock()
    graph_client.teams.get.return_value.top.return_value = query

    for no_names in ([], None):
        query.execute_query.side_effect = list(pages)
        found = collect_all_teams(graph_client, no_names)
        assert [team.id for team in found] == ["t1", "t2"]
    # The second page is asked for by the link the first one carried.
    next_urls = [
        call.args[0].keywords["next_url"]
        for call in query.before_execute.call_args_list
        if isinstance(call.args[0], partial)
    ]
    assert set(next_urls) == {"https://graph.example/teams?$skiptoken=2"}


def _graph_answer(status: int, payload: dict[str, Any], url: str) -> requests.Response:
    answer = requests.Response()
    answer.status_code = status
    answer._content = json.dumps(payload).encode()
    answer.headers["Content-Type"] = "application/json"
    answer.url = url
    return answer


def test_a_throttled_page_of_teams_is_asked_for_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real SDK over fake HTTP: it drops a query once sent, so a retry that
    # reuses the object sends nothing and the listing ends a page early.
    second_page = "https://graph.microsoft.com/v1.0/teams?$skiptoken=2"
    answers = [
        (
            200,
            {
                "value": [{"id": "t1", "displayName": "One"}],
                "@odata.nextLink": second_page,
            },
        ),
        (429, {}),
        (200, {"value": [{"id": "t2", "displayName": "Two"}]}),
    ]
    requested: list[str] = []

    def fake_get(url: str, **_: Any) -> requests.Response:
        requested.append(url)
        status, payload = answers.pop(0)
        return _graph_answer(status, payload, url)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _: None)
    client = GraphClient(lambda: {"token_type": "Bearer", "access_token": "x"})

    teams = collect_all_teams(client, [])

    assert [team.id for team in teams] == ["t1", "t2"]
    assert requested[1:] == [second_page, second_page]
