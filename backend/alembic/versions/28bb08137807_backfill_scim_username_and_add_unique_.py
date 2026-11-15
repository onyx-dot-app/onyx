"""backfill scim_username and add unique index

Revision ID: 28bb08137807
Revises: 06a38a307492
Create Date: 2026-08-19 13:07:33.600011

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "28bb08137807"
down_revision = "06a38a307492"
branch_labels = None
depends_on = None

_mapping = sa.table(
    "scim_user_mapping",
    sa.column("id", sa.Integer),
    sa.column("user_id", sa.Uuid),
    sa.column("scim_username", sa.String),
)

_user = sa.table(
    "user",
    sa.column("id", sa.Uuid),
    sa.column("email", sa.String),
)


def upgrade() -> None:
    # Null case-insensitive duplicates among the provisioned values (keeping
    # the oldest row) before the backfill, so a derived value never displaces
    # a provisioned one. Nulled rows keep matching by email via the coalesce.
    keepers = (
        sa.select(sa.func.min(_mapping.c.id).label("keep_id"))
        .where(_mapping.c.scim_username.is_not(None))
        .group_by(sa.func.lower(_mapping.c.scim_username))
        .subquery()
    )
    op.execute(
        _mapping.update()
        .where(
            _mapping.c.scim_username.is_not(None),
            _mapping.c.id.not_in(sa.select(keepers.c.keep_id)),
        )
        .values(scim_username=None)
    )

    # Rows provisioned before scim_username was recorded are seeded from the
    # email, which held the userName. Provisioned values are skipped, and
    # emails are unique lowercase (ensure_lowercase_email), so no collisions.
    taken = _mapping.alias("taken")
    op.execute(
        _mapping.update()
        .where(
            _mapping.c.scim_username.is_(None),
            _mapping.c.user_id == _user.c.id,
            ~sa.exists(
                sa.select(1).where(
                    sa.func.lower(taken.c.scim_username) == sa.func.lower(_user.c.email)
                )
            ),
        )
        .values(scim_username=_user.c.email)
    )

    op.create_index(
        "uq_scim_user_mapping_scim_username_lower",
        "scim_user_mapping",
        [sa.text("lower(scim_username)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_scim_user_mapping_scim_username_lower",
        table_name="scim_user_mapping",
    )
