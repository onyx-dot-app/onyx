"""Checks the OneDrive fixture's scoped paths and idempotent set operations."""

from unittest.mock import MagicMock

import pytest
import scripts.onedrive.provision_test_corpus as provision_test_corpus
from scripts.onedrive.provision_test_corpus import (
    ALTERNATE_UPN_ENV,
    DEFAULT_ALTERNATE_UPN,
    DEFAULT_OWNER_UPN,
    DEFAULT_PRIMARY_UPN,
    DEFAULT_SECOND_OWNER_UPN,
    FIXTURE_ROOT_NAME,
    OWNER_UPN_ENV,
    PRIMARY_UPN_ENV,
    SECOND_OWNER_UPN_ENV,
    TEST_FILE_SIZE_BYTES,
    FilePath,
    FixtureConfig,
    FixtureGraphClient,
    FolderPath,
    GraphItem,
    GraphPermission,
    OneDriveFixtureProvisioner,
    exact_membership_changes,
    fixture_file_bytes,
    load_certificate_credentials,
    load_fixture_config,
    relative_to_fixture_root,
    validate_fixture_paths,
)

from tests.utils.secret_names import TestSecret


def test_fixture_paths_are_scoped_and_have_existing_parents() -> None:
    validate_fixture_paths()
    folder_values = {folder.value for folder in FolderPath}

    for folder in FolderPath:
        assert relative_to_fixture_root(folder).startswith(f"{FIXTURE_ROOT_NAME}/")
        if "/" in folder.value:
            assert folder.value.rsplit("/", 1)[0] in folder_values

    for file in FilePath:
        assert relative_to_fixture_root(file).startswith(f"{FIXTURE_ROOT_NAME}/")
        assert file.value.rsplit("/", 1)[0] in folder_values


def test_exact_membership_changes_returns_disjoint_diffs() -> None:
    additions, removals = exact_membership_changes(
        {"retained", "remove"}, {"retained", "add"}
    )

    assert additions == {"add"}
    assert removals == {"remove"}


def test_set_exact_group_members_is_idempotent() -> None:
    graph = MagicMock(spec=FixtureGraphClient)
    graph.base_url = "https://graph.microsoft.com/v1.0"
    graph.get_collection.return_value = [{"id": "member"}]
    provisioner = OneDriveFixtureProvisioner(
        FixtureConfig(),
        graph,
        MagicMock(),
    )

    provisioner._set_exact_group_members("group", {"member"})

    graph.post.assert_not_called()
    graph.delete.assert_not_called()


def test_set_exact_group_members_adds_and_removes_only_the_diff() -> None:
    graph = MagicMock(spec=FixtureGraphClient)
    graph.base_url = "https://graph.microsoft.com/v1.0"
    graph.get_collection.return_value = [{"id": "remove"}]
    provisioner = OneDriveFixtureProvisioner(
        FixtureConfig(),
        graph,
        MagicMock(),
    )

    provisioner._set_exact_group_members("group", {"add"})

    graph.delete.assert_called_once_with("groups/group/members/remove/$ref")
    graph.post.assert_called_once_with(
        "groups/group/members/$ref",
        {"@odata.id": ("https://graph.microsoft.com/v1.0/directoryObjects/add")},
    )


def test_permission_matches_direct_and_collection_identities() -> None:
    direct = GraphPermission.model_validate(
        {"id": "direct", "grantedToV2": {"user": {"id": "user"}}}
    )
    collection = GraphPermission.model_validate(
        {
            "id": "collection",
            "grantedToIdentitiesV2": [{"group": {"id": "group"}}],
        }
    )

    assert direct.grants_principal("user")
    assert collection.grants_principal("group")
    assert not direct.grants_principal("other")


def test_fixture_content_is_valid_and_mutation_is_distinct() -> None:
    baseline = fixture_file_bytes(FilePath.UPDATE)
    mutated = fixture_file_bytes(FilePath.UPDATE, mutated=True)

    assert baseline.startswith(b"PK")
    assert mutated.startswith(b"PK")
    assert baseline != mutated
    assert len(fixture_file_bytes(FilePath.OVER_SIZE)) == TEST_FILE_SIZE_BYTES


def test_baseline_does_not_create_move_destination_file() -> None:
    graph = MagicMock(spec=FixtureGraphClient)
    graph.put_item.side_effect = lambda path, _content: GraphItem(
        id=path,
        name=path,
        webUrl="https://example.test/item",
    )
    folders = {
        path: GraphItem(
            id=path.value,
            name=path.name,
            webUrl="https://example.test/folder",
        )
        for path in FolderPath
    }
    provisioner = OneDriveFixtureProvisioner(
        FixtureConfig(),
        graph,
        MagicMock(),
    )

    files = provisioner._create_files("drive", folders)

    assert FilePath.MOVE in files
    assert FilePath.MOVE_DESTINATION not in files


def test_fixture_config_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OWNER_UPN_ENV, raising=False)
    monkeypatch.delenv(PRIMARY_UPN_ENV, raising=False)
    monkeypatch.delenv(ALTERNATE_UPN_ENV, raising=False)
    monkeypatch.delenv(SECOND_OWNER_UPN_ENV, raising=False)

    config = load_fixture_config()

    assert config.owner_upn == DEFAULT_OWNER_UPN
    assert config.primary_upn == DEFAULT_PRIMARY_UPN
    assert config.alternate_upn == DEFAULT_ALTERNATE_UPN
    assert config.second_owner_upn == DEFAULT_SECOND_OWNER_UPN


def test_fixture_config_accepts_identity_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OWNER_UPN_ENV, "owner@example.com")
    monkeypatch.setenv(PRIMARY_UPN_ENV, "primary@example.com")
    monkeypatch.setenv(ALTERNATE_UPN_ENV, "alternate@example.com")
    monkeypatch.setenv(SECOND_OWNER_UPN_ENV, "second@example.com")

    config = load_fixture_config()

    assert config.owner_upn == "owner@example.com"
    assert config.primary_upn == "primary@example.com"
    assert config.alternate_upn == "alternate@example.com"
    assert config.second_owner_upn == "second@example.com"


def test_certificate_credentials_use_test_secret_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID: "client",
        TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY: "private-key",
        TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD: "password",
        TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID: "directory",
    }
    monkeypatch.setattr(provision_test_corpus, "get_secrets", lambda _keys: values)

    credentials = load_certificate_credentials()

    assert credentials.client_id == "client"
    assert credentials.private_key == "private-key"
    assert credentials.certificate_password == "password"
    assert credentials.directory_id == "directory"
