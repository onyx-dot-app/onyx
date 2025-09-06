"""merge prompt into persona

Revision ID: abbfec3a5ac5
Revises: b329d00a9ea6
Create Date: 2024-12-19 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "abbfec3a5ac5"
down_revision = "8818cf73fa1a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Add new columns to persona table (only if they don't exist)

    # Check if columns exist before adding them
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_columns = [col["name"] for col in inspector.get_columns("persona")]

    if "system_prompt" not in existing_columns:
        op.add_column(
            "persona", sa.Column("system_prompt", sa.String(length=8000), nullable=True)
        )

    if "task_prompt" not in existing_columns:
        op.add_column(
            "persona", sa.Column("task_prompt", sa.String(length=8000), nullable=True)
        )

    if "datetime_aware" not in existing_columns:
        op.add_column(
            "persona",
            sa.Column(
                "datetime_aware", sa.Boolean(), nullable=False, server_default="true"
            ),
        )

    if "is_default_prompt" not in existing_columns:
        op.add_column(
            "persona",
            sa.Column(
                "is_default_prompt",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )

    # Step 2: Migrate data from prompt table to persona table (only if tables exist)
    existing_tables = inspector.get_table_names()

    if "prompt" in existing_tables and "persona__prompt" in existing_tables:
        # For personas that have associated prompts, copy the prompt data
        op.execute(
            """
            UPDATE persona
            SET
                system_prompt = p.system_prompt,
                task_prompt = p.task_prompt,
                datetime_aware = p.datetime_aware,
                is_default_prompt = p.default_prompt
            FROM (
                -- Get the first prompt for each persona (in case there are multiple)
                SELECT DISTINCT ON (pp.persona_id)
                    pp.persona_id,
                    pr.system_prompt,
                    pr.task_prompt,
                    pr.datetime_aware,
                    pr.default_prompt
                FROM persona__prompt pp
                JOIN prompt pr ON pp.prompt_id = pr.id
                ORDER BY pp.persona_id, pr.id
            ) p
            WHERE persona.id = p.persona_id
        """
        )

        # Step 4: Handle orphaned prompts (prompts not associated with any persona)
        # Create new personas for default/system prompts that aren't linked to any persona
        op.execute(
            """
            INSERT INTO persona (
                name,
                description,
                system_prompt,
                task_prompt,
                datetime_aware,
                is_default_prompt,
                chunks_above,
                chunks_below,
                llm_relevance_filter,
                llm_filter_extraction,
                recency_bias,
                builtin_persona,
                is_visible,
                deleted,
                is_public
            )
            SELECT
                p.name,
                p.description,
                p.system_prompt,
                p.task_prompt,
                p.datetime_aware,
                p.default_prompt,
                0,  -- chunks_above default
                0,  -- chunks_below default
                false,  -- llm_relevance_filter default
                false,  -- llm_filter_extraction default
                'base_decay',  -- recency_bias default
                p.default_prompt,  -- builtin_persona matches default_prompt
                NOT p.deleted,  -- is_visible based on deleted status
                false,  -- deleted default
                true  -- is_public default
            FROM prompt p
            WHERE p.id NOT IN (
                SELECT DISTINCT prompt_id FROM persona__prompt
            )
            AND p.deleted = false
        """
        )

        # Step 5: Update chat_message references
        # Since chat messages referenced prompt_id, we need to update them to use persona_id
        # This is complex as we need to map from prompt_id to persona_id

        # First, create a temporary mapping table
        op.execute(
            """
            CREATE TEMP TABLE prompt_to_persona_mapping AS
            SELECT
                pp.prompt_id,
                pp.persona_id
            FROM persona__prompt pp
        """
        )

        # Check if chat_message has prompt_id column
        chat_message_columns = [
            col["name"] for col in inspector.get_columns("chat_message")
        ]
        if "prompt_id" in chat_message_columns:
            # For chat messages with prompt_id but no persona (via chat_session)
            # we'll need to handle this carefully - set to NULL for now
            op.execute(
                """
                UPDATE chat_message cm
                SET alternate_assistant_id = pmap.persona_id
                FROM prompt_to_persona_mapping pmap
                WHERE cm.prompt_id = pmap.prompt_id
                AND cm.alternate_assistant_id IS NULL
            """
            )

            # Step 6: Drop the foreign key constraint on chat_message.prompt_id if it exists
            op.execute(
                """
                ALTER TABLE chat_message
                DROP CONSTRAINT IF EXISTS chat_message__prompt_fk
            """
            )

            # Step 7: Drop the prompt_id column from chat_message
            op.drop_column("chat_message", "prompt_id")

    # Step 3: Handle personas without prompts - set default values if needed (always run this)
    op.execute(
        """
        UPDATE persona
        SET
            system_prompt = COALESCE(system_prompt, ''),
            task_prompt = COALESCE(task_prompt, '')
        WHERE system_prompt IS NULL OR task_prompt IS NULL
    """
    )

    # Step 8: Drop the persona__prompt association table (if it exists)
    if "persona__prompt" in existing_tables:
        op.drop_table("persona__prompt")

    # Step 9: Drop the prompt table (if it exists)
    if "prompt" in existing_tables:
        op.drop_table("prompt")

    # Step 10: Make system_prompt and task_prompt non-nullable after migration (only if they exist)
    if "system_prompt" in existing_columns:
        op.alter_column(
            "persona",
            "system_prompt",
            existing_type=sa.String(length=8000),
            nullable=False,
            server_default="",
        )
        # Remove server default after setting non-nullable
        op.alter_column("persona", "system_prompt", server_default=None)

    if "task_prompt" in existing_columns:
        op.alter_column(
            "persona",
            "task_prompt",
            existing_type=sa.String(length=8000),
            nullable=False,
            server_default="",
        )
        # Remove server default after setting non-nullable
        op.alter_column("persona", "task_prompt", server_default=None)


def downgrade() -> None:
    # Step 1: Recreate the prompt table
    op.create_table(
        "prompt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.String(length=8000), nullable=False),
        sa.Column("task_prompt", sa.String(length=8000), nullable=False),
        sa.Column(
            "datetime_aware", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "default_prompt", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Step 2: Recreate the persona__prompt association table
    op.create_table(
        "persona__prompt",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompt.id"],
        ),
        sa.PrimaryKeyConstraint("persona_id", "prompt_id"),
    )

    # Step 3: Migrate data back from persona to prompt table
    op.execute(
        """
        INSERT INTO prompt (
            name,
            description,
            system_prompt,
            task_prompt,
            datetime_aware,
            default_prompt,
            deleted,
            user_id
        )
        SELECT
            CONCAT('Prompt for ', name),
            description,
            system_prompt,
            task_prompt,
            datetime_aware,
            is_default_prompt,
            deleted,
            user_id
        FROM persona
        WHERE system_prompt IS NOT NULL AND system_prompt != ''
        RETURNING id, name
    """
    )

    # Step 4: Re-establish persona__prompt relationships
    op.execute(
        """
        INSERT INTO persona__prompt (persona_id, prompt_id)
        SELECT
            p.id as persona_id,
            pr.id as prompt_id
        FROM persona p
        JOIN prompt pr ON pr.name = CONCAT('Prompt for ', p.name)
        WHERE p.system_prompt IS NOT NULL AND p.system_prompt != ''
    """
    )

    # Step 5: Add prompt_id column back to chat_message
    op.add_column("chat_message", sa.Column("prompt_id", sa.Integer(), nullable=True))

    # Step 6: Re-establish foreign key constraint
    op.create_foreign_key(
        "chat_message__prompt_fk", "chat_message", "prompt", ["prompt_id"], ["id"]
    )

    # Step 7: Remove columns from persona table
    op.drop_column("persona", "is_default_prompt")
    op.drop_column("persona", "datetime_aware")
    op.drop_column("persona", "task_prompt")
    op.drop_column("persona", "system_prompt")
