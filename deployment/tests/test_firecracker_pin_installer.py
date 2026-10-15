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
OFFICIAL_X86_64_SHA256 = (
    "06094a1108ae9e82aa4c23a775aa92758f53f1175d422270d9d6162cb9ade558"
)


def _write_fake_binary(path: Path, name: str, version: str) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ -n "${ONYX_TEST_EXECUTABLE_DIR:-}" ]; then\n'
        '  case "$0" in\n'
        '    "${ONYX_TEST_EXECUTABLE_DIR}/"*) ;;\n'
        "    *)\n"
        '      echo "test execution policy denied $0" >&2\n'
        "      exit 126\n"
        "      ;;\n"
        "  esac\n"
        "fi\n"
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
    *,
    installer: Path = INSTALLER,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "ONYX_FIRECRACKER_ARCH": ARCH,
            "ONYX_FIRECRACKER_ARCHIVE_URL": archive.as_uri(),
            "ONYX_FIRECRACKER_INSTALL_DIR": str(install_dir),
        }
    )
    if environment is not None:
        env.update(environment)
    return subprocess.run(
        [str(installer), command],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _installer_with_fixture_checksum(tmp_path: Path, checksum: str) -> Path:
    source = INSTALLER.read_text()
    fixture_source = source.replace(
        f'FIRECRACKER_X86_64_TGZ_SHA256="{OFFICIAL_X86_64_SHA256}"',
        f'FIRECRACKER_X86_64_TGZ_SHA256="{checksum}"',
    )
    assert fixture_source != source
    installer = tmp_path / "fixture-installer.sh"
    installer.write_text(fixture_source)
    installer.chmod(0o755)
    return installer


def test_installs_when_ambient_temp_directory_cannot_execute(tmp_path: Path) -> None:
    archive, checksum = _make_archive(tmp_path)
    installer = _installer_with_fixture_checksum(tmp_path, checksum)
    install_dir = tmp_path / "kata-bin"
    install_dir.mkdir()
    restricted_tmp = tmp_path / "restricted-tmp"
    restricted_tmp.mkdir()

    result = _run_installer(
        "install",
        archive,
        install_dir,
        installer=installer,
        environment={
            "TMPDIR": str(restricted_tmp),
            "ONYX_TEST_EXECUTABLE_DIR": str(install_dir),
        },
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "firecracker").read_bytes() == (
        tmp_path / f"release-{VERSION}-{ARCH}/firecracker-{VERSION}-{ARCH}"
    ).read_bytes()
    assert (install_dir / "jailer").read_bytes() == (
        tmp_path / f"release-{VERSION}-{ARCH}/jailer-{VERSION}-{ARCH}"
    ).read_bytes()
    assert stat.S_IMODE((install_dir / "firecracker").stat().st_mode) == 0o755
    assert stat.S_IMODE((install_dir / "jailer").stat().st_mode) == 0o755
    assert sorted(path.name for path in install_dir.iterdir()) == [
        "firecracker",
        "jailer",
    ]
    assert list(restricted_tmp.iterdir()) == []


def test_rejects_verified_wrong_version_before_replacing_binaries(
    tmp_path: Path,
) -> None:
    archive, checksum = _make_archive(tmp_path, firecracker_version="v1.16.0")
    installer = _installer_with_fixture_checksum(tmp_path, checksum)
    install_dir = tmp_path / "kata-bin"
    install_dir.mkdir()
    _write_fake_binary(install_dir / "firecracker", "Firecracker", VERSION)
    _write_fake_binary(install_dir / "jailer", "Jailer", VERSION)
    original_firecracker = (install_dir / "firecracker").read_bytes()
    original_jailer = (install_dir / "jailer").read_bytes()

    result = _run_installer("install", archive, install_dir, installer=installer)

    assert result.returncode != 0
    assert (
        "reported 'Firecracker v1.16.0', expected 'Firecracker v1.17.0'"
        in result.stderr
    )
    assert (install_dir / "firecracker").read_bytes() == original_firecracker
    assert (install_dir / "jailer").read_bytes() == original_jailer


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
