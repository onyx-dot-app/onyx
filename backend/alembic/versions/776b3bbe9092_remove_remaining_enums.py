"""Remove Remaining Enums

Revision ID: 776b3bbe9092
Revises: 4738e4b3bae1
Create Date: 2024-03-22 21:34:27.629444

"""

from alembic import op
import sqlalchemy as sa

from onyx.db.models import IndexModelStatus
from onyx.context.search.enums import RecencyBiasSetting
from onyx.context.search.enums import SearchType

# revision identifiers, used by Alembic.
revision = "776b3bbe9092"
down_revision = "4738e4b3bae1"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.alter_column(
        "persona",
        "search_type",
        type_=sa.String,
        existing_type=sa.Enum(SearchType, native_enum=False),
        existing_nullable=False,
    )
    op.alter_column(
        "persona",
        "recency_bias",
        type_=sa.String,
        existing_type=sa.Enum(RecencyBiasSetting, native_enum=False),
        existing_nullable=False,
    )

    # Because the indexmodelstatus enum does not have a mapping to a string type
    # we need this workaround instead of directly changing the type
    op.add_column("embedding_model", sa.Column("temp_status", sa.String))
    op.execute("UPDATE embedding_model SET temp_status = status::text")
    op.drop_column("embedding_model", "status")
    op.alter_column("embedding_model", "temp_status", new_column_name="status")

    op.execute("DROP TYPE IF EXISTS searchtype")
    op.execute("DROP TYPE IF EXISTS recencybiassetting")
    op.execute("DROP TYPE IF EXISTS indexmodelstatus")


def downgrade() -> None:
    op.alter_column(
        "persona",
        "search_type",
        type_=sa.Enum(SearchType, native_enum=False),
        existing_type=sa.String(length=50),
        existing_nullable=False,
    )
    op.alter_column(
        "persona",
        "recency_bias",
        type_=sa.Enum(RecencyBiasSetting, native_enum=False),
        existing_type=sa.String(length=50),
        existing_nullable=False,
    )
    op.alter_column(
        "embedding_model",
        "status",
        type_=sa.Enum(IndexModelStatus, native_enum=False),
        existing_type=sa.String(length=50),
        existing_nullable=False,
    )
