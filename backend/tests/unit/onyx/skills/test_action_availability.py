"""The external-app skill's action list: an allow-list of what the grant and the
admin's policies leave available, so the agent never plans against commands the
skill body documents but the app can't perform."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.external_apps.providers import registry
from onyx.external_apps.providers.gmail import GmailAction
from onyx.skills.rendering import build_action_availability_section


def test_lists_available_actions_with_descriptions() -> None:
    section = build_action_availability_section(ExternalAppType.GMAIL, {})
    assert "Send a message — Send an email from the connected account." in section
    assert "Read messages" in section


def test_denied_actions_are_omitted() -> None:
    section = build_action_availability_section(
        ExternalAppType.GMAIL, {GmailAction.MESSAGES_SEND: EndpointPolicy.DENY}
    )
    assert "Send a message" not in section
    assert "Read messages" in section


def test_actions_outside_the_grant_are_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Onyx's OAuth client Gmail is send-only, so the reads the skill body
    documents must not appear as available."""
    monkeypatch.setattr(registry, "MULTI_TENANT", True)
    section = build_action_availability_section(ExternalAppType.GMAIL, {})
    assert "Send a message" in section
    assert "Read messages" not in section
    assert "Create a draft" not in section


def test_nothing_available_tells_the_agent_to_stand_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "MULTI_TENANT", True)
    section = build_action_availability_section(
        ExternalAppType.GMAIL, {GmailAction.MESSAGES_SEND: EndpointPolicy.DENY}
    )
    assert section == "No actions are available for this app — do not use this skill."
