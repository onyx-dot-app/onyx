"""seed_craft_documentation_built_in_skill

Seeds the built-in ``craft-documentation`` skill row, which points the agent at
the official docs at docs.onyx.app so it can answer questions about how Onyx and
Onyx Craft work. Mirrors the browser seeding in
989bc57562e4_seed_browser_built_in_skill and guards against a tenant's custom
skill already owning the ``craft-documentation`` slug.

Revision ID: 94899c60270d
Revises: bd38e2a494ff
Create Date: 2026-07-16 00:07:17.047286

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "94899c60270d"
down_revision = "bd38e2a494ff"
branch_labels = None
depends_on = None

_CRAFT_DOCUMENTATION_SLUG = "craft-documentation"
_CRAFT_DOCUMENTATION_DESCRIPTION = (
    "Answer questions about how Onyx and Onyx Craft work using the official "
    "documentation at docs.onyx.app. Use when the user asks what Craft can do, "
    "how a feature works, how to set up skills or apps, or how to deploy, "
    "configure, or administer Onyx."
)

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
    sa.column("public_permission", sa.String),
    sa.column("enabled", sa.Boolean),
)


def upgrade() -> None:
    bind = op.get_bind()

    # Fail loud if a custom skill already owns the slug (built_in_skill_id IS
    # NULL): the built-in must not clobber it via the upsert below.
    existing = bind.execute(
        sa.text("SELECT built_in_skill_id FROM skill WHERE slug = :slug"),
        {"slug": _CRAFT_DOCUMENTATION_SLUG},
    ).first()
    if existing is not None and existing[0] is None:
        raise RuntimeError(
            "Cannot seed built-in 'craft-documentation' skill: a custom skill "
            "already owns the 'craft-documentation' slug. Rename that custom "
            "skill before upgrading."
        )

    insert_stmt = postgresql.insert(_skill_table).values(
        [
            {
                "id": uuid.uuid4(),
                "slug": _CRAFT_DOCUMENTATION_SLUG,
                "name": _CRAFT_DOCUMENTATION_SLUG,
                "description": _CRAFT_DOCUMENTATION_DESCRIPTION,
                "built_in_skill_id": _CRAFT_DOCUMENTATION_SLUG,
                "bundle_file_id": None,
                "bundle_sha256": None,
                "author_user_id": None,
                "public_permission": "VIEWER",
                "enabled": True,
            }
        ]
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["slug"],
        set_={
            "name": insert_stmt.excluded.name,
            "description": insert_stmt.excluded.description,
        },
    )
    bind.execute(stmt)


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM skill WHERE slug = :slug AND built_in_skill_id = :slug"),
        {"slug": _CRAFT_DOCUMENTATION_SLUG},
    )
