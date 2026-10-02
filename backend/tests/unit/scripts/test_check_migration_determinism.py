"""The migration determinism check flags run-dependent values anywhere in a
new revision but its downgrade, leaves schema defaults, updates, history and
allow-marked statements alone, and walks the chain to find history."""

from pathlib import Path

import pytest
from scripts import check_migration_determinism

_MARKER = "mmm"


def _in_upgrade(line: str) -> str:
    return f"def upgrade() -> None:\n    {line}\n"


@pytest.mark.parametrize(
    "line",
    [
        'op.execute("INSERT INTO tool (id, created_at) VALUES (1, now())")',
        'op.execute("INSERT INTO tool (id) VALUES (gen_random_uuid())")',
        'op.execute("INSERT INTO tool (id, at) VALUES (1, current_timestamp)")',
        "op.execute(insert(tool_table).values(id=uuid4(), name='x'))",
        "op.execute(insert(tool_table).values(id=1, created_at=func.now()))",
        "op.execute(tool_table.insert().values(id=1, created_at=sa.func.now()))",
        "op.bulk_insert(tool_table, [{'id': str(uuid.uuid4())}])",
        "new_id = uuid4()",
        "stamp = func.now()",
        "op.bulk_insert(tool_table, [{'id': 1, 'created_at': sa.func.now()}])",
        "stamp = datetime.now()",
        "stamp = datetime.datetime.utcnow()",
        "seed = random.randint(1, 10)",
        'api_key = os.environ["EXA_API_KEY"]',
        'api_key = os.getenv("EXA_API_KEY")',
        'api_key = os.environ.get("EXA_API_KEY")',
    ],
)
def test_run_dependent_values_are_flagged(line: str) -> None:
    assert check_migration_determinism.find_run_dependent_values(_in_upgrade(line)) == [
        2
    ]


@pytest.mark.parametrize(
    "line",
    [
        'op.add_column("tool", sa.Column("c", sa.DateTime(), server_default=sa.text("now()")))',
        'op.add_column("tool", sa.Column("c", sa.DateTime(), server_default=func.now()))',
        'op.create_table("t", sa.Column("c", sa.DateTime(), server_default=sa.func.now()))',
        'op.alter_column("tool", "c", server_default=func.now())',
        "op.execute(sa.update(tool).values(updated_at=sa.func.now()))",
        "op.execute(update(tool).where(tool.c.id == 1).values(updated_at=func.now()))",
        "op.execute(\"UPDATE tool SET updated_at = now() WHERE name = 'x'\")",
        "op.execute(\"INSERT INTO tool (id, name) VALUES (1, 'x')\")",
        "op.execute(insert(tool_table).values(id=1, name='x'))",
        "op.bulk_insert(tool_table, [{'id': 1, 'name': 'x'}])",
        '"""ids were generated with uuid4() at the time"""',
        "op.execute(insert(t).values(id=uuid4()))  # migration-determinism: allow",
    ],
)
def test_fixed_values_and_schema_defaults_pass(line: str) -> None:
    assert (
        check_migration_determinism.find_run_dependent_values(_in_upgrade(line)) == []
    )


def test_marker_exempts_only_its_own_value() -> None:
    source = (
        "def upgrade() -> None:\n    op.execute(\n"
        '        "INSERT INTO a VALUES (now())",  # migration-determinism: allow\n'
        '        "INSERT INTO b VALUES (now())",\n    )\n'
    )
    assert check_migration_determinism.find_run_dependent_values(source) == [4]


def test_only_the_downgrade_body_is_skipped() -> None:
    source = (
        'def upgrade() -> None:\n    op.execute("DELETE FROM tool")\n\n\n'
        "def downgrade() -> None:\n    op.bulk_insert(t, [{'id': uuid4()}])\n"
        "SEED_ID = uuid4()\n"
    )
    assert check_migration_determinism.find_run_dependent_values(source) == [7]


def test_module_level_helper_is_flagged() -> None:
    source = (
        "def _seed() -> None:\n    op.bulk_insert(t, [{'id': uuid4()}])\n\n\n"
        "def upgrade() -> None:\n    _seed()\n"
    )
    assert check_migration_determinism.find_run_dependent_values(source) == [2]


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
    monkeypatch.setattr(check_migration_determinism, "_VERSIONS_DIR", directory)
    monkeypatch.setattr(check_migration_determinism, "_RULE_LANDED_AT", _MARKER)
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
    assert check_migration_determinism.revisions_before_rule() == {
        "base",
        "aaa",
        "bbb",
        "ccc",
        _MARKER,
    }


def test_new_revision_with_generated_id_fails_naming_the_line(
    versions: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_revision(
        versions, "new", f'"{_MARKER}"', "op.bulk_insert(t, [{'id': uuid4()}])"
    )
    assert check_migration_determinism.main([str(path)]) == 1
    assert f"{path}:6" in capsys.readouterr().out


def test_exempt_revision_passes(versions: Path) -> None:
    path = _write_revision(
        versions, "bbb", '"aaa"', "op.bulk_insert(t, [{'id': uuid4()}])"
    )
    assert check_migration_determinism.main([str(path)]) == 0


def test_new_deterministic_revision_passes(versions: Path) -> None:
    path = _write_revision(
        versions, "new", f'"{_MARKER}"', "op.bulk_insert(t, [{'id': 1}])"
    )
    assert check_migration_determinism.main([str(path)]) == 0


@pytest.mark.usefixtures("versions")
def test_files_outside_the_versions_dir_are_ignored(tmp_path: Path) -> None:
    other = tmp_path / "seed.py"
    other.write_text("SEED_ID = uuid4()\n")
    assert check_migration_determinism.main([str(other)]) == 0


def test_every_current_revision_is_exempt() -> None:
    paths = [
        str(path) for path in check_migration_determinism._VERSIONS_DIR.glob("*.py")
    ]
    assert paths
    assert check_migration_determinism.main(paths) == 0
