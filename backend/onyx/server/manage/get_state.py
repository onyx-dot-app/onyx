import concurrent.futures
import re

import requests
from fastapi import APIRouter
from fastapi import HTTPException

from onyx import __version__
from onyx.auth.users import anonymous_user_enabled
from onyx.auth.users import user_needs_to_be_verified
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.constants import DEV_VERSION_PATTERN
from onyx.configs.constants import STABLE_VERSION_PATTERN
from onyx.server.manage.models import AllVersions
from onyx.server.manage.models import AuthTypeResponse
from onyx.server.manage.models import ContainerVersions
from onyx.server.manage.models import VersionResponse
from onyx.server.models import StatusResponse

router = APIRouter()


@router.get("/health")
def healthcheck() -> StatusResponse:
    return StatusResponse(success=True, message="ok")


@router.get("/auth/type")
def get_auth_type() -> AuthTypeResponse:
    return AuthTypeResponse(
        auth_type=AUTH_TYPE,
        requires_verification=user_needs_to_be_verified(),
        anonymous_user_enabled=anonymous_user_enabled(),
    )


@router.get("/version")
def get_version() -> VersionResponse:
    return VersionResponse(backend_version=__version__)


@router.get("/versions")
def get_versions() -> AllVersions:
    """
    Fetches the latest stable and beta versions of Onyx Docker images.
    Since DockerHub does not explicitly flag stable and beta images,
    this endpoint can be used to programmatically check for new images.
    """
    # Fetch the latest tags from DockerHub for each Onyx component
    dockerhub_repos = [
        "onyxdotapp/onyx-model-server",
        "onyxdotapp/onyx-backend",
        "onyxdotapp/onyx-web-server",
    ]

    # For good measure, we fetch 10 pages of tags
    def get_dockerhub_tags(repo: str, pages: int = 10) -> list[str]:
        url = f"https://hub.docker.com/v2/repositories/{repo}/tags"
        tags = []
        for _ in range(pages):
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            tags.extend(
                [
                    tag["name"]
                    for tag in data["results"]
                    if re.match(r"^v\d", tag["name"])
                ]
            )
            url = data.get("next")
            if not url:
                break
        return tags

    # Get tags for all repos in parallel
    with concurrent.futures.ThreadPoolExecutor() as executor:
        all_tags = list(
            executor.map(lambda repo: set(get_dockerhub_tags(repo)), dockerhub_repos)
        )

    # Find common tags across all repos
    common_tags = set.intersection(*all_tags)

    # Filter tags by strict version patterns
    dev_tags = [tag for tag in common_tags if DEV_VERSION_PATTERN.match(tag)]
    stable_tags = [tag for tag in common_tags if STABLE_VERSION_PATTERN.match(tag)]

    # Ensure we have at least one tag of each type
    if not dev_tags:
        raise HTTPException(
            status_code=500,
            detail="No valid dev versions found matching pattern v(number).(number).(number)-beta.(number)",
        )
    if not stable_tags:
        raise HTTPException(
            status_code=500,
            detail="No valid stable versions found matching pattern v(number).(number).(number)",
        )

    # Sort common tags and get the latest one
    def version_key(version: str) -> tuple[int, int, int, int]:
        """Extract major, minor, patch, beta as integers for sorting"""
        # Remove 'v' prefix
        clean_version = version[1:]

        # Check if it's a beta version
        if "-beta." in clean_version:
            # Split on '-beta.' to separate version and beta number
            base_version, beta_num = clean_version.split("-beta.")
            parts = base_version.split(".")
            return (int(parts[0]), int(parts[1]), int(parts[2]), int(beta_num))
        else:
            # Stable version - no beta number
            parts = clean_version.split(".")
            return (int(parts[0]), int(parts[1]), int(parts[2]), 0)

    latest_dev_version = sorted(dev_tags, key=version_key, reverse=True)[0]
    latest_stable_version = sorted(stable_tags, key=version_key, reverse=True)[0]

    return AllVersions(
        stable=ContainerVersions(
            onyx=latest_stable_version,
            relational_db="postgres:15.2-alpine",
            index="vespaengine/vespa:8.277.17",
            nginx="nginx:1.23.4-alpine",
        ),
        dev=ContainerVersions(
            onyx=latest_dev_version,
            relational_db="postgres:15.2-alpine",
            index="vespaengine/vespa:8.277.17",
            nginx="nginx:1.23.4-alpine",
        ),
        migration=ContainerVersions(
            onyx="airgapped-intfloat-nomic-migration",
            relational_db="postgres:15.2-alpine",
            index="vespaengine/vespa:8.277.17",
            nginx="nginx:1.23.4-alpine",
        ),
    )
