from alembic import op
import sqlalchemy as sa


revision = "9071f636d5f2"
down_revision = "131ed5e307a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_provider", sa.Column("zoom_voice_provider_id", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_llm_provider_zoom_voice_provider_id",
        "llm_provider",
        ["zoom_voice_provider_id"],
    )
    op.create_foreign_key(
        "fk_llm_provider_zoom_voice_provider",
        "llm_provider",
        "voice_provider",
        ["zoom_voice_provider_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_llm_provider_zoom_voice_provider", "llm_provider", type_="foreignkey"
    )
    op.drop_index("ix_llm_provider_zoom_voice_provider_id", table_name="llm_provider")
    op.drop_column("llm_provider", "zoom_voice_provider_id")
