"""Unit tests for the outputs artifact classifier.

The classifier decides what the panel presents as deliverables, so its
top-level-only reduction, the webapp convention, and the hidden-name rule are
all load-bearing, and directory hashes must move exactly when visible content
moves.
"""

import pytest

from onyx.db.enums import ArtifactType
from onyx.server.features.build.artifact_classifier import (
    DerivedArtifact,
    OutputEntry,
    classify_file,
    derive_artifacts,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("deck.pptx", ArtifactType.PPTX),
        ("legacy.ppt", ArtifactType.PPTX),
        ("report.DOCX", ArtifactType.DOCX),
        ("sheet.xlsx", ArtifactType.EXCEL),
        ("macro.xlsm", ArtifactType.EXCEL),
        ("paper.pdf", ArtifactType.PDF),
        ("rows.csv", ArtifactType.CSV),
        ("notes.md", ArtifactType.MARKDOWN),
        ("logo.png", ArtifactType.IMAGE),
        ("LOGO.PNG", ArtifactType.IMAGE),
        ("icon.svg", ArtifactType.IMAGE),
        ("song.mp3", ArtifactType.AUDIO),
        ("clip.mp4", ArtifactType.VIDEO),
        ("bundle.zip", ArtifactType.ARCHIVE),
        ("bundle.tar", ArtifactType.ARCHIVE),
        ("bundle.tar.gz", ArtifactType.ARCHIVE),
        ("script.py", ArtifactType.CODE),
        ("page.html", ArtifactType.CODE),
        ("data.json", ArtifactType.CODE),
        ("view.tsx", ArtifactType.CODE),
        # .ts is registered as video/mp2t, the code set must win.
        ("main.ts", ArtifactType.CODE),
        # Legacy binary formats with no product surface stay generic.
        ("old.doc", ArtifactType.FILE),
        ("mystery.xyz", ArtifactType.FILE),
        ("no_extension", ArtifactType.FILE),
    ],
)
def test_classify_file(name: str, expected: ArtifactType) -> None:
    assert classify_file(name) == expected


def test_top_level_entries_become_artifacts_nested_do_not() -> None:
    artifacts = derive_artifacts(
        [
            OutputEntry("deck.pptx", False, size=10, sha256="a" * 64),
            OutputEntry("report", True),
            OutputEntry("report/final.pdf", False, size=5, sha256="b" * 64),
        ]
    )
    assert [a.path for a in artifacts] == ["deck.pptx", "report"]
    deck, report = artifacts
    assert deck == DerivedArtifact(
        path="deck.pptx",
        name="deck.pptx",
        type=ArtifactType.PPTX,
        size_bytes=10,
        content_hash="a" * 64,
    )
    assert report.type == ArtifactType.DIRECTORY
    assert report.size_bytes == 5
    assert report.content_hash is not None


def test_deep_nesting_collapses_into_the_top_level_directory() -> None:
    artifacts = derive_artifacts(
        [
            OutputEntry("a", True),
            OutputEntry("a/b", True),
            OutputEntry("a/b/c", True),
            OutputEntry("a/b/c/d.txt", False, size=7, sha256="a" * 64),
            OutputEntry("a/top.txt", False, size=3, sha256="b" * 64),
        ]
    )
    assert [a.path for a in artifacts] == ["a"]
    assert artifacts[0].size_bytes == 10


def test_directory_hash_tracks_visible_content() -> None:
    base = [
        OutputEntry("report", True),
        OutputEntry("report/final.pdf", False, size=5, sha256="b" * 64),
    ]
    changed_hash = [
        OutputEntry("report", True),
        OutputEntry("report/final.pdf", False, size=5, sha256="c" * 64),
    ]
    renamed_child = [
        OutputEntry("report", True),
        OutputEntry("report/renamed.pdf", False, size=5, sha256="b" * 64),
    ]
    added_file = base + [
        OutputEntry("report/extra.txt", False, size=1, sha256="d" * 64)
    ]
    hidden_churn = base + [
        OutputEntry("report/node_modules", True),
        OutputEntry("report/node_modules/x.js", False, size=9, sha256="e" * 64),
    ]

    def one(entries: list[OutputEntry]) -> DerivedArtifact:
        (artifact,) = derive_artifacts(entries)
        return artifact

    assert one(base).content_hash != one(changed_hash).content_hash
    assert one(base).content_hash != one(renamed_child).content_hash
    assert one(base).content_hash != one(added_file).content_hash
    assert one(base).content_hash == one(hidden_churn).content_hash
    assert one(base).size_bytes == one(hidden_churn).size_bytes


def test_identical_trees_hash_identically() -> None:
    artifacts = derive_artifacts(
        [
            OutputEntry("first", True),
            OutputEntry("first/x.txt", False, size=2, sha256="a" * 64),
            OutputEntry("second", True),
            OutputEntry("second/x.txt", False, size=2, sha256="a" * 64),
        ]
    )
    assert artifacts[0].content_hash == artifacts[1].content_hash


def test_hidden_only_directory_hashes_like_an_empty_one() -> None:
    artifacts = derive_artifacts(
        [
            OutputEntry("empty", True),
            OutputEntry("shell", True),
            OutputEntry("shell/node_modules", True),
            OutputEntry("shell/node_modules/x.js", False, size=9, sha256="a" * 64),
        ]
    )
    empty, shell = artifacts
    assert empty.content_hash == shell.content_hash
    assert shell.size_bytes == 0


def test_unhashed_file_signals_size_and_mtime_changes() -> None:
    def top(entry: OutputEntry) -> str | None:
        (artifact,) = derive_artifacts([entry])
        return artifact.content_hash

    base = OutputEntry("big.bin", False, size=10, mtime_ns=1, sha256=None)
    assert top(base) is not None
    assert top(base) == top(OutputEntry("big.bin", False, size=10, mtime_ns=1))
    assert top(base) != top(OutputEntry("big.bin", False, size=20, mtime_ns=1))
    assert top(base) != top(OutputEntry("big.bin", False, size=10, mtime_ns=2))
    assert top(OutputEntry("big.bin", False)) is None

    # Partial metadata degrades to what is present, never to no signal.
    assert top(OutputEntry("big.bin", False, size=10)) != top(
        OutputEntry("big.bin", False, size=20)
    )
    assert top(OutputEntry("big.bin", False, mtime_ns=1)) != top(
        OutputEntry("big.bin", False, mtime_ns=2)
    )

    # The same surrogate drives the directory hash for nested unhashed files.
    def nested(entry: OutputEntry) -> str | None:
        return derive_artifacts([OutputEntry("d", True), entry])[0].content_hash

    assert nested(OutputEntry("d/big.bin", False, size=10, mtime_ns=1)) != nested(
        OutputEntry("d/big.bin", False, size=10, mtime_ns=2)
    )


def test_webapp_detected_by_scaffold_convention() -> None:
    artifacts = derive_artifacts(
        [
            OutputEntry("web", True),
            OutputEntry("web/package.json", False, size=100, sha256="a" * 64),
            OutputEntry("web/app", True),
        ]
    )
    assert [a.type for a in artifacts] == [ArtifactType.WEB_APP]


def test_web_directory_without_package_json_is_a_directory() -> None:
    artifacts = derive_artifacts(
        [
            OutputEntry("web", True),
            OutputEntry("web/index.html", False, size=10, sha256="a" * 64),
        ]
    )
    assert [a.type for a in artifacts] == [ArtifactType.DIRECTORY]


def test_webapp_convention_is_exact() -> None:
    artifacts = derive_artifacts(
        [
            # A nested web directory is not the scaffold.
            OutputEntry("sub", True),
            OutputEntry("sub/web", True),
            OutputEntry("sub/web/package.json", False, size=1, sha256="a" * 64),
            # Nor is a package.json that is itself a directory.
            OutputEntry("web", True),
            OutputEntry("web/package.json", True),
        ]
    )
    assert [(a.path, a.type) for a in artifacts] == [
        ("sub", ArtifactType.DIRECTORY),
        ("web", ArtifactType.DIRECTORY),
    ]


def test_hidden_names_never_surface() -> None:
    artifacts = derive_artifacts(
        [
            OutputEntry(".DS_Store", False, size=1, sha256="a" * 64),
            OutputEntry(".secrets", True),
            OutputEntry(".secrets/key.pem", False, size=1, sha256="b" * 64),
            OutputEntry("node_modules", True),
            OutputEntry("real.txt", False, size=1, sha256="c" * 64),
        ]
    )
    assert [a.path for a in artifacts] == ["real.txt"]


def test_output_is_sorted_regardless_of_input_order() -> None:
    artifacts = derive_artifacts(
        [
            OutputEntry("zeta.txt", False, size=1, sha256="a" * 64),
            OutputEntry("mid", True),
            OutputEntry("alpha.txt", False, size=1, sha256="b" * 64),
        ]
    )
    assert [a.path for a in artifacts] == ["alpha.txt", "mid", "zeta.txt"]


def test_empty_listing_yields_no_artifacts() -> None:
    assert derive_artifacts([]) == []
