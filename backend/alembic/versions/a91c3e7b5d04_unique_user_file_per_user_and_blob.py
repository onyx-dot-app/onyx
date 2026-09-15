"""unique user_file per user and store blob

Revision ID: a91c3e7b5d04
Revises: ad99acb9be41
Create Date: 2026-09-15 13:50:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a91c3e7b5d04"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_user_file_user_id_file_id"


def upgrade() -> None:
    # Keep one row per (user_id, file_id) before the unique constraint.
    # Prefer a completed row so an already-indexed file stays attached.
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE _user_file_keepers ON COMMIT DROP AS
            SELECT DISTINCT ON (user_id, file_id) id, user_id, file_id
            FROM user_file
            ORDER BY
                user_id,
                file_id,
                CASE status
                    WHEN 'COMPLETED' THEN 0
                    WHEN 'INDEXING' THEN 1
                    WHEN 'PROCESSING' THEN 2
                    WHEN 'SKIPPED' THEN 3
                    WHEN 'FAILED' THEN 4
                    WHEN 'CANCELED' THEN 5
                    WHEN 'DELETING' THEN 6
                    ELSE 7
                END,
                created_at ASC,
                id ASC
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO project__user_file (project_id, user_file_id)
            SELECT puf.project_id, k.id
            FROM project__user_file puf
            JOIN user_file dup ON dup.id = puf.user_file_id
            JOIN _user_file_keepers k
                ON k.user_id = dup.user_id AND k.file_id = dup.file_id
            WHERE dup.id <> k.id
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO persona__user_file (persona_id, user_file_id)
            SELECT puf.persona_id, k.id
            FROM persona__user_file puf
            JOIN user_file dup ON dup.id = puf.user_file_id
            JOIN _user_file_keepers k
                ON k.user_id = dup.user_id AND k.file_id = dup.file_id
            WHERE dup.id <> k.id
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM project__user_file
            WHERE user_file_id NOT IN (SELECT id FROM _user_file_keepers)
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM user_file
            WHERE id NOT IN (SELECT id FROM _user_file_keepers)
            """
        )
    )
    op.create_unique_constraint(CONSTRAINT_NAME, "user_file", ["user_id", "file_id"])


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "user_file", type_="unique")
