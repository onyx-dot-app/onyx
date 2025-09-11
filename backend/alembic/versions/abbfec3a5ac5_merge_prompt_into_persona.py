"""merge prompt into persona

Revision ID: abbfec3a5ac5
Revises: 8818cf73fa1a
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


MAX_PROMPT_LENGTH = 5_000_000


def upgrade() -> None:
    """NOTE: Prompts without any Personas will just be lost."""
    # Step 1: Add new columns to persona table (only if they don't exist)

    # Check if columns exist before adding them
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_columns = [col["name"] for col in inspector.get_columns("persona")]

    if "system_prompt" not in existing_columns:
        op.add_column(
            "persona",
            sa.Column(
                "system_prompt", sa.String(length=MAX_PROMPT_LENGTH), nullable=True
            ),
        )

    if "task_prompt" not in existing_columns:
        op.add_column(
            "persona",
            sa.Column(
                "task_prompt", sa.String(length=MAX_PROMPT_LENGTH), nullable=True
            ),
        )

    if "datetime_aware" not in existing_columns:
        op.add_column(
            "persona",
            sa.Column(
                "datetime_aware", sa.Boolean(), nullable=False, server_default="true"
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
                datetime_aware = p.datetime_aware
            FROM (
                -- Get the first prompt for each persona (in case there are multiple)
                SELECT DISTINCT ON (pp.persona_id)
                    pp.persona_id,
                    pr.system_prompt,
                    pr.task_prompt,
                    pr.datetime_aware
                FROM persona__prompt pp
                JOIN prompt pr ON pp.prompt_id = pr.id
            ) p
            WHERE persona.id = p.persona_id
        """
        )

        # Step 3: Update chat_message references
        # Since chat messages referenced prompt_id, we need to update them to use persona_id
        # This is complex as we need to map from prompt_id to persona_id

        # Check if chat_message has prompt_id column
        chat_message_columns = [
            col["name"] for col in inspector.get_columns("chat_message")
        ]
        if "prompt_id" in chat_message_columns:
            op.execute(
                """
                ALTER TABLE chat_message
                DROP CONSTRAINT IF EXISTS chat_message__prompt_fk
            """
            )
            op.drop_column("chat_message", "prompt_id")

    # Step 4: Handle personas without prompts - set default values if needed (always run this)
    op.execute(
        """
        UPDATE persona
        SET
            system_prompt = COALESCE(system_prompt, ''),
            task_prompt = COALESCE(task_prompt, '')
        WHERE system_prompt IS NULL OR task_prompt IS NULL
    """
    )

    # Step 5: Drop the persona__prompt association table (if it exists)
    if "persona__prompt" in existing_tables:
        op.drop_table("persona__prompt")

    # Step 6: Drop the prompt table (if it exists)
    if "prompt" in existing_tables:
        op.drop_table("prompt")

    # Step 7: Make system_prompt and task_prompt non-nullable after migration (only if they exist)
    op.alter_column(
        "persona",
        "system_prompt",
        existing_type=sa.String(length=MAX_PROMPT_LENGTH),
        nullable=False,
        server_default=None,
    )

    op.alter_column(
        "persona",
        "task_prompt",
        existing_type=sa.String(length=MAX_PROMPT_LENGTH),
        nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    # Step 1: Recreate the prompt table
    op.create_table(
        "prompt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.String(length=MAX_PROMPT_LENGTH), nullable=False),
        sa.Column("task_prompt", sa.String(length=MAX_PROMPT_LENGTH), nullable=False),
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
            is_default_persona,
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
    op.drop_column("persona", "datetime_aware")
    op.drop_column("persona", "task_prompt")
    op.drop_column("persona", "system_prompt")
