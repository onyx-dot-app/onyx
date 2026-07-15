"""Fetch and discover skills from GitHub repository archives."""

from __future__ import annotations

import io
import re
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import Final
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse

import requests

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES
from onyx.skills.bundle import DEFAULT_TOTAL_MAX_BYTES
from onyx.skills.bundle import parse_skill_md_metadata
from onyx.skills.bundle import SKILL_MD_NAME
from onyx.skills.bundle import slug_from_skill_name
from onyx.skills.bundle import TEMPLATE_SUFFIX
from onyx.skills.bundle import validate_and_normalize_custom_bundle
from onyx.skills.models import GitHubRepository
from onyx.skills.models import GitHubSkillBundle
from onyx.utils.url import ssrf_safe_get
from onyx.utils.url import SSRFException

_ARCHIVE_MAX_BYTES: Final[int] = 25 * 1024 * 1024
_ARCHIVE_MAX_MEMBERS: Final[int] = 10_000
_FETCH_TIMEOUT_SECONDS: Final[int] = 30


def fetch_github_skill_bundles(
    source: str,
    authorization_header: str | None = None,
) -> tuple[GitHubRepository, list[GitHubSkillBundle]]:
    """Fetch a repository and return every directory containing SKILL.md."""
    value = source.strip().rstrip("/")
    if not value:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Enter a GitHub repository URL or owner/repository.",
        )

    if "://" not in value:
        parts = value.removesuffix(".git").split("/")
        if len(parts) != 2 or not all(
            re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Enter a GitHub repository URL or owner/repository.",
            )
        repository = GitHubRepository(owner=parts[0], repo=parts[1])
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

        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Invalid GitHub repository URL."
            )
        owner, repo = parts[0], parts[1].removesuffix(".git")
        if not all(
            re.fullmatch(r"[A-Za-z0-9_.-]+", component) for component in (owner, repo)
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Invalid GitHub repository URL."
            )
        if len(parts) == 2:
            repository = GitHubRepository(owner=owner, repo=repo)
        else:
            if len(parts) < 4 or parts[2] != "tree":
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Enter a repository URL or a URL for a folder within a repository.",
                )
            repository = GitHubRepository(
                owner=owner,
                repo=repo,
                ref=parts[3],
                subpath="/".join(parts[4:]) or None,
            )

    search_prefix = repository.subpath.rstrip("/") if repository.subpath else ""
    if search_prefix and (
        "\\" in search_prefix
        or any(part in {"", ".", ".."} for part in search_prefix.split("/"))
    ):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Invalid repository folder.")

    ref = quote(repository.ref or "HEAD", safe="/")
    owner = quote(repository.owner, safe="")
    repo = quote(repository.repo, safe="")
    if authorization_header is not None:
        api_url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{ref}"
        try:
            redirect_response = ssrf_safe_get(
                api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": authorization_header,
                },
                timeout=_FETCH_TIMEOUT_SECONDS,
                follow_redirects=False,
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
        with redirect_response:
            if redirect_response.status_code == 401:
                raise OnyxError(
                    OnyxErrorCode.UNAUTHENTICATED,
                    "Your GitHub connection has expired. Reconnect GitHub, then try again.",
                )
            if redirect_response.status_code in {403, 429}:
                if (
                    redirect_response.status_code == 429
                    or redirect_response.headers.get("X-RateLimit-Remaining") == "0"
                    or "Retry-After" in redirect_response.headers
                ):
                    raise OnyxError(
                        OnyxErrorCode.RATE_LIMITED,
                        "GitHub's API rate limit has been reached. Try again in a few minutes.",
                    )
                raise OnyxError(
                    OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                    "GitHub denied access to this repository. Make sure your connected account has access and, if required, has authorized organization SSO.",
                )
            if redirect_response.status_code == 404:
                raise OnyxError(
                    OnyxErrorCode.NOT_FOUND,
                    "Repository or branch not found. Check the URL and confirm that your connected GitHub account has access.",
                )
            if redirect_response.status_code not in {301, 302, 307, 308}:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    "Couldn't download the repository from GitHub. Try again in a few minutes.",
                )
            archive_url = redirect_response.headers.get("Location")
            if not archive_url:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    "GitHub didn't provide a repository download. Try again.",
                )
    else:
        archive_url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    try:
        response = ssrf_safe_get(
            archive_url,
            timeout=_FETCH_TIMEOUT_SECONDS,
            stream=True,
        )
    except SSRFException as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub returned an unsupported repository download URL. Try again.",
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

    with response:
        if response.status_code == 404:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                "Repository or branch not found. Check the URL. If the repository is private, connect GitHub and try again.",
            )
        if response.status_code == 429 or (
            response.status_code == 403
            and (
                response.headers.get("X-RateLimit-Remaining") == "0"
                or "Retry-After" in response.headers
            )
        ):
            raise OnyxError(
                OnyxErrorCode.RATE_LIMITED,
                "GitHub's API rate limit has been reached. Try again in a few minutes.",
            )
        if response.status_code == 403 and authorization_header is not None:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "GitHub denied access to this repository. Make sure your connected account has access and, if required, has authorized organization SSO.",
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
                archive_size += len(chunk)
                if archive_size > _ARCHIVE_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"Repository download exceeds the {_ARCHIVE_MAX_BYTES // (1024 * 1024)} MiB limit. Remove large files or move the skills to a smaller repository.",
                    )
                archive_chunks.append(chunk)
        except requests.RequestException as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "The GitHub repository download was interrupted. Try again.",
            ) from exc

    try:
        archive = tarfile.open(
            fileobj=io.BytesIO(b"".join(archive_chunks)), mode="r:gz"
        )
    except tarfile.TarError as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub returned an unreadable repository download. Try again.",
        ) from exc

    files: dict[str, bytes] = {}
    total_size = 0
    with archive:
        for member_index, member in enumerate(archive, start=1):
            if member_index > _ARCHIVE_MAX_MEMBERS:
                raise OnyxError(
                    OnyxErrorCode.PAYLOAD_TOO_LARGE,
                    f"Repository archive contains more than {_ARCHIVE_MAX_MEMBERS:,} entries. Use a smaller repository and try again.",
                )
            member_path = member.name.rstrip("/") if member.isdir() else member.name
            path_parts = member_path.split("/")
            if (
                not member_path
                or member_path.startswith("/")
                or "\\" in member_path
                or any(part in {"", ".", ".."} for part in path_parts)
            ):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Repository contains unsupported path '{member.name}'. Remove or rename it and try again.",
                )
            if member.isdir():
                continue
            if not member.isfile():
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Repository contains a symbolic link at '{member.name}'. Replace it with a regular file and try again.",
                )
            if member.size > DEFAULT_PER_FILE_MAX_BYTES:
                raise OnyxError(
                    OnyxErrorCode.PAYLOAD_TOO_LARGE,
                    f"Repository file '{member.name}' exceeds the {DEFAULT_PER_FILE_MAX_BYTES // (1024 * 1024)} MiB limit. Reduce or remove the file and try again.",
                )
            total_size += member.size
            if total_size > DEFAULT_TOTAL_MAX_BYTES:
                raise OnyxError(
                    OnyxErrorCode.PAYLOAD_TOO_LARGE,
                    f"Repository exceeds the {DEFAULT_TOTAL_MAX_BYTES // (1024 * 1024)} MiB uncompressed limit. Remove large files or move the skills to a smaller repository.",
                )
            extracted = archive.extractfile(member)
            if extracted is None:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    f"Could not read repository file '{member.name}'. Try again.",
                )
            if member.name in files:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Repository contains duplicate path '{member.name}'. Remove the duplicate and try again.",
                )
            files[member.name] = extracted.read(DEFAULT_PER_FILE_MAX_BYTES + 1)

    root_directories = {path.split("/", maxsplit=1)[0] for path in files}
    if len(root_directories) != 1:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub returned an unexpected repository download. Enter a standard GitHub repository URL and try again.",
        )
    files = {
        path.split("/", maxsplit=1)[1]: content
        for path, content in files.items()
        if "/" in path
    }

    if search_prefix and not any(
        path == search_prefix or path.startswith(f"{search_prefix}/") for path in files
    ):
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Repository folder not found. Check the GitHub URL and try again.",
        )

    skill_md_paths = sorted(
        path
        for path in files
        if PurePosixPath(path).name == SKILL_MD_NAME
        and (
            not search_prefix
            or path.startswith(f"{search_prefix}/")
            or path == search_prefix
        )
    )
    if not skill_md_paths:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "No SKILL.md files were found in this repository. Add a SKILL.md file, then try again.",
        )

    skills: list[GitHubSkillBundle] = []
    for skill_md_path in skill_md_paths:
        skill_directory = str(PurePosixPath(skill_md_path).parent)
        if skill_directory == ".":
            skill_directory = ""
        try:
            name, description = parse_skill_md_metadata(files[skill_md_path])
        except OnyxError as exc:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Invalid SKILL.md at '{skill_md_path}': {exc.detail}",
            ) from exc

        slug = slug_from_skill_name(name)
        if slug in BUILT_IN_SKILLS:
            skills.append(
                GitHubSkillBundle(
                    path=skill_directory or ".",
                    slug=slug,
                    name=name,
                    description=description,
                    bundle_bytes=None,
                    unavailable_reason=(
                        f"Can't import: '{slug}' is a reserved skill name in Onyx."
                    ),
                )
            )
            continue

        output = io.BytesIO()
        with zipfile.ZipFile(
            output, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as bundle:
            prefix = f"{skill_directory}/" if skill_directory else ""
            for path, content in files.items():
                if prefix and not path.startswith(prefix):
                    continue
                relative_path = path.removeprefix(prefix)
                if not relative_path or relative_path.endswith(TEMPLATE_SUFFIX):
                    continue
                if "__pycache__" in PurePosixPath(relative_path).parts:
                    continue
                bundle.writestr(relative_path, content)

        skills.append(
            GitHubSkillBundle(
                path=skill_directory or ".",
                slug=slug,
                name=name,
                description=description,
                bundle_bytes=validate_and_normalize_custom_bundle(
                    output.getvalue(), slug=slug
                ),
            )
        )
    return repository, skills
