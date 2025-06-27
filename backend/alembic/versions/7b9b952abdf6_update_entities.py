"""update-entities

Revision ID: 7b9b952abdf6
Revises: 36e9220ab794
Create Date: 2025-06-23 20:24:08.139201

"""

import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7b9b952abdf6"
down_revision = "36e9220ab794"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # new entity type metadata_attribute_conversion
    new_entity_type_conversion = {
        "LINEAR": {
            "team": {"name": "team", "keep": True, "implication_property": None},
            "state": {"name": "state", "keep": True, "implication_property": None},
            "priority": {
                "name": "priority",
                "keep": True,
                "implication_property": None,
            },
            "estimate": {
                "name": "estimate",
                "keep": True,
                "implication_property": None,
            },
            "created_at": {
                "name": "created_at",
                "keep": True,
                "implication_property": None,
            },
            "started_at": {
                "name": "started_at",
                "keep": True,
                "implication_property": None,
            },
            "completed_at": {
                "name": "completed_at",
                "keep": True,
                "implication_property": None,
            },
            "due_date": {
                "name": "due_date",
                "keep": True,
                "implication_property": None,
            },
            "creator": {
                "name": "creator",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "from_email",
                    "implied_relationship_name": "is_creator_of",
                },
            },
            "assignee": {
                "name": "assignee",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "from_email",
                    "implied_relationship_name": "is_assignee_of",
                },
            },
        },
        "JIRA": {
            "issuetype": {
                "name": "subtype",
                "keep": True,
                "implication_property": None,
            },
            "status": {"name": "status", "keep": True, "implication_property": None},
            "priority": {
                "name": "priority",
                "keep": True,
                "implication_property": None,
            },
            "project_name": {
                "name": "project",
                "keep": True,
                "implication_property": None,
            },
            "created": {
                "name": "created_at",
                "keep": True,
                "implication_property": None,
            },
            "updated": {
                "name": "updated_at",
                "keep": True,
                "implication_property": None,
            },
            "resolution_date": {
                "name": "completed_at",
                "keep": True,
                "implication_property": None,
            },
            "duedate": {"name": "due_date", "keep": True, "implication_property": None},
            "reporter_email": {
                "name": "creator",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "from_email",
                    "implied_relationship_name": "is_creator_of",
                },
            },
            "assignee_email": {
                "name": "assignee",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "from_email",
                    "implied_relationship_name": "is_assignee_of",
                },
            },
            "key": {"name": "key", "keep": True, "implication_property": None},
            "parent": {"name": "parent", "keep": True, "implication_property": None},
        },
        "GITHUB_PR": {
            "repo": {"name": "repository", "keep": True, "implication_property": None},
            "state": {"name": "state", "keep": True, "implication_property": None},
            "num_commits": {
                "name": "num_commits",
                "keep": True,
                "implication_property": None,
            },
            "num_files_changed": {
                "name": "num_files_changed",
                "keep": True,
                "implication_property": None,
            },
            "labels": {"name": "labels", "keep": True, "implication_property": None},
            "merged": {"name": "merged", "keep": True, "implication_property": None},
            "merged_at": {
                "name": "merged_at",
                "keep": True,
                "implication_property": None,
            },
            "closed_at": {
                "name": "closed_at",
                "keep": True,
                "implication_property": None,
            },
            "created_at": {
                "name": "created_at",
                "keep": True,
                "implication_property": None,
            },
            "updated_at": {
                "name": "updated_at",
                "keep": True,
                "implication_property": None,
            },
            "user": {
                "name": "creator",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "from_email",
                    "implied_relationship_name": "is_creator_of",
                },
            },
            "assignees": {
                "name": "assignees",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "from_email",
                    "implied_relationship_name": "is_assignee_of",
                },
            },
        },
        "GITHUB_ISSUE": {
            "repo": {"name": "repository", "keep": True, "implication_property": None},
            "state": {"name": "state", "keep": True, "implication_property": None},
            "labels": {"name": "labels", "keep": True, "implication_property": None},
            "closed_at": {
                "name": "closed_at",
                "keep": True,
                "implication_property": None,
            },
            "created_at": {
                "name": "created_at",
                "keep": True,
                "implication_property": None,
            },
            "updated_at": {
                "name": "updated_at",
                "keep": True,
                "implication_property": None,
            },
            "user": {
                "name": "creator",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "from_email",
                    "implied_relationship_name": "is_creator_of",
                },
            },
            "assignees": {
                "name": "assignees",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "from_email",
                    "implied_relationship_name": "is_assignee_of",
                },
            },
        },
        "FIREFLIES": {},
        "ACCOUNT": {},
        "OPPORTUNITY": {
            "name": {"name": "name", "keep": True, "implication_property": None},
            "stage_name": {"name": "stage", "keep": True, "implication_property": None},
            "type": {"name": "type", "keep": True, "implication_property": None},
            "amount": {"name": "amount", "keep": True, "implication_property": None},
            "fiscal_year": {
                "name": "fiscal_year",
                "keep": True,
                "implication_property": None,
            },
            "fiscal_quarter": {
                "name": "fiscal_quarter",
                "keep": True,
                "implication_property": None,
            },
            "is_closed": {
                "name": "is_closed",
                "keep": True,
                "implication_property": None,
            },
            "close_date": {
                "name": "close_date",
                "keep": True,
                "implication_property": None,
            },
            "probability": {
                "name": "close_probability",
                "keep": True,
                "implication_property": None,
            },
            "created_date": {
                "name": "created_at",
                "keep": True,
                "implication_property": None,
            },
            "last_modified_date": {
                "name": "updated_at",
                "keep": True,
                "implication_property": None,
            },
            "account": {
                "name": "account",
                "keep": False,
                "implication_property": {
                    "implied_entity_type": "ACCOUNT",
                    "implied_relationship_name": "is_account_of",
                },
            },
        },
        "VENDOR": {},
        "EMPLOYEE": {},
    }

    current_entity_types = conn.execute(
        sa.text("SELECT id_name, attributes from kg_entity_type")
    ).all()
    for entity_type, attributes in current_entity_types:
        # delete removed entity types
        if entity_type not in new_entity_type_conversion:
            op.execute(
                sa.text(f"DELETE FROM kg_entity_type WHERE id_name = '{entity_type}'")
            )
            continue

        # update entity type attributes
        if "metadata_attributes" in attributes:
            del attributes["metadata_attributes"]
        attributes["metadata_attribute_conversion"] = new_entity_type_conversion[
            entity_type
        ]
        attributes_str = json.dumps(attributes).replace("'", "''")
        op.execute(
            sa.text(
                f"UPDATE kg_entity_type SET attributes = '{attributes_str}'"
                f"WHERE id_name = '{entity_type}'"
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()

    current_entity_types = conn.execute(
        sa.text("SELECT id_name, attributes from kg_entity_type")
    ).all()
    for entity_type, attributes in current_entity_types:
        conversion = {}
        if "metadata_attribute_conversion" in attributes:
            conversion = attributes.pop("metadata_attribute_conversion")
        attributes["metadata_attributes"] = {
            attr: prop["name"] for attr, prop in conversion.items() if prop["keep"]
        }

        attributes_str = json.dumps(attributes).replace("'", "''")
        op.execute(
            sa.text(
                f"UPDATE kg_entity_type SET attributes = '{attributes_str}'"
                f"WHERE id_name = '{entity_type}'"
            ),
        )
