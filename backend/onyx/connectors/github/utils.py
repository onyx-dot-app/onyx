from collections.abc import Callable
from typing import cast
from urllib.parse import ParseResult, urlparse

from github import Github
from github.Repository import Repository

from onyx.access.models import ExternalAccess
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.github.models import SerializedRepository
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


def get_external_access_permission(
    repo: Repository, github_client: Github
) -> ExternalAccess:
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
        Callable[[Repository, Github, bool], ExternalAccess],
        fetch_versioned_implementation(
            "onyx.external_permissions.github.utils",
            "get_external_access_permission",
        ),
    )

    return ee_get_external_access_permission(repo, github_client, True)


def deserialize_repository(
    cached_repo: SerializedRepository, github_client: Github
) -> Repository:
    """
    Deserialize a SerializedRepository back into a Repository object.
    """
    # Try to access the requester - different PyGithub versions may use different attribute names
    try:
        # Try to get the requester using getattr to avoid linter errors
        requester = getattr(github_client, "_requester", None)  # ods: ignore[getattr]
        if requester is None:
            requester = getattr(  # ods: ignore[getattr]
                github_client, "_Github__requester", None
            )
        if requester is None:
            # If we can't find the requester attribute, we need to fall back to recreating the repo
            raise AttributeError("Could not find requester attribute")

        return cached_repo.to_Repository(requester)
    except Exception as e:
        # If all else fails, re-fetch the repo directly
        logger.warning(
            "Failed to deserialize repository: %s. Attempting to re-fetch.", e
        )
        repo_id = cached_repo.id
        return github_client.get_repo(repo_id)
