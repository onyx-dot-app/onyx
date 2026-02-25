import pytest
from office365.graph_client import AzureEnvironment  # type: ignore[import-untyped]

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_graph_env import resolve_microsoft_environment


def test_resolve_global_defaults() -> None:
    env = resolve_microsoft_environment(
        "https://graph.microsoft.com", "https://login.microsoftonline.com"
    )
    assert env.environment == AzureEnvironment.Global
    assert env.sharepoint_domain_suffix == "sharepoint.com"


def test_resolve_gcc_high() -> None:
    env = resolve_microsoft_environment(
        "https://graph.microsoft.us", "https://login.microsoftonline.us"
    )
    assert env.environment == AzureEnvironment.USGovernmentHigh
    assert env.graph_host == "https://graph.microsoft.us"
    assert env.authority_host == "https://login.microsoftonline.us"
    assert env.sharepoint_domain_suffix == "sharepoint.us"


def test_resolve_dod() -> None:
    env = resolve_microsoft_environment(
        "https://dod-graph.microsoft.us", "https://login.microsoftonline.us"
    )
    assert env.environment == AzureEnvironment.USGovernmentDoD
    assert env.sharepoint_domain_suffix == "sharepoint.us"


def test_trailing_slashes_are_stripped() -> None:
    env = resolve_microsoft_environment(
        "https://graph.microsoft.us/", "https://login.microsoftonline.us/"
    )
    assert env.environment == AzureEnvironment.USGovernmentHigh


def test_mismatched_authority_raises() -> None:
    with pytest.raises(ConnectorValidationError, match="inconsistent"):
        resolve_microsoft_environment(
            "https://graph.microsoft.us", "https://login.microsoftonline.com"
        )


def test_unknown_graph_host_raises() -> None:
    with pytest.raises(ConnectorValidationError, match="Unsupported"):
        resolve_microsoft_environment(
            "https://graph.example.com", "https://login.example.com"
        )
