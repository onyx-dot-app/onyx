import time

import pytest

from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode
from onyx.connectors.teams.connector import TeamsConnector
from tests.daily.connectors.teams.models import TeamsThread, readers_of
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.TEAMS_APPLICATION_ID,
    TestSecret.TEAMS_DIRECTORY_ID,
    TestSecret.TEAMS_SECRET,
)

# A thread names its channel's group and the group sync names the people in it,
# so the readers below are the members of that group. A standard channel is
# visible to its team, not the tenant: the team has two members.
TEAM_READERS = {"test@danswerai.onmicrosoft.com", "raunak@onyx.app"}

TEAMS_THREAD = [
    # Posted in "Public Channel"
    TeamsThread(
        thread="This is the first message in Onyx-Testing ...This is a reply!This is a second reply.Third.4th.5",
        readers=TEAM_READERS,
    ),
    TeamsThread(
        thread="Testing body.",
        readers=TEAM_READERS,
    ),
    TeamsThread(
        thread="Hello, world! Nice to meet you all.",
        readers=TEAM_READERS,
    ),
    # Posted in "Private Channel (Raunak is excluded)"
    TeamsThread(
        thread="This is a test post. Raunak should not be able to see this!",
        readers={"test@danswerai.onmicrosoft.com"},
    ),
    # Posted in "Private Channel (Raunak is a member)"
    TeamsThread(
        thread="This is a test post in a private channel that Raunak does have access to! Hello, Raunak!"
        "Hello, world! I am just a member in this chat, but not an owner.",
        readers={"test@danswerai.onmicrosoft.com", "raunak@onyx.app"},
    ),
    # Posted in "Private Channel (Raunak owns)"
    TeamsThread(
        thread="This is a test post in a private channel that Raunak is an owner of! Whoa!"
        "Hello, world! I am an owner of this chat. The power!",
        readers={"test@danswerai.onmicrosoft.com", "raunak@onyx.app"},
    ),
]


@pytest.fixture
def teams_credentials(
    test_secrets: dict[TestSecret, str],
) -> dict[str, str]:
    app_id = test_secrets[TestSecret.TEAMS_APPLICATION_ID]
    dir_id = test_secrets[TestSecret.TEAMS_DIRECTORY_ID]
    secret = test_secrets[TestSecret.TEAMS_SECRET]

    return {
        "teams_client_id": app_id,
        "teams_directory_id": dir_id,
        "teams_client_secret": secret,
    }


@pytest.fixture
def teams_connector(
    teams_credentials: dict[str, str],
) -> TeamsConnector:
    teams_connector = TeamsConnector(teams=["Onyx-Testing"])
    teams_connector.load_credentials(teams_credentials)
    return teams_connector


def _build_map(threads: list[TeamsThread]) -> dict[str, TeamsThread]:
    map: dict[str, TeamsThread] = {}

    for thread in threads:
        assert thread.thread not in map, f"Duplicate thread found in map; {thread=}"
        map[thread.thread] = thread

    return map


def _readers_by_group(
    connector: TeamsConnector, for_indexing: bool
) -> dict[str, set[str]]:
    """The people the group sync puts in each group, under the id a document
    names it by. Indexing stores the source prefix, and the permission sync adds
    it to the ids its walk yields."""
    return {
        (
            build_ext_group_name_for_onyx(group_id, DocumentSource.TEAMS)
            if for_indexing
            else group_id
        ): set(emails)
        for group_id, emails in connector.channel_member_groups()
    }


@pytest.mark.parametrize(
    "expected_teams_threads",
    [TEAMS_THREAD],
)
def test_loading_all_docs_from_teams_connector(
    teams_connector: TeamsConnector,
    expected_teams_threads: list[TeamsThread],
) -> None:
    docs = list(
        load_all_from_connector(
            connector=teams_connector,
            start=0.0,
            end=time.time(),
        ).documents
    )
    readers_by_group = _readers_by_group(teams_connector, for_indexing=True)
    actual_teams_threads = [TeamsThread.from_doc(doc, readers_by_group) for doc in docs]
    actual_teams_threads_map = _build_map(threads=actual_teams_threads)
    expected_teams_threads_map = _build_map(threads=expected_teams_threads)

    # Each thread matches, and its one group holds the readers we expect.
    assert actual_teams_threads_map == expected_teams_threads_map


def test_slim_docs_retrieval_from_teams_connector(
    teams_connector: TeamsConnector,
) -> None:
    slim_docs = [
        slim_doc
        for slim_doc_batch in teams_connector.retrieve_all_slim_docs_perm_sync()
        for slim_doc in slim_doc_batch
    ]
    readers_by_group = _readers_by_group(teams_connector, for_indexing=False)

    for slim_doc in slim_docs:
        if isinstance(slim_doc, HierarchyNode):
            continue
        assert slim_doc.external_access, (
            f"ExternalAccess should always be available, instead got {slim_doc=}"
        )
        readers_of(slim_doc.external_access, readers_by_group)


def test_load_from_checkpoint_with_perm_sync(
    teams_connector: TeamsConnector,
    enable_ee: None,  # noqa: ARG001
) -> None:
    """Test that load_from_checkpoint_with_perm_sync returns documents with external_access.

    This verifies the CheckpointedConnectorWithPermSync interface is properly implemented.
    """
    docs = load_all_from_connector(
        connector=teams_connector,
        start=0.0,
        end=time.time(),
        include_permissions=True,  # Uses load_from_checkpoint_with_perm_sync
    ).documents

    # We should have at least some documents
    assert len(docs) > 0, "Expected to find at least one document"
    readers_by_group = _readers_by_group(teams_connector, for_indexing=True)

    for doc in docs:
        assert doc.external_access is not None, (
            f"Document {doc.id} should have external_access when using perm sync"
        )
        readers_of(doc.external_access, readers_by_group)
