import time
from datetime import datetime
from datetime import timezone

import pytest

import onyx.chat.process_message as process_message_module
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.server.documents.models import DocumentSource
from onyx.server.documents.models import IndexAttemptSnapshot
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.external_dependency_unit.connectors.seafile.conftest import delete_file
from tests.external_dependency_unit.connectors.seafile.conftest import move_file
from tests.external_dependency_unit.connectors.seafile.conftest import overwrite_file
from tests.external_dependency_unit.connectors.seafile.conftest import (
    SeafileTestLibrary,
)
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.document_search import (
    DocumentSearchManager,
)
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser

_DUMMY_OPENAI_API_KEY = "sk-mock-seafile-e2e-tests"
_SEARCH_TIMEOUT_SECONDS = 60
pytest_plugins = ["tests.external_dependency_unit.connectors.seafile.conftest"]


def _wait_for_search_result(
    query: str,
    expected_content: str,
    admin_user: DATestUser,
) -> list[str]:
    deadline = time.monotonic() + _SEARCH_TIMEOUT_SECONDS
    latest_results: list[str] = []
    while time.monotonic() < deadline:
        latest_results = DocumentSearchManager.search_documents(
            query=query,
            user_performing_action=admin_user,
        )
        if any(expected_content in result for result in latest_results):
            return latest_results
        time.sleep(2)

    raise AssertionError(
        f"Timed out waiting for Seafile search result containing {expected_content!r}. "
        f"Latest results: {latest_results}"
    )


def _wait_for_search_absence(
    query: str,
    unexpected_content: str,
    admin_user: DATestUser,
) -> list[str]:
    deadline = time.monotonic() + _SEARCH_TIMEOUT_SECONDS
    latest_results: list[str] = []
    while time.monotonic() < deadline:
        latest_results = DocumentSearchManager.search_documents(
            query=query,
            user_performing_action=admin_user,
        )
        if all(unexpected_content not in result for result in latest_results):
            return latest_results
        time.sleep(2)

    raise AssertionError(
        "Timed out waiting for Seafile search result to disappear: "
        f"{unexpected_content!r}. Latest results: {latest_results}"
    )


def _get_internal_search_tool_id(admin_user: DATestUser) -> int:
    tools = ToolManager.list_tools(user_performing_action=admin_user)
    for tool in tools:
        if tool.in_code_tool_id == SEARCH_TOOL_ID:
            return tool.id
    raise AssertionError("SearchTool must exist for this test")


def _run_once_and_wait_for_completion(
    cc_pair_id: int,
    admin_user: DATestUser,
) -> IndexAttemptSnapshot:
    index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair_id,
        user_performing_action=admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair_id,
        user_performing_action=admin_user,
    )
    return IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair_id,
        user_performing_action=admin_user,
    )


def test_seafile_connector_indexes_via_workers_and_searches(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    seafile_test_library: SeafileTestLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )

    credential = CredentialManager.create(
        source=DocumentSource.SEAFILE,
        credential_json={"seafile_api_token": seafile_test_library.api_token},
        user_performing_action=admin_user,
    )
    connector = ConnectorManager.create(
        name=f"SeafileE2E-{int(datetime.now().timestamp())}",
        source=DocumentSource.SEAFILE,
        input_type=InputType.POLL,
        connector_specific_config={
            "base_url": seafile_test_library.base_url,
            "repo_ids": [seafile_test_library.repo_id],
            "path_prefixes": ["/docs"],
            "allowed_extensions": [".txt", ".md"],
            "max_file_size_bytes": 200,
        },
        access_type=AccessType.PUBLIC,
        groups=[],
        user_performing_action=admin_user,
    )
    cc_pair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    before = datetime.now(timezone.utc)
    CCPairManager.run_once(
        cc_pair=cc_pair,
        from_beginning=True,
        user_performing_action=admin_user,
    )
    index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )

    finished_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_attempt.status is not None
    assert finished_attempt.status.is_successful()
    assert finished_attempt.total_docs_indexed == len(
        seafile_test_library.seeded_text_files
    )
    assert finished_attempt.new_docs_indexed == len(
        seafile_test_library.seeded_text_files
    )

    search_phrase = "Seafile connector fixture readme"
    _wait_for_search_result(
        query=search_phrase,
        expected_content=search_phrase,
        admin_user=admin_user,
    )

    search_tool_id = _get_internal_search_tool_id(admin_user)
    persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="seafile_e2e_search_persona",
        tool_ids=[search_tool_id],
    )
    chat_session = ChatSessionManager.create(
        user_performing_action=admin_user,
        persona_id=persona.id,
    )
    monkeypatch.setattr(process_message_module, "INTEGRATION_TESTS_MODE", True)
    chat_response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=f"Search for {search_phrase}",
        user_performing_action=admin_user,
        forced_tool_ids=[search_tool_id],
        mock_llm_response=(
            '{"name":"internal_search","arguments":'
            f'{{"queries":["{search_phrase}"]}}}}'
        ),
    )

    assert chat_response.error is None, f"Unexpected chat error: {chat_response.error}"
    searched_documents = [
        document
        for used_tool in chat_response.used_tools
        for document in used_tool.documents
    ]
    assert any(search_phrase in document.blurb for document in searched_documents)


def test_seafile_connector_indexes_multiple_libraries_via_workers_and_searches(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    seafile_test_library: SeafileTestLibrary,
    seafile_second_test_library: SeafileTestLibrary,
) -> None:
    credential = CredentialManager.create(
        source=DocumentSource.SEAFILE,
        credential_json={"seafile_api_token": seafile_test_library.api_token},
        user_performing_action=admin_user,
    )
    connector = ConnectorManager.create(
        name=f"SeafileMultiLibraryE2E-{int(datetime.now().timestamp())}",
        source=DocumentSource.SEAFILE,
        input_type=InputType.POLL,
        connector_specific_config={
            "base_url": seafile_test_library.base_url,
            "repo_ids": [
                seafile_test_library.repo_id,
                seafile_second_test_library.repo_id,
            ],
            "path_prefixes": ["/docs"],
            "allowed_extensions": [".txt", ".md"],
            "max_file_size_bytes": 200,
        },
        access_type=AccessType.PUBLIC,
        groups=[],
        user_performing_action=admin_user,
    )
    cc_pair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    before = datetime.now(timezone.utc)
    CCPairManager.run_once(
        cc_pair=cc_pair,
        from_beginning=True,
        user_performing_action=admin_user,
    )
    finished_attempt = _run_once_and_wait_for_completion(cc_pair.id, admin_user)
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )

    expected_doc_count = len(seafile_test_library.seeded_text_files) + len(
        seafile_second_test_library.seeded_text_files
    )
    assert finished_attempt.status is not None
    assert finished_attempt.status.is_successful()
    assert finished_attempt.total_docs_indexed == expected_doc_count

    first_library_phrase = "Seafile connector fixture readme"
    second_library_phrase = "Second Seafile library fixture content"
    _wait_for_search_result(
        query=first_library_phrase,
        expected_content=first_library_phrase,
        admin_user=admin_user,
    )
    _wait_for_search_result(
        query=second_library_phrase,
        expected_content=second_library_phrase,
        admin_user=admin_user,
    )


def test_seafile_connector_reindexes_and_prunes_source_mutations(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    seafile_mutation_test_library: SeafileTestLibrary,
) -> None:
    credential = CredentialManager.create(
        source=DocumentSource.SEAFILE,
        credential_json={"seafile_api_token": seafile_mutation_test_library.api_token},
        user_performing_action=admin_user,
    )
    connector = ConnectorManager.create(
        name=f"SeafileMutationE2E-{int(datetime.now().timestamp())}",
        source=DocumentSource.SEAFILE,
        input_type=InputType.POLL,
        connector_specific_config={
            "base_url": seafile_mutation_test_library.base_url,
            "repo_ids": [seafile_mutation_test_library.repo_id],
            "path_prefixes": ["/docs"],
            "allowed_extensions": [".txt"],
            "max_file_size_bytes": 200,
        },
        access_type=AccessType.PUBLIC,
        groups=[],
        user_performing_action=admin_user,
    )
    cc_pair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    before = datetime.now(timezone.utc)
    CCPairManager.run_once(
        cc_pair=cc_pair,
        from_beginning=True,
        user_performing_action=admin_user,
    )
    finished_attempt = _run_once_and_wait_for_completion(cc_pair.id, admin_user)
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )
    assert finished_attempt.status is not None
    assert finished_attempt.status.is_successful()

    delete_phrase = "Mutation fixture delete target"
    moved_out_phrase = "Mutation fixture move target"
    replacement_phrase = "Mutation fixture readme replacement indexed"
    moved_in_phrase = "Mutation fixture private scope target"
    _wait_for_search_result(
        query=delete_phrase,
        expected_content=delete_phrase,
        admin_user=admin_user,
    )
    _wait_for_search_result(
        query=moved_out_phrase,
        expected_content=moved_out_phrase,
        admin_user=admin_user,
    )

    overwrite_file(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        path="/docs/readme.txt",
        content=f"{replacement_phrase}\n".encode("utf-8"),
    )
    delete_file(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        path="/docs/delete-me.txt",
    )
    move_file(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        source_path="/docs/move-me.txt",
        destination_dir="/private",
    )
    move_file(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        source_path="/private/scope-change.txt",
        destination_dir="/docs",
    )

    before = datetime.now(timezone.utc)
    CCPairManager.run_once(
        cc_pair=cc_pair,
        from_beginning=True,
        user_performing_action=admin_user,
    )
    finished_attempt = _run_once_and_wait_for_completion(cc_pair.id, admin_user)
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )
    assert finished_attempt.status is not None
    assert finished_attempt.status.is_successful()

    prune_started_at = datetime.now(timezone.utc)
    CCPairManager.prune(cc_pair, user_performing_action=admin_user)
    CCPairManager.wait_for_prune(
        cc_pair=cc_pair,
        after=prune_started_at,
        user_performing_action=admin_user,
    )

    _wait_for_search_result(
        query=replacement_phrase,
        expected_content=replacement_phrase,
        admin_user=admin_user,
    )
    _wait_for_search_result(
        query=moved_in_phrase,
        expected_content=moved_in_phrase,
        admin_user=admin_user,
    )
    _wait_for_search_absence(
        query=delete_phrase,
        unexpected_content=delete_phrase,
        admin_user=admin_user,
    )
    _wait_for_search_absence(
        query=moved_out_phrase,
        unexpected_content=moved_out_phrase,
        admin_user=admin_user,
    )
