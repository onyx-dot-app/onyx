import pytest
from sqlalchemy import text

from onyx.configs.constants import DEFAULT_BOOST
from onyx.db.engine import get_session_context_manager
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
    with get_session_context_manager() as db_session:
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
    with get_session_context_manager() as db_session:
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
    with get_session_context_manager() as db_session:
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
