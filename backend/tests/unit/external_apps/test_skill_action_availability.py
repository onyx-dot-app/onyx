"""Scope-gating of the actions a skill advertises (ENG-4262).

``build_action_availability_section`` fences off what the agent must not
attempt. Beyond the admin's ``DENY`` policies it now also hides actions the
user's OAuth grant can't authorize — HubSpot requests its write scopes as
*optional* scopes (ENG-4260), so a read-only account connects fine but 401s on
every write. A grant we have no record of (``granted_scopes is None``, i.e. a
credential written before ENG-4261 or a provider that never reports scopes)
gates nothing, so pre-existing credentials keep their full skill body.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.external_apps.providers.hubspot import HubspotAction
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.skills.rendering import (
    ACTION_AVAILABILITY_PLACEHOLDER,
    build_action_availability_section,
    render_external_app_skill,
)

_READ_SCOPES = [
    "oauth",
    "crm.objects.owners.read",
    "crm.objects.contacts.read",
    "crm.objects.companies.read",
    "crm.objects.deals.read",
]
_WRITE_SCOPES = [
    "crm.objects.contacts.write",
    "crm.objects.companies.write",
    "crm.objects.deals.write",
]
_FULL_SCOPES = _READ_SCOPES + _WRITE_SCOPES

_WRITE_ACTIONS = (
    HubspotAction.CONTACTS_WRITE,
    HubspotAction.COMPANIES_WRITE,
    HubspotAction.DEALS_WRITE,
)
_READ_ACTIONS = (
    HubspotAction.OWNERS_READ,
    HubspotAction.CONTACTS_READ,
    HubspotAction.COMPANIES_READ,
    HubspotAction.DEALS_READ,
    HubspotAction.CRM_SEARCH,
)


def _name(action: HubspotAction) -> str:
    """The action's admin display name, which is what the section lists."""
    for endpoint in get_endpoint_catalog(ExternalAppType.HUBSPOT):
        if endpoint.id == action:
            return endpoint.normalised_name
    raise AssertionError(f"{action} missing from the HubSpot catalog")


def _listed(section: str) -> list[str]:
    return [line[2:] for line in section.splitlines() if line.startswith("- ")]


# --- The catalog declares which actions are scope-gated at all ---------------


@pytest.mark.parametrize(
    "action, scope",
    [
        (HubspotAction.CONTACTS_WRITE, "crm.objects.contacts.write"),
        (HubspotAction.COMPANIES_WRITE, "crm.objects.companies.write"),
        (HubspotAction.DEALS_WRITE, "crm.objects.deals.write"),
    ],
)
def test_hubspot_writes_declare_their_optional_scope(
    action: HubspotAction, scope: str
) -> None:
    endpoint = next(
        e for e in get_endpoint_catalog(ExternalAppType.HUBSPOT) if e.id == action
    )
    assert endpoint.required_scopes == (scope,)


@pytest.mark.parametrize("action", _READ_ACTIONS)
def test_hubspot_reads_declare_no_required_scopes(action: HubspotAction) -> None:
    """Reads are in the mandatory scope set, so every connected user has them;
    declaring them would only add a check that can never fail."""
    endpoint = next(
        e for e in get_endpoint_catalog(ExternalAppType.HUBSPOT) if e.id == action
    )
    assert endpoint.required_scopes == ()


# --- Scope gating ------------------------------------------------------------


def test_read_only_grant_marks_writes_unavailable() -> None:
    section = build_action_availability_section(
        ExternalAppType.HUBSPOT, {}, _READ_SCOPES
    )
    assert _listed(section) == [_name(action) for action in _WRITE_ACTIONS]
    assert section.startswith(
        "These actions are unavailable and should not be attempted:"
    )


def test_read_only_grant_keeps_reads_available() -> None:
    section = build_action_availability_section(
        ExternalAppType.HUBSPOT, {}, _READ_SCOPES
    )
    listed = _listed(section)
    for action in _READ_ACTIONS:
        assert _name(action) not in listed


def test_partial_write_grant_hides_only_the_missing_writes() -> None:
    """HubSpot drops individual ungrantable optional scopes, so a grant can hold
    some writes and not others."""
    section = build_action_availability_section(
        ExternalAppType.HUBSPOT,
        {},
        _READ_SCOPES + ["crm.objects.contacts.write"],
    )
    assert _listed(section) == [
        _name(HubspotAction.COMPANIES_WRITE),
        _name(HubspotAction.DEALS_WRITE),
    ]


def test_full_grant_lists_nothing() -> None:
    assert (
        build_action_availability_section(ExternalAppType.HUBSPOT, {}, _FULL_SCOPES)
        == ""
    )


def test_unknown_grant_gates_nothing() -> None:
    """Regression guard: ``None`` is "we have no record", not "nothing granted"."""
    assert build_action_availability_section(ExternalAppType.HUBSPOT, {}, None) == ""


def test_granted_scopes_defaults_to_unknown() -> None:
    """Callers that don't resolve a credential keep the pre-ENG-4262 behaviour."""
    assert build_action_availability_section(ExternalAppType.HUBSPOT, {}) == ""


def test_empty_grant_hides_every_scope_gated_action() -> None:
    """An empty list is an authoritative "granted nothing" (providers record an
    unreadable grant as ``None``), so the writes go."""
    assert _listed(
        build_action_availability_section(ExternalAppType.HUBSPOT, {}, [])
    ) == [_name(action) for action in _WRITE_ACTIONS]


# --- DENY policies, and the two gates together -------------------------------


def test_deny_policy_still_listed_with_unknown_grant() -> None:
    section = build_action_availability_section(
        ExternalAppType.HUBSPOT,
        {HubspotAction.DEALS_READ: EndpointPolicy.DENY},
        None,
    )
    assert _listed(section) == [_name(HubspotAction.DEALS_READ)]


def test_deny_policy_still_listed_with_full_grant() -> None:
    section = build_action_availability_section(
        ExternalAppType.HUBSPOT,
        {HubspotAction.CONTACTS_WRITE: EndpointPolicy.DENY},
        _FULL_SCOPES,
    )
    assert _listed(section) == [_name(HubspotAction.CONTACTS_WRITE)]


def test_deny_and_scope_denied_action_is_listed_once() -> None:
    section = build_action_availability_section(
        ExternalAppType.HUBSPOT,
        {HubspotAction.DEALS_WRITE: EndpointPolicy.DENY},
        _READ_SCOPES,
    )
    listed = _listed(section)
    assert listed.count(_name(HubspotAction.DEALS_WRITE)) == 1
    assert listed == [_name(action) for action in _WRITE_ACTIONS]


def test_deny_and_scope_gates_combine() -> None:
    section = build_action_availability_section(
        ExternalAppType.HUBSPOT,
        {HubspotAction.CRM_SEARCH: EndpointPolicy.DENY},
        _READ_SCOPES,
    )
    assert set(_listed(section)) == {
        _name(HubspotAction.CRM_SEARCH),
        *(_name(action) for action in _WRITE_ACTIONS),
    }
    # Catalog order, not "denies first".
    assert _listed(section)[0] == _name(HubspotAction.CRM_SEARCH)


# --- Rendering the template around the section -------------------------------


def _template_dir(tmp_path: Path, body: str) -> Path:
    (tmp_path / "SKILL.md.template").write_text(body)
    return tmp_path


def test_render_substitutes_the_scope_gated_section(tmp_path: Path) -> None:
    skill_dir = _template_dir(
        tmp_path, f"# HubSpot\n\n{ACTION_AVAILABILITY_PLACEHOLDER}\n\n## Usage\n"
    )
    rendered = render_external_app_skill(
        # Unused: ``external_app is None`` short-circuits the policy lookup.
        db_session=cast(Session, None),
        app_type=ExternalAppType.HUBSPOT,
        external_app=None,
        skill_dir=skill_dir,
        granted_scopes=_READ_SCOPES,
    )
    assert ACTION_AVAILABILITY_PLACEHOLDER not in rendered
    assert "These actions are unavailable and should not be attempted:" in rendered
    for action in _WRITE_ACTIONS:
        assert _name(action) in rendered


def test_render_drops_the_placeholder_on_a_full_grant(tmp_path: Path) -> None:
    skill_dir = _template_dir(
        tmp_path, f"# HubSpot\n\n{ACTION_AVAILABILITY_PLACEHOLDER}\n\n## Usage\n"
    )
    rendered = render_external_app_skill(
        # Unused: ``external_app is None`` short-circuits the policy lookup.
        db_session=cast(Session, None),
        app_type=ExternalAppType.HUBSPOT,
        external_app=None,
        skill_dir=skill_dir,
        granted_scopes=_FULL_SCOPES,
    )
    assert rendered == "# HubSpot\n\n## Usage\n"


def test_shipped_hubspot_template_carries_the_placeholder() -> None:
    """The gating is conveyed purely through the placeholder, so the shipped
    template must still contain it."""
    template = (
        Path(__file__).resolve().parents[3]
        / "onyx"
        / "skills"
        / "builtin"
        / "hubspot"
        / "SKILL.md.template"
    ).read_text()
    assert ACTION_AVAILABILITY_PLACEHOLDER in template
