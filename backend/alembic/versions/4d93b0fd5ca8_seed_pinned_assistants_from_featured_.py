"""normalise pinned agents into a table

Revision ID: 4d93b0fd5ca8
Revises: 3350a25df58e
Create Date: 2026-08-13 15:10:53.661660

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "4d93b0fd5ca8"
down_revision = "3350a25df58e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user__pinned_persona",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["persona.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "persona_id"),
    )

    # Carry existing pins over, dropping two kinds of entry the array allowed
    # and the table will not: ids of agents that no longer exist, and the
    # built-in Assistant, which the sidebar never renders - so pinning it left a
    # row the user could neither see nor remove.
    op.execute(
        """
        INSERT INTO user__pinned_persona (user_id, persona_id, display_order)
        SELECT
            u.id,
            (elem #>> '{}')::int,
            (ord - 1)::int
        FROM "user" AS u
        CROSS JOIN LATERAL jsonb_array_elements(u.pinned_assistants)
            WITH ORDINALITY AS t(elem, ord)
        JOIN persona AS p ON p.id = (elem #>> '{}')::int
        WHERE u.pinned_assistants IS NOT NULL
          AND p.id <> 0
          AND NOT p.deleted
        ON CONFLICT DO NOTHING
        """
    )

    # Seed the users who predate seeding entirely. They are the ones the
    # frontend was covering for by substituting featured agents at render time,
    # and that fallback is going away: the API no longer returns null, so
    # without this they would be left with a permanently empty sidebar.
    #
    # This is the only time seeding is applied to an existing user. From here it
    # happens once, at account creation.
    op.execute(
        """
        INSERT INTO user__pinned_persona (user_id, persona_id, display_order)
        SELECT u.id, f.id, f.display_order
        FROM "user" AS u
        CROSS JOIN (
            SELECT
                p.id,
                (ROW_NUMBER() OVER (
                    ORDER BY p.display_priority ASC NULLS LAST, p.id ASC
                ) - 1)::int AS display_order
            FROM persona AS p
            WHERE p.id <> 0
              AND p.is_featured
              AND p.is_public
              AND p.is_listed
              AND NOT p.deleted
        ) AS f
        WHERE u.pinned_assistants IS NULL
        ON CONFLICT DO NOTHING
        """
    )

    op.drop_column("user", "pinned_assistants")


def downgrade() -> None:
    op.add_column(
        "user",
        sa.Column("pinned_assistants", postgresql.JSONB(), nullable=True),
    )

    # Every user gets a list, empty if they pin nothing. The old column was
    # nullable and the difference mattered - null meant "never seeded" - but
    # that distinction is exactly what this revision removed, and it cannot be
    # recovered from rows.
    op.execute(
        """
        UPDATE "user" AS u
        SET pinned_assistants = COALESCE(
            (
                SELECT jsonb_agg(pp.persona_id ORDER BY pp.display_order)
                FROM user__pinned_persona AS pp
                WHERE pp.user_id = u.id
            ),
            '[]'::jsonb
        )
        """
    )

    op.drop_table("user__pinned_persona")
