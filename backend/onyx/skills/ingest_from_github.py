"""Fetch and discover skill bundles in GitHub repository archives."""

from __future__ import annotations

import io
import re
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import Final
from urllib.parse import quote, unquote, urlparse

import requests

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import (
    DEFAULT_PER_FILE_MAX_BYTES,
    DEFAULT_TOTAL_MAX_BYTES,
    SKILL_MD_NAME,
    TEMPLATE_SUFFIX,
    normalize_custom_bundle,
)
from onyx.skills.metadata import parse_skill_document
from onyx.skills.models import GitHubRepository, GitHubSkillBundle
from onyx.utils.url import SSRFException, ssrf_safe_get

_ARCHIVE_MAX_BYTES: Final[int] = 25 * 1024 * 1024
_ARCHIVE_MAX_MEMBERS: Final[int] = 10_000
_FETCH_TIMEOUT_SECONDS: Final[int] = 30
_COMMIT_SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]{40}$")


def fetch_github_skill_bundles(
    source: str,
    authorization_header: str | None = None,
    *,
    revision: str | None = None,
    subpath: str | None = None,
) -> tuple[GitHubRepository, list[GitHubSkillBundle]]:
    """Fetch one immutable repository revision and discover its skills."""
    value = source.strip().rstrip("/")
    if not value:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Enter a GitHub repository URL or owner/repository.",
        )

    tree_tail: list[str] = []
    if "://" not in value:
        source_parts = value.removesuffix(".git").split("/")
        if len(source_parts) != 2 or not all(
            re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in source_parts
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Enter a GitHub repository URL or owner/repository.",
            )
        owner_name, repository_name = source_parts
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
        source_parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(source_parts) < 2:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Invalid GitHub repository URL.",
            )
        owner_name, repository_name = (
            source_parts[0],
            source_parts[1].removesuffix(".git"),
        )
        if len(source_parts) > 2:
            if len(source_parts) < 4 or source_parts[2] != "tree":
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Enter a repository URL or a URL for a folder within a repository.",
                )
            tree_tail = source_parts[3:]

    if not all(
        re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in (owner_name, repository_name)
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid GitHub repository URL.",
        )
    if revision is not None and not _COMMIT_SHA_PATTERN.fullmatch(revision):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid repository revision.",
        )
    search_prefix = subpath.rstrip("/") if subpath else ""
    if search_prefix and (
        "\\" in search_prefix
        or any(part in {"", ".", ".."} for part in search_prefix.split("/"))
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid repository folder.",
        )

    encoded_owner = quote(owner_name, safe="")
    encoded_repo = quote(repository_name, safe="")

    def github_get(
        url: str,
        *,
        authorization: str | None = None,
        stream: bool = False,
        follow_redirects: bool = True,
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
                timeout=_FETCH_TIMEOUT_SECONDS,
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

    resolved_revision = revision.lower() if revision is not None else None
    resolved_subpath = search_prefix or None
    if resolved_revision is None:
        ref_parts = tree_tail or ["HEAD"]
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
            response = github_get(commit_url)
            if response.status_code in {401, 403, 404, 429} and authorization_header:
                response.close()
                response = github_get(
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
                if not isinstance(sha, str) or not _COMMIT_SHA_PATTERN.fullmatch(sha):
                    raise OnyxError(
                        OnyxErrorCode.BAD_GATEWAY,
                        "GitHub returned an invalid repository revision. Try again.",
                    )
                resolved_revision = sha.lower()
                resolved_subpath = candidate_subpath
                break

        if resolved_revision is None:
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

    if resolved_revision is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Repository revision is missing.",
        )

    encoded_revision = quote(resolved_revision, safe="")
    archive_url = (
        f"https://codeload.github.com/{encoded_owner}/{encoded_repo}/"
        f"tar.gz/{encoded_revision}"
    )
    response = github_get(archive_url, stream=True)
    if response.status_code != 200 and authorization_header is not None:
        response.close()
        redirect_response = github_get(
            f"https://api.github.com/repos/{encoded_owner}/{encoded_repo}/"
            f"tarball/{encoded_revision}",
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
        response = github_get(archive_url, stream=True)

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
                archive_size += len(chunk)
                if archive_size > _ARCHIVE_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        "Repository download exceeds the 25 MiB limit. Remove large files or use a smaller repository.",
                    )
                archive_chunks.append(chunk)
        except requests.RequestException as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "The GitHub repository download was interrupted. Try again.",
            ) from exc

    try:
        archive = tarfile.open(
            fileobj=io.BytesIO(b"".join(archive_chunks)),
            mode="r:gz",
        )
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub returned an unreadable repository download. Try again.",
        ) from exc

    files: dict[str, bytes] = {}
    total_size = 0
    try:
        with archive:
            for member_index, member in enumerate(archive, start=1):
                if member_index > _ARCHIVE_MAX_MEMBERS:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"Repository archive contains more than {_ARCHIVE_MAX_MEMBERS:,} entries. Use a smaller repository.",
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
                        f"Repository contains unsupported path '{member.name}'.",
                    )
                if member.isdir():
                    continue
                if not member.isfile():
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"Repository contains a symbolic link at '{member.name}'. Replace it with a regular file.",
                    )
                if member.size > DEFAULT_PER_FILE_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"Repository file '{member.name}' exceeds the {DEFAULT_PER_FILE_MAX_BYTES // (1024 * 1024)} MiB limit.",
                    )
                total_size += member.size
                if total_size > DEFAULT_TOTAL_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"Repository exceeds the {DEFAULT_TOTAL_MAX_BYTES // (1024 * 1024)} MiB uncompressed limit.",
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
                        f"Repository contains duplicate path '{member.name}'.",
                    )
                files[member.name] = extracted.read(DEFAULT_PER_FILE_MAX_BYTES + 1)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub returned an unreadable repository download. Try again.",
        ) from exc

    root_directories = {path.split("/", maxsplit=1)[0] for path in files}
    if len(root_directories) != 1:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub returned an unexpected repository download. Try again.",
        )
    files = {
        path.split("/", maxsplit=1)[1]: content
        for path, content in files.items()
        if "/" in path
    }
    search_prefix = resolved_subpath or ""
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
            or path == f"{search_prefix}/{SKILL_MD_NAME}"
            or path.startswith(f"{search_prefix}/")
        )
    )
    if not skill_md_paths:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "No SKILL.md files were found. Add a skill to the repository and try again.",
        )

    skill_directories = {
        ""
        if str(PurePosixPath(path).parent) == "."
        else str(PurePosixPath(path).parent)
        for path in skill_md_paths
    }
    files_by_skill: dict[str, dict[str, bytes]] = {
        directory: {} for directory in skill_directories
    }
    for path, content in files.items():
        parent = str(PurePosixPath(path).parent)
        parent = "" if parent == "." else parent
        while True:
            if parent in skill_directories:
                prefix = f"{parent}/" if parent else ""
                files_by_skill[parent][path.removeprefix(prefix)] = content
                break
            if not parent:
                break
            next_parent = str(PurePosixPath(parent).parent)
            parent = "" if next_parent == "." else next_parent

    skills: list[GitHubSkillBundle] = []
    for skill_md_path in skill_md_paths:
        skill_directory = str(PurePosixPath(skill_md_path).parent)
        skill_directory = "" if skill_directory == "." else skill_directory
        expected_name = (
            PurePosixPath(skill_directory).name if skill_directory else repository_name
        )
        try:
            document = parse_skill_document(
                files[skill_md_path],
                directory_name=expected_name,
            )
        except OnyxError as exc:
            skills.append(
                GitHubSkillBundle(
                    path=skill_directory or ".",
                    name=expected_name,
                    description=None,
                    bundle_bytes=None,
                    unavailable_reason=f"Invalid SKILL.md: {exc.detail}",
                )
            )
            continue
        if document.metadata.name in BUILT_IN_SKILLS:
            skills.append(
                GitHubSkillBundle(
                    path=skill_directory or ".",
                    name=document.metadata.name,
                    description=document.metadata.description,
                    bundle_bytes=None,
                    unavailable_reason="A built-in Onyx skill already uses this name.",
                )
            )
            continue

        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as bundle:
            for relative_path, content in files_by_skill[skill_directory].items():
                if (
                    not relative_path
                    or relative_path.endswith(TEMPLATE_SUFFIX)
                    or "__pycache__" in PurePosixPath(relative_path).parts
                ):
                    continue
                bundle.writestr(relative_path, content)
        try:
            normalized_bundle = normalize_custom_bundle(output.getvalue()).content
        except OnyxError as exc:
            skills.append(
                GitHubSkillBundle(
                    path=skill_directory or ".",
                    name=document.metadata.name,
                    description=document.metadata.description,
                    bundle_bytes=None,
                    unavailable_reason=f"Invalid skill bundle: {exc.detail}",
                )
            )
            continue
        skills.append(
            GitHubSkillBundle(
                path=skill_directory or ".",
                name=document.metadata.name,
                description=document.metadata.description,
                bundle_bytes=normalized_bundle,
            )
        )

    return (
        GitHubRepository(
            owner=owner_name,
            repo=repository_name,
            revision=resolved_revision,
            subpath=resolved_subpath,
        ),
        skills,
    )
