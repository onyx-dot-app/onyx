"""Per-check actions of draft runs: Run Check and Re-run Check
(``check_ids``), Skip (``skip_check_ids``) and Start Now
(``start_check_id``). Covers the request rules, the stopped and skipped
states, the results a run keeps, the run order, the verdict, and creation's
reuse of the admin's skips."""

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.background.celery.tasks.capability_checks import (
    tasks as capability_check_tasks,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import creation, draft_runs, runner
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckActions,
    DraftCheckRunSnapshot,
    DraftCheckState,
    DraftCheckStateKind,
    DraftRerunMode,
    DraftRunStatus,
    get_cached_draft_result,
    load_draft_run,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CheckNotRunReason,
    CheckOutput,
    CredentialCapability,
    aggregate_capability_verdict,
)
from onyx.connectors.capability_checks.runner import run_order
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.db.enums import AccessType
from onyx.db.models import Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import capability_check_runs
from onyx.server.documents.capability_check_runs import (
    start_draft_capability_check_run,
)
from tests.unit.fakes import FakeCache

_SIGN_IN = "sign_in"
_LIST = "list_items"
_READ = "read_items"
_EXTRA = "read_extra"
_FIND = "find_options"
_DRAFT_KEY = "form-1"


class _Check(CapabilityCheck):
    def __init__(
        self,
        check_id: str,
        runs: list[str],
        *,
        required: bool = True,
        depends_on: tuple[str, ...] = (),
        discovery: bool = False,
        error: Exception | None = None,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=f"Run {check_id}",
            required=required,
            requires_connector_instance=False,
            depends_on=depends_on,
            discovery=discovery,
        )
        self._runs = runs
        self.error = error

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:  # noqa: ARG002
        self._runs.append(self.check_id)
        if self.error is not None:
            raise self.error
        return None


class _Harness:
    """A draft run of a Slack form with fake checks, on a fake cache, with
    the run task called in process."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.runs: list[str] = []
        self.checks: list[CapabilityCheck[Any]] = [
            _Check(_SIGN_IN, self.runs),
            _Check(_LIST, self.runs, depends_on=(_SIGN_IN,)),
            _Check(_READ, self.runs, depends_on=(_LIST,)),
            _Check(_EXTRA, self.runs, required=False, depends_on=(_SIGN_IN,)),
            _Check(_FIND, self.runs, discovery=True),
        ]
        self.cache = FakeCache()
        self.send_task = MagicMock()
        self.user = MagicMock(spec=User)
        self.user.id = uuid4()
        self.credential = Credential(
            id=7,
            source=DocumentSource.SLACK,
            credential_json=None,
            time_updated=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        monkeypatch.setattr(draft_runs, "get_cache_backend", lambda: self.cache)
        monkeypatch.setattr(
            capability_check_runs.client_app, "send_task", self.send_task
        )
        monkeypatch.setattr(
            capability_check_runs, "assert_user_can_use_credential", MagicMock()
        )
        for module in (capability_check_runs, runner, capability_check_tasks):
            monkeypatch.setattr(
                module, "get_capability_checks", lambda _source: self.checks
            )
        monkeypatch.setattr(creation, "get_capability_checks", lambda _: self.checks)
        monkeypatch.setattr(runner, "get_source_operations_class", lambda _: None)
        monkeypatch.setattr(
            capability_check_tasks,
            "get_session_with_current_tenant",
            lambda: nullcontext(MagicMock()),
        )
        monkeypatch.setattr(
            capability_check_tasks,
            "fetch_credential_by_id",
            lambda _id, _session: self.credential,
        )

    def check(self, check_id: str) -> _Check:
        found = next(check for check in self.checks if check.check_id == check_id)
        assert isinstance(found, _Check)
        return found

    def start(
        self,
        actions: DraftCheckActions | None = None,
        rerun: DraftRerunMode = DraftRerunMode.NONE,
    ) -> DraftCheckRunSnapshot:
        self.send_task.reset_mock()
        return start_draft_capability_check_run(
            MagicMock(),
            user=self.user,
            credential=self.credential,
            source=DocumentSource.SLACK,
            config_class=SlackConnectorConfig,
            access_type=AccessType.PUBLIC,
            draft_key=_DRAFT_KEY,
            form_values={},
            rerun=rerun,
            actions=actions,
        )

    def run(
        self,
        actions: DraftCheckActions | None = None,
        rerun: DraftRerunMode = DraftRerunMode.NONE,
    ) -> DraftCheckRunSnapshot:
        """Starts a run, runs its task, and returns the finished snapshot."""
        self.runs.clear()
        snapshot = self.start(actions, rerun)
        if self.send_task.called:
            capability_check_tasks.run_draft_capability_checks_task(
                **self.send_task.call_args.kwargs["kwargs"]
            )
        run = load_draft_run(snapshot.run_id)
        assert run is not None
        return run.snapshot


def _state(snapshot: DraftCheckRunSnapshot, check_id: str) -> DraftCheckState:
    return next(check for check in snapshot.checks if check.check_id == check_id)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    return _Harness(monkeypatch)


def test_plain_run_runs_every_check_in_run_order(harness: _Harness) -> None:
    snapshot = harness.run()

    assert snapshot.status == DraftRunStatus.COMPLETED
    assert harness.runs == [_SIGN_IN, _LIST, _READ, _EXTRA, _FIND]
    assert {check.state for check in snapshot.checks} == {DraftCheckStateKind.PASSED}


def test_skipped_required_check_is_stopped_and_its_dependents_do_not_run(
    harness: _Harness,
) -> None:
    snapshot = harness.run(DraftCheckActions(skip_check_ids=[_LIST]))

    stopped = _state(snapshot, _LIST)
    assert stopped.state == DraftCheckStateKind.STOPPED
    assert stopped.not_run_reason == CheckNotRunReason.STOPPED_BY_USER
    assert stopped.summary == "Not run: stopped by user"
    dependent = _state(snapshot, _READ)
    assert dependent.state == DraftCheckStateKind.SKIPPED
    assert dependent.not_run_reason == CheckNotRunReason.DEPENDENCY_SKIPPED
    assert dependent.blocked_by == _LIST
    assert dependent.summary == f"Not run: Run {_LIST} stopped"
    assert harness.runs == [_SIGN_IN, _EXTRA, _FIND]
    # A stopped required check is never cached, so creation runs it.
    run = load_draft_run(snapshot.run_id)
    assert run is not None
    assert get_cached_draft_result(run.result_cache_keys[_LIST]) is None


def test_skipped_optional_check_is_skipped_by_user_and_cached(
    harness: _Harness,
) -> None:
    snapshot = harness.run(DraftCheckActions(skip_check_ids=[_EXTRA]))

    skipped = _state(snapshot, _EXTRA)
    assert skipped.state == DraftCheckStateKind.SKIPPED
    assert skipped.not_run_reason == CheckNotRunReason.SKIPPED_BY_USER
    assert skipped.summary == "Skipped by you"
    assert _EXTRA not in harness.runs
    run = load_draft_run(snapshot.run_id)
    assert run is not None
    cached = get_cached_draft_result(run.result_cache_keys[_EXTRA])
    assert cached is not None and cached.skipped_by_user


def test_a_cached_skip_holds_only_while_the_request_skips_the_check(
    harness: _Harness,
) -> None:
    harness.run(DraftCheckActions(skip_check_ids=[_EXTRA]))

    snapshot = harness.run()

    assert _EXTRA in harness.runs
    assert _state(snapshot, _EXTRA).state == DraftCheckStateKind.PASSED


def test_check_ids_reruns_only_the_chosen_checks(harness: _Harness) -> None:
    harness.check(_EXTRA).error = UnexpectedValidationError("flaky")
    first = harness.run()
    assert _state(first, _EXTRA).state == DraftCheckStateKind.INCOMPLETE

    harness.check(_EXTRA).error = None
    snapshot = harness.run(DraftCheckActions(check_ids=[_SIGN_IN]))

    # Re-run ignores the cached pass of the chosen check.
    assert harness.runs == [_SIGN_IN]
    assert _state(snapshot, _SIGN_IN).from_cache is False
    # A result the cache does not hold is kept from the latest run.
    kept = _state(snapshot, _EXTRA)
    assert kept.state == DraftCheckStateKind.INCOMPLETE
    assert kept.from_cache is True
    assert _state(snapshot, _READ).state == DraftCheckStateKind.PASSED


def test_run_check_on_a_stopped_check_runs_it_and_its_dependents(
    harness: _Harness,
) -> None:
    harness.run(DraftCheckActions(skip_check_ids=[_LIST]))

    snapshot = harness.run(DraftCheckActions(check_ids=[_LIST]))

    # The dependent's "Not run" was no result of its own, so it runs too.
    assert harness.runs == [_LIST, _READ]
    assert _state(snapshot, _LIST).state == DraftCheckStateKind.PASSED
    assert _state(snapshot, _READ).state == DraftCheckStateKind.PASSED


def test_start_now_runs_the_check_and_what_it_needs_first(
    harness: _Harness,
) -> None:
    snapshot = harness.run(DraftCheckActions(start_check_id=_EXTRA))

    assert harness.runs == [_SIGN_IN, _EXTRA, _LIST, _READ, _FIND]
    assert snapshot.status == DraftRunStatus.COMPLETED


def test_start_now_on_a_check_after_a_skip_does_not_run_it(
    harness: _Harness,
) -> None:
    snapshot = harness.run(
        DraftCheckActions(skip_check_ids=[_LIST], start_check_id=_READ)
    )

    assert harness.runs == [_SIGN_IN, _EXTRA, _FIND]
    assert _state(snapshot, _READ).blocked_by == _LIST


@pytest.mark.parametrize(
    "actions,rerun",
    [
        (DraftCheckActions(check_ids=["nope"]), DraftRerunMode.NONE),
        (DraftCheckActions(skip_check_ids=["nope"]), DraftRerunMode.NONE),
        (DraftCheckActions(start_check_id="nope"), DraftRerunMode.NONE),
        (DraftCheckActions(check_ids=[]), DraftRerunMode.NONE),
        (
            DraftCheckActions(check_ids=[_LIST], skip_check_ids=[_LIST]),
            DraftRerunMode.NONE,
        ),
        (
            DraftCheckActions(skip_check_ids=[_LIST], start_check_id=_LIST),
            DraftRerunMode.NONE,
        ),
        (DraftCheckActions(check_ids=[_LIST]), DraftRerunMode.FAILED),
    ],
)
def test_invalid_actions_are_rejected_before_anything_starts(
    harness: _Harness, actions: DraftCheckActions, rerun: DraftRerunMode
) -> None:
    with pytest.raises(OnyxError) as raised:
        harness.start(actions, rerun)

    assert raised.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert raised.value.status_code == 400
    assert not harness.send_task.called
    assert harness.cache.store == {}


def test_run_order_start_now_keeps_discovery_after_validation() -> None:
    runs: list[str] = []
    checks: list[CapabilityCheck] = [
        _Check(_SIGN_IN, runs),
        _Check(_LIST, runs),
        _Check(_FIND, runs, discovery=True, depends_on=(_SIGN_IN,)),
    ]

    ordered = [check.check_id for check in run_order(checks, _FIND)]

    assert ordered == [_SIGN_IN, _LIST, _FIND]


def _result(
    status: CapabilityCheckStatus,
    *,
    required: bool,
    reason: CheckNotRunReason | None = None,
) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id=str(uuid4()),
        display_name="Check",
        required=required,
        status=status,
        not_run_reason=reason,
    )


def test_a_stopped_required_check_is_no_pass() -> None:
    verdict = aggregate_capability_verdict(
        True,
        [
            _result(CapabilityCheckStatus.PASSED, required=True),
            _result(
                CapabilityCheckStatus.STOPPED,
                required=True,
                reason=CheckNotRunReason.STOPPED_BY_USER,
            ),
        ],
    )

    assert verdict == CapabilityVerdict.SKIPPED


def test_a_skipped_optional_check_does_not_downgrade_the_verdict() -> None:
    verdict = aggregate_capability_verdict(
        True,
        [
            _result(CapabilityCheckStatus.PASSED, required=True),
            _result(
                CapabilityCheckStatus.SKIPPED,
                required=False,
                reason=CheckNotRunReason.SKIPPED_BY_USER,
            ),
        ],
    )

    assert verdict == CapabilityVerdict.PASSED


def test_creation_reuses_an_optional_skip_and_runs_a_required_one(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = harness.run(DraftCheckActions(skip_check_ids=[_EXTRA, _LIST]))
    run = load_draft_run(snapshot.run_id)
    assert run is not None
    # A skip cached before the check became required must not let it pass.
    draft_runs.cache_user_skip(
        run.result_cache_keys[_READ],
        _state(snapshot, _EXTRA).model_copy(update={"check_id": _READ}),
    )
    ran: list[str] = []

    def run_within_budget(
        check_ids: list[str], **_kwargs: Any
    ) -> tuple[list[CapabilityCheckResult], frozenset[str]]:
        ran.extend(check_ids)
        return [
            _result(CapabilityCheckStatus.PASSED, required=True).model_copy(
                update={"check_id": check_id}
            )
            for check_id in check_ids
        ], frozenset()

    monkeypatch.setattr(creation, "_run_checks_within_budget", run_within_budget)

    named_run = creation.run_named_checks_within_budget(
        connector_id=None,
        cc_pair_id=None,
        source=DocumentSource.SLACK,
        input_type=None,
        connector_specific_config={},
        credential=harness.credential,
        access_type=AccessType.PUBLIC,
    )

    assert _EXTRA not in ran
    assert _LIST in ran and _READ in ran
    extra = next(r for r in named_run.finished_results if r.check_id == _EXTRA)
    assert extra.status == CapabilityCheckStatus.SKIPPED
    assert extra.not_run_reason == CheckNotRunReason.SKIPPED_BY_USER
    assert not named_run.failed_required_results


def test_a_chain_after_a_skipped_check_names_the_skipped_check() -> None:
    runs: list[str] = []
    checks: list[CapabilityCheck] = [
        _Check(_READ, runs, depends_on=(_LIST,)),
        _Check(_EXTRA, runs, depends_on=(_READ,)),
    ]
    skipped = _result(
        CapabilityCheckStatus.SKIPPED,
        required=False,
        reason=CheckNotRunReason.SKIPPED_BY_USER,
    ).model_copy(update={"check_id": _LIST, "display_name": "List items"})

    results = runner.run_capability_checks(
        checks,
        CapabilityCheckContext(source=DocumentSource.SLACK, credential_json={}),
        prior_results=[skipped],
    )

    assert runs == []
    assert [result.summary for result in results] == [
        "Not run: List items skipped",
        "Not run: List items skipped",
    ]
    assert {result.blocked_by for result in results} == {_LIST}
    assert {result.not_run_reason for result in results} == {
        CheckNotRunReason.DEPENDENCY_SKIPPED
    }
