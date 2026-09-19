"""Tests for safe OneDrive fixture ownership and suite isolation."""

from unittest.mock import MagicMock

import pytest

import tests.utils.onedrive_fixture as fixture_module
from tests.utils.onedrive_fixture import (
    DAILY_FIXTURE_ROOT_NAME,
    DAILY_MUTATION_FIXTURE_ROOT_NAME,
    INTEGRATION_FIXTURE_ROOT_NAME,
    INTEGRATION_MUTATION_FIXTURE_ROOT_NAME,
    AnonymousLinkOutcome,
    FixtureGraphClient,
    GraphDrive,
    GraphFixtureError,
    GraphItem,
    GraphSite,
    GraphUser,
    LinkScope,
    OneDriveFixtureProvisioner,
    SharePointIds,
    build_daily_fixture_config,
    build_daily_mutation_fixture_config,
    build_integration_fixture_config,
    build_integration_mutation_fixture_config,
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
    daily_mutation = build_daily_mutation_fixture_config().corpus
    integration_mutation = build_integration_mutation_fixture_config().corpus
    corpora = (default, daily, integration, daily_mutation, integration_mutation)

    assert len({corpus.root_name for corpus in corpora}) == len(corpora)
    assert daily.root_name == DAILY_FIXTURE_ROOT_NAME
    assert integration.root_name == INTEGRATION_FIXTURE_ROOT_NAME
    assert daily_mutation.root_name == DAILY_MUTATION_FIXTURE_ROOT_NAME
    assert integration_mutation.root_name == INTEGRATION_MUTATION_FIXTURE_ROOT_NAME
    assert len({corpus.visible_group.mail_nickname for corpus in corpora}) == len(
        corpora
    )
    assert all("-v1" in corpus.visible_group.mail_nickname for corpus in corpora)
    assert len({corpus.ownership_description for corpus in corpora}) == len(corpora)


def test_fixture_configs_are_immutable() -> None:
    config = build_daily_fixture_config()

    assert config.model_config.get("frozen") is True
    assert config.corpus.model_config.get("frozen") is True


def test_load_state_only_reads_existing_fixture() -> None:
    provisioner, graph = _provisioner()
    user_ids = iter(("owner", "second-owner", "primary", "alternate"))
    users = [
        GraphUser.model_validate(
            {"id": user_id, "userPrincipalName": f"{user_id}@example.com"}
        )
        for user_id in user_ids
    ]
    drives = [
        GraphDrive.model_validate(
            {
                "id": drive_id,
                "name": drive_id,
                "webUrl": f"https://example.test/{drive_id}",
                "driveType": "business",
                "sharepointIds": {"siteId": "site"},
            }
        )
        for drive_id in ("drive", "second-drive")
    ]
    graph.get_model.side_effect = [
        *users,
        *drives,
        GraphSite.model_validate({"id": "site", "webUrl": "https://example.test/site"}),
    ]
    graph.get_optional_item.side_effect = lambda path: GraphItem.model_validate(
        {
            "id": path,
            "name": path.rsplit("/", 1)[-1],
            "webUrl": f"https://example.test/{path}",
            "sharepointIds": SharePointIds.model_validate(
                {"siteId": "site"}
            ).model_dump(by_alias=True),
        }
    )
    corpus = provisioner.config.corpus
    graph.get_collection.side_effect = [
        [],
        [
            {
                "id": "visible",
                "displayName": corpus.visible_group.display_name,
                "mailNickname": corpus.visible_group.mail_nickname,
                "description": corpus.ownership_description,
                "visibility": corpus.visible_group.visibility.value,
            }
        ],
        [
            {
                "id": "hidden",
                "displayName": corpus.hidden_group.display_name,
                "mailNickname": corpus.hidden_group.mail_nickname,
                "description": corpus.ownership_description,
                "visibility": corpus.hidden_group.visibility.value,
            }
        ],
    ]

    state = provisioner.load_state()

    assert state.drive.id == "drive"
    graph.post.assert_not_called()
    graph.patch.assert_not_called()
    graph.put_item.assert_not_called()
    graph.patch_item.assert_not_called()
    graph.delete.assert_not_called()


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
