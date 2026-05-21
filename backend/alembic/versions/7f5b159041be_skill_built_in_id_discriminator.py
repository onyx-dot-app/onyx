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

Backfill of existing custom rows is unnecessary: ``bundle_file_id`` is
already NOT NULL and ``built_in_skill_id`` defaults to NULL, so every
pre-existing row satisfies the XOR.

Seed step: also inserts the default built-in rows in the same revision.
Required for MT upgrades — ``setup_postgres`` (which calls the boot-time
seeder) only runs for *new* tenants in multi-tenant mode, so existing
tenants would otherwise silently lose all built-in skills after this
migration. Alembic runs per-tenant schema, so this seeds every tenant.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from onyx.db.skill import seed_built_in_skills

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

    # Seed default built-in rows so existing tenants pick them up on
    # upgrade. Idempotent via ON CONFLICT — re-running this migration
    # on a tenant that's already booted under the new code is safe.
    with Session(bind=op.get_bind()) as session:
        seed_built_in_skills(session)


def downgrade() -> None:
    op.drop_constraint("ck_skill_definition_source", "skill", type_="check")

    # Seeded built-in rows would violate NOT NULL on bundle_file_id;
    # drop them so the downgrade is clean. Custom rows are unaffected.
    op.execute("DELETE FROM skill WHERE built_in_skill_id IS NOT NULL")

    op.alter_column("skill", "bundle_sha256", nullable=False)
    op.alter_column("skill", "bundle_file_id", nullable=False)

    op.drop_column("skill", "built_in_skill_id")
