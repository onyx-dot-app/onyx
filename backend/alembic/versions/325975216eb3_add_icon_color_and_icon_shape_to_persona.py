"""Add icon_color and icon_shape to Persona

Revision ID: 325975216eb3
Revises: 91ffac7e65b3
Create Date: 2024-07-24 21:29:31.784562

"""

import random
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column, select

# revision identifiers, used by Alembic.
revision = "325975216eb3"
down_revision = "91ffac7e65b3"
branch_labels: None = None
depends_on: None = None


colorOptions = [
    "#FF6FBF",
    "#6FB1FF",
    "#B76FFF",
    "#FFB56F",
    "#6FFF8D",
    "#FF6F6F",
    "#6FFFFF",
]


# Function to generate a random shape ensuring at least 3 of the middle 4 squares are filled
def generate_random_shape() -> int:
    center_squares = [12, 10, 6, 14, 13, 11, 7, 15]
    center_fill = random.choice(center_squares)
    remaining_squares = [i for i in range(16) if not (center_fill & (1 << i))]
    random.shuffle(remaining_squares)
    for i in range(10 - bin(center_fill).count("1")):
        center_fill |= 1 << remaining_squares[i]
    return center_fill


def upgrade() -> None:
    op.add_column("persona", sa.Column("icon_color", sa.String(), nullable=True))
    op.add_column("persona", sa.Column("icon_shape", sa.Integer(), nullable=True))
    op.add_column("persona", sa.Column("uploaded_image_id", sa.String(), nullable=True))

    persona = table(
        "persona",
        column("id", sa.Integer),
        column("icon_color", sa.String),
        column("icon_shape", sa.Integer),
    )

    conn = op.get_bind()
    personas = conn.execute(select(persona.c.id))

    for persona_id in personas:
        random_color = random.choice(colorOptions)
        random_shape = generate_random_shape()
        conn.execute(
            persona.update()
            .where(persona.c.id == persona_id[0])
            .values(icon_color=random_color, icon_shape=random_shape)
        )


def downgrade() -> None:
    op.drop_column("persona", "icon_shape")
    op.drop_column("persona", "uploaded_image_id")
    op.drop_column("persona", "icon_color")
