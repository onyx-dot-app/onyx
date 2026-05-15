"""Tests for the _build_targz function in kubernetes_sandbox_manager.py."""

import hashlib
import io
import tarfile

import pytest

from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    _build_targz,
)
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet


def test_round_trip() -> None:
    files: FileSet = {
        "hello.txt": b"hello world",
        "sub/dir/deep.py": b"print('deep')",
        "empty": b"",
    }
    raw, sha = _build_targz(files)

    # Extract and verify
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        members = tar.getmembers()
        extracted: dict[str, bytes] = {}
        for m in members:
            f = tar.extractfile(m)
            if f is not None:
                extracted[m.name] = f.read()

    for name, data in files.items():
        assert name in extracted, f"Missing entry: {name}"
        assert extracted[name] == data, f"Content mismatch for {name}"


def test_deterministic() -> None:
    files: FileSet = {
        "b.txt": b"bbb",
        "a.txt": b"aaa",
        "c.txt": b"ccc",
    }
    raw1, sha1 = _build_targz(files)
    raw2, sha2 = _build_targz(files)

    assert raw1 == raw2
    assert sha1 == sha2


def test_sorted_entries() -> None:
    files: FileSet = {
        "zebra.txt": b"z",
        "alpha.txt": b"a",
        "middle.txt": b"m",
    }
    raw, _ = _build_targz(files)

    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        names = [m.name for m in tar.getmembers()]

    assert names == sorted(names)


def test_empty_dict() -> None:
    raw, sha = _build_targz({})

    # Should be a valid tar.gz with no entries
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        assert tar.getmembers() == []

    # SHA should still be valid
    assert sha == hashlib.sha256(raw).hexdigest()


def test_oversized_bundle_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager._MAX_BUNDLE_BYTES",
        100,
    )
    files: FileSet = {"big.bin": b"x" * 200}
    with pytest.raises(FatalWriteError, match="exceeds"):
        _build_targz(files)
