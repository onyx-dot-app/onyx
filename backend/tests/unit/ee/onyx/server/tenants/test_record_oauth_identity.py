"""Guards the mapping-table writers: cloud-only sessions, link-once semantics
for subjects, and identity movement through rename and invitation flows.

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
    rekey_user_mapping_email,
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


def test_rekey_normalizes_the_new_address_onto_the_matched_row() -> None:
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.scalar.return_value = None
        mapping = SimpleNamespace(
            email="old@example.com", tenant_id="tenant_abc", active=True
        )
        locked_query = db_session.query.return_value.filter.return_value.with_for_update.return_value
        locked_query.all.return_value = [mapping]
        locked_query.one_or_none.return_value = None
        rekey_user_mapping_email(
            new_email="New@Example.com",
            tenant_id="tenant_abc",
            oauth_identities=[("google", "sub-123")],
        )

    assert mapping.email == "new@example.com"
    db_session.commit.assert_called_once()


def test_rekey_moves_links_off_every_mapping_it_deletes() -> None:
    """A second provider can be linked to a different mapping row in the same
    tenant. That row is deleted here, so its link must move first or ON DELETE
    CASCADE strands the subject and the next login provisions a new tenant."""
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.scalar.return_value = None
        survivor = SimpleNamespace(
            email="old@example.com", tenant_id="tenant_abc", active=True
        )
        doomed = SimpleNamespace(
            email="other@example.com", tenant_id="tenant_abc", active=False
        )
        github_account = SimpleNamespace(
            oauth_name="github",
            account_id="sub-456",
            email="other@example.com",
            tenant_id="tenant_abc",
        )
        mapping_query = MagicMock()
        locked_mapping_query = (
            mapping_query.filter.return_value.with_for_update.return_value
        )
        locked_mapping_query.all.return_value = [survivor, doomed]
        locked_mapping_query.one_or_none.return_value = None
        account_query = MagicMock()
        account_query.filter.return_value.with_for_update.return_value.all.return_value = [
            github_account
        ]
        db_session.query.side_effect = [mapping_query, mapping_query, account_query]

        rekey_user_mapping_email(
            new_email="new@example.com",
            tenant_id="tenant_abc",
            oauth_identities=[("google", "sub-123"), ("github", "sub-456")],
        )

    assert (github_account.email, github_account.tenant_id) == (
        "new@example.com",
        "tenant_abc",
    )
    db_session.flush.assert_called_once_with()
    db_session.delete.assert_called_once_with(doomed)
    db_session.commit.assert_called_once()


def test_rekey_accepts_a_different_linked_provider_identity() -> None:
    """The row may have been linked by the first provider rather than the one
    used for this login, so ownership must match any linked subject."""
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.scalar.return_value = None
        mapping = SimpleNamespace(
            email="old@example.com", tenant_id="tenant_abc", active=True
        )
        locked_query = db_session.query.return_value.filter.return_value.with_for_update.return_value
        locked_query.all.return_value = [mapping]
        locked_query.one_or_none.return_value = None
        rekey_user_mapping_email(
            new_email="new@example.com",
            tenant_id="tenant_abc",
            oauth_identities=[("oidc", "sub-999")],
        )

    assert mapping.email == "new@example.com"
    ownership_filter = db_session.query.return_value.filter.call_args_list[0].args[-1]
    sql = str(
        ownership_filter.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "user_tenant_mapping_oauth_account" in sql
    assert "oidc" in sql
    assert "sub-999" in sql
    db_session.commit.assert_called_once()


def test_rekey_merges_an_existing_destination_row() -> None:
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.scalar.return_value = None
        source = SimpleNamespace(
            email="old@example.com", tenant_id="tenant_abc", active=True
        )
        destination = SimpleNamespace(
            email="new@example.com", tenant_id="tenant_abc", active=False
        )
        google_account = SimpleNamespace(
            oauth_name="google",
            account_id="sub-123",
            email="old@example.com",
            tenant_id="tenant_abc",
        )
        github_account = SimpleNamespace(
            oauth_name="github",
            account_id="sub-456",
            email="old@example.com",
            tenant_id="tenant_abc",
        )
        mapping_query = MagicMock()
        locked_mapping_query = (
            mapping_query.filter.return_value.with_for_update.return_value
        )
        locked_mapping_query.all.return_value = [source]
        locked_mapping_query.one_or_none.return_value = destination
        account_query = MagicMock()
        account_query.filter.return_value.with_for_update.return_value.all.return_value = [
            google_account,
            github_account,
        ]
        db_session.query.side_effect = [mapping_query, mapping_query, account_query]

        rekey_user_mapping_email(
            new_email="new@example.com",
            tenant_id="tenant_abc",
            oauth_identities=[("google", "sub-123")],
        )

    assert destination.active is True
    assert {
        (account.email, account.tenant_id)
        for account in (google_account, github_account)
    } == {("new@example.com", "tenant_abc")}
    db_session.flush.assert_called_once_with()
    db_session.delete.assert_called_once_with(source)
    db_session.commit.assert_called_once()


def test_rekey_moves_the_row_the_caller_names() -> None:
    """A tenant can hold several of this user's rows, and the active-email index
    is per address rather than per tenant, so more than one can be active.
    Choosing among them by `active` alone renames whichever row sorted first."""
    other_active = SimpleNamespace(
        email="other@example.com", tenant_id="tenant_abc", active=True
    )
    renamed = SimpleNamespace(
        email="old@example.com", tenant_id="tenant_abc", active=True
    )
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.scalar.return_value = None
        mapping_query = MagicMock()
        locked = mapping_query.filter.return_value.with_for_update.return_value
        # The unrelated active row sorts first.
        locked.all.return_value = [other_active, renamed]
        locked.one_or_none.return_value = None
        account_query = MagicMock()
        account_query.filter.return_value.with_for_update.return_value.all.return_value = []
        db_session.query.side_effect = [mapping_query, mapping_query, account_query]

        rekey_user_mapping_email(
            new_email="new@example.com",
            tenant_id="tenant_abc",
            oauth_identities=[("google", "sub-123")],
            previous_email="old@example.com",
        )

    assert renamed.email == "new@example.com"
    assert other_active.email == "other@example.com"


def test_rekey_leaves_a_co_owners_subject_link_alone() -> None:
    """Several subjects can share one mapping row and they are not always the
    same person's, since a declined rekey parks a row under its old address and
    an invite for the next holder reuses it."""
    source = SimpleNamespace(
        email="old@example.com", tenant_id="tenant_abc", active=True
    )
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.scalar.return_value = None
        mapping_query = MagicMock()
        locked = mapping_query.filter.return_value.with_for_update.return_value
        locked.all.return_value = [source]
        locked.one_or_none.return_value = SimpleNamespace(
            email="new@example.com", tenant_id="tenant_abc", active=False
        )
        account_query = MagicMock()
        account_query.filter.return_value.with_for_update.return_value.all.return_value = []
        db_session.query.side_effect = [mapping_query, mapping_query, account_query]

        rekey_user_mapping_email(
            new_email="new@example.com",
            tenant_id="tenant_abc",
            oauth_identities=[("google", "sub-123")],
            previous_email="old@example.com",
        )

    # Mocks do not evaluate filters, so assert the association query is scoped by
    # subject as well as by row. Without it a co-owner's link moves too.
    sql = str(
        account_query.filter.call_args.args[1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "oauth_name" in sql
    assert "sub-123" in sql


def test_rekey_declines_when_a_row_carries_another_identitys_subject() -> None:
    """A parked row can pick up a second person's subject once an invite hands
    the address on. Renaming it promotes them into this workspace, and deleting
    it cascades their membership away, so touch neither."""
    source = SimpleNamespace(
        email="old@example.com", tenant_id="tenant_abc", active=True
    )
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        mapping_query = MagicMock()
        locked = mapping_query.filter.return_value.with_for_update.return_value
        locked.all.return_value = [source]
        locked.one_or_none.return_value = None
        db_session.query.side_effect = [mapping_query, mapping_query]
        # Address is free, but a subject outside this login's identities is
        # attached to one of the candidate rows.
        db_session.scalar.side_effect = [None, "someone-elses-sub"]

        rekey_user_mapping_email(
            new_email="new@example.com",
            tenant_id="tenant_abc",
            oauth_identities=[("google", "sub-123")],
            previous_email="old@example.com",
        )

    assert source.email == "old@example.com"
    db_session.delete.assert_not_called()
    db_session.commit.assert_not_called()


def test_rekey_declines_when_the_address_is_held_elsewhere() -> None:
    """uq_user_active_email_idx spans tenants. Moving the row onto a taken
    address makes the other tenant's row answer this user's next login, so the
    membership stays under the address whose subject link still resolves it."""
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session") as session_ctx,
    ):
        db_session = session_ctx.return_value.__enter__.return_value
        db_session.scalar.return_value = "tenant_other"

        rekey_user_mapping_email(
            new_email="new@example.com",
            tenant_id="tenant_abc",
            oauth_identities=[("google", "sub-123")],
        )

    db_session.query.assert_not_called()
    db_session.commit.assert_not_called()


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
