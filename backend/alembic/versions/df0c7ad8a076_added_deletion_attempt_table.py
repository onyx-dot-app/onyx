"""Added deletion_attempt table

Revision ID: df0c7ad8a076
Revises: d7111c1238cd
Create Date: 2023-08-05 13:35:39.609619

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "df0c7ad8a076"
down_revision = "d7111c1238cd"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document CASCADE")
    op.create_table(
        "document",
        sa.Column("id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("DROP TABLE IF EXISTS chunk CASCADE")
    op.create_table(
        "chunk",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "document_store_type",
            sa.Enum(
                "VECTOR",
                "KEYWORD",
                name="documentstoretype",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
        ),
        sa.PrimaryKeyConstraint("id", "document_store_type"),
    )
    op.execute("DROP TABLE IF EXISTS deletion_attempt CASCADE")
    op.create_table(
        "deletion_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "NOT_STARTED",
                "IN_PROGRESS",
                "SUCCESS",
                "FAILED",
                name="deletionstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("num_docs_deleted", sa.Integer(), nullable=False),
        sa.Column("error_msg", sa.String(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connector.id"],
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credential.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("DROP TABLE IF EXISTS document_by_connector_credential_pair CASCADE")
    op.create_table(
        "document_by_connector_credential_pair",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connector.id"],
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credential.id"],
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["document.id"],
        ),
        sa.PrimaryKeyConstraint("id", "connector_id", "credential_id"),
    )


def downgrade() -> None:
    # upstream tables first
    op.drop_table("document_by_connector_credential_pair")
    op.drop_table("deletion_attempt")
    op.drop_table("chunk")

    # Alembic op.drop_table() has no "cascade" flag – issue raw SQL
    op.execute("DROP TABLE IF EXISTS document CASCADE")
