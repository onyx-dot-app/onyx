"""rename manage:skills permission to manage:plugins

Rewrites the stored permission value in group grants, user effective
permissions and personal access token scopes. Nothing grants this value, so
most databases have no rows to change.

Revision ID: 7b154e670bd8
Revises: 55bf66dd54dd
Create Date: 2026-11-11 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7b154e670bd8"
down_revision = "55bf66dd54dd"
branch_labels = None
depends_on = None

OLD_VALUE = "manage:skills"
NEW_VALUE = "manage:plugins"


def _rename(old: str, new: str) -> None:
    params = {"old": old, "new": new}

    # A group that holds both rows keeps one, active if either was active.
    op.execute(
        sa.text(
            """
            UPDATE permission_grant AS new_grant
            SET is_deleted = new_grant.is_deleted AND old_grant.is_deleted
            FROM permission_grant AS old_grant
            WHERE new_grant.group_id = old_grant.group_id
              AND new_grant.permission = :new
              AND old_grant.permission = :old
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            DELETE FROM permission_grant AS old_grant
            USING permission_grant AS new_grant
            WHERE new_grant.group_id = old_grant.group_id
              AND new_grant.permission = :new
              AND old_grant.permission = :old
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            "UPDATE permission_grant SET permission = :new WHERE permission = :old"
        ).bindparams(**params)
    )

    for table, column in (
        ('"user"', "effective_permissions"),
        ("personal_access_token", "scopes"),
    ):
        # Keeps first-seen order and drops the duplicate when both values are present.
        op.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET {column} = (
                    SELECT jsonb_agg(value ORDER BY first_position)
                    FROM (
                        SELECT
                            CASE WHEN element = :old THEN :new ELSE element END
                                AS value,
                            MIN(position) AS first_position
                        FROM jsonb_array_elements_text({column})
                            WITH ORDINALITY AS elements(element, position)
                        GROUP BY 1
                    ) AS renamed
                )
                WHERE jsonb_typeof({column}) = 'array' AND {column} ? :old
                """
            ).bindparams(**params)
        )


def upgrade() -> None:
    _rename(OLD_VALUE, NEW_VALUE)


def downgrade() -> None:
    _rename(NEW_VALUE, OLD_VALUE)
