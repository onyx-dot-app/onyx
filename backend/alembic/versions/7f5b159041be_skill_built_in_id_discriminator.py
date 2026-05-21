"""skill_built_in_id_discriminator

Revision ID: 7f5b159041be
Revises: db87b27e93ef
Create Date: 2026-05-20 16:05:14.948817

Adds a discriminator column ``built_in_skill_id`` so a single ``skill``
row can describe either a built-in (definition lives on disk under
``SKILLS_TEMPLATE_PATH``) or a custom (bundle blob in FileStore). The
two bundle columns become nullable; a CHECK constraint enforces
"exactly one source" — XOR of ``built_in_skill_id`` and
``bundle_file_id`` being non-null.

``built_in_skill_id`` is *not* unique — a single built-in can back
multiple ``skill`` rows (different slugs, sharing scopes). Slug
remains the unique natural key and is what the seeder deduplicates on.

Backfill is unnecessary: every pre-existing row is a custom skill
(``bundle_file_id`` already NOT NULL and ``built_in_skill_id`` defaults
to NULL on add) and satisfies the XOR.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "7f5b159041be"
down_revision = "db87b27e93ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill",
        sa.Column("built_in_skill_id", sa.String(), nullable=True),
    )

    op.alter_column("skill", "bundle_file_id", nullable=True)
    op.alter_column("skill", "bundle_sha256", nullable=True)

    op.create_check_constraint(
        "ck_skill_definition_source",
        "skill",
        "(built_in_skill_id IS NULL) <> (bundle_file_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skill_definition_source", "skill", type_="check")

    # Seeded built-in rows would violate NOT NULL on bundle_file_id;
    # drop them so the downgrade is clean. Custom rows are unaffected.
    op.execute("DELETE FROM skill WHERE built_in_skill_id IS NOT NULL")

    op.alter_column("skill", "bundle_sha256", nullable=False)
    op.alter_column("skill", "bundle_file_id", nullable=False)

    op.drop_column("skill", "built_in_skill_id")
