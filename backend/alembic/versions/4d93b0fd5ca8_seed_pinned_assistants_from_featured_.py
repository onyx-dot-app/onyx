"""normalise pinned agents into a table

Revision ID: 4d93b0fd5ca8
Revises: f54501f1435a
Create Date: 2026-08-13 15:10:53.661660

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import aggregate_order_by


# revision identifiers, used by Alembic.
revision = "4d93b0fd5ca8"
down_revision = "f54501f1435a"
branch_labels = None
depends_on = None

# Stubs rather than the ORM models, and duplicating
# `build_seed_pinned_personas_stmt` is deliberate: a migration stays pinned to
# the schema at its own revision, so it can import neither the models nor the
# app helper. `pinned_assistants` only exists on either side of this revision.
user = sa.table(
    "user",
    sa.column("id", sa.UUID()),
    sa.column("pinned_assistants", postgresql.JSONB()),
)
persona = sa.table(
    "persona",
    sa.column("id", sa.Integer()),
    sa.column("display_priority", sa.Integer()),
    sa.column("is_featured", sa.Boolean()),
    sa.column("is_public", sa.Boolean()),
    sa.column("is_listed", sa.Boolean()),
    sa.column("deleted", sa.Boolean()),
)
pinned_persona = sa.table(
    "user__pinned_persona",
    sa.column("user_id", sa.UUID()),
    sa.column("persona_id", sa.Integer()),
    sa.column("display_order", sa.Integer()),
)


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

    # Carry existing pins over, dropping three kinds of entry the array allowed
    # and the table will not: ids of agents that no longer exist, the built-in
    # Assistant, which the sidebar never renders - so pinning it left a row the
    # user could neither see nor remove - and repeats of an id already pinned.
    #
    # Number after the drops, not from the array position, so `display_order`
    # comes out dense. Taking `ord` directly would leave a hole wherever an
    # entry was dropped.
    elements = (
        sa.func.jsonb_array_elements_text(user.c.pinned_assistants)
        .table_valued("elem", with_ordinality="ord")
        .render_derived(name="t")
        .lateral()
    )
    carried_id = sa.cast(elements.c.elem, sa.Integer)
    deduped = (
        sa.select(
            user.c.id.label("user_id"),
            carried_id.label("persona_id"),
            elements.c.ord.label("ord"),
        )
        .select_from(user)
        .join(elements, sa.true())
        .join(persona, persona.c.id == carried_id)
        .where(
            user.c.pinned_assistants.is_not(None),
            persona.c.id != 0,
            sa.not_(persona.c.deleted),
        )
        .distinct(user.c.id, carried_id)
        .order_by(user.c.id, carried_id, elements.c.ord)
        .subquery()
    )

    op.execute(
        postgresql.insert(pinned_persona)
        .from_select(
            ["user_id", "persona_id", "display_order"],
            sa.select(
                deduped.c.user_id,
                deduped.c.persona_id,
                sa.func.row_number().over(
                    partition_by=deduped.c.user_id, order_by=deduped.c.ord
                )
                - 1,
            ),
        )
        .on_conflict_do_nothing()
    )

    # Seed the users who predate seeding entirely. They are the ones the
    # frontend was covering for by substituting featured agents at render time,
    # and that fallback is going away: the API no longer returns null, so
    # without this they would be left with a permanently empty sidebar.
    #
    # This is the only time seeding is applied to an existing user. From here it
    # happens once, at account creation.
    featured = (
        sa.select(
            persona.c.id.label("persona_id"),
            (
                sa.func.row_number().over(
                    order_by=[
                        sa.nulls_last(persona.c.display_priority.asc()),
                        persona.c.id.asc(),
                    ]
                )
                - 1
            ).label("display_order"),
        )
        .where(
            persona.c.id != 0,
            persona.c.is_featured,
            persona.c.is_public,
            persona.c.is_listed,
            sa.not_(persona.c.deleted),
        )
        .subquery()
    )

    op.execute(
        postgresql.insert(pinned_persona)
        .from_select(
            ["user_id", "persona_id", "display_order"],
            sa.select(user.c.id, featured.c.persona_id, featured.c.display_order)
            .select_from(user)
            .join(featured, sa.true())
            .where(user.c.pinned_assistants.is_(None)),
        )
        .on_conflict_do_nothing()
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
    ordered_pins = (
        sa.select(
            sa.func.jsonb_agg(
                aggregate_order_by(
                    pinned_persona.c.persona_id, pinned_persona.c.display_order
                )
            )
        )
        .where(pinned_persona.c.user_id == user.c.id)
        .scalar_subquery()
    )

    op.execute(
        sa.update(user).values(
            pinned_assistants=sa.func.coalesce(
                ordered_pins, sa.cast(sa.literal("[]"), postgresql.JSONB)
            )
        )
    )

    op.drop_table("user__pinned_persona")
