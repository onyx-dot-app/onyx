"""rework-kg-config

Revision ID: 03bf8be6b53a
Revises: cec7ec36c505
Create Date: 2025-06-16 10:52:34.815335

"""

import json


from datetime import datetime
from datetime import timedelta
from sqlalchemy.dialects import postgresql
from sqlalchemy import text
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "03bf8be6b53a"
down_revision = "cec7ec36c505"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # get current config
    current_configs = (
        op.get_bind()
        .execute(text("SELECT kg_variable_name, kg_variable_values FROM kg_config"))
        .all()
    )
    current_config_dict = {
        config.kg_variable_name: (
            config.kg_variable_values[0]
            if config.kg_variable_name
            not in ("KG_VENDOR_DOMAINS", "KG_IGNORE_EMAIL_DOMAINS")
            else config.kg_variable_values
        )
        for config in current_configs
        if config.kg_variable_values
    }

    # not using the KGConfigSettings model here in case it changes in the future
    default_coverage_start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    kg_config_settings = json.dumps(
        {
            "KG_EXPOSED": current_config_dict.get("KG_EXPOSED", False),
            "KG_ENABLED": current_config_dict.get("KG_ENABLED", False),
            "KG_VENDOR": current_config_dict.get("KG_VENDOR", None),
            "KG_VENDOR_DOMAINS": current_config_dict.get("KG_VENDOR_DOMAINS", []),
            "KG_IGNORE_EMAIL_DOMAINS": current_config_dict.get(
                "KG_IGNORE_EMAIL_DOMAINS", []
            ),
            "KG_COVERAGE_START": current_config_dict.get(
                "KG_COVERAGE_START", default_coverage_start
            ),
            "KG_MAX_COVERAGE_DAYS": current_config_dict.get("KG_MAX_COVERAGE_DAYS", 90),
            "KG_MAX_PARENT_RECURSION_DEPTH": current_config_dict.get(
                "KG_MAX_PARENT_RECURSION_DEPTH", 2
            ),
            "KG_BETA_PERSONA_ID": current_config_dict.get("KG_BETA_PERSONA_ID", None),
        }
    )
    op.execute(
        f"INSERT INTO key_value_store (key, value) VALUES ('kg_config', '{kg_config_settings}')"
    )

    # same here
    kg_processing_status = json.dumps({"in_progress": False})
    op.execute(
        f"INSERT INTO key_value_store (key, value) VALUES ('kg_processing_status', '{kg_processing_status}')"
    )

    # drop kg config table
    op.drop_table("kg_config")


def downgrade() -> None:
    op.create_table(
        "kg_config",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
        sa.Column("kg_variable_name", sa.String(), nullable=False, index=True),
        sa.Column("kg_variable_values", postgresql.ARRAY(sa.String()), nullable=False),
        sa.UniqueConstraint("kg_variable_name", name="uq_kg_config_variable_name"),
    )
    op.bulk_insert(
        sa.table(
            "kg_config",
            sa.column("kg_variable_name", sa.String),
            sa.column("kg_variable_values", postgresql.ARRAY(sa.String)),
        ),
        [
            {"kg_variable_name": "KG_EXPOSED", "kg_variable_values": ["false"]},
            {"kg_variable_name": "KG_ENABLED", "kg_variable_values": ["false"]},
            {"kg_variable_name": "KG_VENDOR", "kg_variable_values": []},
            {"kg_variable_name": "KG_VENDOR_DOMAINS", "kg_variable_values": []},
            {"kg_variable_name": "KG_IGNORE_EMAIL_DOMAINS", "kg_variable_values": []},
            {
                "kg_variable_name": "KG_EXTRACTION_IN_PROGRESS",
                "kg_variable_values": ["false"],
            },
            {
                "kg_variable_name": "KG_CLUSTERING_IN_PROGRESS",
                "kg_variable_values": ["false"],
            },
            {
                "kg_variable_name": "KG_COVERAGE_START",
                "kg_variable_values": [
                    (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
                ],
            },
            {"kg_variable_name": "KG_MAX_COVERAGE_DAYS", "kg_variable_values": ["90"]},
            {
                "kg_variable_name": "KG_MAX_PARENT_RECURSION_DEPTH",
                "kg_variable_values": ["2"],
            },
        ],
    )

    op.execute("DELETE FROM key_value_store WHERE key = 'kg_processing_status'")
    op.execute("DELETE FROM key_value_store WHERE key = 'kg_config'")
