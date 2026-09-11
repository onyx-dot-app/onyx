"""Build provider configuration for the Pi worker without opening a transport."""

from typing import Any

from onyx.configs.app_configs import SEND_USER_METADATA_TO_LLM_PROVIDER
from onyx.configs.chat_configs import MAX_LLM_CYCLES
from onyx.llm.api_surfaces import resolve_api_surface
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import ReasoningEffort, resolve_reasoning_effort
from onyx.llm.utils import build_litellm_passthrough_kwargs


def build_start(
    llm: LLM,
    chat_session_id: str | None,
    reasoning_effort: ReasoningEffort,
    user_identity: LLMUserIdentity | None = None,
    mock_response: str | None = None,
) -> dict[str, Any]:
    effort = resolve_reasoning_effort(
        reasoning_effort,
        default=llm.config.reasoning_effort_default,
        user_default=llm.config.reasoning_effort_user_default,
        maximum=llm.config.reasoning_effort_max,
    )
    if effort == ReasoningEffort.AUTO:
        effort = ReasoningEffort.MEDIUM
    options = build_litellm_passthrough_kwargs(llm.request_options, user_identity)
    if (
        SEND_USER_METADATA_TO_LLM_PROVIDER
        and user_identity
        and llm.config.model_provider == "openrouter"
    ):
        extra_body = dict(options.get("extra_body", {}))
        if user_identity.session_id:
            extra_body["session_id"] = user_identity.session_id
        if user_identity.user_id:
            extra_body["user"] = user_identity.user_id
        options = {**options, "extra_body": extra_body}
    surface = resolve_api_surface(llm.config.model_provider, llm.config.custom_config)
    return {
        "type": "start",
        "config": llm.config.model_dump(mode="json"),
        "options": options,
        "apiSurface": surface.value if surface else None,
        "reasoningEffort": effort.value,
        "maxTurns": MAX_LLM_CYCLES,
        "sessionId": chat_session_id if SEND_USER_METADATA_TO_LLM_PROVIDER else None,
        "mockResponse": mock_response,
    }
