"""Pure Craft test payload builders."""

from __future__ import annotations

from typing import Any

from onyx.db.enums import EndpointPolicy
from onyx.external_apps.matching.engine import MatchedAction
from onyx.server.features.build.sandbox.models import LLMProviderConfig


def default_llm_config(
    provider: str = "openai",
    model_name: str = "gpt-5-mini",
    api_key: str = "test-key",
) -> LLMProviderConfig:
    """Standard ``LLMProviderConfig`` for tests that don't care about specifics."""
    return LLMProviderConfig(
        provider=provider,
        model_name=model_name,
        api_key=api_key,
        api_base=None,
    )


def action_entry(
    action_type: str,
    *,
    display_name: str = "Action",
    description: str = "An action.",
    policy: EndpointPolicy = EndpointPolicy.ASK,
) -> dict[str, Any]:
    """JSONB-shape dict for one ``ActionApproval.actions`` entry."""
    return MatchedAction(
        action_type=action_type,
        display_name=display_name,
        description=description,
        policy=policy,
    ).model_dump(mode="json")


def default_action_entries() -> list[dict[str, Any]]:
    """Single ASK entry for tests that don't care about catalog specifics."""
    return [
        action_entry(
            "shell.exec",
            display_name="Run command",
            description="Run a shell command.",
        )
    ]
