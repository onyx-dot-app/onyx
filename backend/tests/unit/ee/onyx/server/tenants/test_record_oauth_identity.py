"""Guards that `record_oauth_identity` only touches the mapping tables on cloud
and never re-links a subject that already belongs to another mapping.

The `public.user_tenant_mapping*` tables are created by the `alembic_tenants`
tree, which only multi-tenant deployments run. Opening a session against them
anywhere else would raise on every OAuth login, so the `MULTI_TENANT` guard is
load-bearing rather than an optimization.
"""

from unittest.mock import MagicMock, patch

from ee.onyx.db.user_tenant_mapping import record_oauth_identity

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
    from sqlalchemy.dialects import postgresql

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
