"""Remove _alt suffix from model_name

Revision ID: d9ec13955951
Revises: da4c21c69164
Create Date: 2024-08-20 16:31:32.955686

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "d9ec13955951"
down_revision = "da4c21c69164"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE embedding_model
        SET model_name = regexp_replace(model_name, '__danswer_alt_index$', '')
        WHERE model_name LIKE '%__danswer_alt_index'
    """
    )


def downgrade() -> None:
    # We can't reliably add the __danswer_alt_index suffix back, so we'll leave this empty
    pass
