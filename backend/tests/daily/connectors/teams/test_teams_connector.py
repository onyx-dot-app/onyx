import os
import time

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.teams.connector import TeamsConnector
from tests.daily.connectors.teams.models import TeamsThread
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector
from tests.daily.connectors.utils import to_documents


TEAMS_THREAD = [
    # Posted in "Public Channel"
    TeamsThread(
        thread="This is the first message in Onyx-Testing ...This is a reply!This is a second reply.Third.4th.5",
        external_access=ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        ),
    ),
    TeamsThread(
        thread="Testing body.",
        external_access=ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        ),
    ),
    TeamsThread(
        thread="Hello, world! Nice to meet you all.",
        external_access=ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        ),
    ),
    # Posted in "Private Channel (Raunak is excluded)"
    TeamsThread(
        thread="This is a test post. Raunak should not be able to see this!",
        external_access=ExternalAccess(
            external_user_emails=set(["test@danswerai.onmicrosoft.com"]),
            external_user_group_ids=set(),
            is_public=False,
        ),
    ),
    # Posted in "Private Channel (Raunak is a member)"
    TeamsThread(
        thread="This is a test post in a private channel that Raunak does have access to! Hello, Raunak!"
        "Hello, world! I am just a member in this chat, but not an owner.",
        external_access=ExternalAccess(
            external_user_emails=set(
                ["test@danswerai.onmicrosoft.com", "raunak@onyx.app"]
            ),
            external_user_group_ids=set(),
            is_public=False,
        ),
    ),
    # Posted in "Private Channel (Raunak owns)"
    TeamsThread(
        thread="This is a test post in a private channel that Raunak is an owner of! Whoa!"
        "Hello, world! I am an owner of this chat. The power!",
        external_access=ExternalAccess(
            external_user_emails=set(
                ["test@danswerai.onmicrosoft.com", "raunak@onyx.app"]
            ),
            external_user_group_ids=set(),
            is_public=False,
        ),
    ),
]


@pytest.fixture
def teams_credentials() -> dict[str, str]:
    app_id = os.environ["TEAMS_APPLICATION_ID"]
    dir_id = os.environ["TEAMS_DIRECTORY_ID"]
    secret = os.environ["TEAMS_SECRET"]

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


def _assert_is_valid_external_access(
    external_access: ExternalAccess,
) -> None:
    assert (
        not external_access.external_user_group_ids
    ), f"{external_access.external_user_group_ids=} should be empty for MS Teams"

    if external_access.is_public:
        assert (
            not external_access.external_user_emails
        ), f"{external_access.external_user_emails=} should be empty for public channels"
    else:
        assert (
            external_access.external_user_emails
        ), f"{external_access.external_user_emails=} should contains at least one user for private channels"


@pytest.mark.parametrize(
    "expected_teams_threads",
    [TEAMS_THREAD],
)
def test_loading_all_docs_from_teams_connector(
    teams_connector: TeamsConnector,
    expected_teams_threads: list[TeamsThread],
) -> None:
    docs = list(
        to_documents(
            iterator=iter(
                load_everything_from_checkpoint_connector(
                    connector=teams_connector,
                    start=0.0,
                    end=time.time(),
                )
            )
        )
    )
    actual_teams_threads = [TeamsThread.from_doc(doc) for doc in docs]
    actual_teams_threads_map = _build_map(threads=actual_teams_threads)
    expected_teams_threads_map = _build_map(threads=expected_teams_threads)

    # Assert that each thread document matches what we expect.
    assert actual_teams_threads_map == expected_teams_threads_map

    # Assert that all the `ExternalAccess` instances are well-formed.
    for thread in actual_teams_threads:
        _assert_is_valid_external_access(external_access=thread.external_access)


def test_slim_docs_retrieval_from_teams_connector(
    teams_connector: TeamsConnector,
) -> None:
    slim_docs = [
        slim_doc
        for slim_doc_batch in teams_connector.retrieve_all_slim_docs_perm_sync()
        for slim_doc in slim_doc_batch
    ]

    for slim_doc in slim_docs:
        assert (
            slim_doc.external_access
        ), f"ExternalAccess should always be available, instead got {slim_doc=}"
        _assert_is_valid_external_access(external_access=slim_doc.external_access)
