"""Test the hybrid OData filtering approach for MS Teams."""

from unittest.mock import MagicMock

from onyx.connectors.teams.connector import _collect_all_teams


def test_hybrid_filtering() -> None:
    """Test that hybrid approach uses OData for safe names, client-side for special chars."""
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

    # Test 1: Special chars (&) should use get_all()
    _collect_all_teams(mock_graph_client, ["Team & Group"])
    mock_graph_client.teams.get_all.assert_called()
    mock_graph_client.teams.get.assert_not_called()

    # Reset mocks
    mock_graph_client.reset_mock()
    mock_get_all_query.execute_query.return_value = mock_team_collection
    mock_filter_query.execute_query.return_value = mock_team_collection

    # Test 2: Safe names should use OData filter
    _collect_all_teams(mock_graph_client, ["Engineering Team"])
    mock_graph_client.teams.get.assert_called()
    mock_get_query.filter.assert_called_once()

    # Test 3: OData failure should fallback to get_all()
    mock_filter_query.execute_query.side_effect = ValueError(
        "OData query parsing error"
    )
    _collect_all_teams(mock_graph_client, ["Simple Team"])
    mock_graph_client.teams.get_all.assert_called()
