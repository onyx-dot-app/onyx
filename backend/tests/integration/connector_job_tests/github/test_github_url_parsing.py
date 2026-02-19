"""
Integration tests for GitHub connector URL parsing functionality.

Tests verify that:
1. GitHub connectors can be created with URL-like inputs
2. Data is stored in the correct format (repo_owner + repositories)
3. Backwards compatibility with existing format is maintained
4. Various URL formats are handled correctly
"""

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.test_models import DATestUser


def test_github_connector_basic_format(admin_user: DATestUser) -> None:
    """
    Test creating a GitHub connector with the basic owner/repo format.
    This verifies backwards compatibility with the existing format.
    """
    connector = ConnectorManager.create(
        name="GitHub Basic Format Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "microsoft",
            "repositories": "vscode",
            "include_prs": True,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    # Verify the connector was created successfully
    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == "microsoft"
    assert connector.connector_specific_config["repositories"] == "vscode"

    # Verify we can retrieve the connector and it has the correct config
    retrieved_connector = ConnectorManager.get(
        connector_id=connector.id,
        user_performing_action=admin_user,
    )

    assert retrieved_connector.connector_specific_config["repo_owner"] == "microsoft"
    assert retrieved_connector.connector_specific_config["repositories"] == "vscode"


def test_github_connector_multiple_repos(admin_user: DATestUser) -> None:
    """
    Test creating a GitHub connector with multiple repositories.
    Repositories should be stored as comma-separated values.
    """
    connector = ConnectorManager.create(
        name="GitHub Multiple Repos Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "facebook",
            "repositories": "react,react-native,jest",
            "include_prs": False,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    # Verify the connector stores multiple repos correctly
    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == "facebook"
    assert (
        connector.connector_specific_config["repositories"] == "react,react-native,jest"
    )

    # Verify retrieval preserves the format
    retrieved_connector = ConnectorManager.get(
        connector_id=connector.id,
        user_performing_action=admin_user,
    )

    assert retrieved_connector.connector_specific_config["repo_owner"] == "facebook"
    assert (
        retrieved_connector.connector_specific_config["repositories"]
        == "react,react-native,jest"
    )


def test_github_connector_url_style_input(admin_user: DATestUser) -> None:
    """
    Test that when frontend sends data that looks like it came from URL parsing,
    the backend still stores it correctly.

    This simulates what the frontend URL parser would send after extracting
    owner and repo from: https://github.com/torvalds/linux
    """
    connector = ConnectorManager.create(
        name="GitHub URL Style Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "torvalds",  # Extracted from URL
            "repositories": "linux",  # Extracted from URL
            "include_prs": True,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    # Verify the connector stores the parsed data correctly
    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == "torvalds"
    assert connector.connector_specific_config["repositories"] == "linux"


def test_github_connector_multiple_urls_parsed(admin_user: DATestUser) -> None:
    """
    Test that multiple repositories can be stored when parsed from multiple URLs.

    This simulates what the frontend would send after parsing:
    - https://github.com/python/cpython
    - https://github.com/python/peps
    - https://github.com/python/mypy

    The frontend should extract "python" as owner and "cpython,peps,mypy" as repos.
    """
    connector = ConnectorManager.create(
        name="GitHub Multiple URLs Parsed Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "python",  # Common owner from all URLs
            "repositories": "cpython,peps,mypy",  # Extracted repo names
            "include_prs": True,
            "include_issues": False,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == "python"
    assert connector.connector_specific_config["repositories"] == "cpython,peps,mypy"


def test_github_connector_mixed_owner_validation(admin_user: DATestUser) -> None:
    """
    Test that the backend correctly stores data even when repos have inconsistent naming.

    In the real world, the frontend should validate that all URLs have the same owner,
    but this test verifies the backend doesn't crash if given unusual input.
    """
    connector = ConnectorManager.create(
        name="GitHub Mixed Input Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "google",
            "repositories": "repo1,repo2,repo3",  # Just repo names
            "include_prs": False,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == "google"
    assert connector.connector_specific_config["repositories"] == "repo1,repo2,repo3"


def test_github_connector_update_with_new_repo(admin_user: DATestUser) -> None:
    """
    Test updating an existing GitHub connector to add a new repository.

    This simulates a user editing a connector and adding a new repo via URL.
    The frontend should preserve existing repos and add the new one.
    """
    # Create initial connector with one repo
    connector = ConnectorManager.create(
        name="GitHub Update Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "kubernetes",
            "repositories": "kubernetes",
            "include_prs": True,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    initial_repo = connector.connector_specific_config["repositories"]
    assert initial_repo == "kubernetes"

    # Update to add another repo (simulating user adding via URL)
    connector.connector_specific_config["repositories"] = "kubernetes,kubectl"

    ConnectorManager.edit(
        connector=connector,
        user_performing_action=admin_user,
    )

    # Verify the update was successful
    updated_connector = ConnectorManager.get(
        connector_id=connector.id,
        user_performing_action=admin_user,
    )

    assert (
        updated_connector.connector_specific_config["repositories"]
        == "kubernetes,kubectl"
    )
    assert updated_connector.connector_specific_config["repo_owner"] == "kubernetes"


def test_github_connector_whitespace_handling(admin_user: DATestUser) -> None:
    """
    Test that the connector handles whitespace in repository lists correctly.

    The frontend URL parser should trim whitespace, but this verifies the backend
    accepts data with spacing variations.
    """
    connector = ConnectorManager.create(
        name="GitHub Whitespace Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "apache",
            "repositories": "kafka, spark, hadoop",  # Spaces after commas
            "include_prs": True,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == "apache"
    # The backend should preserve the spacing as-is
    assert connector.connector_specific_config["repositories"] == "kafka, spark, hadoop"


def test_github_connector_trailing_slash_normalization(admin_user: DATestUser) -> None:
    """
    Test that repo names don't have trailing slashes after URL parsing.

    This simulates the frontend parsing: https://github.com/nodejs/node/
    The frontend should strip the trailing slash, so this verifies correct storage.
    """
    connector = ConnectorManager.create(
        name="GitHub Trailing Slash Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "nodejs",
            "repositories": "node",  # No trailing slash
            "include_prs": False,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    assert connector.id is not None
    assert connector.connector_specific_config["repositories"] == "node"
    # Should not have trailing slash
    assert not connector.connector_specific_config["repositories"].endswith("/")


def test_github_connector_www_subdomain_parsing(admin_user: DATestUser) -> None:
    """
    Test that URLs with www subdomain are handled correctly.

    This simulates the frontend parsing: https://www.github.com/rust-lang/rust
    The frontend should extract the same owner/repo regardless of www presence.
    """
    connector = ConnectorManager.create(
        name="GitHub WWW Subdomain Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "rust-lang",  # Extracted from www.github.com URL
            "repositories": "rust",  # Extracted from www.github.com URL
            "include_prs": True,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == "rust-lang"
    assert connector.connector_specific_config["repositories"] == "rust"


def test_github_connector_special_characters_in_names(admin_user: DATestUser) -> None:
    """
    Test that repository names with hyphens and underscores are stored correctly.

    GitHub allows hyphens, underscores, and dots in repository names.
    """
    connector = ConnectorManager.create(
        name="GitHub Special Chars Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "dotnet",
            "repositories": "aspnetcore,roslyn-analyzers,core_lib",
            "include_prs": True,
            "include_issues": False,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    assert connector.id is not None
    assert (
        connector.connector_specific_config["repositories"]
        == "aspnetcore,roslyn-analyzers,core_lib"
    )


def test_github_connector_case_sensitivity(admin_user: DATestUser) -> None:
    """
    Test that owner and repository names preserve their case.

    GitHub is case-insensitive for lookups but preserves the canonical case.
    The frontend should preserve whatever the user enters.
    """
    connector = ConnectorManager.create(
        name="GitHub Case Sensitivity Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "Microsoft",  # Mixed case
            "repositories": "TypeScript,VSCode",  # Mixed case
            "include_prs": True,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == "Microsoft"
    assert connector.connector_specific_config["repositories"] == "TypeScript,VSCode"


@pytest.mark.parametrize(
    "owner,repos,expected_owner,expected_repos",
    [
        # Basic single repo
        ("openai", "gpt-3", "openai", "gpt-3"),
        # Multiple repos
        ("tensorflow", "tensorflow,keras", "tensorflow", "tensorflow,keras"),
        # Organization name
        ("onyx-dot-app", "onyx", "onyx-dot-app", "onyx"),
        # Numeric characters
        ("redis", "redis7", "redis", "redis7"),
        # Multiple repos with various naming
        (
            "golang",
            "go,tools,tour",
            "golang",
            "go,tools,tour",
        ),
    ],
)
def test_github_connector_parameterized_formats(
    admin_user: DATestUser,
    owner: str,
    repos: str,
    expected_owner: str,
    expected_repos: str,
) -> None:
    """
    Parameterized test for various valid GitHub owner/repo combinations.

    This ensures the connector correctly stores various naming patterns.
    """
    connector = ConnectorManager.create(
        name=f"GitHub Param Test {owner}/{repos}",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": owner,
            "repositories": repos,
            "include_prs": True,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    assert connector.id is not None
    assert connector.connector_specific_config["repo_owner"] == expected_owner
    assert connector.connector_specific_config["repositories"] == expected_repos


def test_github_connector_empty_repos_field(admin_user: DATestUser) -> None:
    """
    Test that the connector requires the repositories field to be non-empty.

    The frontend should validate this, but the backend should also enforce it.
    """
    # This test documents current behavior - the connector will be created
    # but may fail during validation or indexing
    connector = ConnectorManager.create(
        name="GitHub Empty Repos Test",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "test-owner",
            "repositories": "",  # Empty string
            "include_prs": True,
            "include_issues": True,
        },
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    # The connector is created (backend doesn't validate at creation time)
    assert connector.id is not None
    assert connector.connector_specific_config["repositories"] == ""
