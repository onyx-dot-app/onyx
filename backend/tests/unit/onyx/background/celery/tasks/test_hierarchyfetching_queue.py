from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.background.celery.tasks.hierarchyfetching.tasks import (
    _connector_supports_hierarchy_fetching,
)
from onyx.background.celery.tasks.hierarchyfetching.tasks import (
    check_for_hierarchy_fetching,
)
from onyx.connectors.factory import ConnectorMissingException
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.interfaces import HierarchyConnector
from onyx.connectors.interfaces import HierarchyOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch

TASKS_MODULE = "onyx.background.celery.tasks.hierarchyfetching.tasks"


class _NonHierarchyConnector(BaseConnector):
    def load_credentials(self, credentials: dict) -> dict | None:  # noqa: ARG002
        return None


class _HierarchyCapableConnector(HierarchyConnector):
    def load_credentials(self, credentials: dict) -> dict | None:  # noqa: ARG002
        return None

    def load_hierarchy(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
    ) -> HierarchyOutput:
        return
        yield


def _build_cc_pair_mock() -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.connector.source = "mock-source"
    cc_pair.connector.input_type = "mock-input-type"
    return cc_pair


def _build_redis_mock_with_lock() -> tuple[MagicMock, MagicMock]:
    redis_client = MagicMock()
    lock = MagicMock()
    lock.acquire.return_value = True
    lock.owned.return_value = True
    redis_client.lock.return_value = lock
    return redis_client, lock


@patch(f"{TASKS_MODULE}.identify_connector_class")
def test_connector_supports_hierarchy_fetching_false_for_non_hierarchy_connector(
    mock_identify_connector_class: MagicMock,
) -> None:
    mock_identify_connector_class.return_value = _NonHierarchyConnector

    assert _connector_supports_hierarchy_fetching(_build_cc_pair_mock()) is False


@patch(f"{TASKS_MODULE}.identify_connector_class")
def test_connector_supports_hierarchy_fetching_false_when_class_missing(
    mock_identify_connector_class: MagicMock,
) -> None:
    mock_identify_connector_class.side_effect = ConnectorMissingException("missing")

    assert _connector_supports_hierarchy_fetching(_build_cc_pair_mock()) is False


@patch(f"{TASKS_MODULE}.identify_connector_class")
def test_connector_supports_hierarchy_fetching_true_for_supported_connector(
    mock_identify_connector_class: MagicMock,
) -> None:
    mock_identify_connector_class.return_value = _HierarchyCapableConnector

    assert _connector_supports_hierarchy_fetching(_build_cc_pair_mock()) is True


@patch(f"{TASKS_MODULE}._try_creating_hierarchy_fetching_task")
@patch(f"{TASKS_MODULE}._is_hierarchy_fetching_due")
@patch(f"{TASKS_MODULE}.get_connector_credential_pair_from_id")
@patch(f"{TASKS_MODULE}.fetch_indexable_standard_connector_credential_pair_ids")
@patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
@patch(f"{TASKS_MODULE}.get_redis_client")
@patch(f"{TASKS_MODULE}._connector_supports_hierarchy_fetching")
def test_check_for_hierarchy_fetching_skips_unsupported_connectors(
    mock_supports_hierarchy_fetching: MagicMock,
    mock_get_redis_client: MagicMock,
    mock_get_session: MagicMock,
    mock_fetch_cc_pair_ids: MagicMock,
    mock_get_cc_pair: MagicMock,
    mock_is_due: MagicMock,
    mock_try_create_task: MagicMock,
) -> None:
    redis_client, lock = _build_redis_mock_with_lock()
    mock_get_redis_client.return_value = redis_client
    mock_get_session.return_value.__enter__.return_value = MagicMock()
    mock_fetch_cc_pair_ids.return_value = [123]
    mock_get_cc_pair.return_value = _build_cc_pair_mock()
    mock_supports_hierarchy_fetching.return_value = False
    mock_is_due.return_value = True

    task_app = MagicMock()
    with patch.object(check_for_hierarchy_fetching, "app", task_app):
        result = check_for_hierarchy_fetching.run(tenant_id="test-tenant")

    assert result == 0
    mock_is_due.assert_not_called()
    mock_try_create_task.assert_not_called()
    lock.release.assert_called_once()


@patch(f"{TASKS_MODULE}._try_creating_hierarchy_fetching_task")
@patch(f"{TASKS_MODULE}._is_hierarchy_fetching_due")
@patch(f"{TASKS_MODULE}.get_connector_credential_pair_from_id")
@patch(f"{TASKS_MODULE}.fetch_indexable_standard_connector_credential_pair_ids")
@patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
@patch(f"{TASKS_MODULE}.get_redis_client")
@patch(f"{TASKS_MODULE}._connector_supports_hierarchy_fetching")
def test_check_for_hierarchy_fetching_creates_task_for_supported_due_connector(
    mock_supports_hierarchy_fetching: MagicMock,
    mock_get_redis_client: MagicMock,
    mock_get_session: MagicMock,
    mock_fetch_cc_pair_ids: MagicMock,
    mock_get_cc_pair: MagicMock,
    mock_is_due: MagicMock,
    mock_try_create_task: MagicMock,
) -> None:
    redis_client, lock = _build_redis_mock_with_lock()
    cc_pair = _build_cc_pair_mock()
    mock_get_redis_client.return_value = redis_client
    mock_get_session.return_value.__enter__.return_value = MagicMock()
    mock_fetch_cc_pair_ids.return_value = [123]
    mock_get_cc_pair.return_value = cc_pair
    mock_supports_hierarchy_fetching.return_value = True
    mock_is_due.return_value = True
    mock_try_create_task.return_value = "task-id"

    task_app = MagicMock()
    with patch.object(check_for_hierarchy_fetching, "app", task_app):
        result = check_for_hierarchy_fetching.run(tenant_id="test-tenant")

    assert result == 1
    mock_is_due.assert_called_once_with(cc_pair)
    mock_try_create_task.assert_called_once()
    lock.release.assert_called_once()


@patch(f"{TASKS_MODULE}._try_creating_hierarchy_fetching_task")
@patch(f"{TASKS_MODULE}._is_hierarchy_fetching_due")
@patch(f"{TASKS_MODULE}.get_connector_credential_pair_from_id")
@patch(f"{TASKS_MODULE}.fetch_indexable_standard_connector_credential_pair_ids")
@patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
@patch(f"{TASKS_MODULE}.get_redis_client")
@patch(f"{TASKS_MODULE}._connector_supports_hierarchy_fetching")
def test_check_for_hierarchy_fetching_skips_supported_connector_when_not_due(
    mock_supports_hierarchy_fetching: MagicMock,
    mock_get_redis_client: MagicMock,
    mock_get_session: MagicMock,
    mock_fetch_cc_pair_ids: MagicMock,
    mock_get_cc_pair: MagicMock,
    mock_is_due: MagicMock,
    mock_try_create_task: MagicMock,
) -> None:
    redis_client, lock = _build_redis_mock_with_lock()
    cc_pair = _build_cc_pair_mock()
    mock_get_redis_client.return_value = redis_client
    mock_get_session.return_value.__enter__.return_value = MagicMock()
    mock_fetch_cc_pair_ids.return_value = [123]
    mock_get_cc_pair.return_value = cc_pair
    mock_supports_hierarchy_fetching.return_value = True
    mock_is_due.return_value = False

    task_app = MagicMock()
    with patch.object(check_for_hierarchy_fetching, "app", task_app):
        result = check_for_hierarchy_fetching.run(tenant_id="test-tenant")

    assert result == 0
    mock_is_due.assert_called_once_with(cc_pair)
    mock_try_create_task.assert_not_called()
    lock.release.assert_called_once()
