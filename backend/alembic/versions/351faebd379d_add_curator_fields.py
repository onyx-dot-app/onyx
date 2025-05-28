"""Add curator fields

Revision ID: 351faebd379d
Revises: ee3f4b47fad5
Create Date: 2024-08-15 22:37:08.397052

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "351faebd379d"
down_revision = "ee3f4b47fad5"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Add is_curator column to User__UserGroup table
    op.add_column(
        "user__user_group",
        sa.Column("is_curator", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Use batch mode to modify the enum type
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column(  # type: ignore[attr-defined]
            "role",
            type_=sa.Enum(
                "BASIC",
                "ADMIN",
                "CURATOR",
                "GLOBAL_CURATOR",
                name="userrole",
                native_enum=False,
            ),
            existing_type=sa.Enum("BASIC", "ADMIN", name="userrole", native_enum=False),
            existing_nullable=False,
        )
    # Create the association table
    op.create_table(
        "credential__user_group",
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("user_group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credential.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_group_id"],
            ["user_group.id"],
        ),
        sa.PrimaryKeyConstraint("credential_id", "user_group_id"),
    )
    op.add_column(
        "credential",
        sa.Column(
            "curator_public", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    # Update existing records to ensure they fit within the BASIC/ADMIN roles
    op.execute(
        "UPDATE \"user\" SET role = 'ADMIN' WHERE role IN ('CURATOR', 'GLOBAL_CURATOR')"
    )

    # Remove is_curator column from User__UserGroup table
    op.drop_column("user__user_group", "is_curator")

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column(  # type: ignore[attr-defined]
            "role",
            type_=sa.Enum(
                "BASIC", "ADMIN", name="userrole", native_enum=False, length=20
            ),
            existing_type=sa.Enum(
                "BASIC",
                "ADMIN",
                "CURATOR",
                "GLOBAL_CURATOR",
                name="userrole",
                native_enum=False,
            ),
            existing_nullable=False,
        )
    # Drop the association table
    op.drop_table("credential__user_group")
    op.drop_column("credential", "curator_public")
