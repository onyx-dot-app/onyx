"""Add Craft action policy storage.

Rename workspace action policies and add personal and task policy storage.
Deploy the workspace model rename with this migration; older application
versions still query gated_action_policy. Existing policy values are preserved.

Revision ID: 131ed5e307a4
Revises: b034d72b7abe
Create Date: 2026-10-16 13:22:48.760872

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "131ed5e307a4"
down_revision = "b034d72b7abe"
branch_labels = None
depends_on = None


# Frozen provider catalog at f4340d8129. Historical migrations must not import
# the live registry, whose actions change over time.
_CATALOG_VALUES = """
    ('GITHUB', 'github.comments.create'),
    ('GITHUB', 'github.contents.read'),
    ('GITHUB', 'github.contents.write'),
    ('GITHUB', 'github.git_data.read'),
    ('GITHUB', 'github.graphql.repo.read'),
    ('GITHUB', 'github.issues.create'),
    ('GITHUB', 'github.issues.read'),
    ('GITHUB', 'github.pulls.create'),
    ('GITHUB', 'github.pulls.read'),
    ('GITHUB', 'github.refs.read'),
    ('GITHUB', 'github.refs.write'),
    ('GITHUB', 'github.releases.read'),
    ('GITHUB', 'github.repos.read'),
    ('GITHUB', 'github.search.read'),
    ('GITHUB', 'github.user.read'),
    ('GMAIL', 'gmail.attachments.read'),
    ('GMAIL', 'gmail.drafts.create'),
    ('GMAIL', 'gmail.drafts.delete'),
    ('GMAIL', 'gmail.drafts.read'),
    ('GMAIL', 'gmail.drafts.send'),
    ('GMAIL', 'gmail.drafts.update'),
    ('GMAIL', 'gmail.labels.read'),
    ('GMAIL', 'gmail.messages.modify'),
    ('GMAIL', 'gmail.messages.read'),
    ('GMAIL', 'gmail.messages.send'),
    ('GMAIL', 'gmail.messages.trash'),
    ('GMAIL', 'gmail.profile.read'),
    ('GMAIL', 'gmail.threads.read'),
    ('GOOGLE_CALENDAR', 'gcal.calendars.read'),
    ('GOOGLE_CALENDAR', 'gcal.events.create'),
    ('GOOGLE_CALENDAR', 'gcal.events.delete'),
    ('GOOGLE_CALENDAR', 'gcal.events.read'),
    ('GOOGLE_CALENDAR', 'gcal.events.update'),
    ('GOOGLE_CALENDAR', 'gcal.freebusy.read'),
    ('GOOGLE_DRIVE', 'gdrive.docs.create'),
    ('GOOGLE_DRIVE', 'gdrive.docs.read'),
    ('GOOGLE_DRIVE', 'gdrive.docs.update'),
    ('GOOGLE_DRIVE', 'gdrive.drives.read'),
    ('GOOGLE_DRIVE', 'gdrive.files.create'),
    ('GOOGLE_DRIVE', 'gdrive.files.delete'),
    ('GOOGLE_DRIVE', 'gdrive.files.export'),
    ('GOOGLE_DRIVE', 'gdrive.files.read'),
    ('GOOGLE_DRIVE', 'gdrive.files.update'),
    ('GOOGLE_DRIVE', 'gdrive.sheets.create'),
    ('GOOGLE_DRIVE', 'gdrive.sheets.read'),
    ('GOOGLE_DRIVE', 'gdrive.sheets.update'),
    ('GOOGLE_DRIVE', 'gdrive.slides.create'),
    ('GOOGLE_DRIVE', 'gdrive.slides.read'),
    ('GOOGLE_DRIVE', 'gdrive.slides.update'),
    ('HUBSPOT', 'hubspot.companies.read'),
    ('HUBSPOT', 'hubspot.companies.write'),
    ('HUBSPOT', 'hubspot.contacts.read'),
    ('HUBSPOT', 'hubspot.contacts.write'),
    ('HUBSPOT', 'hubspot.crm.search'),
    ('HUBSPOT', 'hubspot.deals.read'),
    ('HUBSPOT', 'hubspot.deals.write'),
    ('HUBSPOT', 'hubspot.owners.read'),
    ('LINEAR', 'linear.comments.create'),
    ('LINEAR', 'linear.issues.create'),
    ('LINEAR', 'linear.issues.read'),
    ('LINEAR', 'linear.projects.create'),
    ('LINEAR', 'linear.projects.read'),
    ('LINEAR', 'linear.projects.update'),
    ('LINEAR', 'linear.teams.read'),
    ('LINEAR', 'linear.viewer.read'),
    ('NOTION', 'notion.blocks.append'),
    ('NOTION', 'notion.blocks.delete'),
    ('NOTION', 'notion.blocks.read'),
    ('NOTION', 'notion.blocks.update'),
    ('NOTION', 'notion.comments.create'),
    ('NOTION', 'notion.comments.read'),
    ('NOTION', 'notion.data_sources.create'),
    ('NOTION', 'notion.data_sources.query'),
    ('NOTION', 'notion.data_sources.read'),
    ('NOTION', 'notion.data_sources.update'),
    ('NOTION', 'notion.databases.create'),
    ('NOTION', 'notion.databases.read'),
    ('NOTION', 'notion.databases.update'),
    ('NOTION', 'notion.pages.create'),
    ('NOTION', 'notion.pages.read'),
    ('NOTION', 'notion.pages.update'),
    ('NOTION', 'notion.search'),
    ('NOTION', 'notion.users.read'),
    ('SLACK', 'slack.channels.read'),
    ('SLACK', 'slack.dm.open'),
    ('SLACK', 'slack.files.write'),
    ('SLACK', 'slack.messages.read'),
    ('SLACK', 'slack.messages.write'),
    ('SLACK', 'slack.search.read'),
    ('SLACK', 'slack.users.read'),
    ('ZENDESK', 'zendesk.help_center.read'),
    ('ZENDESK', 'zendesk.help_center.write'),
    ('ZENDESK', 'zendesk.incremental.read'),
    ('ZENDESK', 'zendesk.macros.read'),
    ('ZENDESK', 'zendesk.macros.write'),
    ('ZENDESK', 'zendesk.organizations.read'),
    ('ZENDESK', 'zendesk.satisfaction_ratings.read'),
    ('ZENDESK', 'zendesk.search'),
    ('ZENDESK', 'zendesk.side_conversations.read'),
    ('ZENDESK', 'zendesk.side_conversations.write'),
    ('ZENDESK', 'zendesk.ticket_fields.read'),
    ('ZENDESK', 'zendesk.ticket_metrics.read'),
    ('ZENDESK', 'zendesk.tickets.create'),
    ('ZENDESK', 'zendesk.tickets.delete'),
    ('ZENDESK', 'zendesk.tickets.read'),
    ('ZENDESK', 'zendesk.tickets.update'),
    ('ZENDESK', 'zendesk.users.read'),
    ('ZENDESK', 'zendesk.views.read')
"""


def _backfill_task_action_policies() -> None:
    """Expand pre-approved apps for scheduled tasks into policy rows.

    For each app a task pre-approved, save ALWAYS for each known action.
    Use the catalog above for external apps and stored tool names for MCP servers.
    Create no rows for other apps or actions absent from these lists.

    These rows do not override workspace restrictions. Each request must still
    check the workspace settings, including whether users can manage permissions.
    Missing task settings mean ASK when users can manage permissions.

    After this copy, upgrade removes the old pre-approved app table.
    """
    op.execute(
        sa.text(
            "WITH catalog(app_type, action_id) AS (VALUES "
            + _CATALOG_VALUES
            + """
            ), known_actions AS (
                SELECT g.id AS gated_app_id, catalog.action_id
                FROM gated_app g
                JOIN external_app app ON app.id = g.external_app_id
                JOIN catalog ON catalog.app_type = app.app_type
                UNION
                SELECT g.id, tool.name
                FROM gated_app g
                JOIN tool ON tool.mcp_server_id = g.mcp_server_id
            )
            INSERT INTO scheduled_task_action_policy
                (scheduled_task_id, gated_app_id, action_id, policy)
            SELECT grant_row.scheduled_task_id, action.gated_app_id,
                action.action_id, 'ALWAYS'
            FROM scheduled_task_pre_approved_app grant_row
            JOIN known_actions action ON action.gated_app_id = grant_row.gated_app_id
            """
        )
    )


def upgrade() -> None:
    # Every existing target needs an identity before read-only permission lists run.
    op.execute(
        "INSERT INTO gated_app (external_app_id) SELECT id FROM external_app ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO gated_app (mcp_server_id) SELECT id FROM mcp_server ON CONFLICT DO NOTHING"
    )
    op.rename_table("gated_action_policy", "workspace_action_policy")
    op.execute(
        "ALTER TABLE workspace_action_policy RENAME CONSTRAINT "
        "uq_gated_action_policy TO uq_workspace_action_policy"
    )
    op.execute(
        "ALTER TABLE workspace_action_policy RENAME CONSTRAINT "
        "external_app_policy_pkey TO workspace_action_policy_pkey"
    )
    op.execute(
        "ALTER TABLE workspace_action_policy RENAME CONSTRAINT "
        "gated_action_policy_gated_app_id_fkey TO workspace_action_policy_gated_app_id_fkey"
    )
    op.execute(
        "ALTER SEQUENCE external_app_policy_id_seq RENAME TO workspace_action_policy_id_seq"
    )
    op.add_column(
        "gated_app",
        sa.Column(
            "users_can_manage_policies",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_table(
        "user_action_policy",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gated_app_id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("policy", sa.String(length=6), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "gated_app_id", "action_id", name="pk_user_action_policy"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_user_action_policy_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["gated_app_id"],
            ["gated_app.id"],
            name="fk_user_action_policy_gated_app",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_user_action_policy_gated_app",
        "user_action_policy",
        ["gated_app_id"],
    )
    op.create_table(
        "scheduled_task_action_policy",
        sa.Column("scheduled_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gated_app_id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("policy", sa.String(length=6), nullable=False),
        sa.PrimaryKeyConstraint(
            "scheduled_task_id",
            "gated_app_id",
            "action_id",
            name="pk_scheduled_task_action_policy",
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_task_id"],
            ["scheduled_task.id"],
            name="fk_scheduled_task_action_policy_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["gated_app_id"],
            ["gated_app.id"],
            name="fk_scheduled_task_action_policy_gated_app",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_scheduled_task_action_policy_gated_app",
        "scheduled_task_action_policy",
        ["gated_app_id"],
    )
    _backfill_task_action_policies()
    op.create_table(
        "scheduled_task_enabled_app",
        sa.Column("scheduled_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gated_app_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "scheduled_task_id", "gated_app_id", name="pk_scheduled_task_enabled_app"
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_task_id"], ["scheduled_task.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["gated_app_id"], ["gated_app.id"], ondelete="CASCADE"),
    )
    # Preserve every pre-approved app, including apps without known actions.
    # New tasks receive no memberships until their owner enables an app.
    op.execute(
        sa.text("""
        INSERT INTO scheduled_task_enabled_app (scheduled_task_id, gated_app_id)
        SELECT DISTINCT scheduled_task_id, gated_app_id
        FROM scheduled_task_pre_approved_app
    """)
    )

    op.drop_table("scheduled_task_pre_approved_app")
    op.create_index(
        "ix_action_approval_session",
        "action_approval",
        ["session_id"],
    )


def downgrade() -> None:
    # Per-action choices cannot be restored as whole-app grants without widening access.
    op.create_table(
        "scheduled_task_pre_approved_app",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheduled_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gated_app_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_task_id"], ["scheduled_task.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["gated_app_id"], ["gated_app.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "scheduled_task_id",
            "gated_app_id",
            name="uq_scheduled_task_pre_approved_app",
        ),
    )
    op.drop_index("ix_action_approval_session", table_name="action_approval")
    op.drop_index(
        "ix_scheduled_task_action_policy_gated_app",
        table_name="scheduled_task_action_policy",
    )
    op.drop_table("scheduled_task_enabled_app")
    op.drop_table("scheduled_task_action_policy")
    op.drop_index("ix_user_action_policy_gated_app", table_name="user_action_policy")
    op.drop_table("user_action_policy")
    op.drop_column("gated_app", "users_can_manage_policies")
    op.execute(
        "ALTER TABLE workspace_action_policy RENAME CONSTRAINT "
        "uq_workspace_action_policy TO uq_gated_action_policy"
    )
    op.execute(
        "ALTER TABLE workspace_action_policy RENAME CONSTRAINT "
        "workspace_action_policy_pkey TO external_app_policy_pkey"
    )
    op.execute(
        "ALTER TABLE workspace_action_policy RENAME CONSTRAINT "
        "workspace_action_policy_gated_app_id_fkey TO gated_action_policy_gated_app_id_fkey"
    )
    op.execute(
        "ALTER SEQUENCE workspace_action_policy_id_seq RENAME TO external_app_policy_id_seq"
    )
    op.rename_table("workspace_action_policy", "gated_action_policy")
