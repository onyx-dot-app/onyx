"""Read GitHub repository downloads."""

import io
import tarfile
from typing import Final

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES

GITHUB_ARCHIVE_MAX_BYTES: Final[int] = 25 * 1024 * 1024
_ARCHIVE_MAX_MEMBERS: Final[int] = 10_000
# Each file is read up to the bundle file limit plus one byte, so a plugin
# with a larger file is refused by the bundle limits, not by this read.
_ARCHIVE_UNPACKED_MAX_BYTES: Final[int] = 256 * 1024 * 1024


def read_repository_archive(archive_bytes: bytes) -> dict[str, bytes]:
    """The files of a GitHub tar.gz download by repository path, without the
    folder GitHub wraps the repository in."""
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
                if member.name in files:
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"Repository contains duplicate path '{member.name}'.",
                    )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise OnyxError(
                        OnyxErrorCode.BAD_GATEWAY,
                        f"Could not read repository file '{member.name}'. Try again.",
                    )
                content = extracted.read(DEFAULT_PER_FILE_MAX_BYTES + 1)
                total_size += len(content)
                if total_size > _ARCHIVE_UNPACKED_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"Repository exceeds the {_ARCHIVE_UNPACKED_MAX_BYTES // (1024 * 1024)} MiB uncompressed limit.",
                    )
                files[member.name] = content
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
    return {
        path.split("/", maxsplit=1)[1]: content
        for path, content in files.items()
        if "/" in path
    }
