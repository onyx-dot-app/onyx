"""hierarchy_nodes_v1

Revision ID: 81c22b1e2e78
Revises: d1b637d7050a
Create Date: 2026-01-13 18:10:01.021451

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.configs.constants import DocumentSource


# revision identifiers, used by Alembic.
revision = "81c22b1e2e78"
down_revision = "d1b637d7050a"
branch_labels = None
depends_on = None


# Human-readable display names for each source
SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "ingestion_api": "Ingestion API",
    "slack": "Slack",
    "web": "Web",
    "google_drive": "Google Drive",
    "gmail": "Gmail",
    "requesttracker": "Request Tracker",
    "github": "GitHub",
    "gitbook": "GitBook",
    "gitlab": "GitLab",
    "guru": "Guru",
    "bookstack": "BookStack",
    "outline": "Outline",
    "confluence": "Confluence",
    "jira": "Jira",
    "slab": "Slab",
    "productboard": "Productboard",
    "file": "File",
    "coda": "Coda",
    "notion": "Notion",
    "zulip": "Zulip",
    "linear": "Linear",
    "hubspot": "HubSpot",
    "document360": "Document360",
    "gong": "Gong",
    "google_sites": "Google Sites",
    "zendesk": "Zendesk",
    "loopio": "Loopio",
    "dropbox": "Dropbox",
    "sharepoint": "SharePoint",
    "teams": "Teams",
    "salesforce": "Salesforce",
    "discourse": "Discourse",
    "axero": "Axero",
    "clickup": "ClickUp",
    "mediawiki": "MediaWiki",
    "wikipedia": "Wikipedia",
    "asana": "Asana",
    "s3": "S3",
    "r2": "R2",
    "google_cloud_storage": "Google Cloud Storage",
    "oci_storage": "OCI Storage",
    "xenforo": "XenForo",
    "not_applicable": "Not Applicable",
    "discord": "Discord",
    "freshdesk": "Freshdesk",
    "fireflies": "Fireflies",
    "egnyte": "Egnyte",
    "airtable": "Airtable",
    "highspot": "Highspot",
    "drupal_wiki": "Drupal Wiki",
    "imap": "IMAP",
    "bitbucket": "Bitbucket",
    "testrail": "TestRail",
    "mock_connector": "Mock Connector",
    "user_file": "User File",
}


def upgrade() -> None:
    # 1. Create hierarchy_node table
    op.create_table(
        "hierarchy_node",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_node_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("node_type", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["hierarchy_node.id"]),
        sa.UniqueConstraint(
            "raw_node_id", "source", name="uq_hierarchy_node_raw_id_source"
        ),
    )
    op.create_index("ix_hierarchy_node_parent_id", "hierarchy_node", ["parent_id"])
    op.create_index(
        "ix_hierarchy_node_source_type", "hierarchy_node", ["source", "node_type"]
    )

    # 2. Create hierarchy_fetch_attempt table
    op.create_table(
        "hierarchy_fetch_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_credential_pair_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("nodes_fetched", sa.Integer(), nullable=True, default=0),
        sa.Column("nodes_updated", sa.Integer(), nullable=True, default=0),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("full_exception_trace", sa.Text(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("time_started", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["connector_credential_pair_id"],
            ["connector_credential_pair.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_hierarchy_fetch_attempt_status", "hierarchy_fetch_attempt", ["status"]
    )
    op.create_index(
        "ix_hierarchy_fetch_attempt_time_created",
        "hierarchy_fetch_attempt",
        ["time_created"],
    )
    op.create_index(
        "ix_hierarchy_fetch_attempt_cc_pair",
        "hierarchy_fetch_attempt",
        ["connector_credential_pair_id"],
    )

    # 3. Insert SOURCE-type hierarchy nodes for each DocumentSource
    # We insert these so every existing document can have a parent hierarchy node
    for source in DocumentSource:
        source_value = source.value
        display_name = SOURCE_DISPLAY_NAMES.get(
            source_value, source_value.replace("_", " ").title()
        )
        op.execute(
            sa.text(
                """
                INSERT INTO hierarchy_node (raw_node_id, display_name, source, node_type, parent_id)
                VALUES (:raw_node_id, :display_name, :source, 'source', NULL)
                """
            ).bindparams(
                raw_node_id=source_value,
                display_name=display_name,
                source=source_value,
            )
        )

    # 4. Add parent_hierarchy_node_id column to document table
    op.add_column(
        "document",
        sa.Column("parent_hierarchy_node_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_document_parent_hierarchy_node",
        "document",
        "hierarchy_node",
        ["parent_hierarchy_node_id"],
        ["id"],
    )
    op.create_index(
        "ix_document_parent_hierarchy_node_id",
        "document",
        ["parent_hierarchy_node_id"],
    )

    # 5. Set all existing documents' parent_hierarchy_node_id to their source's SOURCE node
    # For documents with multiple connectors, we pick one source deterministically (MIN connector_id)
    op.execute(
        sa.text(
            """
            UPDATE document d
            SET parent_hierarchy_node_id = hn.id
            FROM (
                -- Get the source for each document (pick MIN connector_id for determinism)
                SELECT DISTINCT ON (dbcc.id)
                    dbcc.id as doc_id,
                    c.source as source
                FROM document_by_connector_credential_pair dbcc
                JOIN connector c ON dbcc.connector_id = c.id
                ORDER BY dbcc.id, dbcc.connector_id
            ) doc_source
            JOIN hierarchy_node hn ON hn.raw_node_id = doc_source.source AND hn.node_type = 'source'
            WHERE d.id = doc_source.doc_id
            """
        )
    )

    # Create the persona__hierarchy_node association table
    op.create_table(
        "persona__hierarchy_node",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("hierarchy_node_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hierarchy_node_id"],
            ["hierarchy_node.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("persona_id", "hierarchy_node_id"),
    )

    # Add index for efficient lookups
    op.create_index(
        "ix_persona__hierarchy_node_hierarchy_node_id",
        "persona__hierarchy_node",
        ["hierarchy_node_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_persona__hierarchy_node_hierarchy_node_id",
        table_name="persona__hierarchy_node",
    )
    op.drop_table("persona__hierarchy_node")

    # Remove parent_hierarchy_node_id from document
    op.drop_index("ix_document_parent_hierarchy_node_id", table_name="document")
    op.drop_constraint(
        "fk_document_parent_hierarchy_node", "document", type_="foreignkey"
    )
    op.drop_column("document", "parent_hierarchy_node_id")

    # Drop hierarchy_fetch_attempt table
    op.drop_index(
        "ix_hierarchy_fetch_attempt_cc_pair", table_name="hierarchy_fetch_attempt"
    )
    op.drop_index(
        "ix_hierarchy_fetch_attempt_time_created", table_name="hierarchy_fetch_attempt"
    )
    op.drop_index(
        "ix_hierarchy_fetch_attempt_status", table_name="hierarchy_fetch_attempt"
    )
    op.drop_table("hierarchy_fetch_attempt")

    # Drop hierarchy_node table
    op.drop_index("ix_hierarchy_node_source_type", table_name="hierarchy_node")
    op.drop_index("ix_hierarchy_node_parent_id", table_name="hierarchy_node")
    op.drop_table("hierarchy_node")
