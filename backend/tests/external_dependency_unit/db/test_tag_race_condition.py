"""
Test suite for tag creation race condition handling.

Tests that concurrent tag creation operations don't fail due to
UniqueViolation errors, which would occur if the upsert logic
isn't properly implemented.
"""

from concurrent.futures import as_completed
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from typing import Union
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document
from onyx.db.models import Tag
from onyx.db.tag import create_or_add_document_tag
from onyx.db.tag import create_or_add_document_tag_list


def _create_test_document(db_session: Session, doc_id: str) -> Document:
    """Create a minimal test document."""
    document = Document(
        id=doc_id,
        semantic_id=f"semantic_{doc_id}",
        boost=0,
        hidden=False,
        from_ingestion_api=False,
    )
    db_session.add(document)
    db_session.commit()
    return document


class TestTagRaceCondition:
    """Tests for tag creation race condition handling."""

    def test_concurrent_tag_creation_single_tag(
        self, db_session: Session, tenant_context: None
    ) -> None:
        """
        Test that multiple concurrent calls to create_or_add_document_tag
        with the same tag key/value all succeed without UniqueViolation errors.

        This simulates the race condition that occurs when multiple workers
        try to create the same tag simultaneously during document indexing.
        """
        # Create multiple test documents that will all get the same tag
        num_documents = 20
        doc_ids = [f"test_doc_race_{uuid4().hex[:8]}" for _ in range(num_documents)]

        for doc_id in doc_ids:
            _create_test_document(db_session, doc_id)

        # Use a unique tag key/value for this test run to avoid interference
        test_tag_key = f"test_key_{uuid4().hex[:8]}"
        test_tag_value = f"test_value_{uuid4().hex[:8]}"
        test_source = DocumentSource.FILE

        errors: list[Exception] = []
        results: list[Tag | None] = []

        def create_tag_for_document(doc_id: str) -> Tag | None:
            """Worker function that creates a tag for a document using its own session."""
            with get_session_with_current_tenant() as session:
                return create_or_add_document_tag(
                    tag_key=test_tag_key,
                    tag_value=test_tag_value,
                    source=test_source,
                    document_id=doc_id,
                    db_session=session,
                )

        # Run all tag creations concurrently with high parallelism
        with ThreadPoolExecutor(max_workers=num_documents) as executor:
            futures = {
                executor.submit(create_tag_for_document, doc_id): doc_id
                for doc_id in doc_ids
            }

            for future in as_completed(futures):
                doc_id = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    errors.append(e)

        # All operations should succeed without errors
        assert len(errors) == 0, f"Got {len(errors)} errors: {errors}"
        assert len(results) == num_documents

        # All results should be valid Tag objects
        for result in results:
            assert result is not None
            assert result.tag_key == test_tag_key
            assert result.tag_value == test_tag_value
            assert result.source == test_source

        # Verify only ONE tag was created in the database (not num_documents tags)
        with get_session_with_current_tenant() as session:
            tag_count = (
                session.execute(
                    select(Tag).where(
                        Tag.tag_key == test_tag_key,
                        Tag.tag_value == test_tag_value,
                        Tag.source == test_source,
                    )
                )
                .scalars()
                .all()
            )

        assert len(tag_count) == 1, f"Expected 1 tag, found {len(tag_count)}"

    def test_concurrent_tag_list_creation(
        self, db_session: Session, tenant_context: None
    ) -> None:
        """
        Test that multiple concurrent calls to create_or_add_document_tag_list
        with the same tag values all succeed without UniqueViolation errors.
        """
        # Create multiple test documents
        num_documents = 20
        doc_ids = [
            f"test_doc_list_race_{uuid4().hex[:8]}" for _ in range(num_documents)
        ]

        for doc_id in doc_ids:
            _create_test_document(db_session, doc_id)

        # Use unique tag key/values for this test run
        test_tag_key = f"test_list_key_{uuid4().hex[:8]}"
        test_tag_values = [f"value_{i}_{uuid4().hex[:4]}" for i in range(5)]
        test_source = DocumentSource.FILE

        errors: list[Exception] = []
        results: list[list[Tag]] = []

        def create_tag_list_for_document(doc_id: str) -> list[Tag]:
            """Worker function that creates tag list for a document using its own session."""
            with get_session_with_current_tenant() as session:
                return create_or_add_document_tag_list(
                    tag_key=test_tag_key,
                    tag_values=test_tag_values,
                    source=test_source,
                    document_id=doc_id,
                    db_session=session,
                )

        # Run all tag creations concurrently
        with ThreadPoolExecutor(max_workers=num_documents) as executor:
            futures = {
                executor.submit(create_tag_list_for_document, doc_id): doc_id
                for doc_id in doc_ids
            }

            for future in as_completed(futures):
                doc_id = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    errors.append(e)

        # All operations should succeed without errors
        assert len(errors) == 0, f"Got {len(errors)} errors: {errors}"
        assert len(results) == num_documents

        # Each result should have all the expected tags
        for result in results:
            assert len(result) == len(test_tag_values)
            result_values = {tag.tag_value for tag in result}
            assert result_values == set(test_tag_values)

        # Verify exactly len(test_tag_values) tags were created (one per value)
        with get_session_with_current_tenant() as session:
            tags = (
                session.execute(
                    select(Tag).where(
                        Tag.tag_key == test_tag_key,
                        Tag.tag_value.in_(test_tag_values),
                        Tag.source == test_source,
                    )
                )
                .scalars()
                .all()
            )

        assert len(tags) == len(
            test_tag_values
        ), f"Expected {len(test_tag_values)} tags, found {len(tags)}"

    def test_concurrent_mixed_tag_operations(
        self, db_session: Session, tenant_context: None
    ) -> None:
        """
        Test that concurrent single tag and tag list operations on the same
        tag key/value don't interfere with each other.

        This is a more realistic scenario where different documents might
        have the same metadata key but different value types (single vs list).
        """
        num_documents = 10
        doc_ids_single = [
            f"test_doc_single_{uuid4().hex[:8]}" for _ in range(num_documents)
        ]
        doc_ids_list = [
            f"test_doc_list_{uuid4().hex[:8]}" for _ in range(num_documents)
        ]

        for doc_id in doc_ids_single + doc_ids_list:
            _create_test_document(db_session, doc_id)

        # Same key but used as both single value and list value
        test_tag_key = f"mixed_key_{uuid4().hex[:8]}"
        test_single_value = f"single_value_{uuid4().hex[:8]}"
        test_list_values = [test_single_value]  # Same value but as list
        test_source = DocumentSource.FILE

        errors: list[Exception] = []

        def create_single_tag(doc_id: str) -> Tag | None:
            with get_session_with_current_tenant() as session:
                return create_or_add_document_tag(
                    tag_key=test_tag_key,
                    tag_value=test_single_value,
                    source=test_source,
                    document_id=doc_id,
                    db_session=session,
                )

        def create_list_tag(doc_id: str) -> list[Tag]:
            with get_session_with_current_tenant() as session:
                return create_or_add_document_tag_list(
                    tag_key=test_tag_key,
                    tag_values=test_list_values,
                    source=test_source,
                    document_id=doc_id,
                    db_session=session,
                )

        # Run both types of operations concurrently
        with ThreadPoolExecutor(max_workers=num_documents * 2) as executor:
            futures: list[Future[Union[Tag | None] | list[Tag]]] = []
            for doc_id in doc_ids_single:
                futures.append(executor.submit(create_single_tag, doc_id))
            for doc_id in doc_ids_list:
                futures.append(executor.submit(create_list_tag, doc_id))

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    errors.append(e)

        # All operations should succeed
        assert len(errors) == 0, f"Got {len(errors)} errors: {errors}"

        # Should have exactly 2 tags: one with is_list=False, one with is_list=True
        with get_session_with_current_tenant() as session:
            tags = (
                session.execute(
                    select(Tag).where(
                        Tag.tag_key == test_tag_key,
                        Tag.tag_value == test_single_value,
                        Tag.source == test_source,
                    )
                )
                .scalars()
                .all()
            )

        assert (
            len(tags) == 2
        ), f"Expected 2 tags (is_list=True and False), found {len(tags)}"
        is_list_values = {tag.is_list for tag in tags}
        assert is_list_values == {True, False}
