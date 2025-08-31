"""add project__userfile table and userfile column changes

Revision ID: 85956d2f6eed
Revises: b329d00a9ea6
Create Date: 2025-08-30 18:30:22.439888

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql

# revision identifiers, used by Alembic.
revision = "85956d2f6eed"
down_revision = "b329d00a9ea6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0) Ensure UUID generator exists
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # 1) Add transitional UUID column on user_file + UNIQUE so FKs can reference it
    op.add_column(
        "user_file",
        sa.Column(
            "new_id",
            psql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_unique_constraint("uq_user_file_new_id", "user_file", ["new_id"])

    # 2) Move FK users to the transitional UUID
    # ---- persona__user_file.user_file_id (INT) -> UUID ----
    op.add_column(
        "persona__user_file",
        sa.Column("user_file_id_uuid", psql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE persona__user_file p
        SET user_file_id_uuid = uf.new_id
        FROM user_file uf
        WHERE p.user_file_id = uf.id
        """
    )
    # swap FK to reference user_file.new_id (the transitional UNIQUE)
    op.drop_constraint(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        type_="foreignkey",
    )
    op.alter_column("persona__user_file", "user_file_id_uuid", nullable=False)
    op.create_foreign_key(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        "user_file",
        local_cols=["user_file_id_uuid"],
        remote_cols=["new_id"],
    )
    op.drop_column("persona__user_file", "user_file_id")
    op.alter_column(
        "persona__user_file",
        "user_file_id_uuid",
        new_column_name="user_file_id",
        existing_type=psql.UUID(as_uuid=True),
        nullable=False,
    )
    # ---- end persona__user_file ----

    # (Repeat 2) for any other FK tables that point to user_file.id)

    # 3) Swap PK on user_file from int -> uuid
    op.drop_constraint("user_file_pkey", "user_file", type_="primary")
    op.drop_column("user_file", "id")
    op.alter_column(
        "user_file",
        "new_id",
        new_column_name="id",
        existing_type=psql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_primary_key("user_file_pkey", "user_file", ["id"])

    # 4) Now **force** FKs to bind to the PK:
    #    (a) drop FK(s)
    op.drop_constraint(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        type_="foreignkey",
    )
    #    (b) drop the transitional UNIQUE so it cannot be chosen
    op.drop_constraint("uq_user_file_new_id", "user_file", type_="unique")
    #    (c) recreate FK(s) to user_file(id) — only PK remains, so it will bind there
    op.create_foreign_key(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        "user_file",
        local_cols=["user_file_id"],
        remote_cols=["id"],
    )

    # 5) Safe to create new tables referencing the UUID PK
    op.create_table(
        "project__user_file",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_file_id", psql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["user_folder.id"]),
        sa.ForeignKeyConstraint(["user_file_id"], ["user_file.id"]),
        sa.PrimaryKeyConstraint("project_id", "user_file_id"),
    )

    # 6) Add extra columns
    op.add_column(
        "user_file",
        sa.Column(
            "status",
            sa.Enum(
                "processing",
                "completed",
                "failed",
                "canceled",
                name="userfilestatus",
                native_enum=False,
            ),
            nullable=False,
            server_default="processing",
        ),
    )
    op.add_column("user_file", sa.Column("chunk_count", sa.Integer(), nullable=True))
    op.add_column(
        "user_file",
        sa.Column("boost", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "user_file",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_folder",
        sa.Column("prompt_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "user_folder_prompt_id_fkey",
        "user_folder",
        "prompt",
        ["prompt_id"],
        ["id"],
    )


def downgrade() -> None:
    # Drop extra columns
    op.drop_column("user_file", "last_accessed_at")
    op.drop_column("user_file", "boost")
    op.drop_column("user_file", "chunk_count")
    op.drop_column("user_file", "status")
    op.execute("DROP TYPE IF EXISTS userfilestatus")

    # Drop association table
    op.drop_table("project__user_file")

    # Recreate an integer PK (best-effort; original values aren’t retained)
    op.drop_constraint(
        "persona__user_file_user_file_id_fkey", "persona__user_file", type_="foreignkey"
    )
    op.drop_constraint("user_file_pkey", "user_file", type_="primary")

    op.add_column(
        "user_file",
        sa.Column("id_int_tmp", sa.Integer(), autoincrement=True, nullable=False),
    )
    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS user_file_id_seq OWNED BY user_file.id_int_tmp"
    )
    op.execute(
        "ALTER TABLE user_file ALTER COLUMN id_int_tmp SET DEFAULT nextval('user_file_id_seq')"
    )
    op.create_primary_key("user_file_pkey", "user_file", ["id_int_tmp"])

    op.add_column(
        "persona__user_file",
        sa.Column("user_file_id_int_tmp", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "persona__user_file_user_file_id_fkey",
        "persona__user_file",
        "user_file",
        ["user_file_id_int_tmp"],
        ["id_int_tmp"],
    )

    # Remove UUID id and rename int back to id
    op.drop_column("user_file", "id")
    op.alter_column(
        "user_file",
        "id_int_tmp",
        new_column_name="id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.drop_column("persona__user_file", "user_file_id")
    op.alter_column(
        "persona__user_file",
        "user_file_id_int_tmp",
        new_column_name="user_file_id",
        existing_type=sa.Integer(),
    )

    op.drop_column("user_folder", "prompt_id")
