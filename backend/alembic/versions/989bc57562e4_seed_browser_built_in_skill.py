"""seed_browser_built_in_skill

Seeds the built-in ``browser`` skill row (drives the in-pod agent-browser via
the session-pinned ``browser`` wrapper). Mirrors the seeding in
7f5b159041be_skill_built_in_id_discriminator, but — per that migration's own
guidance — guards against a tenant's custom skill already owning the ``browser``
slug: a built-in must never silently clobber or shadow a custom row.

Availability is gated per-deployment by the skill's registry ``is_available``
(keyed on ENABLE_BROWSER, in onyx.skills.built_in); this migration only creates
the row.

Revision ID: 989bc57562e4
Revises: a4c9d2e7f1b8
Create Date: 2026-07-01 11:08:10.633955

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "989bc57562e4"
down_revision = "a4c9d2e7f1b8"
branch_labels = None
depends_on = None

_BROWSER_SLUG = "browser"
_BROWSER_DESCRIPTION = (
    "Drive a real (headless) browser for anything webfetch can't do: navigating "
    "JS-rendered pages, clicking, filling forms, multi-step flows, taking "
    "screenshots, extracting data, logging into sites, testing web apps, or "
    "visually checking your own app. Use whenever the task needs a rendered, "
    "interactive browser rather than static page content."
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
        {"slug": _BROWSER_SLUG},
    ).first()
    if existing is not None and existing[0] is None:
        raise RuntimeError(
            "Cannot seed built-in 'browser' skill: a custom skill already owns "
            "the 'browser' slug. Rename that custom skill before upgrading."
        )

    insert_stmt = postgresql.insert(_skill_table).values(
        [
            {
                "id": uuid.uuid4(),
                "slug": _BROWSER_SLUG,
                "name": _BROWSER_SLUG,
                "description": _BROWSER_DESCRIPTION,
                "built_in_skill_id": _BROWSER_SLUG,
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
        {"slug": _BROWSER_SLUG},
    )
