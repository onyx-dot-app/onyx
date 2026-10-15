from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.jira.connector import (
    ONE_HOUR,
    JiraConnector,
    JiraConnectorCheckpoint,
)

_START = 1_700_000_000.0
_END = _START + 600
_DATE_ERROR = ConnectorValidationError(
    "Invalid JQL query. Error: Date value '1700000000000' for field 'updated' "
    "is invalid."
)

LoadMethod = Callable[
    [JiraConnector, float, float, JiraConnectorCheckpoint],
    CheckpointOutput[JiraConnectorCheckpoint],
]
_METHODS: list[LoadMethod] = [
    JiraConnector.load_from_checkpoint,
    JiraConnector.load_from_checkpoint_with_perm_sync,
]


def _raises(error: Exception) -> Iterator[Any]:
    raise error
    yield


def _one_issue_then(error: Exception) -> Iterator[Any]:
    yield MagicMock()
    raise error


def _drain(output: Any) -> tuple[list[Any], JiraConnectorCheckpoint]:
    items: list[Any] = []
    while True:
        try:
            items.append(next(output))
        except StopIteration as stop:
            return items, stop.value


@pytest.mark.parametrize("method", _METHODS, ids=lambda method: method.__name__)
def test_date_error_retries_with_an_earlier_start(
    jira_connector: JiraConnector, method: LoadMethod
) -> None:
    searches: list[str] = []

    def search(**kwargs: Any) -> Iterator[Any]:
        searches.append(kwargs["jql"])
        return _raises(_DATE_ERROR) if len(searches) == 1 else iter([])

    with patch(
        "onyx.connectors.jira.connector._perform_jql_search", side_effect=search
    ):
        items, checkpoint = _drain(
            method(
                jira_connector,
                _START,
                _END,
                jira_connector.build_dummy_checkpoint(),
            )
        )

    assert items == []
    assert checkpoint.has_more is False
    assert len(searches) == 2
    assert f"updated >= {int(_START * 1000)}" in searches[0]
    assert f"updated >= {int((_START - ONE_HOUR) * 1000)}" in searches[1]


@pytest.mark.parametrize("method", _METHODS, ids=lambda method: method.__name__)
def test_other_errors_are_not_retried(
    jira_connector: JiraConnector, method: LoadMethod
) -> None:
    search = MagicMock(
        return_value=_raises(ConnectorValidationError("Invalid JQL query."))
    )

    with (
        patch("onyx.connectors.jira.connector._perform_jql_search", search),
        pytest.raises(ConnectorValidationError, match="Invalid JQL"),
    ):
        _drain(
            method(
                jira_connector,
                _START,
                _END,
                jira_connector.build_dummy_checkpoint(),
            )
        )

    search.assert_called_once()


def test_date_error_after_the_first_item_is_not_retried(
    jira_connector: JiraConnector,
) -> None:
    """A retry then would yield the first items again."""
    search = MagicMock(return_value=_one_issue_then(_DATE_ERROR))

    with (
        patch("onyx.connectors.jira.connector._perform_jql_search", search),
        pytest.raises(ConnectorValidationError, match="field 'updated'"),
    ):
        _drain(
            jira_connector.load_from_checkpoint(
                _START, _END, jira_connector.build_dummy_checkpoint()
            )
        )

    search.assert_called_once()
