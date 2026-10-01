"""Draft capability-check runs: immediate states, the run task, the result
cache, superseding, and access."""

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.capability_checks.tasks import (
    run_draft_capability_checks_task,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import runner
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckRunSnapshot,
    DraftCheckStateKind,
    DraftRerunMode,
    DraftRunStatus,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.db.enums import AccessType
from onyx.db.models import Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import capability_check_runs
from onyx.server.documents.credential_capabilities import (
    DraftCheckRunRequest,
    get_draft_check_run,
    start_draft_check_run,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_TOKEN = "fake_token"
_CHANNELS = "fake_channels"
_PERM_SYNC = "fake_perm_sync"


class _FakeCheck(CapabilityCheck[SlackConnectorConfig]):
    config_class = SlackConnectorConfig

    def __init__(
        self,
        check_id: str,
        runs: list[str],
        *,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        requires_fields: frozenset[str] = frozenset(),
        on_run: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=check_id,
            requires_connector_instance=False,
            requires_fields=requires_fields,
        )
        self._runs = runs
        self._on_run = on_run

    def run(self, context: CapabilityCheckContext) -> None:  # noqa: ARG002
        self._runs.append(self.check_id)
        if self._on_run is not None:
            self._on_run()


class _Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.runs: list[str] = []
        self.on_token_run: Callable[[], object] | None = None
        self.send_task = MagicMock()
        monkeypatch.setattr(
            capability_check_runs.client_app, "send_task", self.send_task
        )
        monkeypatch.setattr(capability_check_runs, "get_capability_checks", self.checks)
        monkeypatch.setattr(runner, "get_capability_checks", self.checks)

    def checks(self, source: DocumentSource) -> list[CapabilityCheck[Any]]:
        assert source == DocumentSource.SLACK
        return [
            _FakeCheck(_TOKEN, self.runs, on_run=lambda: self._token_hook()),
            _FakeCheck(_CHANNELS, self.runs, requires_fields=frozenset({"channels"})),
            _FakeCheck(
                _PERM_SYNC,
                self.runs,
                capability=CredentialCapability.DOC_PERMISSION_SYNC,
            ),
        ]

    def _token_hook(self) -> None:
        if self.on_token_run is not None:
            self.on_token_run()

    def run_last_task(self) -> None:
        run_draft_capability_checks_task(**self.send_task.call_args.kwargs["kwargs"])


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    return _Harness(monkeypatch)


@pytest.fixture
def users(db_session: Session) -> Generator[tuple[User, User], None, None]:
    admin = create_test_user(db_session, "draft_admin", is_admin=True)
    other = create_test_user(db_session, "draft_other", is_admin=True)
    yield admin, other
    delete_test_user(db_session, admin, other)
    db_session.commit()


def _credential(
    db_session: Session, source: DocumentSource
) -> Generator[Credential, None, None]:
    credential = Credential(source=source, credential_json={}, admin_public=True)
    db_session.add(credential)
    db_session.commit()
    yield credential
    db_session.delete(credential)
    db_session.commit()


@pytest.fixture
def slack_credential(db_session: Session) -> Generator[Credential, None, None]:
    yield from _credential(db_session, DocumentSource.SLACK)


@pytest.fixture
def web_credential(db_session: Session) -> Generator[Credential, None, None]:
    yield from _credential(db_session, DocumentSource.WEB)


def _start(
    db_session: Session,
    user: User,
    credential: Credential,
    form_state: dict[str, Any],
    draft_key: str,
    source: DocumentSource = DocumentSource.SLACK,
    rerun: DraftRerunMode = DraftRerunMode.NONE,
) -> DraftCheckRunSnapshot:
    return start_draft_check_run(
        DraftCheckRunRequest(
            source=source,
            credential_id=credential.id,
            access_type=AccessType.PUBLIC,
            draft_key=draft_key,
            form_state=form_state,
            rerun=rerun,
        ),
        user=user,
        db_session=db_session,
    )


def _states(snapshot: DraftCheckRunSnapshot) -> dict[str, DraftCheckStateKind]:
    return {check.check_id: check.state for check in snapshot.checks}


@pytest.mark.usefixtures("tenant_context")
def test_run_resolves_states_runs_pending_checks_and_reuses_cached_results(
    db_session: Session,
    harness: _Harness,
    users: tuple[User, User],
    slack_credential: Credential,
) -> None:
    admin, _ = users
    draft_key = uuid4().hex

    started = _start(db_session, admin, slack_credential, {}, draft_key)

    assert started.status == DraftRunStatus.RUNNING
    assert _states(started) == {
        _TOKEN: DraftCheckStateKind.PENDING,
        _CHANNELS: DraftCheckStateKind.WAITING,
        _PERM_SYNC: DraftCheckStateKind.NOT_APPLICABLE,
    }
    harness.send_task.assert_called_once()
    harness.run_last_task()
    done = get_draft_check_run(started.run_id, user=admin)
    assert done.status == DraftRunStatus.COMPLETED
    assert _states(done)[_TOKEN] == DraftCheckStateKind.PASSED
    assert harness.runs == [_TOKEN]

    edited = _start(db_session, admin, slack_credential, {"channels": ["a"]}, draft_key)
    harness.run_last_task()

    done = get_draft_check_run(edited.run_id, user=admin)
    from_cache = {check.check_id: check.from_cache for check in done.checks}
    assert from_cache[_TOKEN] is True
    assert from_cache[_CHANNELS] is False
    assert _states(done)[_CHANNELS] == DraftCheckStateKind.PASSED
    assert harness.runs == [_TOKEN, _CHANNELS]


@pytest.mark.usefixtures("tenant_context")
def test_rerun_failed_runs_a_cached_failure_again(
    db_session: Session,
    harness: _Harness,
    users: tuple[User, User],
    slack_credential: Credential,
) -> None:
    admin, _ = users
    draft_key = uuid4().hex

    def fail() -> None:
        raise ConnectorValidationError("missing scope")

    harness.on_token_run = fail
    first = _start(db_session, admin, slack_credential, {}, draft_key)
    harness.run_last_task()
    assert (
        _states(get_draft_check_run(first.run_id, user=admin))[_TOKEN]
        == DraftCheckStateKind.FAILED
    )

    harness.on_token_run = None
    cached = _start(db_session, admin, slack_credential, {}, draft_key)
    assert cached.status == DraftRunStatus.COMPLETED
    assert _states(cached)[_TOKEN] == DraftCheckStateKind.FAILED
    assert harness.runs == [_TOKEN]

    rerun = _start(
        db_session,
        admin,
        slack_credential,
        {},
        draft_key,
        rerun=DraftRerunMode.FAILED,
    )
    assert _states(rerun)[_TOKEN] == DraftCheckStateKind.PENDING
    harness.run_last_task()
    assert (
        _states(get_draft_check_run(rerun.run_id, user=admin))[_TOKEN]
        == DraftCheckStateKind.PASSED
    )
    assert harness.runs == [_TOKEN, _TOKEN]


@pytest.mark.usefixtures("tenant_context")
def test_rerun_all_runs_a_cached_pass_again(
    db_session: Session,
    harness: _Harness,
    users: tuple[User, User],
    slack_credential: Credential,
) -> None:
    admin, _ = users
    draft_key = uuid4().hex

    first = _start(db_session, admin, slack_credential, {}, draft_key)
    harness.run_last_task()
    assert (
        _states(get_draft_check_run(first.run_id, user=admin))[_TOKEN]
        == DraftCheckStateKind.PASSED
    )

    only_failed = _start(
        db_session,
        admin,
        slack_credential,
        {},
        draft_key,
        rerun=DraftRerunMode.FAILED,
    )
    assert only_failed.status == DraftRunStatus.COMPLETED
    assert harness.runs == [_TOKEN]

    rerun = _start(
        db_session, admin, slack_credential, {}, draft_key, rerun=DraftRerunMode.ALL
    )
    assert _states(rerun)[_TOKEN] == DraftCheckStateKind.PENDING
    harness.run_last_task()
    done = get_draft_check_run(rerun.run_id, user=admin)
    assert _states(done)[_TOKEN] == DraftCheckStateKind.PASSED
    assert {check.check_id: check.from_cache for check in done.checks}[_TOKEN] is False
    assert harness.runs == [_TOKEN, _TOKEN]

    # The fresh result went to the cache.
    cached = _start(db_session, admin, slack_credential, {}, draft_key)
    assert cached.status == DraftRunStatus.COMPLETED
    assert harness.runs == [_TOKEN, _TOKEN]


@pytest.mark.usefixtures("tenant_context")
def test_newer_run_supersedes_the_older_one_mid_run(
    db_session: Session,
    harness: _Harness,
    users: tuple[User, User],
    slack_credential: Credential,
) -> None:
    admin, _ = users
    draft_key = uuid4().hex
    form = {"channels": ["a"]}
    first = _start(db_session, admin, slack_credential, form, draft_key)
    first_task_kwargs = harness.send_task.call_args.kwargs["kwargs"]
    harness.on_token_run = lambda: _start(
        db_session, admin, slack_credential, {"channels": ["b"]}, draft_key
    )

    run_draft_capability_checks_task(**first_task_kwargs)

    snapshot = get_draft_check_run(first.run_id, user=admin)
    assert snapshot.status == DraftRunStatus.SUPERSEDED
    # The task stopped before the check after the supersede.
    assert harness.runs == [_TOKEN]
    assert _states(snapshot)[_CHANNELS] == DraftCheckStateKind.PENDING


@pytest.mark.usefixtures("tenant_context")
def test_only_the_starting_user_reads_the_run(
    db_session: Session,
    harness: _Harness,
    users: tuple[User, User],
    slack_credential: Credential,
) -> None:
    admin, other = users
    started = _start(db_session, admin, slack_credential, {}, uuid4().hex)

    with pytest.raises(OnyxError) as error:
        get_draft_check_run(started.run_id, user=other)

    assert error.value.error_code == OnyxErrorCode.NOT_FOUND
    harness.send_task.assert_called_once()


@pytest.mark.usefixtures("tenant_context", "harness")
def test_credential_of_another_source_is_rejected(
    db_session: Session,
    users: tuple[User, User],
    web_credential: Credential,
) -> None:
    admin, _ = users

    with pytest.raises(OnyxError) as error:
        _start(db_session, admin, web_credential, {}, uuid4().hex)

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
