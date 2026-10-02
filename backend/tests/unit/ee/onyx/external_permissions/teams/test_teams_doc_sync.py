"""The Teams permission sync reads threads only while an indexed thread still
lacks its group, and never empties the access of a thread it did not read."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.external_permissions.teams.doc_sync import teams_doc_sync
from onyx.access.models import DocExternalAccess, ExternalAccess
from onyx.connectors.models import SlimDocument
from onyx.connectors.teams import listing as listing_module
from onyx.connectors.teams.connector import TeamsConnector
from onyx.connectors.teams.files import file_document_id
from onyx.connectors.teams.meeting_chats import chat_document_id
from onyx.connectors.teams.transcripts import transcript_document_id
from onyx.connectors.teams.utils import message_delta_url
from onyx.db.utils import DocumentRow, SortOrder
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL_ID,
    TEAM_ID,
    connector,
    graph_client,
    message,
)

MODULE = "ee.onyx.external_permissions.teams.doc_sync"
FILE_ID = file_document_id("item-1")
GONE_FILE_ID = file_document_id("item-gone")
GONE_TRANSCRIPT_ID = transcript_document_id("user-1", "t-gone")
GONE_CHAT_DAY_ID = chat_document_id("user-1", "19:meeting", date(2026, 9, 20))
FILE_ACCESS = ExternalAccess(
    external_user_emails={"ada@example.com"},
    external_user_group_ids=set(),
    is_public=False,
)
DELTA_URL = message_delta_url(TEAM_ID, CHANNEL_ID, 0)


def _cc_pair() -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.connector.connector_specific_config = {}
    cc_pair.connector.indexing_start = None
    cc_pair.credential.credential_json.get_value.return_value = {}
    return cc_pair


def _row(
    doc_id: str, groups: list[str] | None = None, emails: list[str] | None = None
) -> DocumentRow:
    return DocumentRow(
        id=doc_id,
        doc_metadata={},
        external_user_group_ids=groups or [],
        external_user_emails=emails or [],
    )


def _sync(
    teams_connector: MagicMock | TeamsConnector,
    rows: list[DocumentRow],
) -> list:
    """Runs the sync over the rows the task hands it. The ids fetcher is what
    the platform injects too, and this sync must not need it."""

    def existing_rows(sort_order: SortOrder | None) -> list[DocumentRow]:  # noqa: ARG001
        return rows

    def existing_ids() -> list[str]:
        raise AssertionError("the rows already hold the ids, the pair is read once")

    with patch(f"{MODULE}.TeamsConnector", return_value=teams_connector):
        return list(teams_doc_sync(_cc_pair(), existing_rows, existing_ids, None))


def test_threads_that_all_name_a_group_are_left_alone() -> None:
    teams_connector = MagicMock()
    teams_connector.retrieve_all_slim_docs_perm_sync.return_value = iter(
        [[SlimDocument(id=FILE_ID, external_access=FILE_ACCESS)]]
    )
    rows = [
        _row("m1", groups=["teams_team-members:team-1"]),
        _row(FILE_ID, emails=["ada@example.com"]),
        _row(GONE_FILE_ID, emails=["ada@example.com"]),
        _row(GONE_TRANSCRIPT_ID, emails=["ada@example.com"]),
        _row(GONE_CHAT_DAY_ID, emails=["ada@example.com"]),
    ]

    updates = _sync(teams_connector, rows)

    teams_connector.skip_threads_in_perm_sync.assert_called_once()
    # The walk did not list the thread, and its access is not emptied for that.
    # Everything else the walk should have listed still loses its access.
    assert updates[0] == DocExternalAccess(doc_id=FILE_ID, external_access=FILE_ACCESS)
    assert {update.doc_id for update in updates[1:]} == {
        GONE_FILE_ID,
        GONE_TRANSCRIPT_ID,
        GONE_CHAT_DAY_ID,
    }
    assert all(u.external_access == ExternalAccess.empty() for u in updates[1:])


def test_a_thread_without_a_group_brings_the_thread_walk_back() -> None:
    thread_access = ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={"team-members:team-1"},
        is_public=False,
    )
    teams_connector = MagicMock()
    teams_connector.retrieve_all_slim_docs_perm_sync.return_value = iter(
        [[SlimDocument(id="m-old", external_access=thread_access)]]
    )

    # Indexed by a version that put member emails on the thread: only a walk
    # over the threads moves it to its group.
    rows = [_row("m-old", emails=["ada@example.com"]), _row("m-gone", emails=["b@x"])]
    updates = _sync(teams_connector, rows)

    teams_connector.skip_threads_in_perm_sync.assert_not_called()
    assert updates == [
        DocExternalAccess(doc_id="m-old", external_access=thread_access),
        # With threads read, a thread the walk no longer lists loses its access.
        DocExternalAccess(doc_id="m-gone", external_access=ExternalAccess.empty()),
    ]


def test_a_thread_whose_access_was_emptied_does_not_bring_the_walk_back() -> None:
    teams_connector = MagicMock()
    teams_connector.retrieve_all_slim_docs_perm_sync.return_value = iter([])

    # An earlier sync emptied it and pruning will remove it: no group and no
    # people is not the shape an older version left behind.
    updates = _sync(teams_connector, [_row("m-emptied")])

    teams_connector.skip_threads_in_perm_sync.assert_called_once()
    assert updates == []


@pytest.mark.parametrize("a_thread_names_no_group", [False, True])
def test_the_walk_itself_follows_the_decision(
    monkeypatch: pytest.MonkeyPatch, a_thread_names_no_group: bool
) -> None:
    team = MagicMock()
    team.id = TEAM_ID
    channel = MagicMock()
    channel.id = CHANNEL_ID
    channel.properties = {"displayName": "General", "membershipType": "standard"}
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: [channel]
    )
    client = graph_client({DELTA_URL: {"value": [message("m1", "one")]}})
    teams_connector = connector(client)
    monkeypatch.setattr(teams_connector, "load_credentials", MagicMock())

    row = (
        _row("m1", emails=["ada@example.com"])
        if a_thread_names_no_group
        else _row("m1", groups=["teams_team-members:team-1"])
    )
    updates = _sync(teams_connector, [row])

    # The decision is made before the walk, so the walk it runs is the lean one.
    requested = [c.args[0] for c in client.execute_request_direct.call_args_list]
    assert (DELTA_URL in requested) is a_thread_names_no_group
    assert [update.doc_id for update in updates] == (
        ["m1"] if a_thread_names_no_group else []
    )
