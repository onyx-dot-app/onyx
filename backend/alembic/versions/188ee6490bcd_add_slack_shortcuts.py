"""add slack shortcuts

Revision ID: 188ee6490bcd
Revises: 5c448911b12f
Create Date: 2025-05-08 17:21:21.810793

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '188ee6490bcd'
down_revision = '5c448911b12f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('slack_shortcut_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slack_bot_id', sa.Integer(), nullable=False),
        sa.Column('persona_id', sa.Integer(), nullable=True),
        sa.Column('shortcut_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('enable_auto_filters', sa.Boolean(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('response_type', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['persona_id'], ['persona.id'], ),
        sa.ForeignKeyConstraint(['slack_bot_id'], ['slack_bot.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    
    op.create_index('ix_slack_shortcut_config_slack_bot_id_default', 'slack_shortcut_config', 
                   ['slack_bot_id', 'is_default'], unique=True, postgresql_where=sa.text("is_default IS TRUE"))
    
    op.create_table('slack_shortcut_config__standard_answer_category',
        sa.Column('slack_shortcut_config_id', sa.Integer(), nullable=False),
        sa.Column('standard_answer_category_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['slack_shortcut_config_id'], ['slack_shortcut_config.id'], ),
        sa.ForeignKeyConstraint(['standard_answer_category_id'], ['standard_answer_category.id'], ),
        sa.PrimaryKeyConstraint('slack_shortcut_config_id', 'standard_answer_category_id')
    )

    # Create default shortcut configs for existing slack bots without one
    conn = op.get_bind()
    slack_bots = conn.execute(sa.text("SELECT id FROM slack_bot")).fetchall()

    for slack_bot in slack_bots:
        slack_bot_id = slack_bot[0]
        existing_default = conn.execute(
            sa.text(
                "SELECT id FROM slack_shortcut_config WHERE slack_bot_id = :bot_id AND is_default = TRUE"
            ),
            {"bot_id": slack_bot_id},
        ).fetchone()

        if not existing_default:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO slack_shortcut_config (
                        slack_bot_id, persona_id, shortcut_config, enable_auto_filters, is_default, response_type
                    ) VALUES (
                        :bot_id, NULL,
                        '{"shortcut_name": null, '
                        '"shortcut_description": "Default shortcut configuration", '
                        '"default_message": "", '
                        '"respond_member_group_list": [], '
                        '"answer_filters": [], '
                        '"follow_up_tags": [], '
                        '"is_ephemeral": false, '
                        '"show_continue_in_web_ui": true}',
                        FALSE, TRUE, 'citations'
                    )
                """
                ),
                {"bot_id": slack_bot_id},
            )


def downgrade() -> None:
    op.drop_index('ix_slack_shortcut_config_slack_bot_id_default', table_name='slack_shortcut_config')

    op.drop_table('slack_shortcut_config__standard_answer_category')
    op.drop_table('slack_shortcut_config')