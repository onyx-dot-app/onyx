"""
External dependency unit tests for UserFileIndexingAdapter metadata writing.

Validates that build_metadata_aware_chunks produces DocMetadataAwareIndexChunk
objects with both `user_project` and `personas` fields populated correctly
based on actual DB associations.

Uses real PostgreSQL for UserFile/Persona/UserProject rows.
Mocks the LLM tokenizer and file store since they are not relevant here.
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.db.enums import UserFileStatus
from onyx.db.models import Persona
from onyx.db.models import Persona__UserFile
from onyx.db.models import Project__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserProject
from onyx.indexing.adapters.user_file_indexing_adapter import UserFileIndexingAdapter
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import IndexChunk
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.constants import TEST_TENANT_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_user_file(db_session: Session, user: User) -> UserFile:
    uf = UserFile(
        id=uuid4(),
        user_id=user.id,
        file_id=f"test_file_{uuid4().hex[:8]}",
        name=f"test_{uuid4().hex[:8]}.txt",
        file_type="text/plain",
        status=UserFileStatus.COMPLETED,
        chunk_count=1,
    )
    db_session.add(uf)
    db_session.commit()
    db_session.refresh(uf)
    return uf


def _create_persona(db_session: Session, user: User) -> Persona:
    persona = Persona(
        name=f"Test Persona {uuid4().hex[:8]}",
        description="Test persona",
        system_prompt="test",
        task_prompt="test",
        tools=[],
        document_sets=[],
        users=[user],
        groups=[],
        is_visible=True,
        is_public=True,
        display_priority=None,
        starter_messages=None,
        deleted=False,
        user_id=user.id,
    )
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


def _create_project(db_session: Session, user: User) -> UserProject:
    project = UserProject(
        user_id=user.id,
        name=f"project-{uuid4().hex[:8]}",
        instructions="",
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


def _make_index_chunk(user_file: UserFile) -> IndexChunk:
    """Build a minimal IndexChunk whose source document ID matches the UserFile."""
    doc = Document(
        id=str(user_file.id),
        source=DocumentSource.USER_FILE,
        semantic_identifier=user_file.name,
        sections=[TextSection(text="test chunk content", link=None)],
        metadata={},
    )
    return IndexChunk(
        source_document=doc,
        chunk_id=0,
        blurb="test chunk",
        content="test chunk content",
        source_links={0: ""},
        image_file_id=None,
        section_continuation=False,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        contextual_rag_reserved_tokens=0,
        doc_summary="",
        chunk_context="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        embeddings=ChunkEmbedding(
            full_embedding=[0.0] * 768,
            mini_chunk_embeddings=[],
        ),
        title_embedding=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAdapterWritesBothMetadataFields:
    """build_metadata_aware_chunks must populate user_project AND personas."""

    @patch(
        "onyx.indexing.adapters.user_file_indexing_adapter.get_default_llm",
        side_effect=Exception("no LLM in test"),
    )
    def test_file_linked_to_persona_gets_persona_id(
        self,
        _mock_llm: MagicMock,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        user = create_test_user(db_session, "adapter_persona")
        uf = _create_user_file(db_session, user)
        persona = _create_persona(db_session, user)

        db_session.add(Persona__UserFile(persona_id=persona.id, user_file_id=uf.id))
        db_session.commit()

        adapter = UserFileIndexingAdapter(
            tenant_id=TEST_TENANT_ID, db_session=db_session
        )
        chunk = _make_index_chunk(uf)
        doc = chunk.source_document
        context = DocumentBatchPrepareContext(updatable_docs=[doc], id_to_boost_map={})

        result = adapter.build_metadata_aware_chunks(
            chunks_with_embeddings=[chunk],
            chunk_content_scores=[1.0],
            tenant_id=TEST_TENANT_ID,
            context=context,
        )

        assert len(result.chunks) == 1
        aware_chunk = result.chunks[0]
        assert persona.id in aware_chunk.personas
        assert aware_chunk.user_project == []

    @patch(
        "onyx.indexing.adapters.user_file_indexing_adapter.get_default_llm",
        side_effect=Exception("no LLM in test"),
    )
    def test_file_linked_to_project_gets_project_id(
        self,
        _mock_llm: MagicMock,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        user = create_test_user(db_session, "adapter_project")
        uf = _create_user_file(db_session, user)
        project = _create_project(db_session, user)

        db_session.add(Project__UserFile(project_id=project.id, user_file_id=uf.id))
        db_session.commit()

        adapter = UserFileIndexingAdapter(
            tenant_id=TEST_TENANT_ID, db_session=db_session
        )
        chunk = _make_index_chunk(uf)
        context = DocumentBatchPrepareContext(
            updatable_docs=[chunk.source_document], id_to_boost_map={}
        )

        result = adapter.build_metadata_aware_chunks(
            chunks_with_embeddings=[chunk],
            chunk_content_scores=[1.0],
            tenant_id=TEST_TENANT_ID,
            context=context,
        )

        assert len(result.chunks) == 1
        aware_chunk = result.chunks[0]
        assert project.id in aware_chunk.user_project
        assert aware_chunk.personas == []

    @patch(
        "onyx.indexing.adapters.user_file_indexing_adapter.get_default_llm",
        side_effect=Exception("no LLM in test"),
    )
    def test_file_linked_to_both_gets_both_ids(
        self,
        _mock_llm: MagicMock,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        user = create_test_user(db_session, "adapter_both")
        uf = _create_user_file(db_session, user)
        persona = _create_persona(db_session, user)
        project = _create_project(db_session, user)

        db_session.add(Persona__UserFile(persona_id=persona.id, user_file_id=uf.id))
        db_session.add(Project__UserFile(project_id=project.id, user_file_id=uf.id))
        db_session.commit()

        adapter = UserFileIndexingAdapter(
            tenant_id=TEST_TENANT_ID, db_session=db_session
        )
        chunk = _make_index_chunk(uf)
        context = DocumentBatchPrepareContext(
            updatable_docs=[chunk.source_document], id_to_boost_map={}
        )

        result = adapter.build_metadata_aware_chunks(
            chunks_with_embeddings=[chunk],
            chunk_content_scores=[1.0],
            tenant_id=TEST_TENANT_ID,
            context=context,
        )

        aware_chunk = result.chunks[0]
        assert persona.id in aware_chunk.personas
        assert project.id in aware_chunk.user_project

    @patch(
        "onyx.indexing.adapters.user_file_indexing_adapter.get_default_llm",
        side_effect=Exception("no LLM in test"),
    )
    def test_file_with_no_associations_gets_empty_lists(
        self,
        _mock_llm: MagicMock,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        user = create_test_user(db_session, "adapter_empty")
        uf = _create_user_file(db_session, user)

        adapter = UserFileIndexingAdapter(
            tenant_id=TEST_TENANT_ID, db_session=db_session
        )
        chunk = _make_index_chunk(uf)
        context = DocumentBatchPrepareContext(
            updatable_docs=[chunk.source_document], id_to_boost_map={}
        )

        result = adapter.build_metadata_aware_chunks(
            chunks_with_embeddings=[chunk],
            chunk_content_scores=[1.0],
            tenant_id=TEST_TENANT_ID,
            context=context,
        )

        aware_chunk = result.chunks[0]
        assert aware_chunk.personas == []
        assert aware_chunk.user_project == []

    @patch(
        "onyx.indexing.adapters.user_file_indexing_adapter.get_default_llm",
        side_effect=Exception("no LLM in test"),
    )
    def test_multiple_personas_all_appear(
        self,
        _mock_llm: MagicMock,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A file linked to multiple personas should have all their IDs."""
        user = create_test_user(db_session, "adapter_multi")
        uf = _create_user_file(db_session, user)
        persona_a = _create_persona(db_session, user)
        persona_b = _create_persona(db_session, user)

        db_session.add(Persona__UserFile(persona_id=persona_a.id, user_file_id=uf.id))
        db_session.add(Persona__UserFile(persona_id=persona_b.id, user_file_id=uf.id))
        db_session.commit()

        adapter = UserFileIndexingAdapter(
            tenant_id=TEST_TENANT_ID, db_session=db_session
        )
        chunk = _make_index_chunk(uf)
        context = DocumentBatchPrepareContext(
            updatable_docs=[chunk.source_document], id_to_boost_map={}
        )

        result = adapter.build_metadata_aware_chunks(
            chunks_with_embeddings=[chunk],
            chunk_content_scores=[1.0],
            tenant_id=TEST_TENANT_ID,
            context=context,
        )

        aware_chunk = result.chunks[0]
        assert set(aware_chunk.personas) == {persona_a.id, persona_b.id}
