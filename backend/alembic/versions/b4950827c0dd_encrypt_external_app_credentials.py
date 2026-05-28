"""encrypt external app credentials

Revision ID: b4950827c0dd
Revises: 39287906b97a
Create Date: 2026-05-28 13:29:23.568531

Encrypts the credential value columns for external apps at rest:
- ``external_app.organization_credentials``
- ``external_app_user_credential.user_credentials``

Both move from JSONB to ``LargeBinary`` storing the encrypted JSON, matching
the pattern used for ``credential.credential_json`` (see revision
``0a98909f2757``). When ``ENCRYPTION_KEY_SECRET`` is unset the MIT encryption
is a no-op encode, so this is safe to run in either edition.
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import column
from sqlalchemy.sql import table

# revision identifiers, used by Alembic.
revision = "b4950827c0dd"
down_revision = "39287906b97a"
branch_labels = None
depends_on = None


def _encrypt_jsonb_column(table_name: str, column_name: str) -> None:
    """Convert a non-null JSONB credential column to encrypted LargeBinary.

    Adds a temporary binary column, encrypts every existing row's JSON into it,
    then swaps it in for the original column (keeping NOT NULL).
    """
    connection = op.get_bind()

    op.add_column(table_name, sa.Column("temp_column", sa.LargeBinary()))

    target = table(
        table_name,
        column("id", sa.Integer()),
        column(column_name, postgresql.JSONB(astext_type=sa.Text())),
        column("temp_column", sa.LargeBinary()),
    )

    # Inline the encryption rather than depend on application code, which can
    # change or be removed and break this migration on replay. Alembic does not
    # run in an EE context, so the versioned encryption resolves to the MIT
    # implementation — a plain UTF-8 encode (no real encryption). Existing rows
    # are therefore stored as encoded JSON; the app encrypts subsequent writes
    # at runtime. This matches revision 0a98909f2757.
    for row_id, creds, _ in connection.execute(sa.select(target)):
        encoded = json.dumps(creds if creds is not None else {}).encode("utf-8")
        connection.execute(
            target.update().where(target.c.id == row_id).values(temp_column=encoded)
        )

    op.drop_column(table_name, column_name)
    op.alter_column(table_name, "temp_column", new_column_name=column_name)
    op.alter_column(table_name, column_name, nullable=False)


def upgrade() -> None:
    _encrypt_jsonb_column("external_app", "organization_credentials")
    _encrypt_jsonb_column("external_app_user_credential", "user_credentials")


def downgrade() -> None:
    # Drop the encrypted columns and recreate empty JSONB columns. We do not
    # decrypt on downgrade (mirrors revision 0a98909f2757); stored credential
    # values are lost and must be re-entered.
    op.drop_column("external_app_user_credential", "user_credentials")
    op.add_column(
        "external_app_user_credential",
        sa.Column(
            "user_credentials",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.drop_column("external_app", "organization_credentials")
    op.add_column(
        "external_app",
        sa.Column(
            "organization_credentials",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
