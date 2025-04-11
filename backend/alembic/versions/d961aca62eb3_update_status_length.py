"""Update status length

Revision ID: d961aca62eb3
Revises: cf90764725d8
Create Date: 2025-03-23 16:10:05.683965

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d961aca62eb3"
down_revision = "cf90764725d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing enum type constraint
    op.execute("ALTER TABLE connector_credential_pair ALTER COLUMN status TYPE varchar")

    # Create new enum type with all values
    op.execute(
        "ALTER TABLE connector_credential_pair ALTER COLUMN status TYPE VARCHAR(20) USING status::varchar(20)"
    )

    # Update the enum type to include all possible values
    op.alter_column(
        "connector_credential_pair",
        "status",
        type_=sa.Enum(
            "SCHEDULED",
            "INITIAL_INDEXING",
            "ACTIVE",
            "PAUSED",
            "DELETING",
            "INVALID",
            name="connectorcredentialpairstatus",
            native_enum=False,
        ),
        existing_type=sa.String(20),
        nullable=False,
    )

    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "in_repeated_error_state", sa.Boolean, default=False, server_default="false"
        ),
    )


def downgrade() -> None:
    # no need to convert back to the old enum type, since we're not using it anymore
    op.drop_column("connector_credential_pair", "in_repeated_error_state")
