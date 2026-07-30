"""Guards that `record_oauth_identity` only touches the mapping tables on cloud
and never re-links a subject that already belongs to another mapping, and that
invitation flows move subject links only with the authenticated user.

The `public.user_tenant_mapping*` tables are created by the `alembic_tenants`
tree, which only multi-tenant deployments run. Opening a session against them
anywhere else would raise on every OAuth login, so the `MULTI_TENANT` guard is
load-bearing rather than an optimization.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

from ee.onyx.db.user_tenant_mapping import (
    accept_user_invite,
    approve_user_invite,
    record_oauth_identity,
)

_MAPPING_MODULE = "ee.onyx.db.user_tenant_mapping"


def _run(
    *,
    multi_tenant: bool,
    mapping_exists: bool = True,
    insert_result: tuple[str, str] | None = ("user@example.com", "tenant_abc"),
    owner: tuple[str, str] | None = None,
) -> MagicMock:
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", multi_tenant),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.get.return_value = MagicMock() if mapping_exists else None
        insert_execute = MagicMock()
        insert_execute.one_or_none.return_value = insert_result
        owner_execute = MagicMock()
        owner_execute.one_or_none.return_value = owner
        db_session.execute.side_effect = [insert_execute, owner_execute]
        record_oauth_identity(
            email="User@example.com",
            tenant_id="tenant_abc",
            oauth_name="google",
            account_id="sub-123",
        )
    return session_ctx


def _compiled_insert_sql(session_ctx: MagicMock) -> str:
    db_session = session_ctx.return_value.__enter__.return_value
    statement = db_session.execute.call_args_list[0].args[0]
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_single_tenant_opens_no_session() -> None:
    assert _run(multi_tenant=False).call_count == 0


def test_multi_tenant_links_the_subject_to_the_mapping() -> None:
    session_ctx = _run(multi_tenant=True)
    assert session_ctx.call_count == 1

    db_session = session_ctx.return_value.__enter__.return_value
    assert db_session.execute.call_count == 1
    db_session.commit.assert_called_once()

    sql = _compiled_insert_sql(session_ctx)
    assert "user_tenant_mapping_oauth_account" in sql
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql
    assert "'user@example.com'" in sql


def test_missing_mapping_row_links_nothing() -> None:
    session_ctx = _run(multi_tenant=True, mapping_exists=False)

    db_session = session_ctx.return_value.__enter__.return_value
    db_session.execute.assert_not_called()
    db_session.commit.assert_not_called()


def test_subject_linked_elsewhere_is_not_re_linked() -> None:
    """Address reassignment: the new holder of an address must not inherit a
    subject link that still belongs to the renamed user's mapping."""
    session_ctx = _run(
        multi_tenant=True,
        insert_result=None,
        owner=("other@example.com", "tenant_other"),
    )

    db_session = session_ctx.return_value.__enter__.return_value
    assert db_session.execute.call_count == 2
    db_session.commit.assert_not_called()


def test_repeat_login_for_the_linked_mapping_is_idempotent() -> None:
    session_ctx = _run(
        multi_tenant=True,
        insert_result=None,
        owner=("user@example.com", "tenant_abc"),
    )

    db_session = session_ctx.return_value.__enter__.return_value
    db_session.commit.assert_called_once()


def test_accept_invite_moves_every_link_off_a_row_this_identity_owns() -> None:
    """Links are selected by the row a presented subject already links to, then
    ALL of that row's links move. Selecting by presented identity alone would
    leave the siblings on a row that is then deleted, and ON DELETE CASCADE
    strands them. The old membership is also flushed away before the
    destination activates, because the active-email unique index is
    immediate."""
    old_mapping = SimpleNamespace(
        email="renamed@example.com", tenant_id="tenant_old", active=True
    )
    destination = SimpleNamespace(
        email="user@example.com", tenant_id="tenant_new", active=False
    )
    google_account = SimpleNamespace(
        oauth_name="google",
        account_id="sub-123",
        email="renamed@example.com",
        tenant_id="tenant_old",
    )
    # Never presented to accept_user_invite below, yet must still move.
    github_account = SimpleNamespace(
        oauth_name="github",
        account_id="sub-456",
        email="renamed@example.com",
        tenant_id="tenant_old",
    )
    with (
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
        patch(f"{_MAPPING_MODULE}.get_invited_users", return_value=[]),
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        mapping_query = MagicMock()
        mapping_query.filter.return_value.with_for_update.return_value.all.return_value = [
            old_mapping,
            destination,
        ]
        account_query = MagicMock()
        account_query.filter.return_value.with_for_update.return_value.all.return_value = [
            google_account,
            github_account,
        ]
        db_session.query.side_effect = [mapping_query, account_query]
        db_session.execute.return_value.all.return_value = [
            ("google", "sub-123", "renamed@example.com", "tenant_old")
        ]
        events: list[tuple[str, object]] = []
        db_session.delete.side_effect = lambda deleted: events.append(
            ("delete", deleted)
        )
        db_session.flush.side_effect = lambda: events.append(
            ("flush_destination_active", destination.active)
        )
        db_session.commit.side_effect = lambda: events.append(("commit", None))

        accept_user_invite("User@Example.com", "tenant_new", [("google", "sub-123")])

    # Mocks do not evaluate filters, so assert the association query is keyed by
    # the owning row rather than by the presented identities. Keying by identity
    # silently drops github below.
    association_filter = account_query.filter.call_args.args[-1]
    sql = str(
        association_filter.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "'renamed@example.com'" in sql and "'tenant_old'" in sql
    assert "sub-123" not in sql

    assert destination.active is True
    assert {
        (account.email, account.tenant_id)
        for account in (google_account, github_account)
    } == {("user@example.com", "tenant_new")}
    assert db_session.add_all.call_args.args[0] == []
    assert events == [
        ("flush_destination_active", False),
        ("delete", old_mapping),
        ("flush_destination_active", False),
        ("commit", None),
    ]
    db_session.delete.assert_called_once_with(old_mapping)


def test_accept_invite_leaves_a_former_holders_links_alone() -> None:
    """An address can be reassigned, so a mapping matched by address alone may
    be a previous holder's. Moving its links would attach a stranger's subject
    to this workspace, and subject-first resolution would then route them here."""
    stranger_mapping = SimpleNamespace(
        email="user@example.com", tenant_id="tenant_stranger", active=True
    )
    destination = SimpleNamespace(
        email="user@example.com", tenant_id="tenant_new", active=False
    )
    with (
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
        patch(f"{_MAPPING_MODULE}.get_invited_users", return_value=[]),
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        mapping_query = MagicMock()
        mapping_query.filter.return_value.with_for_update.return_value.all.return_value = [
            stranger_mapping,
            destination,
        ]
        account_query = MagicMock()
        account_query.filter.return_value.with_for_update.return_value.all.return_value = []
        db_session.query.side_effect = [mapping_query, account_query]
        # The accepting user's subject links nowhere yet, so no row is provably
        # theirs and nothing may be moved.
        db_session.execute.return_value.all.return_value = []

        accept_user_invite("user@example.com", "tenant_new", [("google", "sub-123")])

    # The association table is never queried at all when no row is owned.
    assert db_session.query.call_count == 1
    created = db_session.add_all.call_args.args[0]
    assert [(a.oauth_name, a.account_id) for a in created] == [("google", "sub-123")]
    assert destination.active is True
    # Deactivated to free the address, never deleted: the row and its subject
    # links belong to whoever held the address before.
    db_session.delete.assert_not_called()
    assert stranger_mapping.active is False


def test_accept_invite_activates_the_row_for_the_accepted_address() -> None:
    """A tenant can hold several rows for one user, keyed by different addresses.
    The invitation belongs to the address being accepted, so selecting on the
    tenant alone would activate whichever row the query happened to return."""
    stale_same_tenant = SimpleNamespace(
        email="old@example.com", tenant_id="tenant_new", active=False
    )
    invitation = SimpleNamespace(
        email="new@example.com", tenant_id="tenant_new", active=False
    )
    with (
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
        patch(f"{_MAPPING_MODULE}.get_invited_users", return_value=[]),
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        mapping_query = MagicMock()
        # The stale row sorts first, which is what the tenant-only predicate hit.
        mapping_query.filter.return_value.with_for_update.return_value.all.return_value = [
            stale_same_tenant,
            invitation,
        ]
        db_session.query.side_effect = [mapping_query]
        db_session.execute.return_value.all.return_value = []

        accept_user_invite("new@example.com", "tenant_new", [("google", "sub-123")])

    assert invitation.active is True
    assert stale_same_tenant.active is False


def test_accept_invite_links_subjects_that_were_never_linked() -> None:
    """A user can accept before their first OAuth login links anything, so
    acceptance itself must create the missing links on the destination."""
    destination = SimpleNamespace(
        email="user@example.com", tenant_id="tenant_new", active=False
    )
    with (
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
        patch(f"{_MAPPING_MODULE}.get_invited_users", return_value=[]),
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        mapping_query = MagicMock()
        mapping_query.filter.return_value.with_for_update.return_value.all.return_value = [
            destination
        ]
        account_query = MagicMock()
        account_query.filter.return_value.with_for_update.return_value.all.return_value = []
        db_session.query.side_effect = [mapping_query, account_query]
        db_session.execute.return_value.all.return_value = []

        accept_user_invite("user@example.com", "tenant_new", [("google", "sub-123")])

    created = db_session.add_all.call_args.args[0]
    assert [
        (account.oauth_name, account.account_id, account.email, account.tenant_id)
        for account in created
    ] == [("google", "sub-123", "user@example.com", "tenant_new")]
    assert destination.active is True


def test_approve_invite_does_not_transfer_subjects_by_email() -> None:
    """Approval is an email-level admin action: the address may have been
    reassigned at the IdP, so it must never move another identity's links."""
    existing_mapping = SimpleNamespace(
        email="user@example.com", tenant_id="tenant_old", active=True
    )
    with (
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
        patch(f"{_MAPPING_MODULE}.get_pending_users", return_value=[]),
        patch(f"{_MAPPING_MODULE}.get_invited_users", return_value=[]),
        patch(f"{_MAPPING_MODULE}.write_invited_users"),
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.query.return_value.filter.return_value.with_for_update.return_value.all.return_value = [
            existing_mapping
        ]

        approve_user_invite("User@Example.com", "tenant_new")

    added_mapping = db_session.add.call_args.args[0]
    assert added_mapping.email == "user@example.com"
    assert added_mapping.tenant_id == "tenant_new"
    assert db_session.query.call_count == 1
    db_session.add_all.assert_not_called()
    # Deleting would cascade away subject links this approval cannot prove are
    # the approved user's, so the rival row is only deactivated.
    db_session.delete.assert_not_called()
    assert existing_mapping.active is False
