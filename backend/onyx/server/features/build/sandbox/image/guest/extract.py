import io
import os
import re
import shutil
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MiB per entry
MAX_BUNDLE_BYTES = 100 * 1024 * 1024  # 100 MiB total uncompressed
ALLOWED_PREFIX = "/workspace/managed/"
OLD_DIR_GRACE_SECONDS = 60


def _validate_member(member: tarfile.TarInfo, bundle_root: str) -> None:
    try:
        member.name.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"Non-UTF-8 path name: {member.name!r}")

    if member.issym() or member.islnk():
        raise ValueError(f"Links not allowed: {member.name}")

    if not (member.isreg() or member.isdir()):
        raise ValueError(f"Special file not allowed: {member.name}")

    resolved = os.path.normpath(os.path.join(bundle_root, member.name))
    if not resolved.startswith(
        os.path.normpath(bundle_root) + os.sep
    ) and resolved != os.path.normpath(bundle_root):
        raise ValueError(f"Path traversal detected: {member.name}")

    if os.path.isabs(member.name):
        raise ValueError(f"Absolute path not allowed: {member.name}")

    if member.isreg() and member.size > MAX_FILE_BYTES:
        raise ValueError(
            f"Entry too large: {member.name} ({member.size} > {MAX_FILE_BYTES})"
        )


def _prune_versions(parent: Path, versions_dir: Path) -> None:
    active = {child.resolve() for child in parent.iterdir() if child.is_symlink()}
    cutoff = time.time() - OLD_DIR_GRACE_SECONDS
    for version in versions_dir.iterdir():
        if (
            not version.is_symlink()
            and version.is_dir()
            and version not in active
            and version.stat().st_mtime < cutoff
        ):
            shutil.rmtree(version)


def safe_extract_then_atomic_swap(tar_gz_bytes: bytes, mount_path: str) -> None:
    if not re.fullmatch(
        re.escape(ALLOWED_PREFIX)
        + r"(?:skills|user_library|document-preview/[A-Za-z0-9_-]+)",
        mount_path,
    ):
        raise ValueError("unsupported managed mount path")
    mount = Path(mount_path)
    parent = mount.parent
    parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    versions_dir = parent / ".versions"
    sha_prefix = os.urandom(4).hex()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    version_name = f"{timestamp}-{sha_prefix}"
    dest = versions_dir / version_name

    if not str(dest.resolve()).startswith(ALLOWED_PREFIX):
        raise ValueError(
            f"mount_path resolves outside {ALLOWED_PREFIX}: {dest.resolve()}"
        )

    os.makedirs(dest, exist_ok=True)

    try:
        total_size = 0
        with tarfile.open(fileobj=io.BytesIO(tar_gz_bytes), mode="r:gz") as tar:
            for member in tar.getmembers():
                _validate_member(member, str(dest))

                if member.isreg():
                    total_size += member.size
                    if total_size > MAX_BUNDLE_BYTES:
                        raise ValueError(
                            f"Total uncompressed size exceeds {MAX_BUNDLE_BYTES}"
                        )

                final_path = Path(
                    os.path.normpath(os.path.join(str(dest), member.name))
                )
                if not str(final_path).startswith(ALLOWED_PREFIX):
                    raise ValueError(f"Extracted path escapes allow-list: {final_path}")

                if member.isdir():
                    os.makedirs(final_path, exist_ok=True)
                    os.chmod(final_path, 0o755)  # noqa: S103 -- root-owned readable bundles
                elif member.isreg():
                    os.makedirs(str(final_path.parent), exist_ok=True)
                    src = tar.extractfile(member)
                    if src is None:
                        raise ValueError(f"Cannot read entry: {member.name}")
                    with open(final_path, "wb") as f:
                        f.write(src.read())
                    # 0o755 mask strips setuid (4000), setgid (2000), sticky (1000), and group/other write (022)
                    os.chmod(final_path, (member.mode or 0o644) & 0o755)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    tmp_link = f"{mount}.tmp.{os.getpid()}.{os.urandom(4).hex()}"
    os.symlink(str(dest), tmp_link)
    try:
        os.rename(tmp_link, str(mount))
    except OSError:
        os.unlink(tmp_link)
        raise

    _prune_versions(parent, versions_dir)
