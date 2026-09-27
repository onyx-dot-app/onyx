"""seed_craft_documentation_built_in_skill

Seeds the built-in ``craft-documentation`` skill row, which points the agent at
the official docs at docs.onyx.app so it can answer questions about how Onyx and
Onyx Craft work. Skill names are no longer unique, so the seed is made idempotent
by keying on ``built_in_skill_id``.

Revision ID: c5d9662b3c50
Revises: c71a18ea7d07
Create Date: 2026-08-17 11:20:47.623155

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c5d9662b3c50"
down_revision = "c71a18ea7d07"
branch_labels = None
depends_on = None

_CRAFT_DOCUMENTATION_SKILL_ID = "craft-documentation"
_CRAFT_DOCUMENTATION_DESCRIPTION = (
    "Answer questions about how Onyx and Onyx Craft work using the official "
    "documentation at docs.onyx.app. Use when the user asks what Craft can do, "
    "how a feature works, how to set up skills or apps, or how to deploy, "
    "configure, or administer Onyx."
)

_skill_table = sa.table(
    "skill",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("built_in_skill_id", sa.String),
    sa.column("bundle_file_id", sa.String),
    sa.column("bundle_sha256", sa.String),
    sa.column("author_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("public_permission", sa.String),
)


def upgrade() -> None:
    bind = op.get_bind()

    existing = bind.execute(
        sa.select(_skill_table.c.id).where(
            _skill_table.c.built_in_skill_id == _CRAFT_DOCUMENTATION_SKILL_ID
        )
    ).first()
    if existing is not None:
        bind.execute(
            sa.update(_skill_table)
            .where(_skill_table.c.built_in_skill_id == _CRAFT_DOCUMENTATION_SKILL_ID)
            .values(
                name=_CRAFT_DOCUMENTATION_SKILL_ID,
                description=_CRAFT_DOCUMENTATION_DESCRIPTION,
            )
        )
        return

    bind.execute(
        sa.insert(_skill_table).values(
            id=uuid.uuid4(),
            name=_CRAFT_DOCUMENTATION_SKILL_ID,
            description=_CRAFT_DOCUMENTATION_DESCRIPTION,
            built_in_skill_id=_CRAFT_DOCUMENTATION_SKILL_ID,
            bundle_file_id=None,
            bundle_sha256=None,
            author_user_id=None,
            public_permission="VIEWER",
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.delete(_skill_table).where(
            _skill_table.c.built_in_skill_id == _CRAFT_DOCUMENTATION_SKILL_ID
        )
    )
