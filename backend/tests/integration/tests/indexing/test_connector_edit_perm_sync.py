"""Connector edits into and out of permission sync, on the mock connector: a
public pair that enters sync stops granting access to users outside the
synced ACL, and leaving sync makes it public again. Lives with the other mock
server tests, which share the server's behavior queue."""

import os
import time
import uuid
from collections.abc import Callable

import httpx
import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.edit_plan.models import EditStepKind
from onyx.connectors.mock_connector.connector import MockConnectorCheckpoint
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from tests.integration.common_utils.constants import (
    API_SERVER_URL,
    MAX_DELAY,
    MOCK_CONNECTOR_SERVER_HOST,
    MOCK_CONNECTOR_SERVER_PORT,
)
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector_edit import (
    ConnectorEditManager,
)
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.test_document_utils import create_test_document
from tests.integration.common_utils.test_models import DATestUser

_POLL_SECONDS = 3
# The initial run, the full re-index on entering sync, and spare runs.
_MOCK_RUNS = 6


def _wait_until(condition: Callable[[], bool], what: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out waiting for {what}")
        time.sleep(_POLL_SECONDS)


def _can_find(text: str, user: DATestUser) -> bool:
    response = client.post(
        f"{API_SERVER_URL}/search",
        json={"query": text, "skip_query_expansion": True},
        headers=user.headers,
    )
    response.raise_for_status()
    return any(text in result["content"] for result in response.json()["results"])


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission sync is enterprise only",
)
def test_entering_and_leaving_perm_sync_changes_visibility(
    mock_server_client: httpx.Client,
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    text = f"perm sync edit {uuid.uuid4().hex} marker"
    test_doc = create_test_document(text=text)
    run = {
        "documents": [test_doc.model_dump(mode="json")],
        "checkpoint": MockConnectorCheckpoint(has_more=False).model_dump(mode="json"),
        "failures": [],
    }
    response = mock_server_client.post("/set-behavior", json=[run] * _MOCK_RUNS)
    assert response.status_code == 200

    cc_pair = CCPairManager.create_from_scratch(
        name=f"edit-perm-sync-{uuid.uuid4()}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )
    first = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id, user_performing_action=admin_user
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=first.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    _wait_until(lambda: _can_find(text, basic_user), "the public document", MAX_DELAY)

    # PUBLIC -> SYNC: the synced ACL names only the mock's external users.
    synced = ConnectorEditManager.current_proposal(cc_pair.id, admin_user)
    synced.access_type = AccessType.SYNC
    plan = ConnectorEditManager.plan(cc_pair.id, synced, admin_user)
    assert EditStepKind.ENTER_PERM_SYNC in [step.kind for step in plan.plan.steps]
    ConnectorEditManager.apply(cc_pair.id, plan.plan_id, admin_user)
    _wait_until(
        lambda: not _can_find(text, basic_user), "the document to close", MAX_DELAY
    )

    # SYNC -> PUBLIC.
    public = ConnectorEditManager.current_proposal(cc_pair.id, admin_user)
    public.access_type = AccessType.PUBLIC
    plan = ConnectorEditManager.plan(cc_pair.id, public, admin_user)
    assert [step.kind for step in plan.plan.steps] == [EditStepKind.LEAVE_PERM_SYNC]
    ConnectorEditManager.apply(cc_pair.id, plan.plan_id, admin_user)
    _wait_until(lambda: _can_find(text, basic_user), "the document to open", MAX_DELAY)
