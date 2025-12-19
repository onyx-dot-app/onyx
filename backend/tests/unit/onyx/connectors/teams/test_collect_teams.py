"""Test the OData filtering for MS Teams with special character handling."""

from unittest.mock import MagicMock

from onyx.connectors.teams.connector import _collect_all_teams


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
    mock_team_collection.__iter__ = lambda self: iter([mock_team])

    mock_get_query = MagicMock()
    mock_top_query = MagicMock()
    mock_top_query.execute_query.return_value = mock_team_collection
    mock_get_query.top.return_value = mock_top_query
    mock_graph_client.teams.get = MagicMock(return_value=mock_get_query)

    # Test with team name containing special characters (has &, parentheses)
    # This should use client-side filtering (get().top()) instead of OData filtering
    result = _collect_all_teams(
        mock_graph_client, ["Research & Development (R&D) Team"]
    )

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
    mock_team_collection.__iter__ = lambda self: iter([])

    mock_get_query = MagicMock()
    mock_filter_query = MagicMock()
    mock_filter_query.before_execute = MagicMock(return_value=mock_filter_query)
    mock_filter_query.execute_query.return_value = mock_team_collection
    mock_get_query.filter.return_value = mock_filter_query
    mock_graph_client.teams.get = MagicMock(return_value=mock_get_query)

    # Test with a team name containing a single quote (no &, (, ) so uses OData)
    _collect_all_teams(mock_graph_client, ["Team's Group"])

    # Verify OData filter was used (since no special characters)
    mock_graph_client.teams.get.assert_called()
    mock_get_query.filter.assert_called_once()

    # Verify the filter: single quote should be escaped to '' for OData syntax
    filter_arg = mock_get_query.filter.call_args[0][0]
    expected_filter = "displayName eq 'Team''s Group'"
    assert (
        filter_arg == expected_filter
    ), f"Expected: {expected_filter}, Got: {filter_arg}"


def test_helper_functions() -> None:
    """Test the helper functions for team name processing."""
    from onyx.connectors.teams.connector import (
        _escape_odata_string,
        _has_odata_incompatible_chars,
        _can_use_odata_filter,
    )

    # Test OData string escaping
    assert _escape_odata_string("Team's Group") == "Team''s Group"
    assert _escape_odata_string("Normal Team") == "Normal Team"

    # Test special character detection
    assert _has_odata_incompatible_chars(["R&D Team"])
    assert _has_odata_incompatible_chars(["Team (Alpha)"])
    assert not _has_odata_incompatible_chars(["Normal Team"])
    assert not _has_odata_incompatible_chars([])
    assert not _has_odata_incompatible_chars(None)

    # Test filtering strategy determination
    can_use, safe, problematic = _can_use_odata_filter(["Normal Team", "R&D Team"])
    assert can_use
    assert "Normal Team" in safe
    assert "R&D Team" in problematic
