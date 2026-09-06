"""End-to-end integration tests for the reindex *port* flow.

Unlike the unit and external-dependency-unit suites, these drive the whole live wiring
with no mocking: beat's check_for_port enqueues onto the `port` queue, docprocessing
re-embeds PRESENT into FUTURE, and the beat-driven swap then promotes FUTURE to PRESENT.

Docs are seeded into PRESENT via the ingestion API before the reindex starts, so only the
port copy -- not a connector re-fetch -- can land them in the new index. Reindexing to the
current model always creates a new ALT index, so a changed index_name is proof the swap ran.
"""

import os
import time
from uuid import uuid4

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, SwitchoverType
from onyx.db.search_settings import get_current_search_settings
from tests.integration.common_utils.constants import API_SERVER_URL, MAX_DELAY
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.reindex_port import ReindexPortManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import (
    DATestAPIKey,
    DATestLLMProvider,
    DATestUser,
)

_EE_ONLY = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group permissions are Enterprise-only",
)


def _search_finds(content: str, user: DATestUser) -> bool:
    """True if a document whose content contains ``content`` is returned by search.

    OpenSearch is shared across the integration suite (only Postgres is reset), so we
    match on the unique content marker rather than result counts.
    """
    response = client.post(
        f"{API_SERVER_URL}/search",
        json={"query": content},
        headers=user.headers,
    )
    response.raise_for_status()
    return any(content in result["content"] for result in response.json()["results"])


def test_reindex_port_happy_path(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    """A reindex ports every doc into a fresh index and the swap serves it."""
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    marker = uuid4().hex[:8]
    contents = [f"reindex port happy path {marker} doc {i}" for i in range(3)]
    for content in contents:
        DocumentManager.seed_doc_with_content(cc_pair, content, api_key)

    for content in contents:
        assert _search_finds(content, admin_user)

    original_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]

    ReindexPortManager.start_reindex(admin_user)
    ReindexPortManager.wait_for_reindex_completion(admin_user)
    new_settings = ReindexPortManager.wait_for_swap(original_index_name, admin_user)
    assert new_settings["index_name"] != original_index_name

    for content in contents:
        assert _search_finds(content, admin_user)


@_EE_ONLY
def test_reindex_port_preserves_acls(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    """The port copies chunk ACLs unchanged: a private doc stays private across a swap."""
    privileged_user = UserManager.create(name="port-acl-allowed")
    blocked_user = UserManager.create(name="port-acl-blocked")

    restricted_cc_pair = CCPairManager.create_from_scratch(
        access_type=AccessType.PRIVATE,
        user_performing_action=admin_user,
    )
    user_group = UserGroupManager.create(
        user_ids=[privileged_user.id],
        cc_pair_ids=[restricted_cc_pair.id],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
        user_groups_to_check=[user_group],
    )

    marker = uuid4().hex[:8]
    doc_content = f"restricted port acl doc {marker}"
    DocumentManager.seed_doc_with_content(restricted_cc_pair, doc_content, api_key)

    assert _search_finds(doc_content, privileged_user)
    assert not _search_finds(doc_content, blocked_user)

    original_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]
    ReindexPortManager.start_reindex(admin_user)
    ReindexPortManager.wait_for_reindex_completion(admin_user)
    ReindexPortManager.wait_for_swap(original_index_name, admin_user)

    assert _search_finds(doc_content, privileged_user)
    assert not _search_finds(doc_content, blocked_user)


def test_reindex_port_multiple_connectors(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    """The scheduler fans a reindex out across every cc_pair; all get ported and swap."""
    marker = uuid4().hex[:8]
    num_connectors = 3
    contents: list[str] = []
    for i in range(num_connectors):
        cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
        content = f"multi connector port {marker} conn {i}"
        DocumentManager.seed_doc_with_content(cc_pair, content, api_key)
        contents.append(content)

    for content in contents:
        assert _search_finds(content, admin_user)

    original_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]
    ReindexPortManager.start_reindex(admin_user)

    # The progress total counts every portable cc_pair, including the default
    # ingestion pair alongside the N we just created.
    initial = ReindexPortManager.get_progress(admin_user)
    assert initial.total >= num_connectors

    ReindexPortManager.wait_for_reindex_completion(admin_user)
    ReindexPortManager.wait_for_swap(original_index_name, admin_user)

    for content in contents:
        assert _search_finds(content, admin_user)


def test_cancel_reindex_during_port(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    """Canceling a reindex tears the FUTURE down and leaves PRESENT untouched."""
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    marker = uuid4().hex[:8]
    content = f"cancel reindex doc {marker}"
    DocumentManager.seed_doc_with_content(cc_pair, content, api_key)
    assert _search_finds(content, admin_user)

    original_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]

    ReindexPortManager.start_reindex(admin_user)
    assert ReindexPortManager.get_secondary_settings(admin_user) is not None

    ReindexPortManager.cancel_reindex(admin_user)

    # With the FUTURE gone there is no active port target left, so no swap can follow.
    assert ReindexPortManager.get_secondary_settings(admin_user) is None
    assert ReindexPortManager.get_progress(admin_user).total == 0
    assert (
        ReindexPortManager.get_current_settings(admin_user)["index_name"]
        == original_index_name
    )

    # Sleep past the swap-check interval to rule out a swap that fires late after cancel.
    time.sleep(5)
    assert (
        ReindexPortManager.get_current_settings(admin_user)["index_name"]
        == original_index_name
    )
    assert _search_finds(content, admin_user)

    # The canceled FUTURE's index held partial-port data. Cancel reclaims it, so a retry
    # takes that name back instead of being refused forever by the name-reuse guard.
    ReindexPortManager.wait_for_reindex_accepted(admin_user)
    retried = ReindexPortManager.get_secondary_settings(admin_user)
    assert retried is not None
    assert retried["index_name"] != original_index_name

    ReindexPortManager.cancel_reindex(admin_user)


def test_reindex_reclaims_the_index_name_of_a_retired_generation(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    """The ALT suffix alternates, so the reindex after a swap wants the name the retired
    generation still occupies. The server refuses it, hands that index to the reclaim
    loop, and accepts the reindex once it drains -- without which every later reindex of
    this model would be blocked."""
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    marker = uuid4().hex[:8]
    content = f"reused index name {marker}"
    DocumentManager.seed_doc_with_content(cc_pair, content, api_key)

    retired_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]
    ReindexPortManager.start_reindex(admin_user)
    ReindexPortManager.wait_for_reindex_completion(admin_user)
    ReindexPortManager.wait_for_swap(retired_index_name, admin_user)

    refused = ReindexPortManager.start_reindex_response(admin_user)
    assert refused.status_code == 409
    assert ReindexPortManager.get_secondary_settings(admin_user) is None

    ReindexPortManager.wait_for_reindex_accepted(admin_user)
    secondary = ReindexPortManager.get_secondary_settings(admin_user)
    assert secondary is not None
    assert secondary["index_name"] == retired_index_name

    ReindexPortManager.cancel_reindex(admin_user)


def test_connector_deletion_during_reindex(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    """Deleting a connector mid-reindex is not blocked by its port, and the reindex
    still completes + swaps for the surviving connector."""
    marker = uuid4().hex[:8]
    keep_cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    delete_cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=admin_user
    )
    keep_content = f"deletion during reindex keep {marker}"
    delete_content = f"deletion during reindex remove {marker}"
    DocumentManager.seed_doc_with_content(keep_cc_pair, keep_content, api_key)
    DocumentManager.seed_doc_with_content(delete_cc_pair, delete_content, api_key)
    assert _search_finds(keep_content, admin_user)
    assert _search_finds(delete_content, admin_user)

    original_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]
    ReindexPortManager.start_reindex(admin_user)

    # Deleting a connector triggers request_port_cancel on its running port attempt,
    # so the deletion below is not left blocked waiting on it.
    CCPairManager.delete(delete_cc_pair, user_performing_action=admin_user)
    CCPairManager.wait_for_deletion_completion(
        user_performing_action=admin_user, cc_pair_id=delete_cc_pair.id
    )

    ReindexPortManager.wait_for_reindex_completion(admin_user)
    ReindexPortManager.wait_for_swap(original_index_name, admin_user)

    assert _search_finds(keep_content, admin_user)
    assert not _search_finds(delete_content, admin_user)


def _wait_for_backfill_unpin(timeout: float = MAX_DELAY) -> None:
    """Poll until the promoted index's port_backfill_source_id is cleared -- the port
    drained and check_for_port unpinned the source (the INSTANT completion signal).

    Read from the DB: no HTTP surface exposes the pin, and reindex-progress reports
    total=0 as soon as work drains, a tick before the unpin commits.
    """
    start = time.monotonic()
    while True:
        with get_session_with_current_tenant() as db_session:
            if get_current_search_settings(db_session).port_backfill_source_id is None:
                return
        if time.monotonic() - start > timeout:
            raise TimeoutError(
                f"INSTANT backfill source was not unpinned within {timeout}s"
            )
        time.sleep(5)


def test_reindex_port_instant_switchover(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    """INSTANT promotes the new index immediately, then the port backfills the now-live
    index in the background and unpins the source when done."""
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    marker = uuid4().hex[:8]
    contents = [f"instant switchover port {marker} doc {i}" for i in range(3)]
    for content in contents:
        DocumentManager.seed_doc_with_content(cc_pair, content, api_key)
    for content in contents:
        assert _search_finds(content, admin_user)

    original_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]

    ReindexPortManager.start_reindex(
        admin_user, switchover_type=SwitchoverType.INSTANT.value
    )

    new_settings = ReindexPortManager.wait_for_swap(original_index_name, admin_user)
    assert new_settings["index_name"] != original_index_name

    # This call is not a no-op here: the promoted PRESENT carries port_backfill_source_id,
    # so /reindex-progress keeps reporting the INSTANT backfill's progress, and this blocks
    # until it drains (still failing fast on a FAILED/PAUSED unit). _wait_for_backfill_unpin
    # then waits out the final tick that clears the source pin.
    ReindexPortManager.wait_for_reindex_completion(admin_user)
    _wait_for_backfill_unpin()

    for content in contents:
        assert _search_finds(content, admin_user)

    # Cancel is a no-op here: INSTANT already promoted the new model instead of staging
    # it, so once the backfill drains there is nothing left to revert.
    ReindexPortManager.cancel_reindex(admin_user)
    assert (
        ReindexPortManager.get_current_settings(admin_user)["index_name"]
        == new_settings["index_name"]
    )
