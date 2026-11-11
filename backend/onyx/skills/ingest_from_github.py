"""Fetch and discover skill bundles in GitHub repository archives."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import Final

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
from onyx.skills.models import (
    GITHUB_SKILL_MAX_COUNT,
    GitHubRepository,
    GitHubSkillBundle,
)
from onyx.utils.github import (
    download_github_archive,
    parse_github_source,
    resolve_github_revision,
)

_ARCHIVE_MAX_BYTES: Final[int] = 25 * 1024 * 1024
_ARCHIVE_MAX_MEMBERS: Final[int] = 10_000


def fetch_github_skill_bundles(
    source: str,
    authorization_header: str | None = None,
    *,
    revision: str | None = None,
    subpath: str | None = None,
    selected_paths: set[str] | None = None,
) -> tuple[GitHubRepository, list[GitHubSkillBundle]]:
    """Fetch one immutable repository revision and discover its skills."""
    github_source = parse_github_source(source, allow_tree_path=True)
    resolved_source = resolve_github_revision(
        github_source,
        authorization_header,
        revision=revision,
        subpath=subpath,
    )
    archive_bytes = download_github_archive(
        github_source,
        resolved_source.revision,
        authorization_header,
        max_size_bytes=_ARCHIVE_MAX_BYTES,
    )

    files: dict[str, bytes] = {}
    total_size = 0
    try:
        # typeshed does not yet expose Python 3.13's stream parameter.
        with tarfile.open(  # ty: ignore[no-matching-overload]
            fileobj=io.BytesIO(archive_bytes),
            mode="r:gz",
            stream=True,
        ) as archive:
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
    search_prefix = resolved_source.subpath or ""
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
    if len(skill_md_paths) > GITHUB_SKILL_MAX_COUNT:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"Repository contains more than {GITHUB_SKILL_MAX_COUNT} skills. Import from a smaller repository or folder.",
        )

    skill_directories = {
        ""
        if str(PurePosixPath(path).parent) == "."
        else str(PurePosixPath(path).parent)
        for path in skill_md_paths
    }
    selected_directories = (
        skill_directories
        if selected_paths is None
        else {
            directory
            for directory in skill_directories
            if (directory or ".") in selected_paths
        }
    )
    files_by_skill: dict[str, dict[str, bytes]] = {
        directory: {} for directory in selected_directories
    }
    for path, content in files.items():
        parent = str(PurePosixPath(path).parent)
        parent = "" if parent == "." else parent
        while True:
            if parent in skill_directories:
                if parent in files_by_skill:
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
        if skill_directory not in selected_directories:
            continue
        expected_name = (
            PurePosixPath(skill_directory).name
            if skill_directory
            else github_source.repo
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
            owner=github_source.owner,
            repo=github_source.repo,
            revision=resolved_source.revision,
            subpath=resolved_source.subpath,
        ),
        skills,
    )
