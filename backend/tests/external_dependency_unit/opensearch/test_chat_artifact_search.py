"""Published files (chat artifacts) in ordinary internal search, against
Postgres, the file store and OpenSearch, with in-process embeddings: the owner finds
them and no one else does, knowledge-scoped searches leave them out, and
every delete of the file, its chat or its owner removes them."""

from uuid import UUID, uuid4

import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.orm import Session

from onyx.auth.users import UserManager
from onyx.background.celery.tasks.chat_artifact_indexing.tasks import (
    process_single_chat_artifact,
)
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.context.search.models import ChunkSearchRequest, PersonaSearchInfo
from onyx.context.search.pipeline import search_pipeline
from onyx.db.api_key import remove_all_api_keys__no_commit
from onyx.db.chat import save_chat_artifact
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import ChatArtifactIndexStatus
from onyx.db.models import ApiKey, ChatArtifact, ChatSession, User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.users import delete_user_from_db, finish_user_delete
from onyx.document_index.factory import (
    build_opensearch_document_index,
    get_default_document_index,
)
from onyx.indexing.chat_artifact_index import delete_chat_artifacts_from_index
from onyx.server.query_and_chat.chat_backend import (
    delete_all_chat_sessions,
    delete_chat_session_by_id,
)
from onyx.tools.tool_implementations.sandbox.models import ArtifactAtPath
from onyx.tools.tool_implementations.search import search_tool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.async_client_utils import dispose_loop_async_clients
from tests.external_dependency_unit.conftest import MakeTestUser

pytestmark = pytest.mark.usefixtures(
    "tenant_context",
    "initialize_file_store",
    "full_deployment_setup",
    "fake_embeddings",
)


def _publish_and_index(db_session: Session, user: User, word: str) -> UUID:
    """A file published in a new chat of `user` that contains `word`,
    indexed by its task."""
    chat = ChatSession(id=uuid4(), user_id=user.id, persona_id=DEFAULT_PERSONA_ID)
    db_session.add(chat)
    db_session.commit()
    published = save_chat_artifact(
        f"# Field notes\n\nThe survey counted {word} near the river.\n".encode(),
        name="notes.md",
        mime_type="text/markdown",
        target=ArtifactAtPath(
            chat_session_id=chat.id,
            path="/workspace/notes.md",
        ),
        title=None,
        thumbnail=None,
    )
    if published.artifact_id is None:
        raise RuntimeError("save_chat_artifact always sets the artifact")
    process_single_chat_artifact.run(
        artifact_id=str(published.artifact_id),  # ty: ignore[invalid-argument-type]
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,  # ty: ignore[invalid-argument-type]
    )
    return published.artifact_id


def _found(
    db_session: Session,
    user: User,
    word: str,
    document_id: str,
    *,
    persona: PersonaSearchInfo | None = None,
    project_id: int | None = None,
) -> bool:
    """Whether an internal search of `word` by `user` returns the document,
    after a refresh of the PRESENT index."""
    search_settings = get_current_search_settings(db_session)
    build_opensearch_document_index(search_settings).get_documents_with_any_chunk(
        [document_id]
    )
    chunks = search_pipeline(
        chunk_search_request=ChunkSearchRequest(query=word),
        document_index=get_default_document_index(search_settings, None),
        user=user,
        persona_search_info=persona,
        db_session=db_session,
        project_id_filter=project_id,
    )
    return any(chunk.document_id == document_id for chunk in chunks)


def test_only_the_owner_finds_a_published_file_and_only_in_unscoped_search(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("artifact_search_owner")
    other = make_test_user("artifact_search_other")
    word = f"quokka{uuid4().hex[:8]}"
    artifact_id = _publish_and_index(db_session, owner, word)
    document_id = str(artifact_id)
    try:
        assert _found(db_session, owner, word, document_id)

        assert not _found(db_session, other, word, document_id)
        # An agent with knowledge and a project chat search only their scope.
        assert not _found(
            db_session,
            owner,
            word,
            document_id,
            persona=PersonaSearchInfo(
                document_set_names=["field-guides"],
                search_start_date=None,
                attached_document_ids=[],
                hierarchy_node_ids=[],
            ),
        )
        assert not _found(db_session, owner, word, document_id, project_id=1)
    finally:
        delete_chat_artifacts_from_index([artifact_id])


def test_internal_search_is_available_with_only_published_files(
    db_session: Session,
    make_test_user: MakeTestUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for no_source in (
        "check_connectors_exist",
        "check_federated_connectors_exist",
    ):
        monkeypatch.setattr(search_tool, no_source, lambda _db_session: False)
    monkeypatch.setattr(
        "onyx.db.connector.check_user_files_exist", lambda _db_session: False
    )
    owner = make_test_user("artifact_search_available")
    artifact_id = _publish_and_index(db_session, owner, "pangolin")
    try:
        assert SearchTool.is_available(db_session)
    finally:
        delete_chat_artifacts_from_index([artifact_id])


@pytest.mark.parametrize(
    "delete",
    ["soft chat delete", "hard chat delete", "delete of all chats"],
)
def test_a_deleted_chat_takes_its_files_out_of_search(
    db_session: Session, make_test_user: MakeTestUser, delete: str
) -> None:
    owner = make_test_user("artifact_search_delete")
    word = f"wombat{uuid4().hex[:8]}"
    artifact_id = _publish_and_index(db_session, owner, word)
    document_id = str(artifact_id)
    try:
        assert _found(db_session, owner, word, document_id)
        [chat] = db_session.query(ChatSession).filter_by(user_id=owner.id).all()

        if delete == "delete of all chats":
            delete_all_chat_sessions(user=owner, db_session=db_session)
        else:
            delete_chat_session_by_id(
                chat.id,
                hard_delete=delete == "hard chat delete",
                user=owner,
                db_session=db_session,
            )

        assert not _found(db_session, owner, word, document_id)
        db_session.expire_all()
        artifact = db_session.get(ChatArtifact, artifact_id)
        # A soft delete keeps the row, outside the indexing beat's reads.
        assert (artifact is None) == (delete == "hard chat delete")
        if artifact is not None:
            assert artifact.index_status == ChatArtifactIndexStatus.REMOVED
    finally:
        delete_chat_artifacts_from_index([artifact_id])


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("delete_path", ["admin", "auth", "key removal"])
async def test_a_deleted_user_leaves_no_files_for_the_next_holder_of_the_email(
    db_session: Session, make_test_user: MakeTestUser, delete_path: str
) -> None:
    owner = make_test_user("artifact_search_departed")
    word = f"numbat{uuid4().hex[:8]}"
    artifact_id = _publish_and_index(db_session, owner, word)
    document_id = str(artifact_id)
    try:
        assert _found(db_session, owner, word, document_id)
        email = owner.email
        if delete_path == "admin":
            delete_user_from_db(owner, db_session)
        elif delete_path == "key removal":
            # A Community downgrade removes the keys that admins manage, with
            # the user behind each, and finishes every user's delete at once.
            db_session.add(
                ApiKey(
                    name="artifact search",
                    hashed_api_key=uuid4().hex,
                    api_key_display=uuid4().hex,
                    user_id=owner.id,
                    owner_id=make_test_user("artifact_search_key_admin").id,
                )
            )
            db_session.flush()
            cleanup = remove_all_api_keys__no_commit(db_session)
            db_session.commit()
            finish_user_delete(cleanup, db_session)
        else:
            async with get_async_session_context_manager(
                get_current_tenant_id()
            ) as session:
                async_user = await session.get(User, owner.id)
                if async_user is None:
                    raise RuntimeError("the owner exists until the delete")
                await UserManager(SQLAlchemyUserDatabase(session, User)).delete(
                    async_user
                )
        successor = make_test_user("artifact_search_successor")
        successor.email = email
        db_session.commit()

        assert not _found(db_session, successor, word, document_id)
    finally:
        delete_chat_artifacts_from_index([artifact_id])
        # The pooled async connections belong to this module's loop.
        await dispose_loop_async_clients()
