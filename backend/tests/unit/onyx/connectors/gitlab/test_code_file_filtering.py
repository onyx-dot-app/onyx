from __future__ import annotations

import pytest

from onyx.connectors.gitlab.connector import (
    _looks_like_binary,
    _should_exclude,
    exclude_patterns,
)


class TestShouldExclude:
    """Covers matcher behavior on the built-in DEFAULT_EXCLUDE_PATTERNS."""

    @pytest.mark.parametrize(
        "path",
        [
            # Vendored dependencies at any depth.
            "node_modules/react/index.js",
            "web/node_modules/react/index.js",
            "packages/foo/node_modules/lodash/index.js",
            "vendor/rails/activesupport.rb",
            "backend/vendor/gems/foo.rb",
            "bower_components/jquery/dist/jquery.js",
            # Build output.
            "dist/main.js",
            "web/dist/main.js",
            "backend/build/artifacts.tar",
            "target/release/foo",
            # Minified assets anywhere in the tree.
            "assets/bootstrap.min.js",
            "public/js/vendor.min.js",
            "web/static/app.min.css",
            "assets/main.min.map",
            # Generated protobuf / gRPC.
            "proto/gen/agent_services_pb.rb",
            "app/rpc/executable_services_pb.rb",
            "internal/gen/service.pb.go",
            "python_gen/foo_pb2.py",
            "python_gen/foo_pb2_grpc.py",
            # Lockfiles.
            "package-lock.json",
            "web/package-lock.json",
            "Gemfile.lock",
            "backend/Cargo.lock",
            # Binary/media assets.
            "assets/logo.png",
            "docs/screenshots/foo.jpg",
            "static/font.woff2",
            "media/intro.mp4",
            # Legacy single-name entries still work.
            "logs",
            ".pre-commit-config.yaml",
            # Legacy trailing-slash directory names match at any depth.
            ".github/workflows/ci.yml",
            "some/nested/.github/workflows/ci.yml",
            ".gitlab/merge_request_templates/foo.md",
        ],
    )
    def test_default_excludes_match(self, path: str) -> None:
        assert _should_exclude(path), f"expected {path!r} to be excluded"

    @pytest.mark.parametrize(
        "path",
        [
            # Actual source code.
            "app/models/user.rb",
            "app/controllers/api/v1/users_controller.rb",
            "src/components/Button.tsx",
            "backend/onyx/main.py",
            "internal/service/foo.go",
            # Files whose names contain but do not equal an excluded segment.
            "app/models/vendor_details.rb",  # "vendor_details" != "vendor"
            "docs/build_and_deploy.md",  # "build_and_deploy" != "build"
            # Non-min .js.
            "web/app.js",
            "web/app.map.js",  # trailing .js, not .map
            # README/Markdown.
            "README.md",
            "docs/architecture.md",
        ],
    )
    def test_source_files_not_excluded(self, path: str) -> None:
        assert not _should_exclude(path), f"expected {path!r} to be kept"

    def test_bare_directory_name_matches_at_any_depth(self) -> None:
        # Regression test: the previous fnmatch(path, "node_modules/*")
        # implementation did NOT match nested node_modules folders.
        assert _should_exclude("apps/web/node_modules/react/index.js")
        assert _should_exclude("node_modules/react/index.js")

    def test_slash_bearing_patterns_match_full_path(self) -> None:
        # "public/assets" is a slash-bearing pattern -> full-path match.
        assert _should_exclude("public/assets/main.css")
        # But should NOT match segment-wise: a top-level "assets" file is kept.
        assert not _should_exclude("assets/main.css")

    def test_operator_can_extend_via_module_attribute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate GITLAB_CONNECTOR_EXCLUDE_PATTERNS by appending directly to
        # the module-level list.
        monkeypatch.setattr(
            "onyx.connectors.gitlab.connector.exclude_patterns",
            exclude_patterns + ["secrets", "*.custom_ext"],
        )
        assert _should_exclude("secrets/db.yml")
        assert _should_exclude("app/config/foo.custom_ext")
        # Sanity: unrelated files still pass.
        assert not _should_exclude("app/models/user.rb")


class TestLooksLikeBinary:
    """Ensures we don't index arbitrary bytes as text via latin-1 fallback."""

    def test_empty_returns_false(self) -> None:
        assert not _looks_like_binary(b"")

    def test_plain_ascii_text_is_not_binary(self) -> None:
        assert not _looks_like_binary(b"def foo():\n    return 42\n")

    def test_utf8_text_is_not_binary(self) -> None:
        text = "def greet():\n    return 'héllo, 世界'\n"
        assert not _looks_like_binary(text.encode("utf-8"))

    def test_nul_byte_is_binary(self) -> None:
        assert _looks_like_binary(b"MZ\x00\x00\x00some bytes")

    def test_png_header_is_binary(self) -> None:
        # First few bytes of the PNG magic number plus IHDR chunk marker.
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 4
        assert _looks_like_binary(png)

    def test_dense_non_text_bytes_are_binary(self) -> None:
        # No NUL, but mostly control bytes -> should still be flagged.
        payload = bytes(b for b in range(1, 32) if b not in (9, 10, 12, 13)) * 100
        assert _looks_like_binary(payload)
