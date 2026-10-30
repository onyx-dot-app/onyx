"""Preserve draft fast defaults as chat naming defaults

Revision ID: c92b67e56ec4
Revises: 1c7b6cce66ac
Create Date: 2026-10-14 16:53:14.197305

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "c92b67e56ec4"
down_revision = "1c7b6cce66ac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE llm_model_flow
        SET is_default = FALSE
        WHERE llm_model_flow_type = 'FAST'
          AND is_default = TRUE
          AND EXISTS (
              SELECT 1 FROM llm_model_flow
              WHERE llm_model_flow_type = 'CHAT_NAMING' AND is_default = TRUE
          )
        """)
    op.execute("""
        UPDATE llm_model_flow AS naming
        SET is_default = TRUE
        FROM llm_model_flow AS fast
        WHERE naming.llm_model_flow_type = 'CHAT_NAMING'
          AND fast.llm_model_flow_type = 'FAST'
          AND fast.is_default = TRUE
          AND naming.model_configuration_id = fast.model_configuration_id
        """)
    op.execute("""
        DELETE FROM llm_model_flow AS fast
        USING llm_model_flow AS naming
        WHERE fast.llm_model_flow_type = 'FAST'
          AND naming.llm_model_flow_type = 'CHAT_NAMING'
          AND fast.model_configuration_id = naming.model_configuration_id
        """)
    op.execute("""
        UPDATE llm_model_flow
        SET llm_model_flow_type = 'CHAT_NAMING'
        WHERE llm_model_flow_type = 'FAST'
        """)


def downgrade() -> None:
    # Original naming rows cannot be distinguished from converted draft rows.
    pass
