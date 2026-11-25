import re
from collections.abc import Sequence
from urllib.parse import parse_qs, unquote, urlsplit

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ActionPolicy,
    ApiAppType,
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
)
from onyx.db.integration import (
    get_api_app_for_integration,
    get_external_app_for_integration,
    get_integration_by_id,
    integration_action_from_spec,
    list_integration_actions,
    lock_integration__no_commit,
    replace_integration_actions__no_commit,
)
from onyx.db.models import ApiApp, ExternalApp, Integration, IntegrationAction
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    recognize_actions,
    url_matches_patterns,
)
from onyx.external_apps.matching.graphql_parsing import (
    operation_invocations,
    parse_invocations,
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
from onyx.tools.interface import Tool
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.tool_implementations.app_action.app_action_tool import (
    AppActionSettings,
    AppActionTool,
)
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.custom.graphql_tool import (
    GraphQLTool,
    graphql_root_fields,
    graphql_tool_parameters,
    parse_graphql_schema,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    MethodSpec,
    openapi_to_method_specs,
    openapi_to_url,
    parse_openapi_document,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

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


def graphql_action_specs(sdl: str) -> list[IntegrationActionSpec]:
    """One action per root field: a query runs, a mutation asks."""
    try:
        schema = parse_graphql_schema(sdl)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
    fields = graphql_root_fields(schema)
    if not fields:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The GraphQL schema has no query or mutation fields.",
        )
    return [
        IntegrationActionSpec(
            key=key,
            source=IntegrationActionSource.GRAPHQL,
            display_name=key.split(".", 1)[1],
            description=field.description,
            read_only=key.startswith("query."),
            default_policy=(
                IntegrationActionPolicyValue.ALLOW
                if key.startswith("query.")
                else IntegrationActionPolicyValue.ASK
            ),
            input_schema=graphql_tool_parameters(field),
            http_method="POST",
        )
        for key, field in fields
    ]


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


def _matched_action(
    integration_id: int, action: IntegrationAction
) -> MatchedIntegrationAction:
    return MatchedIntegrationAction(
        integration_id=integration_id,
        action_key=action.key,
        display_name=action.display_name,
        description=action.description or "",
        default_policy=action.default_policy or IntegrationActionPolicyValue.ASK,
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
    """An HTTP API. The kind row decides the shape: a REST ``api_app`` row
    (each OpenAPI operation is an action), a GraphQL ``api_app`` row (each
    query or mutation root field is an action), an ``external_app`` with a preset (the
    catalog of the preset gives the actions, plus one action for each other
    request), or a CUSTOM ``external_app`` (one action for all of its URLs, and
    no chat tools)."""

    def _openapi_config(
        self, integration: Integration, db_session: Session
    ) -> ApiConfig | None:
        if integration.api_app_id is None:
            return None
        app = get_api_app_for_integration(integration.id, db_session)
        return self.config_from_api_app(app) if app is not None else None

    @staticmethod
    def config_from_api_app(app: ApiApp) -> ApiConfig | None:
        if app.api_type is ApiAppType.GRAPHQL and app.graphql_schema is not None:
            return ApiConfig(
                shape=ApiShape.GRAPHQL,
                base_url=app.base_url,
                graphql_schema=app.graphql_schema,
            )
        if app.api_type is not ApiAppType.REST or app.openapi_document is None:
            return None
        try:
            spec = parse_openapi_document(app.openapi_document)
        except ValueError as e:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
        try:
            base_url: str | None = openapi_to_url(spec)
        except ValueError:
            # A spec with no single server URL matches no request; it must not
            # break the readers that only need the shape.
            base_url = None
        return ApiConfig(
            shape=ApiShape.OPENAPI,
            openapi_spec=spec,
            base_url=base_url,
        )

    def load_config(self, integration: Integration, db_session: Session) -> ApiConfig:
        config = self._openapi_config(integration, db_session)
        if config is not None:
            return config
        return self.config_from_external_app(
            self._external_app(integration, db_session)
        )

    @staticmethod
    def config_from_external_app(app: ExternalApp) -> ApiConfig:
        return ApiConfig(
            shape=(
                ApiShape.CUSTOM
                if app.app_type == ExternalAppType.CUSTOM
                else ApiShape.PRESET
            ),
            app_type=app.app_type,
            url_regexes=tuple(app.upstream_url_regexes),
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

    def discover_actions(
        self, integration: Integration, db_session: Session
    ) -> list[IntegrationActionSpec]:
        """Makes no network call."""
        config = self.load_config(integration, db_session)
        if config.shape is ApiShape.OPENAPI:
            if config.openapi_spec is None:
                return []
            try:
                return [
                    openapi_action_spec(spec)
                    for spec in openapi_to_method_specs(config.openapi_spec)
                ]
            except ValueError as e:
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
        if config.shape is ApiShape.GRAPHQL and config.graphql_schema is not None:
            return graphql_action_specs(config.graphql_schema)
        other_requests = IntegrationActionSpec(
            key=WHOLE_DOMAIN_ACTION_TYPE,
            source=IntegrationActionSource.EXTERNAL_APP,
            display_name=(
                integration.name
                if config.shape is ApiShape.CUSTOM
                else "Any other request"
            ),
            description=(
                f"Any request to {integration.name}."
                if config.shape is ApiShape.CUSTOM
                else f"A request to {integration.name} that is no other action."
            ),
            read_only=None,
            default_policy=IntegrationActionPolicyValue.ASK,
        )
        if config.shape is ApiShape.CUSTOM or config.app_type is None:
            return [other_requests]
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
        ] + [other_requests]

    def build_chat_tools(
        self,
        integration: Integration,
        actions: Sequence[IntegrationAction],
        ctx: ChatToolContext,
        db_session: Session,
    ) -> list[Tool]:
        """An OpenAPI tool for each operation, a GraphQL tool for each root
        field, or an app action tool for each action of a preset."""
        if not actions:
            return []
        config = (
            ctx.config
            if isinstance(ctx.config, ApiConfig)
            else self.load_config(integration, db_session)
        )
        if config.shape is ApiShape.PRESET:
            return self._app_action_tools(integration, actions, config, ctx)
        if (
            config.shape is ApiShape.GRAPHQL
            and config.graphql_schema is not None
            and config.base_url is not None
        ):
            schema = parse_graphql_schema(config.graphql_schema)
            keys = {key for key, _ in graphql_root_fields(schema)}
            return [
                GraphQLTool(
                    integration_id=integration.id,
                    action_key=action.key,
                    schema=schema,
                    endpoint_url=config.base_url,
                    headers=ctx.additional_headers,
                    approval=ctx.approval_for(action.key),
                    credentials=ctx.credentials,
                    acting_user_id=ctx.user_id,
                )
                for action in actions
                if action.key in keys
            ]
        if config.shape is not ApiShape.OPENAPI or config.openapi_spec is None:
            return []
        keys = {action.key for action in actions}
        tools = build_custom_tools_from_openapi_schema_and_headers(
            integration_id=integration.id,
            openapi_schema=config.openapi_spec,
            headers=ctx.additional_headers,
            dynamic_schema_info=DynamicSchemaInfo(
                chat_session_id=ctx.chat_session_id,
                message_id=ctx.message_id,
                user_id=ctx.user_id,
                user_email=ctx.user_email,
            ),
            approval_for=ctx.approval_for,
            credentials=ctx.credentials,
            acting_user_id=ctx.user_id,
        )
        return [
            tool
            for tool in tools
            if tool.integration_action is not None
            and tool.integration_action.action in keys
        ]

    @staticmethod
    def _app_action_tools(
        integration: Integration,
        actions: Sequence[IntegrationAction],
        config: ApiConfig,
        ctx: ChatToolContext,
    ) -> list[Tool]:
        """A stored action that the catalog no longer has gives no tool."""
        if config.app_type is None or not config.url_regexes:
            return []
        rules = {
            endpoint.id.value: endpoint.matches
            for endpoint in get_endpoint_catalog(config.app_type)
        }
        offered = [
            action
            for action in actions
            if action.key in rules or action.key == WHOLE_DOMAIN_ACTION_TYPE
        ]
        settings = AppActionSettings(
            integration_id=integration.id,
            integration_name=integration.name,
            app_type=config.app_type,
            url_regexes=config.url_regexes,
            credentials=ctx.credentials,
            acting_user_id=ctx.user_id,
            offered_keys=frozenset(action.key for action in offered),
        )
        return [
            AppActionTool(
                settings,
                action_key=action.key,
                display_name=action.display_name,
                description=action.description or "",
                rules=rules.get(action.key, ()),
                approval=ctx.approval_for(action.key),
            )
            for action in offered
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
        if target.endpoint is not None and target.graphql:
            return self._match_graphql(
                integration.id, target.endpoint, request.url, request, db_session
            )
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
            for action in api_integration_actions(integration_id, db_session)
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
        matched = [_matched_action(integration_id, action) for action in winners]
        return RequestMatch(
            actions=matched
            or [_whole_domain_action(integration_id, f"{method} {path}")],
            path_prefix_length=len(target.path_prefix),
        )

    def _match_graphql(
        self,
        integration_id: int,
        target: CraftMCPTarget,
        url: str,
        request: ProxiedRequest,
        db_session: Session,
    ) -> RequestMatch | None:
        """A request to the endpoint URL calls the action of each root field
        in its body and in the ``query`` of its URL (the GET form). A request
        with no root field, or with a root field that is no action, also calls
        the request action, which asks. A request to another path under the
        endpoint is no match."""
        proxied = http.Request.make(request.method, url)
        if match_request((target,), proxied) is None or normalized_request_path(
            proxied.path or ""
        ) != (target.path_prefix or "/"):
            return None
        actions = {
            action.key: action
            for action in api_integration_actions(integration_id, db_session)
        }
        url_queries = parse_qs(urlsplit(url).query).get("query", [])
        invoked = {
            f"{operation}.{field}"
            for operation, field in [
                *parse_invocations(request.body),
                *(
                    invocation
                    for query in url_queries
                    for invocation in operation_invocations(query)
                ),
            ]
        }
        matched = [
            _matched_action(integration_id, actions[key])
            for key in sorted(invoked)
            if key in actions
        ]
        if not invoked or len(matched) < len(invoked):
            matched.append(
                _whole_domain_action(
                    integration_id, f"{request.method.upper()} {request.path}"
                )
            )
        return RequestMatch(actions=matched, path_prefix_length=len(target.path_prefix))


def sync_integration_actions__no_commit(
    integration: Integration, db_session: Session
) -> None:
    """A stored source that the kind no longer finds loses its rows. The kind
    settings are read under the integration lock, so a sync that started
    earlier cannot write an older action list over a newer one."""
    lock_integration__no_commit(integration.id, db_session)
    specs = ApiKindHandler().discover_actions(integration, db_session)
    stored_sources = {
        action.source for action in list_integration_actions(integration.id, db_session)
    }
    for source in sorted(stored_sources | {spec.source for spec in specs}):
        replace_integration_actions__no_commit(
            integration.id,
            source,
            [spec for spec in specs if spec.source == source],
            db_session,
        )


def api_integration_actions(
    integration_id: int, db_session: Session
) -> list[IntegrationAction]:
    """The stored actions. The migration of the integration tables writes no
    API actions: with no stored rows, the actions come from the settings and
    stay unsaved, so a read path never writes. An admin save of the actions,
    an edit or a refresh writes them."""
    stored = list_integration_actions(integration_id, db_session)
    if stored:
        return stored
    integration = get_integration_by_id(integration_id, db_session)
    if integration is None:
        return []
    try:
        specs = ApiKindHandler().discover_actions(integration, db_session)
    except OnyxError as error:
        logger.warning(
            "Integration %s: the API settings give no actions: %s",
            integration_id,
            error.detail,
        )
        return []
    return [integration_action_from_spec(integration_id, spec) for spec in specs]
