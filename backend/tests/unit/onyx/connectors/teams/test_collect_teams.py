"""Test the OData filtering for MS Teams with special character handling."""

from unittest.mock import MagicMock

from onyx.connectors.teams.connector import _collect_all_teams


def test_special_characters_in_team_names() -> None:
    """Test that team names with special characters work correctly with OData filters."""
    mock_graph_client = MagicMock()

    # Mock successful responses
    mock_team_collection = MagicMock()
    mock_team_collection.has_next = False
    mock_team_collection.__iter__ = lambda self: iter([])

    mock_get_all_query = MagicMock()
    mock_get_all_query.execute_query.return_value = mock_team_collection
    mock_graph_client.teams.get_all = MagicMock(return_value=mock_get_all_query)

    mock_get_query = MagicMock()
    mock_filter_query = MagicMock()
    mock_filter_query.execute_query.return_value = mock_team_collection
    mock_get_query.filter.return_value = mock_filter_query
    mock_graph_client.teams.get = MagicMock(return_value=mock_get_query)

    # Test with the actual customer's problematic team name (has &, parentheses, spaces)
    _collect_all_teams(mock_graph_client, ["Grainger Data & Analytics (GDA) Users"])

    # Verify OData filter was used with raw special characters
    mock_graph_client.teams.get.assert_called()
    filter_arg = mock_get_query.filter.call_args[0][0]
    expected_filter = "displayName eq 'Grainger Data & Analytics (GDA) Users'"
    assert (
        filter_arg == expected_filter
    ), f"Expected: {expected_filter}, Got: {filter_arg}"

    # Reset mocks
    mock_graph_client.reset_mock()
    mock_get_all_query.execute_query.return_value = mock_team_collection
    mock_filter_query.execute_query.return_value = mock_team_collection

    # Test that OData filter failure falls back to get_all()
    mock_filter_query.execute_query.side_effect = ValueError(
        "OData query parsing error"
    )
    _collect_all_teams(mock_graph_client, ["Simple Team"])
    mock_graph_client.teams.get_all.assert_called()


def test_single_quote_escaping() -> None:
    """Test that team names with single quotes are properly escaped for OData."""
    mock_graph_client = MagicMock()

    # Mock successful responses
    mock_team_collection = MagicMock()
    mock_team_collection.has_next = False
    mock_team_collection.__iter__ = lambda self: iter([])

    mock_get_query = MagicMock()
    mock_filter_query = MagicMock()
    mock_filter_query.execute_query.return_value = mock_team_collection
    mock_get_query.filter.return_value = mock_filter_query
    mock_graph_client.teams.get = MagicMock(return_value=mock_get_query)

    # Test with a team name containing a single quote
    _collect_all_teams(mock_graph_client, ["Team's Group"])

    # Verify OData filter was used
    mock_graph_client.teams.get.assert_called()
    mock_get_query.filter.assert_called_once()

    # Verify the filter: single quote should be escaped to '' for OData syntax
    filter_arg = mock_get_query.filter.call_args[0][0]
    expected_filter = "displayName eq 'Team''s Group'"
    assert (
        filter_arg == expected_filter
    ), f"Expected: {expected_filter}, Got: {filter_arg}"
