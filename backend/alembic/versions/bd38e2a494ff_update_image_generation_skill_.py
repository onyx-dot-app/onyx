"""update image generation skill description

Revision ID: bd38e2a494ff
Revises: c7d1f0a4b8e2
Create Date: 2026-07-14 01:40:41.362266

"""

import sqlalchemy as sa
from alembic import op

revision = "bd38e2a494ff"
down_revision = "c7d1f0a4b8e2"
branch_labels = None
depends_on = None


_BUILT_IN_SKILL_ID = "image-generation"

_OLD_DESCRIPTION = "Generate images using nano banana."

_NEW_DESCRIPTION = (
    "Generate or edit images with onyx-cli using the image generation provider "
    "configured in Onyx."
)

_skill_table = sa.table(
    "skill",
    sa.column("slug", sa.String),
    sa.column("description", sa.Text),
    sa.column("built_in_skill_id", sa.String),
)


def _set_description(description: str) -> None:
    op.get_bind().execute(
        sa.update(_skill_table)
        .where(_skill_table.c.slug == _BUILT_IN_SKILL_ID)
        .where(_skill_table.c.built_in_skill_id == _BUILT_IN_SKILL_ID)
        .values(description=description)
    )


def upgrade() -> None:
    _set_description(_NEW_DESCRIPTION)


def downgrade() -> None:
    _set_description(_OLD_DESCRIPTION)
