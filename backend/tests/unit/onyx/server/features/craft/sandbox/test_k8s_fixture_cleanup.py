"""Keep fixture cleanup within owned and confirmed-deleted sandboxes."""

from collections.abc import Callable, Generator
from unittest.mock import MagicMock, call, patch
from uuid import UUID, uuid4

import pytest
from _pytest.fixtures import FixtureFunctionDefinition
from kubernetes.client import CoreV1Api

from onyx.db.models import Sandbox
from onyx.server.features.build.sandbox.manager import SandboxManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s import conftest as k8s_conftest
from tests.integration.tests.craft.k8s import k8s_fixtures
from tests.integration.tests.craft.k8s import test_messages_api_k8s as message_tests


@pytest.fixture(autouse=True)
def owned_sandbox_lookup() -> Generator[MagicMock, None, None]:
    with (
        patch.object(k8s_fixtures, "get_session_with_current_tenant"),
        patch.object(
            k8s_fixtures, "get_sandbox_by_user_id", return_value=None
        ) as lookup,
    ):
        yield lookup


@pytest.fixture
def fixture_user() -> DATestUser:
    return DATestUser(
        id=str(uuid4()),
        email="fixture-cleanup@example.com",
        password="test-password",
        headers={},
        is_admin=False,
        is_active=True,
    )


def test_module_reaper_overrides_parent_and_terminates_only_suite_sandboxes() -> None:
    reaper = vars(k8s_conftest)["_reap_module_sandboxes"]
    assert isinstance(reaper, FixtureFunctionDefinition)
    assert reaper.name == "_reap_module_sandboxes"
    owned_id, unrelated_id = uuid4(), uuid4()
    manager = MagicMock()
    with (
        patch.object(k8s_conftest, "suite_sandbox_ids", return_value={owned_id}),
        patch.object(k8s_conftest, "get_session_with_tenant") as session,
        patch.object(
            k8s_conftest,
            "get_running_sandboxes",
            return_value=[Sandbox(id=owned_id), Sandbox(id=unrelated_id)],
        ) as running,
        patch.object(k8s_conftest, "get_sandbox_manager", return_value=manager),
    ):
        teardown = reaper._get_wrapped_function()()
        next(teardown)
        with pytest.raises(StopIteration):
            next(teardown)
        running.assert_called_once_with(session.return_value.__enter__.return_value)
    assert manager.mock_calls == [call.terminate(owned_id)]


def test_empty_module_reaper_does_not_need_an_initialized_engine() -> None:
    reaper = k8s_conftest._reap_module_sandboxes._get_wrapped_function()
    with (
        patch.object(k8s_conftest, "suite_sandbox_ids", return_value=set()),
        patch.object(
            k8s_conftest,
            "get_session_with_tenant",
            side_effect=RuntimeError("Engine not initialized"),
        ) as session,
        patch.object(k8s_conftest, "get_sandbox_manager") as manager,
    ):
        teardown = reaper()
        next(teardown)
        with pytest.raises(StopIteration):
            next(teardown)
        assert session.mock_calls == []
        assert manager.mock_calls == []


def test_failed_session_creation_still_cleans_up_fixture_created_user(
    fixture_user: DATestUser,
) -> None:
    user = fixture_user
    manager = MagicMock()
    k8s_client = MagicMock()
    failure = RuntimeError("injected session creation failure")
    sandbox_ids_before = k8s_fixtures.suite_sandbox_ids()
    with (
        patch.object(k8s_fixtures.UserManager, "create", return_value=user),
        patch.object(
            k8s_fixtures.BuildSessionManager,
            "create_with_sandbox",
            side_effect=failure,
        ),
        patch.object(k8s_fixtures, "cleanup_api_user_sandbox_rows") as cleanup,
    ):
        with pytest.raises(RuntimeError) as raised:
            with k8s_fixtures._provisioned_sandbox(manager, k8s_client):
                pytest.fail("Failed session creation must not yield a sandbox")
        assert raised.value is failure
        cleanup.assert_called_once_with(UUID(user.id))
    assert manager.mock_calls == []
    assert k8s_client.mock_calls == []
    assert k8s_fixtures.suite_sandbox_ids() == sandbox_ids_before


@pytest.mark.parametrize("failure_at", [None, "terminate", "wait_for_pod_deletion"])
def test_failed_session_creation_cleans_up_committed_sandbox_before_owner(
    fixture_user: DATestUser,
    owned_sandbox_lookup: MagicMock,
    failure_at: str | None,
) -> None:
    sandbox_id = uuid4()
    owned_sandbox_lookup.return_value = Sandbox(
        id=sandbox_id, user_id=UUID(fixture_user.id)
    )
    manager, runtime, k8s_client = MagicMock(), MagicMock(), MagicMock()
    runtime.pod_name.return_value = "owned-failed-create-pod"
    creation_failure = AssertionError("API returned a non-RUNNING sandbox")
    cleanup_failure = RuntimeError(f"injected {failure_at} failure")
    events = MagicMock()
    events.attach_mock(manager.terminate, "terminate")
    with (
        patch.object(k8s_fixtures.UserManager, "create", return_value=fixture_user),
        patch.object(
            k8s_fixtures.BuildSessionManager,
            "create_with_sandbox",
            side_effect=creation_failure,
        ),
        patch.object(k8s_fixtures, "kubernetes_runtime", return_value=runtime),
        patch.object(k8s_fixtures, "_SUITE_SANDBOX_IDS", set()),
        patch.object(k8s_fixtures, "wait_for_pod_deletion") as wait,
        patch.object(k8s_fixtures, "cleanup_api_user_sandbox_rows") as cleanup,
    ):
        events.attach_mock(wait, "wait")
        events.attach_mock(cleanup, "cleanup")
        if failure_at == "terminate":
            manager.terminate.side_effect = cleanup_failure
        elif failure_at == "wait_for_pod_deletion":
            wait.side_effect = cleanup_failure
        expected_failure = creation_failure if failure_at is None else cleanup_failure
        with pytest.raises(type(expected_failure)) as raised:
            with k8s_fixtures._provisioned_sandbox(manager, k8s_client):
                pytest.fail("Failed session creation must not yield a sandbox")
        assert raised.value is expected_failure
        assert k8s_fixtures.suite_sandbox_ids() == {sandbox_id}
        assert owned_sandbox_lookup.call_args.args[1] == UUID(fixture_user.id)
        expected_calls = [call.terminate(sandbox_id)]
        if failure_at != "terminate":
            expected_calls.append(
                call.wait(
                    k8s_client,
                    "owned-failed-create-pod",
                    k8s_fixtures.SANDBOX_NAMESPACE,
                )
            )
        if failure_at is None:
            expected_calls.append(call.cleanup(UUID(fixture_user.id)))
        assert events.mock_calls == expected_calls


@pytest.mark.parametrize(
    "message_test",
    [
        message_tests.test_send_message_api_runs_real_celery_turn,
        message_tests.test_interrupt_running_bash_turn_stops_work_and_allows_follow_up,
    ],
)
@pytest.mark.parametrize("creation_fails", [True, False])
@pytest.mark.parametrize("deletion_fails", [True, False])
def test_message_test_cleanup_tracks_owned_vm_and_preserves_identity_on_failure(
    fixture_user: DATestUser,
    owned_sandbox_lookup: MagicMock,
    message_test: Callable[[SandboxManager, CoreV1Api], None],
    creation_fails: bool,
    deletion_fails: bool,
) -> None:
    sandbox_id, session_id = uuid4(), uuid4()
    owned_sandbox_lookup.return_value = (
        Sandbox(id=sandbox_id, user_id=UUID(fixture_user.id))
        if creation_fails
        else None
    )
    manager, runtime, k8s_client = MagicMock(), MagicMock(), MagicMock()
    runtime.pod_name.return_value = "owned-message-pod"
    session = MagicMock(id=str(session_id), sandbox=MagicMock(id=str(sandbox_id)))
    test_failure = AssertionError("injected message API failure")
    deletion_failure = RuntimeError("injected pod deletion failure")
    wait = MagicMock(side_effect=deletion_failure if deletion_fails else None)
    cleanup = MagicMock()
    events = MagicMock()
    events.attach_mock(manager.terminate, "terminate")
    events.attach_mock(wait, "wait")
    events.attach_mock(cleanup, "cleanup")
    with (
        patch.object(message_tests.UserManager, "create", return_value=fixture_user),
        patch.object(
            message_tests.BuildSessionManager,
            "create",
            return_value=session,
            side_effect=test_failure if creation_fails else None,
        ),
        patch.object(
            message_tests.BuildSessionManager, "start_turn", side_effect=test_failure
        ),
        patch.object(message_tests, "kubernetes_runtime", return_value=runtime),
        patch.object(k8s_fixtures, "kubernetes_runtime", return_value=runtime),
        patch.object(k8s_fixtures, "_SUITE_SANDBOX_IDS", set()),
        patch.object(k8s_fixtures, "wait_for_pod_deletion", wait),
        patch.object(k8s_fixtures, "cleanup_api_user_sandbox_rows", cleanup),
    ):
        expected_failure = deletion_failure if deletion_fails else test_failure
        with pytest.raises(type(expected_failure)) as raised:
            message_test(manager, k8s_client)
        assert raised.value is expected_failure
        assert k8s_fixtures.suite_sandbox_ids() == {sandbox_id}
        assert owned_sandbox_lookup.call_args.args[1] == UUID(fixture_user.id)
        expected_calls = [
            call.terminate(sandbox_id),
            call.wait(k8s_client, "owned-message-pod", k8s_fixtures.SANDBOX_NAMESPACE),
        ]
        if not deletion_fails:
            expected_calls.append(call.cleanup(UUID(fixture_user.id)))
        assert events.mock_calls == expected_calls


@pytest.mark.parametrize("failure_at", ["terminate", "wait_for_pod_deletion"])
def test_failed_teardown_preserves_identity_rows(
    fixture_user: DATestUser, failure_at: str
) -> None:
    sandbox_id, session_id = uuid4(), uuid4()
    manager, runtime, k8s_client = MagicMock(), MagicMock(), MagicMock()
    runtime.pod_name.return_value = "owned-test-pod"
    failure = RuntimeError(f"injected {failure_at} failure")
    with (
        patch.object(k8s_fixtures.UserManager, "create", return_value=fixture_user),
        patch.object(
            k8s_fixtures.BuildSessionManager,
            "create_with_sandbox",
            return_value=(session_id, sandbox_id),
        ),
        patch.object(k8s_fixtures, "kubernetes_runtime", return_value=runtime),
        patch.object(k8s_fixtures, "_SUITE_SANDBOX_IDS", set()),
        patch.object(k8s_fixtures, "wait_for_pod_deletion") as wait,
        patch.object(k8s_fixtures, "cleanup_api_user_sandbox_rows") as cleanup,
    ):
        if failure_at == "terminate":
            manager.terminate.side_effect = failure
        else:
            wait.side_effect = failure
        with pytest.raises(RuntimeError) as raised:
            with k8s_fixtures._provisioned_sandbox(manager, k8s_client) as owned:
                assert owned == k8s_fixtures.OwnedLivePod(
                    fixture_user, sandbox_id, session_id, "owned-test-pod"
                )
        assert raised.value is failure
        assert k8s_fixtures.suite_sandbox_ids() == {sandbox_id}
        assert cleanup.mock_calls == []
        assert manager.mock_calls == [call.terminate(sandbox_id)]
        if failure_at == "wait_for_pod_deletion":
            wait.assert_called_once_with(
                k8s_client, "owned-test-pod", k8s_fixtures.SANDBOX_NAMESPACE
            )


def test_successful_teardown_deletes_identity_only_after_confirmed_pod_deletion(
    fixture_user: DATestUser,
) -> None:
    sandbox_id, session_id = uuid4(), uuid4()
    manager, runtime, k8s_client = MagicMock(), MagicMock(), MagicMock()
    runtime.pod_name.return_value = "owned-test-pod"
    events = MagicMock()
    events.attach_mock(manager.terminate, "terminate")
    with (
        patch.object(k8s_fixtures.UserManager, "create", return_value=fixture_user),
        patch.object(
            k8s_fixtures.BuildSessionManager,
            "create_with_sandbox",
            return_value=(session_id, sandbox_id),
        ),
        patch.object(k8s_fixtures, "kubernetes_runtime", return_value=runtime),
        patch.object(k8s_fixtures, "_SUITE_SANDBOX_IDS", set()),
        patch.object(k8s_fixtures, "wait_for_pod_deletion") as wait,
        patch.object(k8s_fixtures, "cleanup_api_user_sandbox_rows") as cleanup,
    ):
        events.attach_mock(wait, "wait")
        events.attach_mock(cleanup, "cleanup")
        with k8s_fixtures._provisioned_sandbox(manager, k8s_client) as owned:
            assert owned.sandbox_id == sandbox_id
        assert events.mock_calls == [
            call.terminate(sandbox_id),
            call.wait(k8s_client, "owned-test-pod", k8s_fixtures.SANDBOX_NAMESPACE),
            call.cleanup(UUID(fixture_user.id)),
        ]


@pytest.mark.parametrize("extra_owner", ["new_user", "pool_user"])
@pytest.mark.parametrize("failure_at", ["terminate", "wait_for_pod_deletion", None])
def test_extra_sandbox_cleanup_requires_confirmed_pod_deletion(
    fixture_user: DATestUser, extra_owner: str, failure_at: str | None
) -> None:
    sandbox_id, session_id = uuid4(), uuid4()
    manager, runtime, k8s_client, request = (
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    runtime.pod_name.return_value = "owned-extra-pod"
    pool_user = fixture_user.model_copy(update={"id": str(uuid4())})
    request.getfixturevalue.return_value = k8s_fixtures._PoolPod(
        pool_user, uuid4(), "owned-pool-pod", manager, k8s_client
    )
    failure = RuntimeError(f"injected {failure_at} failure")
    events = MagicMock()
    events.attach_mock(manager.terminate, "terminate")
    with (
        patch.object(k8s_fixtures, "_cleanup_pool_workspace"),
        patch.object(
            k8s_fixtures.BuildSessionManager,
            "create_with_sandbox",
            return_value=(session_id, sandbox_id),
        ),
        patch.object(k8s_fixtures, "kubernetes_runtime", return_value=runtime),
        patch.object(k8s_fixtures, "_SUITE_SANDBOX_IDS", set()),
        patch.object(k8s_fixtures, "wait_for_pod_deletion") as wait,
        patch.object(k8s_fixtures, "cleanup_api_user_sandbox_rows") as cleanup_user,
        patch.object(k8s_fixtures, "_delete_sandbox_row") as cleanup_sandbox,
    ):
        events.attach_mock(wait, "wait")
        events.attach_mock(cleanup_user, "cleanup_user")
        events.attach_mock(cleanup_sandbox, "cleanup_sandbox")
        factory = k8s_fixtures.running_sandbox._get_wrapped_function()(request)
        handle = factory(with_session=extra_owner == "pool_user")
        if extra_owner == "new_user":
            handle.provision_api_user(fixture_user)
        finalizer = request.addfinalizer.call_args.args[0]
        if failure_at == "terminate":
            manager.terminate.side_effect = failure
        elif failure_at == "wait_for_pod_deletion":
            wait.side_effect = failure
        if failure_at is not None:
            with pytest.raises(RuntimeError) as raised:
                finalizer()
            assert raised.value is failure
            assert cleanup_user.mock_calls == []
            assert cleanup_sandbox.mock_calls == []
            expected_calls = [call.terminate(sandbox_id)]
            if failure_at == "wait_for_pod_deletion":
                expected_calls.append(
                    call.wait(
                        k8s_client, "owned-extra-pod", k8s_fixtures.SANDBOX_NAMESPACE
                    )
                )
            assert events.mock_calls == expected_calls
        else:
            finalizer()
            expected_cleanup = (
                call.cleanup_user(UUID(fixture_user.id))
                if extra_owner == "new_user"
                else call.cleanup_sandbox(sandbox_id)
            )
            assert events.mock_calls == [
                call.terminate(sandbox_id),
                call.wait(
                    k8s_client, "owned-extra-pod", k8s_fixtures.SANDBOX_NAMESPACE
                ),
                expected_cleanup,
            ]
        assert k8s_fixtures.suite_sandbox_ids() == {sandbox_id}
