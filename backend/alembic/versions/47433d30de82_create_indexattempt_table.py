"""Create IndexAttempt table

Revision ID: 47433d30de82
Revises:
Create Date: 2023-05-04 00:55:32.971991

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "47433d30de82"
down_revision: None = None
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "index_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        # String type since python enum will change often
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
        ),
        # String type to easily accomodate new ways of pulling
        # in documents
        sa.Column(
            "input_type",
            sa.String(),
            nullable=False,
        ),
        sa.Column(
            "connector_specific_config",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            server_onupdate=sa.text("now()"),  # type: ignore
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "NOT_STARTED",
                "IN_PROGRESS",
                "SUCCESS",
                "FAILED",
                name="indexingstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("document_ids", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("error_msg", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("index_attempt")
