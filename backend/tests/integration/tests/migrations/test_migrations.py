# TODO(rkuo): All of the downgrade_postgres and upgrade_postgres operations here
# are vulnerable to deadlocks. We could deal with them similar to reset_postgres
# where we retry out of process

import json

import pytest
from sqlalchemy import text

from onyx.configs.constants import DEFAULT_BOOST
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from tests.integration.common_utils.reset import downgrade_postgres
from tests.integration.common_utils.reset import upgrade_postgres


@pytest.mark.skip(
    reason="Migration test no longer needed - migration has been applied to production"
)
def test_fix_capitalization_migration() -> None:
    """Test that the be2ab2aa50ee migration correctly lowercases external_user_group_ids"""
    # Reset the database and run migrations up to the second to last migration
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        # Upgrade it to the migration before the fix
        revision="369644546676",
    )

    # Insert test data with mixed case group IDs
    test_data = [
        {
            "id": "test_doc_1",
            "external_user_group_ids": ["Group1", "GROUP2", "group3"],
            "semantic_id": "test_doc_1",
            "boost": DEFAULT_BOOST,
            "hidden": False,
            "from_ingestion_api": False,
            "last_modified": "NOW()",
        },
        {
            "id": "test_doc_2",
            "external_user_group_ids": ["UPPER1", "upper2", "UPPER3"],
            "semantic_id": "test_doc_2",
            "boost": DEFAULT_BOOST,
            "hidden": False,
            "from_ingestion_api": False,
            "last_modified": "NOW()",
        },
    ]

    # Insert the test data
    with get_session_with_current_tenant() as db_session:
        for doc in test_data:
            db_session.execute(
                text(
                    """
                    INSERT INTO document (
                        id,
                        external_user_group_ids,
                        semantic_id,
                        boost,
                        hidden,
                        from_ingestion_api,
                        last_modified
                    )
                    VALUES (
                        :id,
                        :group_ids,
                        :semantic_id,
                        :boost,
                        :hidden,
                        :from_ingestion_api,
                        :last_modified
                    )
                    """
                ),
                {
                    "id": doc["id"],
                    "group_ids": doc["external_user_group_ids"],
                    "semantic_id": doc["semantic_id"],
                    "boost": doc["boost"],
                    "hidden": doc["hidden"],
                    "from_ingestion_api": doc["from_ingestion_api"],
                    "last_modified": doc["last_modified"],
                },
            )
        db_session.commit()

    # Verify the data was inserted correctly
    with get_session_with_current_tenant() as db_session:
        results = db_session.execute(
            text(
                """
                SELECT id, external_user_group_ids
                FROM document
                WHERE id IN ('test_doc_1', 'test_doc_2')
                ORDER BY id
                """
            )
        ).fetchall()

        # Verify initial state
        assert len(results) == 2
        assert results[0].external_user_group_ids == ["Group1", "GROUP2", "group3"]
        assert results[1].external_user_group_ids == ["UPPER1", "upper2", "UPPER3"]

    # Run migrations again to apply the fix
    upgrade_postgres(
        database="postgres", config_name="alembic", revision="be2ab2aa50ee"
    )

    # Verify the fix was applied
    with get_session_with_current_tenant() as db_session:
        results = db_session.execute(
            text(
                """
                SELECT id, external_user_group_ids
                FROM document
                WHERE id IN ('test_doc_1', 'test_doc_2')
                ORDER BY id
                """
            )
        ).fetchall()

        # Verify all group IDs are lowercase
        assert len(results) == 2
        assert results[0].external_user_group_ids == ["group1", "group2", "group3"]
        assert results[1].external_user_group_ids == ["upper1", "upper2", "upper3"]


def test_jira_connector_migration() -> None:
    """Test that the da42808081e3 migration correctly updates Jira connector configurations"""
    # Reset the database and run migrations up to the migration before the Jira connector change
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        # Upgrade it to the migration before the Jira connector change
        revision="f13db29f3101",
    )

    # Insert test data with various Jira connector configurations
    test_data = [
        {
            "id": 1,
            "name": "jira_connector_1",
            "source": "JIRA",
            "connector_specific_config": {
                "jira_project_url": "https://example.atlassian.net/projects/PROJ",
                "comment_email_blacklist": ["test@example.com"],
                "batch_size": 100,
                "labels_to_skip": ["skip-me"],
            },
        },
        {
            "id": 2,
            "name": "jira_connector_2",
            "source": "JIRA",
            "connector_specific_config": {
                "jira_project_url": "https://other.atlassian.net/projects/OTHER"
            },
        },
        {
            "id": 3,
            "name": "jira_connector_3",
            "source": "JIRA",
            "connector_specific_config": {
                "jira_project_url": "https://example.atlassian.net/projects/TEST",
                "batch_size": 50,
            },
        },
    ]

    # Insert the test data
    with get_session_with_current_tenant() as db_session:
        for connector in test_data:
            db_session.execute(
                text(
                    """
                    INSERT INTO connector (
                        id,
                        name,
                        source,
                        connector_specific_config
                    )
                    VALUES (
                        :id,
                        :name,
                        :source,
                        :config
                    )
                    """
                ),
                {
                    "id": connector["id"],
                    "name": connector["name"],
                    "source": connector["source"],
                    "config": json.dumps(connector["connector_specific_config"]),
                },
            )
        db_session.commit()

    # Verify the data was inserted correctly
    with get_session_with_current_tenant() as db_session:
        results = db_session.execute(
            text(
                """
                SELECT id, connector_specific_config
                FROM connector
                WHERE source = 'JIRA'
                ORDER BY id
                """
            )
        ).fetchall()

        # Verify initial state
        assert len(results) == 3
        assert (
            results[0].connector_specific_config
            == test_data[0]["connector_specific_config"]
        )
        assert (
            results[1].connector_specific_config
            == test_data[1]["connector_specific_config"]
        )
        assert (
            results[2].connector_specific_config
            == test_data[2]["connector_specific_config"]
        )

    # Run migrations again to apply the Jira connector change
    upgrade_postgres(
        database="postgres", config_name="alembic", revision="da42808081e3"
    )

    # Verify the upgrade was applied correctly
    with get_session_with_current_tenant() as db_session:
        results = db_session.execute(
            text(
                """
                SELECT id, connector_specific_config
                FROM connector
                WHERE source = 'JIRA'
                ORDER BY id
                """
            )
        ).fetchall()

        # Verify new format
        assert len(results) == 3

        # First connector - full config
        config_0 = results[0].connector_specific_config
        assert config_0["jira_base_url"] == "https://example.atlassian.net"
        assert config_0["project_key"] == "PROJ"
        assert config_0["comment_email_blacklist"] == ["test@example.com"]
        assert config_0["batch_size"] == 100
        assert config_0["labels_to_skip"] == ["skip-me"]

        # Second connector - minimal config
        config_1 = results[1].connector_specific_config
        assert config_1["jira_base_url"] == "https://other.atlassian.net"
        assert config_1["project_key"] == "OTHER"
        assert "comment_email_blacklist" not in config_1
        assert "batch_size" not in config_1
        assert "labels_to_skip" not in config_1

        # Third connector - partial config
        config_2 = results[2].connector_specific_config
        assert config_2["jira_base_url"] == "https://example.atlassian.net"
        assert config_2["project_key"] == "TEST"
        assert config_2["batch_size"] == 50
        assert "comment_email_blacklist" not in config_2
        assert "labels_to_skip" not in config_2

    # Test downgrade path
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="f13db29f3101"
    )

    # Verify the downgrade was applied correctly
    with get_session_with_current_tenant() as db_session:
        results = db_session.execute(
            text(
                """
                SELECT id, connector_specific_config
                FROM connector
                WHERE source = 'JIRA'
                ORDER BY id
                """
            )
        ).fetchall()

        # Verify reverted to old format
        assert len(results) == 3

        # First connector - full config
        config_0 = results[0].connector_specific_config
        assert (
            config_0["jira_project_url"]
            == "https://example.atlassian.net/projects/PROJ"
        )
        assert config_0["comment_email_blacklist"] == ["test@example.com"]
        assert config_0["batch_size"] == 100
        assert config_0["labels_to_skip"] == ["skip-me"]

        # Second connector - minimal config
        config_1 = results[1].connector_specific_config
        assert (
            config_1["jira_project_url"] == "https://other.atlassian.net/projects/OTHER"
        )

        # Third connector - partial config
        config_2 = results[2].connector_specific_config
        assert (
            config_2["jira_project_url"]
            == "https://example.atlassian.net/projects/TEST"
        )
        assert config_2["batch_size"] == 50
