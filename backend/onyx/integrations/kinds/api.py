import re
from collections.abc import Sequence
from urllib.parse import unquote

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ActionPolicy,
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
)
from onyx.db.integration import (
    get_external_app_for_integration,
    get_openapi_tool_for_integration,
    list_integration_actions,
)
from onyx.db.models import ExternalApp, Integration, IntegrationAction
from onyx.db.models import Tool as ToolModel
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    recognize_actions,
    url_matches_patterns,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.integrations.kinds.base import IntegrationKindHandler
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import (
    ApiConfig,
    ApiShape,
    IntegrationActionSpec,
    MatchedIntegrationAction,
    RequestMatch,
)
from onyx.sandbox_proxy.resolvers.mcp_matching import (
    CraftMCPTarget,
    IntegrationMatchTarget,
    match_request,
    normalized_request_path,
)
from onyx.server.features.mcp.models import merge_mcp_headers
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
        source=IntegrationActionSource.OPENAPI,
        display_name=method_spec.spec.get("summary") or method_spec.raw_name,
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


_PATH_PARAMETER = re.compile(r"\{[^{}/]+\}")


def _literal_length(template: str) -> int:
    return len(unquote(_PATH_PARAMETER.sub("", template.rstrip("/"))))


def _segment_matches(template: str, segment: str) -> bool:
    """Each parameter takes one or more characters. Each literal goes at its
    first place after the previous one, so the time is linear, with no
    backtracking. The literals are decoded as the request path is, after
    the split, so an encoded brace stays literal text."""
    literals = [unquote(literal) for literal in _PATH_PARAMETER.split(template)]
    if len(literals) == 1:
        return literals[0] == segment
    first, *middle, last = literals
    if not segment.startswith(first) or not segment.endswith(last):
        return False
    position = len(first)
    end = len(segment) - len(last)
    for literal in middle:
        found = segment.find(literal, position + 1, end - 1)
        if found < 0:
            return False
        position = found + len(literal)
    return end - position >= 1


def _openapi_path_matches(template: str, path: str) -> bool:
    """A parameter fills all or part of one segment, as in ``/files/{id}.json``.
    A trailing slash on either side is ignored."""
    template_segments = template.rstrip("/").split("/")
    path_segments = path.removesuffix("/").split("/")
    return len(template_segments) == len(path_segments) and all(
        _segment_matches(t, p)
        for t, p in zip(template_segments, path_segments, strict=True)
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

    def _openapi_config(
        self, integration: Integration, db_session: Session
    ) -> ApiConfig | None:
        if integration.tool_id is None:
            return None
        tool = get_openapi_tool_for_integration(integration.id, db_session)
        return self.openapi_config_from_tool(tool) if tool is not None else None

    @staticmethod
    def openapi_config_from_tool(tool: ToolModel) -> ApiConfig | None:
        if tool.openapi_schema is None:
            return None
        try:
            base_url: str | None = openapi_to_url(tool.openapi_schema)
        except ValueError:
            # A spec with no single server URL matches no request; it must not
            # break the readers that only need the shape.
            base_url = None
        return ApiConfig(
            shape=ApiShape.OPENAPI,
            tool_id=tool.id,
            openapi_spec=tool.openapi_schema,
            base_url=base_url,
        )

    def load_config(self, integration: Integration, db_session: Session) -> ApiConfig:
        config = self._openapi_config(integration, db_session)
        if config is not None:
            return config
        app = self._external_app(integration, db_session)
        return ApiConfig(
            shape=(
                ApiShape.CUSTOM
                if app.app_type == ExternalAppType.CUSTOM
                else ApiShape.PRESET
            ),
            app_type=app.app_type,
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

    def discover_actions(
        self, integration: Integration, db_session: Session
    ) -> list[IntegrationActionSpec]:
        """Makes no network call."""
        config = self.load_config(integration, db_session)
        if config.shape is ApiShape.OPENAPI:
            return [openapi_action_spec(spec) for spec in self._method_specs(config)]
        if config.shape is ApiShape.CUSTOM:
            return [
                IntegrationActionSpec(
                    key=WHOLE_DOMAIN_ACTION_TYPE,
                    source=IntegrationActionSource.EXTERNAL_APP,
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
                source=IntegrationActionSource.EXTERNAL_APP,
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
        config = (
            ctx.config
            if isinstance(ctx.config, ApiConfig)
            else self.load_config(integration, db_session)
        )
        if (
            config.shape is not ApiShape.OPENAPI
            or config.tool_id is None
            or config.openapi_spec is None
        ):
            return []
        keys = {action.key for action in actions}
        tools = build_custom_tools_from_openapi_schema_and_headers(
            integration_id=integration.id,
            openapi_schema=config.openapi_spec,
            # The credential wins over a request header of the same name.
            custom_headers=header_dict_to_header_list(
                merge_mcp_headers(ctx.additional_headers, ctx.credentials.headers)
            ),
            dynamic_schema_info=DynamicSchemaInfo(
                chat_session_id=ctx.chat_session_id,
                message_id=ctx.message_id,
                user_id=ctx.user_id,
                user_email=ctx.user_email,
            ),
            approval_for=ctx.approval_for,
        )
        return [
            tool
            for tool in tools
            if tool.integration_action is not None
            and tool.integration_action.action in keys
        ]

    def match_request(
        self,
        integration: Integration,
        target: IntegrationMatchTarget,
        request: ProxiedRequest,
        db_session: Session,
    ) -> RequestMatch | None:
        if request.url is None:
            return None
        if target.endpoint is not None:
            return self._match_openapi(
                integration.id, target.endpoint, request.method, request.url, db_session
            )
        if target.app_type is None or not url_matches_patterns(
            request.url, target.url_regexes
        ):
            return None
        matched = recognize_actions(
            target.app_type,
            request.model_copy(update={"path": request.path.split("?", 1)[0]}),
        )
        return RequestMatch(
            actions=[
                MatchedIntegrationAction(
                    integration_id=integration.id,
                    action_key=action.action_type,
                    display_name=action.display_name,
                    description=action.description,
                    default_policy=CATALOG_POLICY_VALUES[action.policy],
                )
                for action in matched
            ]
        )

    def _match_openapi(
        self,
        integration_id: int,
        target: CraftMCPTarget,
        method: str,
        url: str,
        db_session: Session,
    ) -> RequestMatch | None:
        """The request must be under the server URL of the spec. Then its method
        and the rest of its path pick the stored actions."""
        proxied = http.Request.make(method, url)
        if match_request((target,), proxied) is None:
            return None

        path = normalized_request_path(proxied.path or "")
        relative_path = path[len(target.path_prefix) :] or "/"
        method = method.upper()
        path_matches = [
            (action, action.path_template)
            for action in list_integration_actions(integration_id, db_session)
            if action.path_template is not None
            and _openapi_path_matches(action.path_template, relative_path)
        ]
        # As in OpenAPI, the path decides first, then the method. A concrete
        # path wins over a templated one: the template with the most literal
        # text wins.
        longest = max(
            (_literal_length(template) for _, template in path_matches), default=0
        )
        winners = [
            action
            for action, template in path_matches
            if _literal_length(template) == longest and action.http_method == method
        ]
        matched = [
            MatchedIntegrationAction(
                integration_id=integration_id,
                action_key=action.key,
                display_name=action.display_name,
                description=action.description or "",
                default_policy=action.default_policy
                or IntegrationActionPolicyValue.ASK,
            )
            for action in winners
        ]
        return RequestMatch(
            actions=matched
            or [_whole_domain_action(integration_id, f"{method} {path}")],
            path_prefix_length=len(target.path_prefix),
        )
