"""The sandbox proxy on the integration tables: which integration a request
belongs to, the credential it gets, the policy of a Craft session and of a
scheduled run, approval rows and session grants."""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from mitmproxy import http
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.slack_configs import slack_url_pattern
from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    BuildSessionStatus,
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    PluginInstallationPolicy,
    ScheduledTaskRunStatus,
    ScheduledTaskTriggerSource,
)
from onyx.db.models import (
    ActionApproval,
    BuildSession,
    Integration,
    IntegrationActionPolicy,
    Plugin,
    ScheduledTask,
    ScheduledTask__Plugin,
    ScheduledTaskRun,
    User,
    UserPluginPreference,
)
from onyx.db.scheduled_task import get_scheduled_task_id_for_session
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    AllMatchedActions,
)
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.craft import list_task_plugin_views
from onyx.integrations.models import EffectivePolicy, LinkValue
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import (
    CredentialInjectionDispatcher,
    CredentialUnavailableError,
)
from onyx.sandbox_proxy.destination_policy import parse_destination_policy
from onyx.sandbox_proxy.models import InjectionContext, McpProtocolRequest
from onyx.sandbox_proxy.request_evaluator import IntegrationRequestEvaluator
from onyx.sandbox_proxy.resolvers.integration import IntegrationResolver
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox, SessionContext
from onyx.sandbox_proxy.sandbox_identity.resolution import SandboxIdentityResolver
from onyx.sandbox_proxy.usable_integrations import UsableIntegrations
from onyx.server.features.build.configs import MCP_SESSION_TAG_HEADER
from onyx.server.features.build.sandbox.util.mcp_config import (
    resolve_craft_mcp_servers,
)
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    hold_in_plugin,
    make_app_integration,
    make_mcp_integration,
    make_openapi_integration,
)
from tests.external_dependency_unit.integrations.conftest import add_connection
from tests.unit.sandbox_proxy.conftest import StubResolver, make_flow

TENANT = POSTGRES_DEFAULT_SCHEMA


@pytest.fixture
def created(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    integration_ids: list[int] = []
    try:
        yield integration_ids
    finally:
        delete_integrations(db_session, integration_ids)


@pytest.fixture
def user(make_test_user: MakeTestUser) -> User:
    return make_test_user("integration_proxy")


def _host() -> str:
    return f"api-{uuid4().hex[:8]}.example.com"


def _run(db_session: Session, integrations: list[Integration]) -> Plugin:
    """A published plugin that each user runs by default."""
    return hold_in_plugin(
        db_session,
        integrations,
        published=True,
        installation_policy=PluginInstallationPolicy.DEFAULT,
    )


def _mcp(
    db_session: Session, created: list[int], url: str, **kwargs: Any
) -> Integration:
    integration, _ = make_mcp_integration(
        db_session,
        server_url=url,
        name=kwargs.pop("name", f"mcp-{uuid4().hex[:6]}"),
        tools=kwargs.pop("tools", ("search", "update")),
        read_only=kwargs.pop("read_only", {"search": True}),
        **kwargs,
    )
    created.append(integration.id)
    return integration


def _custom_app(
    db_session: Session, created: list[int], host: str, **kwargs: Any
) -> Integration:
    integration, _ = make_app_integration(
        db_session,
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=[f"https://{host}/*"],
        **kwargs,
    )
    created.append(integration.id)
    return integration


def _tool_call(name: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    ).encode()


def _request(url: str, body: bytes = b"", method: str = "POST") -> http.Request:
    return http.Request.make(
        method, url, content=body, headers={"content-type": "application/json"}
    )


def _sandbox(user: User) -> ResolvedSandbox:
    return ResolvedSandbox(
        sandbox_id=uuid4(),
        user_id=user.id,
        tenant_id=TENANT,
        sandbox_name="sandbox-integration-proxy",
        sandbox_ip="10.0.0.1",
    )


def _evaluate(
    request: http.Request, user: User, scheduled_task_id: UUID | None = None
) -> Any:
    return IntegrationRequestEvaluator().evaluate(
        request, TENANT, user.id, scheduled_task_id
    )


def _headers(request: http.Request, user: User, matched: Any) -> dict[str, str]:
    ctx = InjectionContext(
        sandbox=_sandbox(user),
        matched_actions=matched if isinstance(matched, AllMatchedActions) else None,
        protocol_target=(
            matched.target if isinstance(matched, McpProtocolRequest) else None
        ),
    )
    resolver = IntegrationResolver()
    assert resolver.claims(request, ctx)
    return resolver.resolve(request, ctx)


class _UnusedIdentity(SandboxIdentityResolver):
    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox | None:  # noqa: ARG002
        raise AssertionError("not used")

    def resolve_session_by_id(
        self,
        session_id: UUID,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
    ) -> UUID | None:
        raise AssertionError("not used")


def _addon() -> GateAddon:
    return GateAddon(
        destination_policy=parse_destination_policy(""),
        identity=_UnusedIdentity(),
        request_evaluator=IntegrationRequestEvaluator(),
        cache_factory=lambda tenant: get_cache_backend(tenant_id=tenant),
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
    )


def _session_ctx(db_session: Session, user: User) -> SessionContext:
    session = BuildSession(
        id=uuid4(),
        user_id=user.id,
        status=BuildSessionStatus.ACTIVE,
        last_activity_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(session)
    db_session.commit()
    return _sandbox(user).with_session(session.id)


def test_sandbox_calls_a_preset_app_a_custom_app_and_an_mcp_server(
    db_session: Session, created: list[int], user: User
) -> None:
    slack, _ = make_app_integration(
        db_session,
        app_type=ExternalAppType.SLACK,
        upstream_url_patterns=[slack_url_pattern("/api/.*")],
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
    )
    created.append(slack.id)
    custom_host = _host()
    custom = _custom_app(
        db_session,
        created,
        custom_host,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Api-Key": "{api_key}"},
    )
    mcp_host = _host()
    mcp = _mcp(
        db_session,
        created,
        f"https://{mcp_host}/mcp",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
    )
    _run(db_session, [slack, custom, mcp])
    add_connection(
        db_session, slack, user.id, ConnectionSecret(access_token="slack-token")
    )
    add_connection(
        db_session, custom, None, ConnectionSecret(fields={"api_key": "org-key"})
    )
    add_connection(db_session, mcp, user.id, ConnectionSecret(access_token="mcp-tok"))

    slack_request = _request(
        "https://slack.com/api/chat.postMessage", b'{"channel": "C1"}'
    )
    matched = _evaluate(slack_request, user)
    assert isinstance(matched, AllMatchedActions)
    assert matched.target.integration_id == slack.id
    assert matched.governing_action.action_type == "slack.messages.write"
    assert _headers(slack_request, user, matched) == {
        "Authorization": "Bearer slack-token"
    }

    custom_request = _request(f"https://{custom_host}/v1/items", method="GET")
    matched = _evaluate(custom_request, user)
    assert isinstance(matched, AllMatchedActions)
    assert matched.target.integration_id == custom.id
    assert matched.governing_action.action_type == "unspecified"
    assert _headers(custom_request, user, matched) == {"X-Api-Key": "org-key"}

    mcp_request = _request(f"https://{mcp_host}/mcp", _tool_call("update"))
    matched = _evaluate(mcp_request, user)
    assert isinstance(matched, AllMatchedActions)
    assert matched.target.integration_id == mcp.id
    assert [a.action_type for a in matched.actions] == ["update"]
    assert _headers(mcp_request, user, matched) == {"Authorization": "Bearer mcp-tok"}

    initialize = _request(
        f"https://{mcp_host}/mcp",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}).encode(),
    )
    protocol = _evaluate(initialize, user)
    assert isinstance(protocol, McpProtocolRequest)
    assert protocol.target.integration_id == mcp.id
    assert _headers(initialize, user, protocol) == {"Authorization": "Bearer mcp-tok"}


def test_a_missing_connection_blocks_with_the_reason(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    mcp = _mcp(
        db_session,
        created,
        f"https://{host}/mcp",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Bearer {api_key}"},
    )
    _run(db_session, [mcp])
    request = _request(f"https://{host}/mcp", _tool_call("search"))
    with pytest.raises(CredentialUnavailableError) as error:
        _headers(request, user, _evaluate(request, user))
    assert error.value.sandbox_detail == f"Connect your {mcp.name} account to use it."


def test_the_longest_path_prefix_wins_between_mcp_integrations(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    short = _mcp(db_session, created, f"https://{host}/mcp")
    long = _mcp(db_session, created, f"https://{host}/mcp/team")
    _run(db_session, [short, long])

    matched = _evaluate(_request(f"https://{host}/mcp/team", _tool_call("x")), user)
    assert matched.target.integration_id == long.id
    matched = _evaluate(_request(f"https://{host}/mcp/other", _tool_call("x")), user)
    assert matched.target.integration_id == short.id


def test_an_external_app_wins_over_an_mcp_server_on_a_shared_host(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    mcp = _mcp(db_session, created, f"https://{host}/mcp")
    app = _custom_app(db_session, created, host)
    _run(db_session, [mcp, app])

    matched = _evaluate(_request(f"https://{host}/mcp", _tool_call("search")), user)
    assert isinstance(matched, AllMatchedActions)
    assert matched.target.integration_id == app.id


def test_an_openapi_integration_matches_under_its_server_url(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    integration, _ = make_openapi_integration(
        db_session,
        openapi_schema={
            "openapi": "3.0.0",
            "info": {"title": "Orders", "description": "Orders", "version": "1"},
            "servers": [{"url": f"https://{host}/v1"}],
            "paths": {
                "/orders": {
                    "get": {"operationId": "listOrders", "summary": "List orders"}
                }
            },
        },
    )
    created.append(integration.id)
    _run(db_session, [integration])

    matched = _evaluate(_request(f"https://{host}/v1/orders", method="GET"), user)
    assert isinstance(matched, AllMatchedActions)
    assert matched.target.integration_id == integration.id
    assert [action.action_type for action in matched.actions] == ["listOrders"]
    assert _evaluate(_request(f"https://{host}/v2/orders", method="GET"), user) is None


def test_the_match_targets_reload_after_the_cache_time(
    db_session: Session, created: list[int], user: User
) -> None:
    """The targets are cached for each tenant. A new integration matches
    after the cache time; a disabled one stops at once, because the
    evaluator reads the enabled integrations for each request."""
    usable = UsableIntegrations(ttl_s=0.5)
    evaluator = IntegrationRequestEvaluator(usable)
    resolver = IntegrationResolver(usable)
    host = _host()
    request = _request(f"https://{host}/mcp", _tool_call("search"))
    ctx = InjectionContext(
        sandbox=_sandbox(user), matched_actions=None, protocol_target=None
    )
    assert evaluator.evaluate(request, TENANT, user.id, None) is None

    mcp = _mcp(db_session, created, f"https://{host}/mcp")
    _run(db_session, [mcp])
    assert evaluator.evaluate(request, TENANT, user.id, None) is None
    assert not resolver.claims(request, ctx)

    time.sleep(0.6)
    matched = evaluator.evaluate(request, TENANT, user.id, None)
    assert isinstance(matched, AllMatchedActions)
    assert matched.target.integration_id == mcp.id
    assert resolver.claims(request, ctx)

    mcp.enabled = False
    db_session.commit()
    assert evaluator.evaluate(request, TENANT, user.id, None) is None


def test_an_integration_the_user_does_not_run_is_not_matched(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    mcp = _mcp(db_session, created, f"https://{host}/mcp")
    app_host = _host()
    app = _custom_app(db_session, created, app_host)
    plugin = _run(db_session, [mcp, app])
    db_session.add(
        UserPluginPreference(user_id=user.id, plugin_id=plugin.id, enabled=False)
    )
    db_session.commit()

    request = _request(f"https://{host}/mcp", _tool_call("search"))
    assert _evaluate(request, user) is None
    assert _evaluate(_request(f"https://{app_host}/x", method="GET"), user) is None
    # The MCP host stays claimed, so the request never forwards bare.
    resolver = IntegrationResolver()
    ctx = InjectionContext(sandbox=_sandbox(user), matched_actions=None)
    assert resolver.claims(request, ctx)
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(request, ctx)


def test_a_path_outside_every_server_url_is_blocked(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    _run(db_session, [_mcp(db_session, created, f"https://{host}/mcp")])
    initialize = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    request = _request(f"https://{host}/admin", initialize)

    assert _evaluate(request, user) is None
    resolver = IntegrationResolver()
    ctx = InjectionContext(sandbox=_sandbox(user), matched_actions=None)
    assert resolver.claims(request, ctx)
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(request, ctx)


def test_an_unparsable_mcp_body_is_blocked(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    _run(db_session, [_mcp(db_session, created, f"https://{host}/mcp")])
    matched = _evaluate(_request(f"https://{host}/mcp", b"not json"), user)
    assert isinstance(matched, AllMatchedActions)
    assert matched.governing_action.action_type == "mcp.unclassifiable"
    assert matched.governing_action.policy is ActionPolicy.DENY


def _task_run(
    db_session: Session, user: User, session_id: UUID, links: dict[UUID, Any]
) -> ScheduledTask:
    task = ScheduledTask(
        user_id=user.id,
        name="Report",
        prompt="Create a report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
    )
    db_session.add(task)
    db_session.flush()
    db_session.add_all(
        [
            ScheduledTaskRun(
                task_id=task.id,
                session_id=session_id,
                status=ScheduledTaskRunStatus.RUNNING,
                trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
            ),
            *(
                ScheduledTask__Plugin(
                    scheduled_task_id=task.id,
                    plugin_id=plugin_id,
                    action_settings=settings,
                )
                for plugin_id, settings in links.items()
            ),
        ]
    )
    db_session.commit()
    return task


def test_a_scheduled_task_calls_only_the_integrations_of_its_plugins(
    db_session: Session, created: list[int], user: User
) -> None:
    task_host = _host()
    in_task = _mcp(db_session, created, f"https://{task_host}/mcp")
    other_host = _host()
    other = _mcp(db_session, created, f"https://{other_host}/mcp")
    task_plugin = _run(db_session, [in_task])
    _run(db_session, [other])
    ctx = _session_ctx(db_session, user)
    _task_run(
        db_session,
        user,
        ctx.session_id,
        {task_plugin.id: {"default": "inherit", "actions": {"update": "allow"}}},
    )
    addon = _addon()

    allowed = _evaluate(
        _request(f"https://{task_host}/mcp", _tool_call("update")), user
    )
    run_ctx, resolved = addon._resolve_request_policies(ctx, allowed)
    assert run_ctx.scheduled_context is not None
    # The pre-approval of the task runs with no approval wait.
    assert resolved.governing_action.policy is ActionPolicy.ALWAYS
    assert addon._task_can_use_app(ctx, allowed.target)

    blocked = _evaluate(
        _request(f"https://{other_host}/mcp", _tool_call("search")), user
    )
    _, resolved = addon._resolve_request_policies(ctx, blocked)
    assert resolved.governing_action.policy is ActionPolicy.DENY
    assert not addon._task_can_use_app(ctx, blocked.target)


def test_a_scheduled_task_ask_ignores_the_owners_always_allow(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    mcp = _mcp(db_session, created, f"https://{host}/mcp")
    plugin = _run(db_session, [mcp])
    db_session.add(
        IntegrationActionPolicy(
            integration_id=mcp.id,
            action="update",
            user_id=user.id,
            policy=IntegrationActionPolicyValue.ALLOW,
        )
    )
    db_session.commit()
    ctx = _session_ctx(db_session, user)
    addon = _addon()
    request = _request(f"https://{host}/mcp", _tool_call("update"))
    _, resolved = addon._resolve_request_policies(ctx, _evaluate(request, user))
    assert resolved.governing_action.policy is ActionPolicy.ALWAYS

    run_ctx = _session_ctx(db_session, user)
    task = _task_run(
        db_session,
        user,
        run_ctx.session_id,
        {plugin.id: {"default": "inherit", "actions": {"update": "ask"}}},
    )
    _, resolved = addon._resolve_request_policies(
        run_ctx, _evaluate(request, user, task.id)
    )
    assert resolved.governing_action.policy is ActionPolicy.ASK


def test_an_ask_action_in_a_session_opens_an_approval_with_the_integration(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    mcp = _mcp(db_session, created, f"https://{host}/mcp")
    _run(db_session, [mcp])
    ctx = _session_ctx(db_session, user)
    addon = _addon()
    matched = _evaluate(_request(f"https://{host}/mcp", _tool_call("update")), user)
    run_ctx, resolved = addon._resolve_request_policies(ctx, matched)
    assert run_ctx.scheduled_context is None
    assert resolved.governing_action.policy is ActionPolicy.ASK

    approval_id = addon._persist_approval_row(ctx, resolved)
    addon._parked.remove(TENANT, approval_id)
    db_session.expire_all()
    row = db_session.get(ActionApproval, approval_id)
    assert row is not None
    assert row.integration_id == mcp.id
    # An integration made after the upgrade has no old identity row.
    assert row.gated_app_id is None


def test_a_session_grant_approves_the_same_actions_of_the_integration(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    mcp = _mcp(db_session, created, f"https://{host}/mcp")
    other_host = _host()
    other = _mcp(db_session, created, f"https://{other_host}/mcp")
    _run(db_session, [mcp, other])
    ctx = _session_ctx(db_session, user)
    addon = _addon()
    matched = _evaluate(_request(f"https://{host}/mcp", _tool_call("update")), user)
    _, resolved = addon._resolve_request_policies(ctx, matched)
    db_session.add(
        ActionApproval(
            session_id=ctx.session_id,
            integration_id=mcp.id,
            actions=[a.model_dump(mode="json") for a in resolved.actions],
            app_name=mcp.name,
            payload={},
            decision=ApprovalDecision.APPROVED,
            decided_via=ApprovalDecidedVia.SESSION_GRANT,
        )
    )
    db_session.commit()

    applied = addon._apply_session_grant(ctx, resolved)
    assert applied is not None
    assert (
        db_session.scalar(
            select(ActionApproval.integration_id).where(
                ActionApproval.approval_id == applied
            )
        )
        == mcp.id
    )
    other_matched = _evaluate(
        _request(f"https://{other_host}/mcp", _tool_call("update")), user
    )
    _, other_resolved = addon._resolve_request_policies(ctx, other_matched)
    assert addon._apply_session_grant(ctx, other_resolved) is None


def test_the_craft_mcp_config_lists_only_connected_integrations_of_enabled_plugins(
    db_session: Session, created: list[int], user: User
) -> None:
    open_mcp = _mcp(db_session, created, f"https://{_host()}/mcp")
    unconnected = _mcp(
        db_session,
        created,
        f"https://{_host()}/mcp",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Bearer {api_key}"},
    )
    connected = _mcp(
        db_session,
        created,
        f"https://{_host()}/mcp",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Bearer {api_key}"},
    )
    turned_off = _mcp(db_session, created, f"https://{_host()}/mcp")
    _run(db_session, [open_mcp, unconnected, connected])
    off_plugin = _run(db_session, [turned_off])
    db_session.add(
        UserPluginPreference(user_id=user.id, plugin_id=off_plugin.id, enabled=False)
    )
    db_session.commit()
    add_connection(
        db_session, connected, user.id, ConnectionSecret(fields={"api_key": "k"})
    )

    listed = {
        config.integration_id for config in resolve_craft_mcp_servers(db_session, user)
    }
    assert {open_mcp.id, connected.id} <= listed
    assert unconnected.id not in listed
    assert turned_off.id not in listed


def test_a_scheduled_run_matches_a_task_plugin_that_the_owner_turned_off(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    mcp = _mcp(db_session, created, f"https://{host}/mcp")
    plugin = _run(db_session, [mcp])
    db_session.add(
        UserPluginPreference(user_id=user.id, plugin_id=plugin.id, enabled=False)
    )
    db_session.commit()
    ctx = _session_ctx(db_session, user)
    task = _task_run(
        db_session,
        user,
        ctx.session_id,
        {plugin.id: {"actions": {"update": "allow"}}},
    )
    request = _request(f"https://{host}/mcp", _tool_call("update"))

    assert _evaluate(request, user) is None
    matched = _evaluate(request, user, task.id)
    assert isinstance(matched, AllMatchedActions)
    assert matched.target.integration_id == mcp.id
    _, resolved = _addon()._resolve_request_policies(ctx, matched)
    assert resolved.governing_action.policy is ActionPolicy.ALWAYS

    # The gate finds the task from the session tag of the run.
    gate = GateAddon(
        destination_policy=parse_destination_policy(""),
        identity=StubResolver(session_by_id=ctx.session_id),
        request_evaluator=IntegrationRequestEvaluator(),
        cache_factory=lambda tenant: get_cache_backend(tenant_id=tenant),
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
    )
    request.headers[MCP_SESSION_TAG_HEADER] = str(ctx.session_id)
    flow = make_flow(host=host)
    flow.request = request
    run_matched = gate._evaluate(flow, ctx.without_session())
    assert isinstance(run_matched, AllMatchedActions)
    assert run_matched.target.integration_id == mcp.id
    # The resolver injects for the matched integration of the run, and lets
    # the run reach the server host.
    assert _headers(request, user, run_matched) == {}
    assert IntegrationResolver().allows_destination(_sandbox(user), "https", host, 443)


def test_a_scheduled_run_ignores_a_plugin_that_is_not_on_the_task(
    db_session: Session, created: list[int], user: User
) -> None:
    host = _host()
    in_task = _mcp(db_session, created, f"https://{host}/mcp")
    # Turned on by the owner, with the same URL, but not on the task.
    _run(db_session, [_mcp(db_session, created, f"https://{host}/mcp")])
    plugin = _run(db_session, [in_task])
    ctx = _session_ctx(db_session, user)
    task = _task_run(
        db_session,
        user,
        ctx.session_id,
        {plugin.id: {"actions": {"update": "allow"}}},
    )

    matched = _evaluate(
        _request(f"https://{host}/mcp", _tool_call("update")), user, task.id
    )
    assert isinstance(matched, AllMatchedActions)
    assert matched.target.integration_id == in_task.id


def test_the_task_catalog_locks_a_task_allow_that_the_policy_ignores(
    db_session: Session, created: list[int], user: User
) -> None:
    open_mcp = _mcp(db_session, created, f"https://{_host()}/mcp")
    no_always_allow = _mcp(
        db_session,
        created,
        f"https://{_host()}/mcp",
        users_can_save_always_allow=False,
    )
    _run(db_session, [open_mcp, no_always_allow])

    locked = {
        (integration.id, action.key): action.locked
        for view in list_task_plugin_views(db_session, user, None)
        for integration in view.integrations
        for action in integration.actions
    }
    assert locked[(open_mcp.id, "update")] is False
    assert locked[(no_always_allow.id, "update")] is True


def test_the_task_catalog_shows_that_a_custom_app_always_asks(
    db_session: Session, created: list[int], user: User
) -> None:
    custom = _custom_app(db_session, created, _host())
    _run(db_session, [custom])
    db_session.add(
        IntegrationActionPolicy(
            integration_id=custom.id,
            action=WHOLE_DOMAIN_ACTION_TYPE,
            user_id=None,
            policy=IntegrationActionPolicyValue.ALLOW,
        )
    )
    db_session.commit()

    (action,) = [
        action
        for view in list_task_plugin_views(db_session, user, None)
        for integration in view.integrations
        if integration.id == custom.id
        for action in integration.actions
    ]
    assert action.key == WHOLE_DOMAIN_ACTION_TYPE
    assert action.integration_policy is EffectivePolicy.ASK
    assert action.locked is True


def test_the_task_catalog_ignores_the_owners_always_allow(
    db_session: Session, created: list[int], user: User
) -> None:
    mcp = _mcp(db_session, created, f"https://{_host()}/mcp")
    _run(db_session, [mcp])
    db_session.add(
        IntegrationActionPolicy(
            integration_id=mcp.id,
            action="update",
            user_id=user.id,
            policy=IntegrationActionPolicyValue.ALLOW,
        )
    )
    db_session.commit()

    policies = {
        (integration.id, action.key): action.integration_policy
        for view in list_task_plugin_views(db_session, user, None)
        for integration in view.integrations
        for action in integration.actions
    }
    assert policies[(mcp.id, "update")] is EffectivePolicy.ASK


def test_a_scheduled_session_config_lists_the_task_plugins_the_owner_turned_off(
    db_session: Session, created: list[int], user: User
) -> None:
    mcp = _mcp(db_session, created, f"https://{_host()}/mcp")
    other = _mcp(db_session, created, f"https://{_host()}/mcp")
    plugin = _run(db_session, [mcp])
    _run(db_session, [other])
    db_session.add(
        UserPluginPreference(user_id=user.id, plugin_id=plugin.id, enabled=False)
    )
    db_session.commit()
    ctx = _session_ctx(db_session, user)
    task = _task_run(
        db_session,
        user,
        ctx.session_id,
        {plugin.id: {"actions": {"update": "blocked"}}},
    )

    interactive = {
        config.integration_id: config.disabled_tools
        for config in resolve_craft_mcp_servers(db_session, user)
    }
    scheduled = {
        config.integration_id: config.disabled_tools
        for config in resolve_craft_mcp_servers(
            db_session,
            user,
            get_scheduled_task_id_for_session(db_session, ctx.session_id),
        )
    }

    assert mcp.id not in interactive
    assert interactive[other.id] == ()
    # The task settings decide the tools, as in the proxy.
    assert scheduled[mcp.id] == ("update",)
    assert other.id not in scheduled
    assert get_scheduled_task_id_for_session(db_session, ctx.session_id) == task.id


def test_the_task_catalog_keeps_a_plugin_with_no_enabled_integration(
    db_session: Session, created: list[int], user: User
) -> None:
    mcp = _mcp(db_session, created, f"https://{_host()}/mcp")
    plugin = _run(db_session, [mcp])
    ctx = _session_ctx(db_session, user)
    task = _task_run(
        db_session,
        user,
        ctx.session_id,
        {plugin.id: {"actions": {"update": "allow", "removed": "allow"}}},
    )
    mcp.enabled = False
    db_session.commit()

    views = {
        view.plugin_id: view
        for view in list_task_plugin_views(db_session, user, task.id)
    }

    assert views[plugin.id].enabled
    assert views[plugin.id].integrations == []
    # A key that no integration has any more is left out, so a save that
    # sends the settings back passes the action check.
    settings = views[plugin.id].action_settings
    assert settings is not None
    assert settings.actions == {"update": LinkValue.ALLOW}
