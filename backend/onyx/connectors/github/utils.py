from collections.abc import Callable, Mapping
from typing import Any, cast
from urllib.parse import ParseResult, urlparse

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import GITHUB_CONNECTOR_BASE_URL
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.github.models import GitHubRepository
from onyx.server.security.models import web_connector_ssrf_enforced
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, validate_outbound_http_url
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

logger = setup_logger()


# GitHub Enterprise Server exposes its REST API under /api/v3, while github.com
# uses api.github.com. PyGithub needs the full API root, not the web host.
GHES_API_SUFFIX = "/api/v3"


def normalize_github_base_url(base_url: str | None) -> str | None:
    """Turn a user-supplied GitHub Enterprise Server URL into a PyGithub base URL.

    Accepts the web host (``https://ghes.example.com``) or the API root
    (``https://ghes.example.com/api/v3``) and always returns the API root.
    Returns None for blank input so callers can fall back to github.com.
    """
    if base_url is None:
        return None

    cleaned: str = base_url.strip()
    if not cleaned:
        return None

    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"

    parsed: ParseResult = urlparse(cleaned)
    if not parsed.hostname:
        raise ValueError(f"Invalid GitHub base URL: {base_url}")

    # An explicit path already points at an API root; leave it alone.
    path: str = parsed.path.rstrip("/") or GHES_API_SUFFIX
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def validate_credential_base_url(base_url: str) -> None:
    """Reject a credential-supplied Enterprise Server URL that points at
    internal infrastructure.

    A workspace admin sets this field through the API, and PyGithub sends the
    access token to whatever host it names, so it is both an SSRF surface and a
    token-leak surface. ``GITHUB_CONNECTOR_BASE_URL`` is deployment config, set
    by whoever runs the app, and stays exempt.

    The SSRF protection level decides how strict this is, the same control the
    web connector uses. At the default level only public hosts are reachable.
    When an admin relaxes it, a private Enterprise Server becomes reachable but
    cloud metadata stays blocked.
    """
    enforced: bool = web_connector_ssrf_enforced(
        get_security_settings().ssrf_protection_level
    )
    try:
        validate_outbound_http_url(
            base_url,
            https_only=True,
            allow_private_network=not enforced,
            block_link_local_only=not enforced,
        )
    except (SSRFException, ValueError) as e:
        raise ConnectorValidationError(
            f"Invalid GitHub Enterprise Server URL '{base_url}': {e}"
        ) from e


def parse_repository_names(repositories: str | None) -> list[str]:
    """The repository names of the comma-separated setting, without blanks.
    Empty means every repository of the owner."""
    return [name.strip() for name in (repositories or "").split(",") if name.strip()]


def resolve_github_base_url(credentials: Mapping[str, Any]) -> str | None:
    """The API root the client calls. None means github.com.

    The credential's URL wins, so one deployment can index github.com and a
    GitHub Enterprise Server at once; ``GITHUB_CONNECTOR_BASE_URL`` is the
    fallback. Each side is normalized, so a blank credential value cannot
    shadow the env var. Only the credential is user input, so only it gets
    the SSRF check.
    """
    credential_base_url: str | None = normalize_github_base_url(
        credentials.get("github_base_url")
    )
    if credential_base_url is not None:
        validate_credential_base_url(credential_base_url)
        return credential_base_url
    return normalize_github_base_url(GITHUB_CONNECTOR_BASE_URL)


def get_external_access_permission(repo: GitHubRepository) -> ExternalAccess:
    """
    Get the external access permission for a repository.
    This functionality requires Enterprise Edition.
    """
    # Check if EE is enabled
    if not global_version.is_ee_version():
        # For the MIT version, return an empty ExternalAccess (private document)
        return ExternalAccess.empty()

    # Fetch the EE implementation
    ee_get_external_access_permission = cast(
        Callable[[GitHubRepository, bool], ExternalAccess],
        fetch_versioned_implementation(
            "onyx.external_permissions.github.utils",
            "get_external_access_permission",
        ),
    )

    return ee_get_external_access_permission(repo, True)
