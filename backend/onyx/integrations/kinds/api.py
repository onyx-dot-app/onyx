from collections.abc import Sequence
from typing import ClassVar

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ActionPolicy,
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationKind,
)
from onyx.db.integration import (
    get_external_app_for_integration,
    get_openapi_tool_for_integration,
)
from onyx.db.models import ExternalApp, Integration, IntegrationAction
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    recognize_actions,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.providers.actions import path_matches
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.integrations.kinds.base import ChatToolContext, IntegrationKindHandler
from onyx.integrations.models import (
    ApiConfig,
    ApiShape,
    IntegrationActionSpec,
    MatchedIntegrationAction,
)
from onyx.integrations.presets import get_preset
from onyx.sandbox_proxy.request_evaluator import resolve_app_for_url
from onyx.sandbox_proxy.resolvers.mcp_matching import (
    match_request,
    normalized_request_path,
    parse_target,
)
from onyx.tools.interface import Tool
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    MethodSpec,
    openapi_to_method_specs,
    openapi_to_url,
)
from onyx.utils.headers import header_dict_to_header_list

# The catalog policy of an external app, as an integration action policy.
CATALOG_POLICY_VALUES: dict[ActionPolicy, IntegrationActionPolicyValue] = {
    ActionPolicy.ALWAYS: IntegrationActionPolicyValue.ALLOW,
    ActionPolicy.ASK: IntegrationActionPolicyValue.ASK,
    ActionPolicy.DENY: IntegrationActionPolicyValue.BLOCKED,
}


def openapi_action_spec(method_spec: MethodSpec) -> IntegrationActionSpec:
    """One OpenAPI operation as an action: GET runs, each other method asks."""
    is_get = method_spec.method.upper() == "GET"
    return IntegrationActionSpec(
        key=method_spec.raw_name,
        source=IntegrationActionSource.OPENAPI_SPEC,
        display_name=method_spec.raw_name,
        description=method_spec.summary,
        read_only=is_get,
        default_policy=(
            IntegrationActionPolicyValue.ALLOW
            if is_get
            else IntegrationActionPolicyValue.ASK
        ),
        input_schema=method_spec.to_tool_definition().parameters,
        http_method=method_spec.method.upper(),
        path_template=method_spec.path,
    )


def _whole_domain_action(
    integration_id: int, description: str
) -> MatchedIntegrationAction:
    return MatchedIntegrationAction(
        integration_id=integration_id,
        action_key=WHOLE_DOMAIN_ACTION_TYPE,
        display_name="Perform action",
        description=description,
        default_policy=IntegrationActionPolicyValue.ASK,
    )


class ApiKindHandler(IntegrationKindHandler):
    """An HTTP API. The kind row decides the shape: an OpenAPI ``tool`` row
    (each operation is an action), an ``external_app`` with a preset (the
    catalog of the preset gives the actions), or a CUSTOM ``external_app``
    (one action for all of its URLs)."""

    kind: ClassVar[IntegrationKind] = IntegrationKind.API

    def load_config(self, integration: Integration, db_session: Session) -> ApiConfig:
        tool = get_openapi_tool_for_integration(integration.id, db_session)
        if tool is not None and tool.openapi_schema is not None:
            try:
                base_url = openapi_to_url(tool.openapi_schema)
            except ValueError as e:
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
            return ApiConfig(
                shape=ApiShape.OPENAPI,
                tool_id=tool.id,
                openapi_spec=tool.openapi_schema,
                base_url=base_url,
            )
        app = self._external_app(integration, db_session)
        return ApiConfig(
            shape=(
                ApiShape.CUSTOM
                if app.app_type == ExternalAppType.CUSTOM
                else ApiShape.PRESET
            ),
            external_app_id=app.id,
            app_type=app.app_type,
            upstream_url_patterns=list(app.upstream_url_patterns),
        )

    def _external_app(
        self, integration: Integration, db_session: Session
    ) -> ExternalApp:
        app = get_external_app_for_integration(integration.id, db_session)
        if app is None:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                f"Integration {integration.id} has no API settings.",
            )
        return app

    def _method_specs(self, config: ApiConfig) -> list[MethodSpec]:
        if config.openapi_spec is None:
            return []
        try:
            return openapi_to_method_specs(config.openapi_spec)
        except ValueError as e:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    def auth_methods(
        self, integration: Integration, db_session: Session
    ) -> frozenset[IntegrationAuthMethod]:
        config = self.load_config(integration, db_session)
        if config.shape is ApiShape.OPENAPI:
            return frozenset(
                {
                    IntegrationAuthMethod.OAUTH2,
                    IntegrationAuthMethod.API_KEY,
                    IntegrationAuthMethod.ONYX_LOGIN,
                }
            )
        preset = get_preset(config.app_type) if config.app_type else None
        if preset is not None and isinstance(preset.provider, OAuthExternalAppProvider):
            return frozenset({IntegrationAuthMethod.OAUTH2})
        return frozenset({IntegrationAuthMethod.API_KEY})

    def discover_actions(
        self, integration: Integration, db_session: Session
    ) -> list[IntegrationActionSpec]:
        config = self.load_config(integration, db_session)
        if config.shape is ApiShape.OPENAPI:
            return [openapi_action_spec(spec) for spec in self._method_specs(config)]
        if config.shape is ApiShape.CUSTOM:
            return [
                IntegrationActionSpec(
                    key=WHOLE_DOMAIN_ACTION_TYPE,
                    source=IntegrationActionSource.PRESET_CATALOG,
                    display_name=integration.name,
                    description=f"Any request to {integration.name}.",
                    read_only=None,
                    default_policy=IntegrationActionPolicyValue.ASK,
                )
            ]
        if config.app_type is None:
            return []
        return [
            IntegrationActionSpec(
                key=endpoint.id.value,
                source=IntegrationActionSource.PRESET_CATALOG,
                display_name=endpoint.normalised_name,
                description=endpoint.description,
                read_only=endpoint.default_policy is ActionPolicy.ALWAYS,
                default_policy=CATALOG_POLICY_VALUES[endpoint.default_policy],
            )
            for endpoint in get_endpoint_catalog(config.app_type)
        ]

    def build_chat_tools(
        self,
        integration: Integration,
        actions: Sequence[IntegrationAction],
        ctx: ChatToolContext,
        db_session: Session,
    ) -> list[Tool]:
        """OpenAPI only. A preset or custom app has no chat tools in release N:
        only Craft uses it."""
        if not actions:
            return []
        config = self.load_config(integration, db_session)
        if (
            config.shape is not ApiShape.OPENAPI
            or config.tool_id is None
            or config.openapi_spec is None
        ):
            return []
        keys = {action.key for action in actions}
        tools = build_custom_tools_from_openapi_schema_and_headers(
            # The tool row id keeps the tool names of today.
            tool_id=config.tool_id,
            openapi_schema=config.openapi_spec,
            custom_headers=header_dict_to_header_list(ctx.custom_headers),
            dynamic_schema_info=DynamicSchemaInfo(
                chat_session_id=ctx.chat_session_id,
                message_id=ctx.message_id,
                user_id=ctx.user_id,
                user_email=ctx.user_email,
            ),
            user_oauth_token=ctx.user_oauth_token,
            approval_for=ctx.approval_for,
        )
        # A CustomTool shows its operationId, the action key, as its display name.
        return [tool for tool in tools if tool.display_name in keys]

    def match_request(
        self,
        integration: Integration,
        request: ProxiedRequest,
        db_session: Session,
    ) -> list[MatchedIntegrationAction] | None:
        if request.url is None:
            return None
        config = self.load_config(integration, db_session)
        if config.shape is ApiShape.OPENAPI:
            return self._match_openapi(integration.id, config, request)

        app = self._external_app(integration, db_session)
        if resolve_app_for_url(request.url, [app]) is None:
            return None
        matched = recognize_actions(
            app, request.model_copy(update={"path": request.path.split("?", 1)[0]})
        )
        return [
            MatchedIntegrationAction(
                integration_id=integration.id,
                action_key=action.action_type,
                display_name=action.display_name,
                description=action.description,
                default_policy=CATALOG_POLICY_VALUES[action.policy],
            )
            for action in matched.actions
        ]

    def _match_openapi(
        self, integration_id: int, config: ApiConfig, request: ProxiedRequest
    ) -> list[MatchedIntegrationAction] | None:
        """The request must be under the server URL of the spec. Then its method
        and the rest of its path pick the operations."""
        if request.url is None or config.base_url is None:
            return None
        target = parse_target(integration_id, config.base_url)
        if target is None:
            return None
        proxied = http.Request.make(request.method, request.url)
        if match_request((target,), proxied) is None:
            return None

        path = normalized_request_path(proxied.path or "")
        relative_path = path[len(target.path_prefix) :] or "/"
        method = request.method.upper()
        matched = [
            MatchedIntegrationAction(
                integration_id=integration_id,
                action_key=spec.key,
                display_name=spec.display_name,
                description=spec.description or "",
                default_policy=spec.default_policy,
            )
            for spec in (
                openapi_action_spec(method_spec)
                for method_spec in self._method_specs(config)
            )
            if spec.http_method == method
            and spec.path_template is not None
            and path_matches(spec.path_template, relative_path)
        ]
        return matched or [_whole_domain_action(integration_id, f"{method} {path}")]
