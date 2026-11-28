from typing import Any
from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.zendesk.access import (
    article_access,
    ticket_access,
)
from onyx.access.models import ExternalAccess
from onyx.connectors.models import Document, SlimDocument
from onyx.connectors.zendesk.access import grants_end_users, has_internal_note
from onyx.connectors.zendesk.connector import ZendeskConnector
from onyx.connectors.zendesk.models import (
    ZendeskGroup,
    ZendeskOrganization,
    ZendeskUser,
)
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector
from tests.unit.onyx.connectors.zendesk.utils import set_request_function

SUBDOMAIN = "Acme"
ADMIN = ZendeskUser(id=1, email="Admin@acme.com", role="admin")
AGENT = ZendeskUser(id=2, email="agent@acme.com", role="agent")
REQUESTER = ZendeskUser(id=3, email="customer@example.com", role="end-user")
CC = ZendeskUser(id=4, email="cc@example.com", role="end-user")
SUSPENDED = ZendeskUser(id=5, email="gone@example.com", role="agent", suspended=True)
USERS = {user.id: user for user in (ADMIN, AGENT, REQUESTER, CC, SUSPENDED)}
PRIVATE_GROUP = ZendeskGroup(id=10, is_public=False)
PUBLIC_GROUP = ZendeskGroup(id=11, is_public=True)
GROUPS = {group.id: group for group in (PRIVATE_GROUP, PUBLIC_GROUP)}
SHARED_ORG = ZendeskOrganization(id=20, shared_tickets=True)
ORGS = {SHARED_ORG.id: SHARED_ORG}


def _ticket(**fields: Any) -> dict[str, Any]:
    return {
        "id": 100,
        "requester_id": REQUESTER.id,
        "assignee_id": AGENT.id,
        "group_id": PRIVATE_GROUP.id,
        "organization_id": SHARED_ORG.id,
        "email_cc_ids": [CC.id],
        "follower_ids": [SUSPENDED.id],
        "collaborator_ids": [CC.id, SUSPENDED.id],
        **fields,
    }


def test_article_without_segments_is_for_signed_in_users() -> None:
    access = article_access(SUBDOMAIN, {"id": 1, "user_segment_ids": []}, False)
    assert access == ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={"acme:all_users"},
        is_public=False,
    )


def test_article_without_segments_on_an_open_help_center_is_public() -> None:
    assert article_access(SUBDOMAIN, {"id": 1}, True).is_public


def test_article_with_segments_names_them_and_guide_managers() -> None:
    access = article_access(SUBDOMAIN, {"id": 1, "user_segment_ids": [7, 8]}, True)
    assert not access.is_public
    assert access.external_user_group_ids == {
        "acme:guide_managers",
        "acme:segment:7",
        "acme:segment:8",
    }


def test_ticket_with_internal_note_grants_agents_only() -> None:
    access = ticket_access(SUBDOMAIN, _ticket(), USERS, GROUPS, ORGS, True)
    assert access.external_user_group_ids == {
        "acme:admins",
        "acme:all_tickets",
        "acme:group:10",
        "acme:org_agents:20",
    }
    # The suspended follower and the end users get nothing.
    assert access.external_user_emails == {"agent@acme.com"}
    assert not access.is_public


def test_ticket_without_internal_note_grants_end_users() -> None:
    access = ticket_access(
        SUBDOMAIN, _ticket(group_id=PUBLIC_GROUP.id), USERS, GROUPS, ORGS, False
    )
    assert access.external_user_group_ids == {
        "acme:admins",
        "acme:all_tickets",
        "acme:group:11",
        "acme:public_groups",
        "acme:org_agents:20",
        "acme:org_end_users:20",
    }
    assert access.external_user_emails == {
        "agent@acme.com",
        "customer@example.com",
        "cc@example.com",
    }


def test_unknown_users_groups_and_orgs_grant_nothing() -> None:
    access = ticket_access(SUBDOMAIN, _ticket(), {}, {}, {}, False)
    assert access.external_user_emails == set()
    assert "acme:public_groups" not in access.external_user_group_ids
    assert "acme:org_end_users:20" not in access.external_user_group_ids


def test_grants_end_users() -> None:
    assert grants_end_users(_ticket(), USERS, ORGS)
    agents_only = _ticket(
        requester_id=AGENT.id,
        email_cc_ids=[],
        collaborator_ids=[],
        organization_id=None,
    )
    assert not grants_end_users(agents_only, USERS, ORGS)
    assert grants_end_users(
        {**agents_only, "organization_id": SHARED_ORG.id}, USERS, ORGS
    )


def test_has_internal_note() -> None:
    assert not has_internal_note([{"public": True}])
    assert has_internal_note([{"public": True}, {"public": False}])
    # Missing flags fail closed.
    assert has_internal_note([{}])


def _ticket_page(ticket: dict[str, Any]) -> dict[str, Any]:
    return {
        "tickets": [ticket],
        "end_of_stream": True,
        "end_time": 1,
        "users": [user.model_dump() for user in USERS.values()],
        "groups": [group.model_dump() for group in GROUPS.values()],
        "organizations": [org.model_dump() for org in ORGS.values()],
    }


def test_perm_sync_slim_reads_comments_only_when_end_users_would_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents_only = _ticket(
        id=101,
        requester_id=AGENT.id,
        email_cc_ids=[],
        collaborator_ids=[],
        organization_id=None,
    )
    responses: dict[str, Any] = {
        "incremental/tickets.json": {
            **_ticket_page(_ticket()),
            "tickets": [_ticket(), agents_only],
        },
        "tickets/100/comments": {"comments": [{"public": True}]},
    }
    make_request = MagicMock(side_effect=lambda endpoint, _params: responses[endpoint])
    connector = ZendeskConnector(content_type="tickets", grant_end_users=True)
    set_request_function(monkeypatch, connector, make_request)

    docs = [
        doc for batch in connector.retrieve_all_slim_docs_perm_sync() for doc in batch
    ]

    endpoints = [c.args[0] for c in make_request.call_args_list]
    assert endpoints.count("tickets/100/comments") == 1
    assert "tickets/101/comments" not in endpoints
    access = {
        doc.id: doc.external_access for doc in docs if isinstance(doc, SlimDocument)
    }
    assert access["zendesk_ticket_100"] is not None
    assert "customer@example.com" in access["zendesk_ticket_100"].external_user_emails
    assert access["zendesk_ticket_101"] is not None
    assert access["zendesk_ticket_101"].external_user_emails == {"agent@acme.com"}


def test_pruning_slim_reads_no_access(monkeypatch: pytest.MonkeyPatch) -> None:
    make_request = MagicMock(
        return_value={"tickets": [_ticket()], "end_of_stream": True, "end_time": 1}
    )
    connector = ZendeskConnector(content_type="tickets", grant_end_users=True)
    set_request_function(monkeypatch, connector, make_request)

    docs = [doc for batch in connector.retrieve_all_slim_docs() for doc in batch]

    assert [c.args[0] for c in make_request.call_args_list] == [
        "incremental/tickets.json"
    ]
    assert "include" not in make_request.call_args_list[0].args[1]
    assert all(
        isinstance(doc, SlimDocument) and doc.external_access is None for doc in docs
    )


def test_perm_sync_indexing_uses_the_comments_it_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: dict[str, Any] = {
        "guide/content_tags": {"records": []},
        "incremental/tickets.json": _ticket_page(_ticket()),
        "tickets/100/comments": {
            "comments": [
                {"public": True, "body": "question", "author_id": AGENT.id},
                {"public": False, "body": "internal", "author_id": AGENT.id},
            ]
        },
        f"users/{AGENT.id}": {"user": AGENT.model_dump()},
    }
    make_request = MagicMock(side_effect=lambda endpoint, _params: responses[endpoint])
    connector = ZendeskConnector(content_type="tickets", grant_end_users=True)
    set_request_function(monkeypatch, connector, make_request)
    # The helper drives load_from_checkpoint; point it at the perm-sync path.
    monkeypatch.setattr(
        connector, "load_from_checkpoint", connector.load_from_checkpoint_with_perm_sync
    )

    outputs = load_everything_from_checkpoint_connector(connector, 0, 2_000_000_000)

    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert len(docs) == 1
    assert docs[0].external_access is not None
    assert docs[0].external_access.external_user_emails == {"agent@acme.com"}
    endpoints = [c.args[0] for c in make_request.call_args_list]
    assert endpoints.count("tickets/100/comments") == 1


def test_unknown_role_counts_as_end_user() -> None:
    unknown = ZendeskUser(id=6, email="who@example.com", role=None)
    ticket = _ticket(requester_id=unknown.id, email_cc_ids=[], collaborator_ids=[])
    users = {**USERS, unknown.id: unknown}
    assert grants_end_users(ticket, users, {})
    access = ticket_access(SUBDOMAIN, ticket, users, GROUPS, {}, True)
    assert "who@example.com" not in access.external_user_emails


def test_slim_walks_skip_what_indexing_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted = _ticket(id=102, status="deleted")
    page = {**_ticket_page(_ticket()), "tickets": [deleted]}
    make_request = MagicMock(return_value=page)
    connector = ZendeskConnector(content_type="tickets", grant_end_users=True)
    set_request_function(monkeypatch, connector, make_request)

    for walk in (
        connector.retrieve_all_slim_docs,
        connector.retrieve_all_slim_docs_perm_sync,
    ):
        assert [doc for batch in walk() for doc in batch] == []
    # The deleted ticket's comments are never read.
    assert all(
        c.args[0] == "incremental/tickets.json" for c in make_request.call_args_list
    )


def test_skipped_articles_are_not_listed_or_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    articles = [
        {"id": 1, "body": "<p>x</p>", "draft": True},
        {"id": 2, "body": None},
        {"id": 3, "body": "<p>x</p>", "user_segment_ids": []},
    ]
    make_request = MagicMock(
        return_value={"articles": articles, "meta": {"has_more": False}}
    )
    connector = ZendeskConnector(content_type="articles")
    set_request_function(monkeypatch, connector, make_request)
    probe = MagicMock(return_value=False)
    monkeypatch.setattr(connector.ops, "is_article_public", probe)

    docs = [
        doc for batch in connector.retrieve_all_slim_docs_perm_sync() for doc in batch
    ]

    assert [doc.id for doc in docs if isinstance(doc, SlimDocument)] == ["article:3"]
    assert len(docs) == 1
    probe.assert_called_once_with(article_id=3)


def test_missing_comments_count_as_internal_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.connectors.zendesk.source_operations import ZendeskRequestError

    def make_request(endpoint: str, _params: dict[str, Any]) -> dict[str, Any]:
        if endpoint == "tickets/100/comments":
            raise ZendeskRequestError(404, "gone")
        return _ticket_page(_ticket())

    connector = ZendeskConnector(content_type="tickets", grant_end_users=True)
    set_request_function(monkeypatch, connector, make_request)

    docs = [
        doc for batch in connector.retrieve_all_slim_docs_perm_sync() for doc in batch
    ]

    assert isinstance(docs[0], SlimDocument)
    assert docs[0].external_access is not None
    assert docs[0].external_access.external_user_emails == {"agent@acme.com"}


def test_end_users_are_not_granted_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    make_request = MagicMock(return_value=_ticket_page(_ticket()))
    connector = ZendeskConnector(content_type="tickets")
    set_request_function(monkeypatch, connector, make_request)

    docs = [
        doc for batch in connector.retrieve_all_slim_docs_perm_sync() for doc in batch
    ]

    # No comment read, and only agents are granted.
    assert all(
        c.args[0] == "incremental/tickets.json" for c in make_request.call_args_list
    )
    assert isinstance(docs[0], SlimDocument)
    assert docs[0].external_access is not None
    assert docs[0].external_access.external_user_emails == {"agent@acme.com"}
    assert (
        "acme:org_end_users:20" not in docs[0].external_access.external_user_group_ids
    )


def test_ticket_without_group_is_for_public_group_agents() -> None:
    access = ticket_access(SUBDOMAIN, _ticket(group_id=None), USERS, GROUPS, ORGS, True)
    assert "acme:public_groups" in access.external_user_group_ids


def test_a_stop_before_the_last_batch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A listing smaller than one batch must not end normally after a stop."""
    make_request = MagicMock(
        return_value={
            "articles": [{"id": 1, "body": "<p>x</p>", "user_segment_ids": [3]}],
            "meta": {"has_more": False},
        }
    )
    connector = ZendeskConnector(content_type="articles")
    set_request_function(monkeypatch, connector, make_request)
    callback = MagicMock()
    callback.should_stop.side_effect = [False, True]

    with pytest.raises(RuntimeError):
        list(connector.retrieve_all_slim_docs(callback=callback))
