"""Read GitHub repository downloads."""

import io
import tarfile
from typing import Final

from pydantic import BaseModel, ConfigDict

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES

GITHUB_ARCHIVE_MAX_BYTES: Final[int] = 25 * 1024 * 1024
_ARCHIVE_MAX_MEMBERS: Final[int] = 10_000
# Each file is read up to the bundle file limit plus one byte, so a plugin
# with a larger file is refused by the bundle limits, not by this read. The
# limit counts each file's full size: the stream decompresses all of it.
_ARCHIVE_UNPACKED_MAX_BYTES: Final[int] = 256 * 1024 * 1024


class RepositoryArchive(BaseModel):
    model_config = ConfigDict(frozen=True)

    files: dict[str, bytes]
    # Paths of symbolic links. Onyx does not follow them; a plugin that holds
    # one is refused, other plugins of the repository are not.
    links: frozenset[str] = frozenset()


def read_repository_archive(archive_bytes: bytes) -> RepositoryArchive:
    """The files of a GitHub tar.gz download by repository path, without the
    folder GitHub wraps the repository in."""
    files: dict[str, bytes] = {}
    links: set[str] = set()
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
                if member.issym() or member.islnk():
                    links.add(member.name)
                    continue
                if not member.isfile():
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"Repository contains an unsupported file at '{member.name}'.",
                    )
                if member.name in files:
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"Repository contains duplicate path '{member.name}'.",
                    )
                total_size += member.size
                if total_size > _ARCHIVE_UNPACKED_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"Repository exceeds the {_ARCHIVE_UNPACKED_MAX_BYTES // (1024 * 1024)} MiB uncompressed limit.",
                    )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise OnyxError(
                        OnyxErrorCode.BAD_GATEWAY,
                        f"Could not read repository file '{member.name}'. Try again.",
                    )
                content = extracted.read(DEFAULT_PER_FILE_MAX_BYTES + 1)
                files[member.name] = content
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub returned an unreadable repository download. Try again.",
        ) from exc

    root_directories = {path.split("/", maxsplit=1)[0] for path in [*files, *links]}
    if len(root_directories) != 1:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub returned an unexpected repository download. Try again.",
        )
    return RepositoryArchive(
        files={
            path.split("/", maxsplit=1)[1]: content
            for path, content in files.items()
            if "/" in path
        },
        links=frozenset(
            path.split("/", maxsplit=1)[1] for path in links if "/" in path
        ),
    )
