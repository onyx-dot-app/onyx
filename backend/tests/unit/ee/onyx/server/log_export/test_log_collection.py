import os
import zipfile
from pathlib import Path

import pytest

from ee.onyx.server.log_export.collection import README_FILE_NAME, build_log_zip

SCOPE_NOTE = "Scope: test scope note."


def _zip_names(zip_file: zipfile.ZipFile) -> list[str]:
    return zip_file.namelist()


def _entry_ending_with(zip_file: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in _zip_names(zip_file) if name.endswith(suffix)]
    assert len(matches) == 1, f"Expected exactly one entry ending with {suffix!r}."
    return matches[0]


def test_collects_log_files_recursively(tmp_path: Path) -> None:
    (tmp_path / "onyx_debug.log").write_text("debug line\n")
    (tmp_path / "onyx_debug.log.1").write_text("rotated line\n")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "memory_usage.log").write_text("memory line\n")
    (tmp_path / "notes.txt").write_text("not a log\n")

    with build_log_zip([tmp_path], SCOPE_NOTE) as zip_buffer:
        with zipfile.ZipFile(zip_buffer) as zip_file:
            names = _zip_names(zip_file)
            assert README_FILE_NAME in names
            # README plus the three log files; ``notes.txt`` is excluded.
            assert len(names) == 4
            assert not any(name.endswith("notes.txt") for name in names)

            debug_entry = _entry_ending_with(zip_file, "onyx_debug.log")
            assert zip_file.read(debug_entry) == b"debug line\n"
            _entry_ending_with(zip_file, "onyx_debug.log.1")
            memory_entry = _entry_ending_with(zip_file, "memory_usage.log")
            assert "memory" in memory_entry

            readme = zip_file.read(README_FILE_NAME).decode("utf-8")
            assert SCOPE_NOTE in readme
            assert "onyx_debug.log" in readme
            assert "WARNING" in readme


def test_empty_directory_yields_readme_only(tmp_path: Path) -> None:
    with build_log_zip([tmp_path], SCOPE_NOTE) as zip_buffer:
        with zipfile.ZipFile(zip_buffer) as zip_file:
            assert _zip_names(zip_file) == [README_FILE_NAME]
            readme = zip_file.read(README_FILE_NAME).decode("utf-8")
            assert "No log files were found" in readme


def test_missing_directory_yields_readme_only(tmp_path: Path) -> None:
    with build_log_zip([tmp_path / "does_not_exist"], SCOPE_NOTE) as zip_buffer:
        with zipfile.ZipFile(zip_buffer) as zip_file:
            assert _zip_names(zip_file) == [README_FILE_NAME]


def test_overlapping_directories_deduplicate(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "worker.log").write_text("worker line\n")

    with build_log_zip([tmp_path, nested], SCOPE_NOTE) as zip_buffer:
        with zipfile.ZipFile(zip_buffer) as zip_file:
            names = _zip_names(zip_file)
            assert len(names) == 2
            _entry_ending_with(zip_file, "worker.log")


def test_symlink_escaping_log_directory_is_skipped(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "real.log").write_text("real line\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("not a log\n")
    (log_dir / "evil.log").symlink_to(secret)

    with build_log_zip([log_dir], SCOPE_NOTE) as zip_buffer:
        with zipfile.ZipFile(zip_buffer) as zip_file:
            names = _zip_names(zip_file)
            # README plus ``real.log``; the escaping symlink is dropped.
            assert len(names) == 2
            _entry_ending_with(zip_file, "real.log")
            assert not any("evil" in name or "secret" in name for name in names)


def test_symlink_within_log_directory_is_included(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("aliased content\n")
    (tmp_path / "alias.log").symlink_to(target)

    with build_log_zip([tmp_path], SCOPE_NOTE) as zip_buffer:
        with zipfile.ZipFile(zip_buffer) as zip_file:
            # The entry is stored under its resolved path, hence ``target.txt``.
            entry = _entry_ending_with(zip_file, "target.txt")
            assert zip_file.read(entry) == b"aliased content\n"


@pytest.mark.skipif(os.geteuid() == 0, reason="Root can read mode-000 files")
def test_unreadable_file_is_skipped_and_noted(tmp_path: Path) -> None:
    readable = tmp_path / "readable.log"
    readable.write_text("fine\n")
    unreadable = tmp_path / "unreadable.log"
    unreadable.write_text("secret\n")
    unreadable.chmod(0o000)

    try:
        with build_log_zip([tmp_path], SCOPE_NOTE) as zip_buffer:
            with zipfile.ZipFile(zip_buffer) as zip_file:
                names = _zip_names(zip_file)
                assert not any(name.endswith("unreadable.log") for name in names)
                _entry_ending_with(zip_file, "readable.log")

                readme = zip_file.read(README_FILE_NAME).decode("utf-8")
                assert "Skipped files" in readme
                assert "unreadable.log" in readme
    finally:
        unreadable.chmod(0o644)
