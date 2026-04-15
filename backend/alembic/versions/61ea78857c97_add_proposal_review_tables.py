"""add proposal review tables

Revision ID: 61ea78857c97
Revises: d129f37b3d87
Create Date: 2026-04-09 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import fastapi_users_db_sqlalchemy


# revision identifiers, used by Alembic.
revision = "61ea78857c97"
down_revision = "d129f37b3d87"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # -- proposal_review_ruleset --
    op.create_table(
        "proposal_review_ruleset",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_proposal_review_ruleset_tenant_id",
        "proposal_review_ruleset",
        ["tenant_id"],
    )

    # -- proposal_review_rule --
    op.create_table(
        "proposal_review_rule",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "ruleset_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column(
            "rule_intent",
            sa.Text(),
            server_default=sa.text("'CHECK'"),
            nullable=False,
        ),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.Text(),
            server_default=sa.text("'MANUAL'"),
            nullable=False,
        ),
        sa.Column("authority", sa.Text(), nullable=True),
        sa.Column(
            "is_hard_stop",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "refinement_needed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("refinement_question", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ruleset_id"],
            ["proposal_review_ruleset.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_proposal_review_rule_ruleset_id",
        "proposal_review_rule",
        ["ruleset_id"],
    )

    # -- proposal_review_proposal --
    # Includes inline proposal-level decision fields (no separate decision table).
    op.create_table(
        "proposal_review_proposal",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        # Inline proposal-level decision fields
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column(
            "decision_officer_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "jira_synced",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("jira_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["decision_officer_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "tenant_id"),
    )
    op.create_index(
        "ix_proposal_review_proposal_tenant_id",
        "proposal_review_proposal",
        ["tenant_id"],
    )
    op.create_index(
        "ix_proposal_review_proposal_document_id",
        "proposal_review_proposal",
        ["document_id"],
    )
    op.create_index(
        "ix_proposal_review_proposal_status",
        "proposal_review_proposal",
        ["status"],
    )

    # -- proposal_review_run --
    op.create_table(
        "proposal_review_run",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "proposal_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "ruleset_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "triggered_by",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("total_rules", sa.Integer(), nullable=False),
        sa.Column(
            "completed_rules",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposal_review_proposal.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ruleset_id"],
            ["proposal_review_ruleset.id"],
        ),
        sa.ForeignKeyConstraint(["triggered_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_proposal_review_run_proposal_id",
        "proposal_review_run",
        ["proposal_id"],
    )

    # -- proposal_review_finding --
    # Includes inline per-finding decision fields (no separate decision table).
    op.create_table(
        "proposal_review_finding",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "proposal_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "review_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.Column("llm_tokens_used", sa.Integer(), nullable=True),
        # Inline per-finding decision fields
        sa.Column("decision_action", sa.Text(), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column(
            "decision_officer_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposal_review_proposal.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["proposal_review_rule.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["review_run_id"],
            ["proposal_review_run.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["decision_officer_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_proposal_review_finding_proposal_id",
        "proposal_review_finding",
        ["proposal_id"],
    )
    op.create_index(
        "ix_proposal_review_finding_review_run_id",
        "proposal_review_finding",
        ["review_run_id"],
    )
    op.create_index(
        "ix_proposal_review_finding_rule_id",
        "proposal_review_finding",
        ["rule_id"],
    )

    # -- proposal_review_document --
    op.create_table(
        "proposal_review_document",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "proposal_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_type", sa.Text(), nullable=True),
        sa.Column("file_store_id", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("document_role", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_by",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposal_review_proposal.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["uploaded_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_proposal_review_document_proposal_id",
        "proposal_review_document",
        ["proposal_id"],
    )

    # -- proposal_review_import_job --
    op.create_table(
        "proposal_review_import_job",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "ruleset_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column(
            "rules_created",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["ruleset_id"],
            ["proposal_review_ruleset.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_proposal_review_import_job_ruleset_id",
        "proposal_review_import_job",
        ["ruleset_id"],
    )

    # -- proposal_review_config --
    op.create_table(
        "proposal_review_config",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False, unique=True),
        sa.Column("jira_connector_id", sa.Integer(), nullable=True),
        sa.Column("jira_project_key", sa.Text(), nullable=True),
        sa.Column("field_mapping", postgresql.JSONB(), nullable=True),
        sa.Column("jira_writeback", postgresql.JSONB(), nullable=True),
        sa.Column("review_model", sa.Text(), nullable=True),
        sa.Column("import_model", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("proposal_review_import_job")
    op.drop_table("proposal_review_config")
    op.drop_table("proposal_review_document")
    op.drop_table("proposal_review_finding")
    op.drop_table("proposal_review_run")
    op.drop_table("proposal_review_proposal")
    op.drop_table("proposal_review_rule")
    op.drop_table("proposal_review_ruleset")
