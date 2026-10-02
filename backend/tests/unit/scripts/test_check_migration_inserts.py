"""The migration insert check flags row writes anywhere in a new revision but
its downgrade, errs toward flagging SQL text, and leaves history, allow-marked
backfills and schema changes alone."""

from pathlib import Path

import pytest
from scripts import check_migration_inserts

_MARKER = "mmm"


@pytest.mark.parametrize(
    "line",
    [
        "op.execute(\"INSERT INTO tool (id, name) VALUES (1, 'x')\")",
        "op.bulk_insert(table, rows)",
        "op.execute(sa.insert(tool_table).values(name='x'))",
        "op.execute(insert(tool_table).values(name='x'))",
        "op.execute(postgresql.insert(tool_table).values(name='x'))",
        "op.execute(tool_table.insert().values(name='x'))",
        "op.execute(tool_table.insert().from_select(cols, query))",
        "db_session.add(Tool(name='x'))",
        "session.add(Tool(name='x'))",
        "s.bulk_save_objects(rows)",
        "s.add_all(rows)",
    ],
)
def test_row_inserts_are_flagged(line: str) -> None:
    assert check_migration_inserts.find_inserts(
        f"def upgrade() -> None:\n    {line}\n"
    ) == [2]


@pytest.mark.parametrize(
    "line",
    [
        'op.add_column("tool", sa.Column("slug", sa.String()))',
        "op.execute(\"UPDATE tool SET name = 'y' WHERE name = 'x'\")",
        "op.execute(\"DELETE FROM tool WHERE name = 'x'\")",
        "seen.add(name)",
        "items.insert(0, item)",
        '"""rows inserted earlier keep their ids"""',
        'op.create_index("ix_tool_slug", "tool", ["slug"])',
        "from sqlalchemy.dialects.postgresql import insert as pg_insert",
        "session = Session(bind=op.get_bind())",
        'op.execute("INSERT INTO b SELECT * FROM a")  # migration-inserts: allow',
    ],
)
def test_schema_changes_and_updates_pass(line: str) -> None:
    assert (
        check_migration_inserts.find_inserts(f"def upgrade() -> None:\n    {line}\n")
        == []
    )


def test_any_sql_text_spelling_an_insert_is_flagged() -> None:
    """Erring toward flagging: comments and data count, the marker clears them."""
    source = (
        'op.execute("""\n    -- INSERT INTO tool VALUES (1)\n""")\n'
        "op.execute(\"UPDATE tool SET description = 'INSERT INTO the form'\")\n"
        "op.execute(\"DO $$ BEGIN EXECUTE 'INSERT INTO tool VALUES (1)'; END $$\")\n"
    )
    assert check_migration_inserts.find_inserts(source) == [1, 4, 5]


def test_marker_exempts_only_its_own_insert() -> None:
    source = (
        "def upgrade() -> None:\n    op.execute(\n"
        '        "INSERT INTO b SELECT * FROM a",  # migration-inserts: allow\n'
        '        "INSERT INTO tool VALUES (1)",\n    )\n'
    )
    assert check_migration_inserts.find_inserts(source) == [4]


def test_only_the_downgrade_body_is_skipped() -> None:
    source = (
        'def upgrade() -> None:\n    op.execute("DELETE FROM tool")\n\n\n'
        "def downgrade() -> None:\n    op.bulk_insert(tool_table, rows)\n"
        'SEED = "INSERT INTO tool VALUES (1)"\n'
    )
    assert check_migration_inserts.find_inserts(source) == [7]


def test_aliased_insert_is_flagged_at_the_call() -> None:
    source = (
        "from sqlalchemy.dialects.postgresql import insert as pg_insert\n\n\n"
        "def upgrade() -> None:\n    op.execute(pg_insert(tool_table).values())\n"
    )
    assert check_migration_inserts.find_inserts(source) == [5]


def test_module_level_helper_is_flagged() -> None:
    source = (
        "def _seed() -> None:\n    op.bulk_insert(tool_table, rows)\n\n\n"
        "def upgrade() -> None:\n    _seed()\n"
    )
    assert check_migration_inserts.find_inserts(source) == [2]


@pytest.mark.parametrize("annotation", ["Session", "orm.Session"])
def test_session_parameter_add_is_flagged(annotation: str) -> None:
    source = (
        f"def _seed(s: {annotation}) -> None:\n    s.add(Tool(name='x'))\n\n\n"
        "def upgrade() -> None:\n    _seed(Session(bind=op.get_bind()))\n"
    )
    assert check_migration_inserts.find_inserts(source) == [2]


def _write_revision(
    versions: Path, revision: str, down_revision: str, body: str = "pass"
) -> Path:
    path = versions / f"{revision}_x.py"
    path.write_text(
        f'revision = "{revision}"\ndown_revision = {down_revision}\n\n\n'
        f"def upgrade() -> None:\n    {body}\n"
    )
    return path


@pytest.fixture
def versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """base -> aaa -> bbb and base -> ccc merge into the marker mmm."""
    directory = tmp_path.resolve() / "versions"
    directory.mkdir()
    monkeypatch.setattr(check_migration_inserts, "_VERSIONS_DIR", directory)
    monkeypatch.setattr(check_migration_inserts, "_INSERTS_BANNED_AFTER", _MARKER)
    (directory / "base_x.py").write_text(
        'revision = "base"\ndown_revision: None = None\n'
    )
    _write_revision(directory, "aaa", '"base"')
    _write_revision(directory, "bbb", '"aaa"')
    _write_revision(directory, "ccc", '"base"')
    _write_revision(directory, _MARKER, '("bbb", "ccc")')
    return directory


def test_chain_walk_exempts_the_marker_and_its_ancestors(versions: Path) -> None:
    _write_revision(versions, "new", f'"{_MARKER}"')
    assert check_migration_inserts.revisions_before_rule() == {
        "base",
        "aaa",
        "bbb",
        "ccc",
        _MARKER,
    }


def test_new_revision_with_insert_fails_naming_the_line(
    versions: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_revision(
        versions, "new", f'"{_MARKER}"', "op.bulk_insert(table, rows)"
    )
    assert check_migration_inserts.main([str(path)]) == 1
    assert f"{path}:6" in capsys.readouterr().out


def test_exempt_revision_with_insert_passes(versions: Path) -> None:
    path = _write_revision(versions, "bbb", '"aaa"', "op.bulk_insert(table, rows)")
    assert check_migration_inserts.main([str(path)]) == 0


def test_new_clean_revision_passes(versions: Path) -> None:
    path = _write_revision(
        versions, "new", f'"{_MARKER}"', 'op.add_column("t", sa.Column("c"))'
    )
    assert check_migration_inserts.main([str(path)]) == 0


@pytest.mark.usefixtures("versions")
def test_files_outside_the_versions_dir_are_ignored(tmp_path: Path) -> None:
    other = tmp_path / "seed.py"
    other.write_text("op.bulk_insert(table, rows)\n")
    assert check_migration_inserts.main([str(other)]) == 0


def test_every_current_revision_is_exempt() -> None:
    paths = [str(path) for path in check_migration_inserts._VERSIONS_DIR.glob("*.py")]
    assert paths
    assert check_migration_inserts.main(paths) == 0
