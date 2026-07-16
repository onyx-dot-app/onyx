"""End-to-end integration tests for the reindex *port* flow.

These exercise the whole live wiring that the unit / external-dependency-unit tests
cannot: beat fires check_for_port -> the docprocessing worker consumes the `port`
queue and re-embeds PRESENT->FUTURE -> the /reindex-progress HTTP surface reflects
state -> the beat-driven index swap promotes FUTURE->PRESENT -> search hits the new
index. Everything is driven through the real API with no mocking.

Docs are seeded into PRESENT via the ingestion API *before* the reindex starts, so the
port copy (not a connector re-fetch) is the only thing that can populate the new index.
Reindexing to the current embedding model creates a new ALT index, so the swap is
observable as a change in the current index_name.
"""

import os
import time
from uuid import uuid4

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.search_settings import get_current_search_settings
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import MAX_DELAY
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.reindex_port import ReindexPortManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

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

    # Baseline: the docs are searchable on the PRESENT index.
    for content in contents:
        assert _search_finds(content, admin_user)

    original_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]

    ReindexPortManager.start_reindex(admin_user)
    ReindexPortManager.wait_for_reindex_completion(admin_user)
    new_settings = ReindexPortManager.wait_for_swap(original_index_name, admin_user)
    assert new_settings["index_name"] != original_index_name

    # The port re-embedded PRESENT -> FUTURE and the swap promoted it: the docs are
    # still searchable, now served entirely from the freshly built index.
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

    # Baseline ACL: the group member sees it, an outsider does not.
    assert _search_finds(doc_content, privileged_user)
    assert not _search_finds(doc_content, blocked_user)

    original_index_name = ReindexPortManager.get_current_settings(admin_user)[
        "index_name"
    ]
    ReindexPortManager.start_reindex(admin_user)
    ReindexPortManager.wait_for_reindex_completion(admin_user)
    ReindexPortManager.wait_for_swap(original_index_name, admin_user)

    # After the port copied chunks into the new index and it was promoted, the ACL is
    # preserved: the member still sees it, the outsider still does not.
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

    # Progress scopes every portable cc_pair (our N + the default ingestion pair).
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

    # The FUTURE is gone, so there is no active port target and no swap can happen.
    assert ReindexPortManager.get_secondary_settings(admin_user) is None
    assert ReindexPortManager.get_progress(admin_user).total == 0
    assert (
        ReindexPortManager.get_current_settings(admin_user)["index_name"]
        == original_index_name
    )

    # PRESENT is untouched and there is no late swap: the doc stays searchable and the
    # current index_name does not change.
    time.sleep(5)
    assert (
        ReindexPortManager.get_current_settings(admin_user)["index_name"]
        == original_index_name
    )
    assert _search_finds(content, admin_user)


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

    # Delete one connector while the reindex is live. The port must ack the cancel so
    # the deletion is not blocked waiting on it (request_port_cancel coordination).
    CCPairManager.delete(delete_cc_pair, user_performing_action=admin_user)
    CCPairManager.wait_for_deletion_completion(
        user_performing_action=admin_user, cc_pair_id=delete_cc_pair.id
    )

    # The reindex still completes for the surviving connector and swaps.
    ReindexPortManager.wait_for_reindex_completion(admin_user)
    ReindexPortManager.wait_for_swap(original_index_name, admin_user)

    assert _search_finds(keep_content, admin_user)
    # The deleted connector's doc is absent from the promoted index.
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

    ReindexPortManager.start_reindex(admin_user, switchover_type="instant")

    # INSTANT promotes the new (initially empty) index immediately, before the port runs.
    new_settings = ReindexPortManager.wait_for_swap(original_index_name, admin_user)
    assert new_settings["index_name"] != original_index_name

    # The port then backfills the now-live index. INSTANT keeps reporting progress against
    # the promoted PRESENT (it carries port_backfill_source_id), so this blocks while the
    # backfill drains and fast-fails on a FAILED/PAUSED unit -- it is NOT a no-op here.
    # _wait_for_backfill_unpin then waits out the final tick that clears the source pin.
    ReindexPortManager.wait_for_reindex_completion(admin_user)
    _wait_for_backfill_unpin()

    # Every doc is served from the backfilled live index.
    for content in contents:
        assert _search_finds(content, admin_user)
