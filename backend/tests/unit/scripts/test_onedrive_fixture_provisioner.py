"""Tests for safe OneDrive fixture ownership and suite isolation."""

from unittest.mock import MagicMock

import pytest

import tests.utils.onedrive_fixture as fixture_module
from tests.utils.onedrive_fixture import (
    DAILY_FIXTURE_ROOT_NAME,
    INTEGRATION_FIXTURE_ROOT_NAME,
    AnonymousLinkOutcome,
    FixtureGraphClient,
    GraphFixtureError,
    LinkScope,
    OneDriveFixtureProvisioner,
    build_daily_fixture_config,
    build_integration_fixture_config,
    load_fixture_config,
)


def _provisioner() -> tuple[OneDriveFixtureProvisioner, MagicMock]:
    graph = MagicMock(spec=FixtureGraphClient)
    graph.base_url = "https://graph.microsoft.com/v1.0"
    provisioner = OneDriveFixtureProvisioner(
        build_daily_fixture_config(),
        graph,
        MagicMock(),
    )
    return provisioner, graph


def test_suite_configs_use_distinct_owned_external_identities() -> None:
    default = load_fixture_config().corpus
    daily = build_daily_fixture_config().corpus
    integration = build_integration_fixture_config().corpus

    assert len({default.root_name, daily.root_name, integration.root_name}) == 3
    assert daily.root_name == DAILY_FIXTURE_ROOT_NAME
    assert integration.root_name == INTEGRATION_FIXTURE_ROOT_NAME
    assert (
        len(
            {
                default.visible_group.mail_nickname,
                daily.visible_group.mail_nickname,
                integration.visible_group.mail_nickname,
            }
        )
        == 3
    )
    assert all(
        "-v1" in corpus.visible_group.mail_nickname
        for corpus in (default, daily, integration)
    )
    assert (
        len(
            {
                default.ownership_description,
                daily.ownership_description,
                integration.ownership_description,
            }
        )
        == 3
    )


def test_fixture_configs_are_immutable() -> None:
    config = build_daily_fixture_config()

    assert config.model_config.get("frozen") is True
    assert config.corpus.model_config.get("frozen") is True


def test_existing_unowned_group_is_not_modified() -> None:
    provisioner, graph = _provisioner()
    group = provisioner.config.corpus.visible_group
    graph.get_collection.return_value = [
        {
            "id": "group-id",
            "displayName": group.display_name,
            "mailNickname": group.mail_nickname,
            "description": "created by someone else",
            "visibility": group.visibility.value,
        }
    ]

    with pytest.raises(RuntimeError, match="Refusing to manage unowned group"):
        provisioner._ensure_group(group, {"member-id"})

    graph.patch.assert_not_called()
    graph.post.assert_not_called()
    graph.delete.assert_not_called()


def test_owned_group_selects_description_and_updates_membership() -> None:
    provisioner, graph = _provisioner()
    group = provisioner.config.corpus.visible_group
    graph.get_collection.side_effect = [
        [
            {
                "id": "group-id",
                "displayName": group.display_name,
                "mailNickname": group.mail_nickname,
                "description": provisioner.config.corpus.ownership_description,
                "visibility": group.visibility.value,
            }
        ],
        [{"id": "member-id"}],
    ]

    provisioner._ensure_group(group, {"member-id"})

    assert "description" in graph.get_collection.call_args_list[0].args[1]["$select"]
    graph.delete.assert_not_called()


def test_group_member_read_retries_graph_fixture_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner, graph = _provisioner()
    graph.get_collection.side_effect = [
        GraphFixtureError("GET", "groups/group-id/members", 404, "notFound"),
        [{"id": "member-id"}],
    ]
    sleep = MagicMock()
    monkeypatch.setattr(fixture_module.time, "sleep", sleep)

    assert provisioner._get_group_member_ids("group-id") == {"member-id"}
    sleep.assert_called_once_with(fixture_module.GROUP_PROVISION_POLL_SECONDS)


def test_invite_retries_transient_invalid_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner, graph = _provisioner()
    graph.post.side_effect = [
        GraphFixtureError(
            "POST", "drives/drive/items/item/invite", 400, "invalidRequest"
        ),
        None,
    ]
    sleep = MagicMock()
    monkeypatch.setattr(fixture_module.time, "sleep", sleep)

    provisioner._invite("drive", "item", "principal")

    assert graph.post.call_count == 2
    sleep.assert_called_once_with(fixture_module.INVITE_PROVISION_POLL_SECONDS)


def test_idempotent_graph_write_retries_network_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FixtureGraphClient(lambda: "token", "https://graph.microsoft.com")
    response = MagicMock(status_code=200, ok=True)
    request = MagicMock(
        side_effect=[fixture_module.requests.ReadTimeout("timeout"), response]
    )
    sleep = MagicMock()
    monkeypatch.setattr(fixture_module.requests, "request", request)
    monkeypatch.setattr(fixture_module.time, "sleep", sleep)

    assert client._request("PUT", "drives/drive/items/item/content") is response
    assert request.call_count == 2
    sleep.assert_called_once()


def test_only_known_anonymous_link_policy_error_is_optional() -> None:
    provisioner, graph = _provisioner()
    graph.post.side_effect = GraphFixtureError(
        "POST", "drives/drive/items/item/createLink", 403, "accessDenied"
    )

    assert (
        provisioner._create_link("drive", "item", LinkScope.ANONYMOUS)
        is AnonymousLinkOutcome.REJECTED_BY_TENANT_POLICY
    )

    graph.post.side_effect = GraphFixtureError(
        "POST", "drives/drive/items/item/createLink", 400, "invalidRequest"
    )
    with pytest.raises(GraphFixtureError):
        provisioner._create_link("drive", "item", LinkScope.ANONYMOUS)
