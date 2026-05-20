import re

import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()

GITHUB_TARBALL_URL = "https://api.github.com/repos/{owner}/{repo}/tarball"
GITHUB_DOWNLOAD_CONNECT_TIMEOUT_SECONDS = 30
GITHUB_DOWNLOAD_READ_TIMEOUT_SECONDS = 300
GITHUB_DOWNLOAD_CHUNK_SIZE_BYTES = 1024 * 1024  # 1 MiB
DEFAULT_MAX_TARBALL_SIZE_BYTES = 500 * 1024 * 1024  # 500 MiB


def parse_github_repo(repo: str) -> tuple[str, str]:
    """Parse a GitHub repo identifier into (owner, name).

    Accepts forms:
        - https://github.com/owner/repo[.git][/...]
        - http://github.com/owner/repo[.git]
        - git@github.com:owner/repo[.git]
        - owner/repo
    """
    repo = repo.strip()

    https_match = re.match(
        r"^https?://github\.com/([^/]+)/([^/?#\s]+?)(?:\.git)?(?:[/?#].*)?$", repo
    )
    if https_match:
        return https_match.group(1), https_match.group(2)

    ssh_match = re.match(r"^git@github\.com:([^/]+)/([^/\s]+?)(?:\.git)?$", repo)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    short_match = re.match(r"^([^/\s]+)/([^/\s]+?)(?:\.git)?$", repo)
    if short_match:
        return short_match.group(1), short_match.group(2)

    raise ValueError(f"Could not parse GitHub repo identifier: {repo!r}")


def download_github_repo(
    repo: str,
    github_token: str | None = None,
    max_size_bytes: int = DEFAULT_MAX_TARBALL_SIZE_BYTES,
) -> bytes:
    """Download a GitHub repo as a gzipped tarball of its default branch.

    ``repo`` accepts any form supported by :func:`parse_github_repo`. The
    response body is streamed and aborted with ``ValueError`` once it exceeds
    ``max_size_bytes`` so a runaway repo cannot exhaust memory.
    """
    owner, name = parse_github_repo(repo)
    url = GITHUB_TARBALL_URL.format(owner=owner, repo=name)
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    logger.info("Downloading GitHub tarball: %s/%s", owner, name)
    with requests.get(
        url,
        headers=headers,
        timeout=(
            GITHUB_DOWNLOAD_CONNECT_TIMEOUT_SECONDS,
            GITHUB_DOWNLOAD_READ_TIMEOUT_SECONDS,
        ),
        allow_redirects=True,
        stream=True,
    ) as response:
        response.raise_for_status()

        chunks: list[bytes] = []
        total_bytes = 0
        for chunk in response.iter_content(chunk_size=GITHUB_DOWNLOAD_CHUNK_SIZE_BYTES):
            if not chunk:
                continue
            total_bytes += len(chunk)
            if total_bytes > max_size_bytes:
                raise ValueError(
                    f"GitHub tarball for {owner}/{name} exceeded "
                    f"max_size_bytes={max_size_bytes}"
                )
            chunks.append(chunk)

    return b"".join(chunks)
