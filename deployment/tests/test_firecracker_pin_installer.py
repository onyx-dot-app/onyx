from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "deployment/firecracker/install-pinned-firecracker.sh"
VERSION = "v1.17.0"
ARCH = "x86_64"


def _write_fake_binary(path: Path, name: str, version: str) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "${1:-}" = "--version" ]; then\n'
        f'  echo "{name} {version}"\n'
        "else\n"
        f'  echo "{name} test binary"\n'
        "fi\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_archive(
    tmp_path: Path,
    *,
    firecracker_version: str = VERSION,
    jailer_version: str = VERSION,
) -> tuple[Path, str]:
    release_dir = tmp_path / f"release-{VERSION}-{ARCH}"
    release_dir.mkdir()
    _write_fake_binary(
        release_dir / f"firecracker-{VERSION}-{ARCH}",
        "Firecracker",
        firecracker_version,
    )
    _write_fake_binary(
        release_dir / f"jailer-{VERSION}-{ARCH}",
        "Jailer",
        jailer_version,
    )

    archive = tmp_path / f"firecracker-{VERSION}-{ARCH}.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(release_dir, arcname=release_dir.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, digest


def _run_installer(
    command: str,
    archive: Path,
    install_dir: Path,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "ONYX_FIRECRACKER_ARCH": ARCH,
            "ONYX_FIRECRACKER_ARCHIVE_URL": archive.as_uri(),
            "ONYX_FIRECRACKER_INSTALL_DIR": str(install_dir),
        }
    )
    return subprocess.run(
        [str(INSTALLER), command],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_constants_keep_official_pin_when_checksum_env_is_set(
    tmp_path: Path,
) -> None:
    archive, _ = _make_archive(tmp_path)
    install_dir = tmp_path / "kata-bin"
    install_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "ONYX_FIRECRACKER_ARCH": ARCH,
            "ONYX_FIRECRACKER_ARCHIVE_URL": archive.as_uri(),
            "ONYX_FIRECRACKER_ARCHIVE_SHA256": "0" * 64,
            "ONYX_FIRECRACKER_INSTALL_DIR": str(install_dir),
        }
    )

    result = subprocess.run(
        [str(INSTALLER), "constants"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "FIRECRACKER_X86_64_TGZ_SHA256="
        "06094a1108ae9e82aa4c23a775aa92758f53f1175d422270d9d6162cb9ade558"
    ) in result.stdout
    assert "ONYX_FIRECRACKER_ARCHIVE_SHA256" not in result.stdout


def test_rejects_archive_checksum_mismatch(tmp_path: Path) -> None:
    archive, _ = _make_archive(tmp_path)
    install_dir = tmp_path / "kata-bin"
    install_dir.mkdir()

    result = _run_installer("install", archive, install_dir)

    assert result.returncode != 0
    assert "FAILED" in result.stdout


def test_rejects_installed_binary_version_mismatch(tmp_path: Path) -> None:
    archive, _ = _make_archive(tmp_path)
    install_dir = tmp_path / "kata-bin"
    install_dir.mkdir()
    _write_fake_binary(install_dir / "firecracker", "Firecracker", "v1.16.0")
    _write_fake_binary(install_dir / "jailer", "Jailer", VERSION)

    result = _run_installer("verify-installed-version", archive, install_dir)

    assert result.returncode != 0
    assert (
        "reported 'Firecracker v1.16.0', expected 'Firecracker v1.17.0'"
        in result.stderr
    )


def test_rejects_missing_installed_jailer(tmp_path: Path) -> None:
    archive, _ = _make_archive(tmp_path)
    install_dir = tmp_path / "kata-bin"
    install_dir.mkdir()
    _write_fake_binary(install_dir / "firecracker", "Firecracker", VERSION)

    result = _run_installer("verify-installed-version", archive, install_dir)

    assert result.returncode != 0
    assert "Firecracker jailer is not executable" in result.stderr


def test_live_process_verifier_hashes_actual_proc_exe() -> None:
    helper = INSTALLER.read_text()

    assert 'sha256sum "${exe_path}"' in helper
    assert "/proc/${pid}/root/firecracker" not in helper
    assert "matched=1" not in helper
    assert '" (deleted)"' in helper
