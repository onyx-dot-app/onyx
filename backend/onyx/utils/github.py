import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, unquote, urlparse

import requests

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.url import SSRFException, ssrf_safe_get

GITHUB_COMMIT_SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]{40}$")

_GITHUB_FETCH_TIMEOUT_SECONDS: Final[int] = 30
_GITHUB_CODELOAD_ARCHIVE_URL_TEMPLATE: Final[str] = (
    "https://codeload.github.com/{owner}/{repo}/tar.gz/{revision}"
)
_GITHUB_REPOSITORY_COMPONENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z0-9_.-]+"
)
_GITHUB_SSH_SOURCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"git@github\.com:([^/]+)/([^/\s]+?)(?:\.git)?$"
)


@dataclass(frozen=True, slots=True)
class GitHubSource:
    owner: str
    repo: str
    tree_tail: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GitHubRevision:
    revision: str
    subpath: str | None


def parse_github_source(
    source: str,
    *,
    allow_ssh: bool = False,
    allow_tree_path: bool = False,
) -> GitHubSource:
    """Parse a GitHub repository or repository-folder source."""
    value = source.strip().rstrip("/")
    if not value:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Enter a GitHub repository URL or owner/repository.",
        )

    tree_tail: tuple[str, ...] = ()
    ssh_match = _GITHUB_SSH_SOURCE_PATTERN.fullmatch(value) if allow_ssh else None
    if ssh_match:
        owner, repo = ssh_match.groups()
    elif "://" not in value:
        source_parts = value.removesuffix(".git").split("/")
        if len(source_parts) != 2:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Enter a GitHub repository URL or owner/repository.",
            )
        owner, repo = source_parts
    else:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in {
            "github.com",
            "www.github.com",
        }:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Enter an HTTPS github.com repository URL.",
            )
        source_parts = tuple(unquote(part) for part in parsed.path.split("/") if part)
        if len(source_parts) < 2:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Invalid GitHub repository URL.",
            )
        owner, repo = source_parts[0], source_parts[1].removesuffix(".git")
        if len(source_parts) > 2:
            if allow_tree_path and len(source_parts) >= 4 and source_parts[2] == "tree":
                tree_tail = source_parts[3:]
            else:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    (
                        "Enter a GitHub repository URL without a branch, file, or subpage."
                        if not allow_tree_path
                        else "Enter a repository URL or a URL for a folder within a repository."
                    ),
                )

    if not all(
        _GITHUB_REPOSITORY_COMPONENT_PATTERN.fullmatch(part) for part in (owner, repo)
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid GitHub repository URL.",
        )
    return GitHubSource(owner=owner, repo=repo, tree_tail=tree_tail)


def _github_get(
    url: str,
    *,
    authorization: str | None = None,
    stream: bool = False,
    follow_redirects: bool = True,
    timeout: float | tuple[float, float] = _GITHUB_FETCH_TIMEOUT_SECONDS,
) -> requests.Response:
    headers = (
        {
            "Accept": "application/vnd.github+json",
            "Authorization": authorization,
        }
        if authorization is not None
        else None
    )
    try:
        return ssrf_safe_get(
            url,
            headers=headers,
            timeout=timeout,
            stream=stream,
            follow_redirects=follow_redirects,
        )
    except SSRFException as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Couldn't securely connect to GitHub. Try again.",
        ) from exc
    except requests.Timeout as exc:
        raise OnyxError(
            OnyxErrorCode.GATEWAY_TIMEOUT,
            "GitHub took too long to respond. Try again.",
        ) from exc
    except requests.RequestException as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Could not reach GitHub. Check your connection and try again.",
        ) from exc


def resolve_github_revision(
    source: GitHubSource,
    authorization_header: str | None = None,
    *,
    revision: str | None = None,
    subpath: str | None = None,
) -> GitHubRevision:
    """Resolve a repository source to an immutable commit and optional subpath."""
    normalized_subpath = subpath.rstrip("/") if subpath else None
    if normalized_subpath and (
        "\\" in normalized_subpath
        or any(part in {"", ".", ".."} for part in normalized_subpath.split("/"))
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid repository folder.",
        )
    if revision is not None:
        if not GITHUB_COMMIT_SHA_PATTERN.fullmatch(revision):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Invalid repository revision.",
            )
        return GitHubRevision(
            revision=revision.lower(),
            subpath=normalized_subpath,
        )

    encoded_owner = quote(source.owner, safe="")
    encoded_repo = quote(source.repo, safe="")
    ref_parts = source.tree_tail or ("HEAD",)
    candidates = [
        ("/".join(ref_parts[:index]), "/".join(ref_parts[index:]) or None)
        for index in range(len(ref_parts), 0, -1)
    ]
    last_status = 404
    last_headers: dict[str, str] = {}
    used_authorization = False
    for candidate_ref, candidate_subpath in candidates:
        commit_url = (
            f"https://api.github.com/repos/{encoded_owner}/{encoded_repo}/"
            f"commits/{quote(candidate_ref, safe='')}"
        )
        response = _github_get(commit_url)
        if response.status_code in {401, 403, 404, 429} and authorization_header:
            response.close()
            response = _github_get(
                commit_url,
                authorization=authorization_header,
            )
            used_authorization = True
        with response:
            last_status = response.status_code
            last_headers = dict(response.headers)
            if response.status_code != 200:
                continue
            try:
                response_body = response.json()
                sha = response_body.get("sha")
            except (requests.JSONDecodeError, ValueError, AttributeError) as exc:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    "GitHub returned an unreadable repository revision. Try again.",
                ) from exc
            if not isinstance(sha, str) or not GITHUB_COMMIT_SHA_PATTERN.fullmatch(sha):
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    "GitHub returned an invalid repository revision. Try again.",
                )
            return GitHubRevision(
                revision=sha.lower(),
                subpath=candidate_subpath,
            )

    if last_status == 401:
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "Your GitHub connection has expired. Reconnect GitHub, then try again.",
        )
    if last_status in {403, 429} and (
        last_status == 429
        or last_headers.get("X-RateLimit-Remaining") == "0"
        or "Retry-After" in last_headers
    ):
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "GitHub's API rate limit has been reached. Try again in a few minutes.",
        )
    if last_status == 403 and used_authorization:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "GitHub denied access to this repository. Confirm that your connected account has access and has authorized organization SSO if required.",
        )
    if last_status in {403, 404}:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Repository or branch not found. Check the URL. If the repository is private, connect GitHub and try again.",
        )
    raise OnyxError(
        OnyxErrorCode.BAD_GATEWAY,
        "Couldn't load the repository from GitHub. Try again in a few minutes.",
    )


def download_github_archive(
    source: GitHubSource,
    revision: str,
    authorization_header: str | None = None,
    *,
    max_size_bytes: int,
    timeout: float | tuple[float, float] = _GITHUB_FETCH_TIMEOUT_SECONDS,
) -> bytes:
    """Download a bounded tarball without forwarding credentials to archive hosts."""
    encoded_owner = quote(source.owner, safe="")
    encoded_repo = quote(source.repo, safe="")
    encoded_revision = quote(revision, safe="")
    archive_url = _GITHUB_CODELOAD_ARCHIVE_URL_TEMPLATE.format(
        owner=encoded_owner,
        repo=encoded_repo,
        revision=encoded_revision,
    )
    response = _github_get(archive_url, stream=True, timeout=timeout)
    if response.status_code != 200 and authorization_header is not None:
        response.close()
        redirect_response = _github_get(
            f"https://api.github.com/repos/{encoded_owner}/{encoded_repo}"
            f"/tarball/{encoded_revision}",
            authorization=authorization_header,
            follow_redirects=False,
        )
        with redirect_response:
            if redirect_response.status_code == 401:
                raise OnyxError(
                    OnyxErrorCode.UNAUTHENTICATED,
                    "Your GitHub connection has expired. Reconnect GitHub, then try again.",
                )
            if redirect_response.status_code in {403, 429}:
                rate_limited = (
                    redirect_response.status_code == 429
                    or redirect_response.headers.get("X-RateLimit-Remaining") == "0"
                    or "Retry-After" in redirect_response.headers
                )
                raise OnyxError(
                    (
                        OnyxErrorCode.RATE_LIMITED
                        if rate_limited
                        else OnyxErrorCode.INSUFFICIENT_PERMISSIONS
                    ),
                    (
                        "GitHub's API rate limit has been reached. Try again in a few minutes."
                        if rate_limited
                        else "GitHub denied access to this repository. Confirm that your connected account has access and has authorized organization SSO if required."
                    ),
                )
            if redirect_response.status_code == 404:
                raise OnyxError(
                    OnyxErrorCode.NOT_FOUND,
                    "Repository or revision not found. Check the URL and your GitHub access.",
                )
            if redirect_response.status_code not in {301, 302, 307, 308}:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    "Couldn't download the repository from GitHub. Try again in a few minutes.",
                )
            archive_url = redirect_response.headers.get("Location", "")
            if not archive_url:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    "GitHub didn't provide a repository download. Try again.",
                )
        response = _github_get(archive_url, stream=True, timeout=timeout)

    with response:
        if response.status_code in {403, 404}:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                "Repository or revision not found. Check the URL. If the repository is private, connect GitHub and try again.",
            )
        if response.status_code == 429:
            raise OnyxError(
                OnyxErrorCode.RATE_LIMITED,
                "GitHub's API rate limit has been reached. Try again in a few minutes.",
            )
        if response.status_code != 200:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Couldn't download the repository from GitHub. Try again in a few minutes.",
            )
        archive_chunks: list[bytes] = []
        archive_size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                archive_size += len(chunk)
                if archive_size > max_size_bytes:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"Repository download exceeds the {max_size_bytes // (1024 * 1024)} MiB limit. Remove large files or use a smaller repository.",
                    )
                archive_chunks.append(chunk)
        except requests.RequestException as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "The GitHub repository download was interrupted. Try again.",
            ) from exc

    return b"".join(archive_chunks)
