"""chosen_assistants changed to jsonb

Revision ID: da4c21c69164
Revises: c5b692fa265c
Create Date: 2024-08-18 19:06:47.291491

"""

import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "da4c21c69164"
down_revision = "c5b692fa265c"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing_ids_and_chosen_assistants = conn.execute(
        sa.text('select id, chosen_assistants from "user"')
    )
    op.drop_column(
        "user",
        "chosen_assistants",
    )
    op.add_column(
        "user",
        sa.Column(
            "chosen_assistants",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    for id, chosen_assistants in existing_ids_and_chosen_assistants:
        conn.execute(
            sa.text(
                'update "user" set chosen_assistants = :chosen_assistants where id = :id'
            ),
            {"chosen_assistants": json.dumps(chosen_assistants), "id": id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    existing_ids_and_chosen_assistants = conn.execute(
        sa.text('select id, chosen_assistants from "user"')
    )
    op.drop_column(
        "user",
        "chosen_assistants",
    )
    op.add_column(
        "user",
        sa.Column("chosen_assistants", postgresql.ARRAY(sa.Integer()), nullable=True),
    )
    for id, chosen_assistants in existing_ids_and_chosen_assistants:
        conn.execute(
            sa.text(
                'update "user" set chosen_assistants = :chosen_assistants where id = :id'
            ),
            {"chosen_assistants": chosen_assistants, "id": id},
        )
