"""Connector edits through plan -> confirm -> apply against a full deployment:
a widened file connector scope backfills only the new file, a narrowed one
prunes, a behavior change re-indexes from the beginning, an edit of a paused
pair waits for resume, access switches change search visibility per user, and
the endpoints reject callers who may not edit the pair or apply the plan."""

import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.edit_plan.models import (
    EditNoteKind,
    EditStepKind,
    EditStepReason,
)
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.server.documents.connector_edit_models import ConnectorEditProposal
from onyx.server.documents.models import FileUploadResponse
from tests.integration.common_utils.constants import API_SERVER_URL, MAX_DELAY
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector_edit import (
    ConnectorEditManager,
)
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import (
    DATestCCPair,
    DATestLLMProvider,
    DATestUser,
)

_FORBIDDEN = 403
_NOT_FOUND = 404
_BAD_REQUEST = 400
_CONFLICT = 409
_POLL_SECONDS = 3
_IS_EE = os.environ.get("RUN_EE_TESTS", "").lower() == "true"


def _wait_until(condition: Callable[[], bool], what: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out waiting for {what}")
        time.sleep(_POLL_SECONDS)


@pytest.fixture(autouse=True)
def _default_llm(llm_provider: DATestLLMProvider) -> None:  # noqa: ARG001
    """The search endpoint these tests read through needs a default LLM."""


def _can_find(text: str, user: DATestUser) -> bool:
    response = client.post(
        f"{API_SERVER_URL}/search",
        json={"query": text, "skip_query_expansion": True},
        headers=user.headers,
    )
    response.raise_for_status()
    return any(text in result["content"] for result in response.json()["results"])


def _unique_text(label: str) -> str:
    return f"{label} {uuid4().hex} connector edit marker"


def _upload(admin: DATestUser, files: dict[str, str]) -> FileUploadResponse:
    response = FileManager.upload_connector_files(
        [(name, text.encode()) for name, text in files.items()],
        admin,
        content_type="text/plain",
    )
    response.raise_for_status()
    return FileUploadResponse.model_validate(response.json())


def _indexed_file_pair(
    admin: DATestUser, files: dict[str, str]
) -> tuple[DATestCCPair, FileUploadResponse]:
    uploaded = _upload(admin, files)
    before = datetime.now(timezone.utc)
    cc_pair = CCPairManager.create_from_scratch(
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": uploaded.file_paths,
            "file_names": uploaded.file_names,
            "zip_metadata_file_id": None,
        },
        user_performing_action=admin,
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair, before, user_performing_action=admin
    )
    return cc_pair, uploaded


def _with_files(
    cc_pair: DATestCCPair,
    admin: DATestUser,
    file_paths: list[str],
    file_names: list[str],
) -> ConnectorEditProposal:
    proposal = ConnectorEditManager.current_proposal(cc_pair.id, admin)
    proposal.connector_specific_config = proposal.connector_specific_config | {
        "file_locations": file_paths,
        "file_names": file_names,
    }
    return proposal


def _backfill_count(cc_pair: DATestCCPair, admin: DATestUser) -> int:
    attempts = IndexAttemptManager.get_index_attempt_page(
        cc_pair.id, user_performing_action=admin, page_size=50
    ).items
    return sum(1 for attempt in attempts if attempt.is_backfill)


def test_file_scope_widening_backfills_and_narrowing_prunes(
    admin_user: DATestUser,
) -> None:
    text_a = _unique_text("alpha")
    text_c = _unique_text("charlie")
    cc_pair, uploaded = _indexed_file_pair(admin_user, {"a.txt": text_a})
    _wait_until(lambda: _can_find(text_a, admin_user), "a.txt indexed", MAX_DELAY)

    staged = ConnectorEditManager.stage_files(
        cc_pair.id, [("c.txt", text_c.encode())], admin_user
    )
    widened = _with_files(
        cc_pair,
        admin_user,
        [*uploaded.file_paths, *staged.file_paths],
        ["a.txt", "c.txt"],
    )
    plan = ConnectorEditManager.plan(cc_pair.id, widened, admin_user)
    assert [step.kind for step in plan.plan.steps] == [EditStepKind.SCOPED_BACKFILL]
    assert plan.plan.indexed_document_count == 1

    applied = ConnectorEditManager.apply(cc_pair.id, plan.plan_id, admin_user)
    assert [step.kind for step in applied.steps] == [EditStepKind.SCOPED_BACKFILL]
    _wait_until(lambda: _can_find(text_c, admin_user), "c.txt backfilled", MAX_DELAY)
    assert _backfill_count(cc_pair, admin_user) == 1

    # A plan is single use.
    response = ConnectorEditManager.apply_response(cc_pair.id, plan.plan_id, admin_user)
    assert response.status_code == _NOT_FOUND

    narrowed = _with_files(cc_pair, admin_user, staged.file_paths, ["c.txt"])
    plan = ConnectorEditManager.plan(cc_pair.id, narrowed, admin_user)
    assert [step.kind for step in plan.plan.steps] == [EditStepKind.PRUNE]
    ConnectorEditManager.apply(cc_pair.id, plan.plan_id, admin_user)

    _wait_until(lambda: not _can_find(text_a, admin_user), "a.txt pruned", MAX_DELAY)
    assert _can_find(text_c, admin_user)


def test_edit_of_a_paused_pair_waits_for_resume(admin_user: DATestUser) -> None:
    text_a = _unique_text("alpha")
    text_c = _unique_text("charlie")
    cc_pair, uploaded = _indexed_file_pair(admin_user, {"a.txt": text_a})
    CCPairManager.pause_cc_pair(cc_pair, admin_user)

    staged = ConnectorEditManager.stage_files(
        cc_pair.id, [("c.txt", text_c.encode())], admin_user
    )
    plan = ConnectorEditManager.plan(
        cc_pair.id,
        _with_files(
            cc_pair,
            admin_user,
            [*uploaded.file_paths, *staged.file_paths],
            ["a.txt", "c.txt"],
        ),
        admin_user,
    )
    assert EditNoteKind.PAUSED in [note.kind for note in plan.plan.notes]
    # That the paused pair starts no backfill is covered by
    # test_pending_backfills.py.
    ConnectorEditManager.apply(cc_pair.id, plan.plan_id, admin_user)

    CCPairManager.unpause_cc_pair(cc_pair, admin_user)
    _wait_until(lambda: _can_find(text_c, admin_user), "c.txt backfilled", MAX_DELAY)
    assert _backfill_count(cc_pair, admin_user) == 1


def test_behavior_change_reindexes_from_the_beginning(admin_user: DATestUser) -> None:
    # Nothing serves this URL: the runs fail, but each attempt records whether
    # it ran from the beginning.
    cc_pair = CCPairManager.create_from_scratch(
        source=DocumentSource.WEB,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "base_url": "http://localhost:9/",
            "web_connector_type": "single",
            "mintlify_cleanup": True,
        },
        user_performing_action=admin_user,
    )
    first = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id, user_performing_action=admin_user
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=first.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    proposal = ConnectorEditManager.current_proposal(cc_pair.id, admin_user)
    proposal.connector_specific_config = proposal.connector_specific_config | {
        "mintlify_cleanup": False
    }
    plan = ConnectorEditManager.plan(cc_pair.id, proposal, admin_user)
    [step] = plan.plan.steps
    assert step.kind == EditStepKind.FULL_REINDEX
    assert step.reasons == [EditStepReason.BEHAVIOR_CHANGED]
    ConnectorEditManager.apply(cc_pair.id, plan.plan_id, admin_user)

    def _reindex_created() -> bool:
        attempts = IndexAttemptManager.get_index_attempt_page(
            cc_pair.id, user_performing_action=admin_user, page_size=50
        ).items
        return any(
            attempt.id != first.id and attempt.from_beginning for attempt in attempts
        )

    _wait_until(_reindex_created, "a full re-index attempt", MAX_DELAY)


@pytest.mark.skipif(not _IS_EE, reason="Data-access groups are enterprise only")
def test_access_switches_change_search_visibility(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    outsider = UserManager.create(name=f"edit_outsider_{uuid4().hex[:6]}")
    group = UserGroupManager.create(
        user_performing_action=admin_user, user_ids=[basic_user.id]
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user, user_groups_to_check=[group]
    )
    text = _unique_text("visibility")
    cc_pair, _ = _indexed_file_pair(admin_user, {"v.txt": text})
    _wait_until(
        lambda: _can_find(text, basic_user) and _can_find(text, outsider),
        "the public document",
        MAX_DELAY,
    )

    # PUBLIC -> PRIVATE: only the data-access group can read it.
    private = ConnectorEditManager.current_proposal(cc_pair.id, admin_user)
    private.access_type = AccessType.PRIVATE
    private.data_access_group_ids = [group.id]
    plan = ConnectorEditManager.plan(cc_pair.id, private, admin_user)
    assert [step.kind for step in plan.plan.steps] == [EditStepKind.ACCESS_TYPE]
    ConnectorEditManager.apply(cc_pair.id, plan.plan_id, admin_user)
    _wait_until(lambda: not _can_find(text, outsider), "the outsider loses it", 180)
    assert _can_find(text, basic_user)

    # PRIVATE -> PUBLIC: everyone reads it again.
    public = ConnectorEditManager.current_proposal(cc_pair.id, admin_user)
    public.access_type = AccessType.PUBLIC
    public.data_access_group_ids = []
    ConnectorEditManager.plan_and_apply(cc_pair.id, public, admin_user)
    _wait_until(lambda: _can_find(text, outsider), "the outsider reads it", 180)


def test_edit_rejections(admin_user: DATestUser, basic_user: DATestUser) -> None:
    cc_pair, _ = _indexed_file_pair(admin_user, {"r.txt": _unique_text("reject")})
    proposal = ConnectorEditManager.current_proposal(cc_pair.id, admin_user)
    proposal.name = f"renamed-{uuid4().hex[:6]}"

    # Not an Editor of the pair.
    response = ConnectorEditManager.plan_response(cc_pair.id, proposal, basic_user)
    assert response.status_code == _FORBIDDEN

    # Unknown plan.
    response = ConnectorEditManager.apply_response(cc_pair.id, uuid4(), admin_user)
    assert response.status_code == _NOT_FOUND

    # A credential of another source.
    slack_credential = CredentialManager.create(
        user_performing_action=admin_user,
        credential_json={"slack_bot_token": "xoxb-not-a-real-token"},
        source=DocumentSource.SLACK,
    )
    wrong_source = proposal.model_copy(update={"credential_id": slack_credential.id})
    response = ConnectorEditManager.plan_response(cc_pair.id, wrong_source, admin_user)
    assert response.status_code == _BAD_REQUEST

    # A plan goes stale when the pair changes before apply.
    stale = ConnectorEditManager.plan(cc_pair.id, proposal, admin_user)
    other = proposal.model_copy(update={"indexing_start": datetime(2020, 1, 1)})
    ConnectorEditManager.plan_and_apply(cc_pair.id, other, admin_user)
    response = ConnectorEditManager.apply_response(
        cc_pair.id, stale.plan_id, admin_user
    )
    assert response.status_code == _CONFLICT
    assert response.json()["error_code"] == "EDIT_PLAN_STALE"


@pytest.mark.skipif(not _IS_EE, reason="A second admin needs the Admin group")
def test_plan_is_private_to_its_user(admin_user: DATestUser) -> None:
    other_admin = UserManager.promote_to_admin(
        UserManager.create(name=f"edit_admin_{uuid4().hex[:6]}"), admin_user
    )
    cc_pair, _ = _indexed_file_pair(admin_user, {"p.txt": _unique_text("private")})
    proposal = ConnectorEditManager.current_proposal(cc_pair.id, admin_user)
    proposal.name = f"renamed-{uuid4().hex[:6]}"
    plan = ConnectorEditManager.plan(cc_pair.id, proposal, admin_user)

    response = ConnectorEditManager.get_plan_response(
        cc_pair.id, plan.plan_id, other_admin
    )
    assert response.status_code == _NOT_FOUND
    response = ConnectorEditManager.apply_response(
        cc_pair.id, plan.plan_id, other_admin
    )
    assert response.status_code == _NOT_FOUND

    response = ConnectorEditManager.get_plan_response(
        cc_pair.id, plan.plan_id, admin_user
    )
    assert response.status_code == 200
    ConnectorEditManager.apply(cc_pair.id, plan.plan_id, admin_user)
