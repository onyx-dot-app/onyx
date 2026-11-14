"""Exercise the PostgreSQL DDL contract for existing JSM capability reports."""

import importlib.util
from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

from onyx.configs.constants import DocumentSource


def test_capability_source_migration_accepts_jsm_without_rewriting_reports() -> None:
    """Widen old source storage and preserve report data on rollback."""
    path = (
        Path(__file__).resolve().parents[5]
        / "alembic/versions/3965ba49ca3d_widen_credential_capability_source_for_.py"
    )
    spec = importlib.util.spec_from_file_location("jsm_source_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    source_type = sa.Enum(DocumentSource, native_enum=False)
    assert source_type.length > 20
    assert len(DocumentSource.JIRA_SERVICE_MANAGEMENT.name) == 23
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    expected_type = source_type.compile(dialect=postgresql.dialect())
    assert f"ALTER COLUMN source TYPE {expected_type}" in sql
    assert "ALTER TABLE credential_capability_report" in sql
    assert "UPDATE " not in sql and "DELETE " not in sql
    output.seek(0)
    output.truncate(0)
    with Operations.context(context):
        migration.downgrade()
    assert output.getvalue() == ""
