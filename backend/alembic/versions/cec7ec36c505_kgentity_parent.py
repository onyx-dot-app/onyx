"""kgentity_parent

Revision ID: cec7ec36c505
Revises: 495cb26ce93e
Create Date: 2025-06-07 20:07:46.400770

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "cec7ec36c505"
down_revision = "495cb26ce93e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kg_entity",
        sa.Column("parent_key", sa.String(), nullable=True, index=True),
    )

    # Set parent key to the immediate parent entity (if any)

    # Each entity e could have at most D=KG_MAX_PARENT_RECURSION_DEPTH ancestors (default=2)
    # The ancestors (i.e., parent candidates) can be found through the relationship pi__has_subcomponent__e
    # If p is an immediate parent of e, then there is no p__has_subcomponent_pi for all pi
    # If p is not an immediate parent of e, then there exists a pi such that p__has_subcomponent__pi
    # We can thus find the immediate parent for N many entities in O(N*D^2) time and O(D) space

    # Note: this won't work if the tenant increased KG_MAX_PARENT_RECURSION_DEPTH after extraction
    # In this case, resetting the kg data before migration and re-extracting later is recommended
    op.execute(
        text(
            """
            UPDATE kg_entity
            SET parent_key = (
                -- 1. find all ancestors (parent candidates) pi of kg_entity
                SELECT pi.entity_key
                FROM kg_relationship r
                JOIN kg_entity pi ON r.source_node = pi.id_name
                WHERE
                    r.target_node = kg_entity.id_name
                    AND r.type = 'has_subcomponent'
                    -- 2. exclude any parent candidate that is a parent of another candidate
                    AND NOT EXISTS (
                        SELECT 1
                        FROM kg_relationship r2
                        WHERE
                            r2.source_node = r.source_node
                            AND r2.type = 'has_subcomponent'
                            AND r2.target_node IN (
                                -- 3. get the other parent candidates
                                SELECT r3.source_node
                                FROM kg_relationship r3
                                WHERE
                                    r3.target_node = kg_entity.id_name
                                    AND r3.type = 'has_subcomponent'
                                    AND r3.source_node != r.source_node
                            )
                    )
                LIMIT 1
            )
            -- only bother setting parent_key for entities that have a parent
            WHERE EXISTS (
                SELECT 1
                FROM kg_relationship
                WHERE
                    target_node = kg_entity.id_name
                    AND type = 'has_subcomponent'
            );
            """
        )
    )


def downgrade() -> None:
    op.drop_column("kg_entity", "parent_key")
