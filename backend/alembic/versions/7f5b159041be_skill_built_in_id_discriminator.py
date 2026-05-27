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
remains the unique natural key and is what the seed step deduplicates on.

Backfill of existing custom rows is unnecessary: ``bundle_file_id`` is
already NOT NULL and ``built_in_skill_id`` defaults to NULL, so every
pre-existing row satisfies the XOR.

Seed step: inserts the default built-in rows in the same revision.
Migrations are the source of truth for built-in ``skill`` rows — adding
or changing a built-in is done by writing a migration, not by reading
application code at boot. Alembic runs per-tenant schema (at deploy and
at new-tenant provisioning), so this seeds every tenant. The name and
description below are hardcoded snapshots, copied from each built-in's
SKILL.md frontmatter at the time of this revision; the migration reads
no application code or on-disk files, so its behavior is frozen forever.
"""

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7f5b159041be"
down_revision = "db87b27e93ef"
branch_labels = None
depends_on = None


# Use built-in python module instead of pydantic
@dataclass(frozen=True)
class _BuiltIn:
    # ``built_in_skill_id`` doubles as the seeded slug for the default row.
    built_in_skill_id: str
    name: str
    description: str


# Frozen snapshot of the built-ins as of this revision. Hardcoded on
# purpose — a later built-in add/edit gets its own migration; this one
# must never change.
_BUILT_INS: tuple[_BuiltIn, ...] = (
    _BuiltIn(
        built_in_skill_id="pptx",
        name="pptx",
        description=(
            "Use this skill any time a .pptx file is involved in any way — as "
            "input, output, or both. This includes: creating slide decks, pitch "
            "decks, or presentations; reading, parsing, or extracting text from "
            "any .pptx file (even if the extracted content will be used "
            "elsewhere, like in an email or summary); editing, modifying, or "
            "updating existing presentations; combining or splitting slide files; "
            "working with templates, layouts, speaker notes, or comments. Trigger "
            'whenever the user mentions "deck," "slides," "presentation," or '
            "references a .pptx filename, regardless of what they plan to do with "
            "the content afterward. If a .pptx file needs to be opened, created, "
            "or touched, use this skill."
        ),
    ),
    _BuiltIn(
        built_in_skill_id="image-generation",
        name="image-generation",
        description="Generate images using nano banana.",
    ),
    _BuiltIn(
        built_in_skill_id="company-search",
        name="company-search",
        description=(
            "Search company knowledge using onyx-cli. Returns permissioned, "
            "citation-rich results from connected sources."
        ),
    ),
)

# Lightweight Core table — deliberately not the ``Skill`` ORM model, which
# is free to evolve. Only the columns this migration writes are declared.
_skill_table = sa.table(
    "skill",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("slug", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("built_in_skill_id", sa.String),
    sa.column("bundle_file_id", sa.String),
    sa.column("bundle_sha256", sa.String),
    sa.column("author_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("is_public", sa.Boolean),
    sa.column("enabled", sa.Boolean),
)


def _seed_built_in_skills() -> None:
    """Insert one default ``skill`` row per frozen built-in. ON CONFLICT
    DO UPDATE on name/description keeps the migration idempotent if it is
    re-applied; lifecycle and bundle fields are left out of the update set.

    No slug-collision handling here on purpose: this migration introduces
    built-in rows for the first time, so the table holds no rows that could
    collide. A *future* migration that adds a built-in whose slug a tenant's
    custom skill may already own must guard against that (gate the upsert on
    ``built_in_skill_id IS NOT NULL`` and fail loud) — that's not a concern
    for this revision.
    """
    rows = [
        {
            "id": uuid.uuid4(),
            "slug": b.built_in_skill_id,
            "name": b.name,
            "description": b.description,
            "built_in_skill_id": b.built_in_skill_id,
            "bundle_file_id": None,
            "bundle_sha256": None,
            "author_user_id": None,
            "is_public": True,
            "enabled": True,
        }
        for b in _BUILT_INS
    ]

    insert_stmt = postgresql.insert(_skill_table).values(rows)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["slug"],
        set_={
            "name": insert_stmt.excluded.name,
            "description": insert_stmt.excluded.description,
        },
    )
    op.get_bind().execute(stmt)


def upgrade() -> None:
    # --- Reconcile schema drift from the in-place rewrite of b6d184cfdaf3 ---
    # b6d184cfdaf3_skills was edited after it had already run on long-lived
    # deployments, so tenants disagree on the `skill` table shape depending on
    # which version they ran. Normalize every lineage to the current (fresh-DB)
    # shape before seeding so the ON CONFLICT (slug) upsert below has a valid
    # arbiter and no stale NOT NULL columns block it.

    # 1) `manifest_metadata` NOT NULL existed in the original revision and was
    #    later removed. The ORM no longer references it; drop it so it can't
    #    trigger a NOT NULL violation on the upsert.
    op.execute("ALTER TABLE skill DROP COLUMN IF EXISTS manifest_metadata")

    # 2) Slug uniqueness. The original revision enforced it with a *partial*
    #    unique index `ux_skill_slug (slug) WHERE deleted_at IS NULL` plus a
    #    `deleted_at` soft-delete column. #11082 rewrote that to a plain *total*
    #    UNIQUE constraint `uq_skill_slug` and dropped `deleted_at`. ON CONFLICT
    #    (slug) requires a *total* unique constraint/index as its arbiter — a
    #    partial index does not match and Postgres raises "no unique or
    #    exclusion constraint matching the ON CONFLICT specification". Old
    #    tenants still carry the partial index and lack the total constraint, so
    #    converge them to the fresh-DB shape:
    #
    #    a. Drop the legacy partial index (fresh DBs never had it).
    op.execute("DROP INDEX IF EXISTS ux_skill_slug")

    #    b. Drop the legacy soft-delete column the rewritten model no longer
    #       references (fresh DBs never had it). Skills V1 only just shipped, so
    #       affected tenants hold no skill rows yet (the table is empty wherever
    #       this migration hasn't committed) — hence no duplicate-slug cleanup
    #       is needed before adding the total constraint below.
    op.execute("ALTER TABLE skill DROP COLUMN IF EXISTS deleted_at")

    #    c. Add the total UNIQUE constraint unless it already exists (fresh DBs
    #       have it from the rewritten b6d184cfdaf3). Postgres has no
    #       ADD CONSTRAINT IF NOT EXISTS, so guard explicitly.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_skill_slug'
                  AND conrelid = 'skill'::regclass
            ) THEN
                ALTER TABLE skill ADD CONSTRAINT uq_skill_slug UNIQUE (slug);
            END IF;
        END$$;
        """
    )

    op.add_column(
        "skill",
        sa.Column("built_in_skill_id", sa.String(), nullable=True),
    )

    op.alter_column(
        "skill",
        "bundle_file_id",
        existing_type=sa.String(),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "skill",
        "bundle_sha256",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )

    op.create_check_constraint(
        "ck_skill_definition_source",
        "skill",
        "(built_in_skill_id IS NULL) <> (bundle_file_id IS NULL)",
    )

    # Seed default built-in rows. Idempotent via ON CONFLICT, so this is
    # safe if the rows somehow already exist.
    _seed_built_in_skills()


def downgrade() -> None:
    op.drop_constraint("ck_skill_definition_source", "skill", type_="check")

    # Seeded built-in rows would violate NOT NULL on bundle_file_id;
    # drop them so the downgrade is clean. Custom rows are unaffected.
    op.execute("DELETE FROM skill WHERE built_in_skill_id IS NOT NULL")

    op.alter_column(
        "skill",
        "bundle_sha256",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "skill",
        "bundle_file_id",
        existing_type=sa.String(),
        nullable=False,
        existing_nullable=True,
    )

    op.drop_column("skill", "built_in_skill_id")
