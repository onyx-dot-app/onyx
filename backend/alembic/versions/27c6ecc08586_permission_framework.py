"""Permission Framework

Revision ID: 27c6ecc08586
Revises: 2666d766cb9b
Create Date: 2023-05-24 18:45:17.244495

"""

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "27c6ecc08586"
down_revision = "2666d766cb9b"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("TRUNCATE TABLE index_attempt")
    op.create_table(
        "connector",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "SLACK",
                "WEB",
                "GOOGLE_DRIVE",
                "GITHUB",
                "CONFLUENCE",
                name="documentsource",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "input_type",
            sa.Enum(
                "LOAD_STATE",
                "POLL",
                "EVENT",
                name="inputtype",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "connector_specific_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("refresh_freq", sa.Integer(), nullable=True),
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
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "credential",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "credential_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column("public_doc", sa.Boolean(), nullable=False),
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
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "connector_credential_pair",
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
        sa.PrimaryKeyConstraint("connector_id", "credential_id"),
    )
    op.add_column(
        "index_attempt",
        sa.Column("connector_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "index_attempt",
        sa.Column("credential_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_index_attempt_credential_id",
        "index_attempt",
        "credential",
        ["credential_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_index_attempt_connector_id",
        "index_attempt",
        "connector",
        ["connector_id"],
        ["id"],
    )
    op.drop_column("index_attempt", "connector_specific_config")
    op.drop_column("index_attempt", "source")
    op.drop_column("index_attempt", "input_type")


def downgrade() -> None:
    op.execute("TRUNCATE TABLE index_attempt")
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {col["name"] for col in inspector.get_columns("index_attempt")}

    if "input_type" not in existing_columns:
        op.add_column(
            "index_attempt",
            sa.Column("input_type", sa.VARCHAR(), autoincrement=False, nullable=False),
        )

    if "source" not in existing_columns:
        op.add_column(
            "index_attempt",
            sa.Column("source", sa.VARCHAR(), autoincrement=False, nullable=False),
        )

    if "connector_specific_config" not in existing_columns:
        op.add_column(
            "index_attempt",
            sa.Column(
                "connector_specific_config",
                postgresql.JSONB(astext_type=sa.Text()),
                autoincrement=False,
                nullable=False,
            ),
        )

    # Check if the constraint exists before dropping
    constraints = inspector.get_foreign_keys("index_attempt")

    if any(
        constraint["name"] == "fk_index_attempt_credential_id"
        for constraint in constraints
    ):
        op.drop_constraint(
            "fk_index_attempt_credential_id", "index_attempt", type_="foreignkey"
        )

    if any(
        constraint["name"] == "fk_index_attempt_connector_id"
        for constraint in constraints
    ):
        op.drop_constraint(
            "fk_index_attempt_connector_id", "index_attempt", type_="foreignkey"
        )

    if "credential_id" in existing_columns:
        op.drop_column("index_attempt", "credential_id")

    if "connector_id" in existing_columns:
        op.drop_column("index_attempt", "connector_id")

    op.execute("DROP TABLE IF EXISTS connector_credential_pair CASCADE")
    op.execute("DROP TABLE IF EXISTS credential CASCADE")
    op.execute("DROP TABLE IF EXISTS connector CASCADE")
