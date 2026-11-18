"""Exercise the migration hook with historical DDL shapes and new revisions."""

from pathlib import Path
from textwrap import indent

import pytest
from lint import check_migration_design

_CASES = [
    # f11b408e39d3
    (
        "not-valid",
        'op.create_check_constraint("lowercase", "user", "email = lower(email)")',
        'op.create_check_constraint("lowercase", "user", "email = lower(email)", '
        "postgresql_not_valid=True)",
    ),
    # 9d8f310ac672
    (
        "not-valid",
        'op.create_foreign_key("invocation", "chat_message", "tool_call", ["call"], ["id"])',
        'op.create_foreign_key("invocation", "chat_message", "tool_call", ["call"], ["id"], '
        "postgresql_not_valid=True)",
    ),
    # cdec9dd9ca3d
    (
        "deferrable",
        'op.create_table("plugin", sa.ForeignKeyConstraint(["id"], ["version.id"], deferrable=True))',
        'op.create_table("plugin", sa.ForeignKeyConstraint(["id"], ["version.id"]))',
    ),
    # 3c5e35aa9af0
    (
        "not-null",
        'op.add_column("connector_credential_pair", sa.Column("total", sa.Integer(), nullable=False))',
        'op.add_column("connector_credential_pair", sa.Column("total", sa.Integer(), '
        'nullable=False, server_default="0"))',
    ),
    # 0f7ff6d75b57 and 9d8f310ac672
    (
        "blocking-index",
        'op.create_index("ix_status", "index_attempt", ["status"], postgresql_concurrently=True)',
        "bind = op.get_bind()\nbind.commit()\n"
        'with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:\n'
        '    conn.exec_driver_sql("CREATE INDEX CONCURRENTLY ix_status ON index_attempt (status)")',
    ),
]


def _revision(directory: Path, revision: str, parent: str | None, body: str) -> Path:
    path = directory / f"{revision}.py"
    path.write_text(
        f"revision: str = {revision!r}\ndown_revision = {parent!r}\n"
        "def upgrade() -> None:\n" + indent(body, "    ") + "\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(("rule", "bad", "clean"), _CASES)
def test_new_revision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    rule: str,
    bad: str,
    clean: str,
) -> None:
    monkeypatch.setattr(check_migration_design, "_MARKERS", {tmp_path: "marker"})
    _revision(tmp_path, "base", None, bad)
    _revision(tmp_path, "marker", "base", bad)
    assert check_migration_design.main() == 0
    path = _revision(tmp_path, "new", "marker", bad)
    assert check_migration_design.main() == 1
    assert f"{path}:4: {rule}:" in capsys.readouterr().out
    _revision(tmp_path, "new", "marker", clean)
    assert check_migration_design.main() == 0
    _revision(tmp_path, "new", "marker", bad + f"  # migration-design: allow {rule} -")
    assert check_migration_design.main() == 1
    _revision(
        tmp_path,
        "new",
        "marker",
        bad + f"  # migration-design: allow {rule} - Intentional test",
    )
    assert check_migration_design.main() == 0


def test_tables_created_in_same_revision(tmp_path: Path) -> None:
    _revision(tmp_path, "marker", None, "pass")
    _revision(
        tmp_path,
        "new",
        "marker",
        'op.create_table("events")\n'
        'op.create_index("ix", "events", ["created_at"])\n'
        'op.add_column("events", sa.Column("name", sa.String(), nullable=False))\n'
        'op.create_check_constraint("ck", "events", "name <> \'\'")',
    )
    assert list(check_migration_design.check_chain(tmp_path, "marker")) == []


def test_second_head_and_merge(tmp_path: Path) -> None:
    _revision(tmp_path, "base", None, "pass")
    _revision(tmp_path, "marker", "base", "pass")
    fork = _revision(
        tmp_path, "fork", "base", 'op.create_index("ix", "existing", ["name"])'
    )
    failures = list(check_migration_design.check_chain(tmp_path, "marker"))
    assert any(f"{fork}:2: single-head:" in error for error in failures)
    assert any(f"{fork}:4: blocking-index:" in error for error in failures)
    (tmp_path / "merge.py").write_text(
        'revision = "merge"\ndown_revision = (\n    "marker",\n    "fork",\n)\n',
        encoding="utf-8",
    )
    assert len(list(check_migration_design.check_chain(tmp_path, "marker"))) == 1
    _revision(tmp_path, "fork", "base", "pass")
    assert list(check_migration_design.check_chain(tmp_path, "marker")) == []


def test_cycle_below_single_head(tmp_path: Path) -> None:
    _revision(tmp_path, "marker", None, "pass")
    _revision(tmp_path, "a", "b", "pass")
    _revision(tmp_path, "b", "a", "pass")
    head = _revision(tmp_path, "head", "a", "pass")
    head.write_text('revision = "head"\ndown_revision = ("a", "marker")\n')
    failures = list(check_migration_design.check_chain(tmp_path, "marker"))
    assert len(failures) == 1
    assert "revision-metadata:" in failures[0]
    assert "cycle" in failures[0]


def test_nested_helper_uses_its_own_table_creations(tmp_path: Path) -> None:
    _revision(tmp_path, "marker", None, "pass")
    _revision(
        tmp_path,
        "new",
        "marker",
        "def helper():\n"
        '    op.create_table("events")\n'
        '    op.create_index("ix", "events", ["created_at"])\n'
        '    op.add_column("events", sa.Column("name", sa.String(), nullable=False))\n'
        '    op.create_check_constraint("ck", "events", "name <> \'\'")\n'
        "helper()",
    )
    assert list(check_migration_design.check_chain(tmp_path, "marker")) == []


@pytest.mark.parametrize(
    "setup",
    [
        'op.create_table("events", if_not_exists=True)',
        'op.create_table("events")\n'
        "if replace_table:\n"
        '    op.drop_table("events")\n'
        '    op.rename_table("existing", "events")',
    ],
)
def test_table_that_may_already_exist_is_not_exempt(tmp_path: Path, setup: str) -> None:
    _revision(tmp_path, "marker", None, "pass")
    _revision(
        tmp_path,
        "new",
        "marker",
        setup + '\nop.create_index("ix", "events", ["created_at"])',
    )
    failures = list(check_migration_design.check_chain(tmp_path, "marker"))
    assert len(failures) == 1
    assert "blocking-index:" in failures[0]


def test_added_column_foreign_key_on_existing_table(tmp_path: Path) -> None:
    _revision(tmp_path, "marker", None, "pass")
    add_column = (
        'op.add_column("index_attempt", sa.Column("targeted_reindex_job_id", '
        'sa.Integer(), sa.ForeignKey("targeted_reindex_job.id", ondelete="SET NULL"), '
        "nullable=False))"
    )
    _revision(tmp_path, "new", "marker", add_column)
    failures = list(check_migration_design.check_chain(tmp_path, "marker"))
    assert sorted(error.split(": ")[1] for error in failures) == [
        "not-null",
        "not-valid",
    ]
    _revision(
        tmp_path, "new", "marker", 'op.create_table("index_attempt")\n' + add_column
    )
    assert list(check_migration_design.check_chain(tmp_path, "marker")) == []
    clean = (
        'op.add_column("index_attempt", sa.Column("targeted_reindex_job_id", sa.Integer()))\n'
        'op.create_foreign_key("fk", "index_attempt", "targeted_reindex_job", '
        '["targeted_reindex_job_id"], ["id"], postgresql_not_valid=True)'
    )
    _revision(tmp_path, "new", "marker", clean)
    assert list(check_migration_design.check_chain(tmp_path, "marker")) == []


@pytest.mark.parametrize(
    ("create_schema", "replace_schema", "blocked"),
    [
        ("", ', schema="public"', True),
        (', schema="public"', "", True),
        (', schema="public"', ', schema="public"', True),
        (', schema="public"', ', schema="other"', False),
    ],
)
def test_table_replacement_respects_schema(
    tmp_path: Path, create_schema: str, replace_schema: str, blocked: bool
) -> None:
    _revision(tmp_path, "marker", None, "pass")
    _revision(
        tmp_path,
        "new",
        "marker",
        f'op.create_table("events"{create_schema})\n'
        f'op.drop_table("events"{replace_schema})\n'
        f'op.rename_table("existing_events", "events"{replace_schema})\n'
        f'op.create_index("ix", "events", ["id"]{create_schema})',
    )
    failures = list(check_migration_design.check_chain(tmp_path, "marker"))
    assert bool(failures) is blocked
    if blocked:
        assert len(failures) == 1
        assert "blocking-index:" in failures[0]
