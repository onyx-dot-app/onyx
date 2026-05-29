"""encrypt external app credentials

Revision ID: b4950827c0dd
Revises: 39287906b97a
Create Date: 2026-05-28 13:29:23.568531

Moves the external-app credential columns from JSONB to encrypted ``LargeBinary``,
matching ``credential.credential_json`` (revision ``0a98909f2757``):
- ``external_app.organization_credentials``
- ``external_app_user_credential.user_credentials``

The feature is not yet in production, so existing (staging) credential data is
dropped rather than migrated. This keeps every value flowing through the
encrypted write path from the start, with no plaintext rows left at rest and no
dependency on application encryption code. Per-user credential rows are deleted
(users reconnect); app config rows are kept but their org credentials are reset
to empty (admins re-enter client secrets).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b4950827c0dd"
down_revision = "39287906b97a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-user credential rows are nothing but credentials — drop them; users
    # reconnect. With no rows left, the new NOT NULL column needs no backfill.
    op.execute("DELETE FROM external_app_user_credential")
    op.drop_column("external_app_user_credential", "user_credentials")
    op.add_column(
        "external_app_user_credential",
        sa.Column("user_credentials", sa.LargeBinary(), nullable=False),
    )

    # Keep app config rows (name, url patterns, policies) but reset their org
    # credentials; admins re-enter client_id/secret. b"{}" is the empty JSON
    # object — no secret to protect — and is replaced by an encrypted value on
    # the next save.
    op.drop_column("external_app", "organization_credentials")
    op.add_column(
        "external_app",
        sa.Column("organization_credentials", sa.LargeBinary(), nullable=True),
    )
    op.get_bind().execute(
        sa.text("UPDATE external_app SET organization_credentials = :empty"),
        {"empty": b"{}"},
    )
    op.alter_column("external_app", "organization_credentials", nullable=False)


def downgrade() -> None:
    # Drop the encrypted columns and recreate empty JSONB columns. Credential
    # values are not restored (mirrors revision 0a98909f2757).
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
