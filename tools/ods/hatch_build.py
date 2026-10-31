from __future__ import annotations

import importlib.util
import os
import subprocess
from typing import Any

import manygo
from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from hatchling.metadata.plugin.interface import MetadataHookInterface


class CustomMetadataHook(MetadataHookInterface):
    """Metadata hook to pin the optional auditor to this exact release."""

    def update(self, metadata: dict[str, Any]) -> None:
        """Pin onyx-devtools-audit, which ships the ods-audit binary.

        Both wheels are built from one commit and published from one tag, so an
        exact pin keeps `ods` and `ods-audit` from ever drifting apart.
        """
        metadata["optional-dependencies"] = {
            "audit": [f"onyx-devtools-audit=={self._version()}"],
        }

    def _version(self) -> str:
        """Read the version the same way [tool.hatch.version] does."""
        path = os.path.join(self.root, "internal", "_version.py")
        spec = importlib.util.spec_from_file_location("ods_version", path)
        if spec is None or spec.loader is None:
            msg = f"Cannot load the version from {path}"
            raise RuntimeError(msg)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return str(module.__version__)


class CustomBuildHook(BuildHookInterface):
    """Build hook to compile the Go binary and include it in the wheel."""

    def initialize(self, version: Any, build_data: Any) -> None:  # noqa: ARG002
        """Build the Go binary before packaging."""
        build_data["pure_python"] = False

        # Set platform tag for cross-compilation
        goos = os.getenv("GOOS")
        goarch = os.getenv("GOARCH")
        if manygo.is_goos(goos) and manygo.is_goarch(goarch):
            build_data["tag"] = "py3-none-" + manygo.get_platform_tag(
                goos=goos,
                goarch=goarch,
            )

        # Get config and environment
        binary_name = self.config["binary_name"]
        # The Go module directory and the package to build, both relative to the
        # project root. `onyx-devtools-audit` builds a package of the module that
        # lives next to it, so both are configurable.
        go_dir = os.path.join(self.root, self.config.get("go_dir", "."))
        go_package = self.config.get("go_package", ".")
        tag_prefix = self.config.get("tag_prefix", binary_name)
        tag = os.getenv("GITHUB_REF_NAME", "dev").removeprefix(f"{tag_prefix}/")
        commit = os.getenv("GITHUB_SHA", "none")

        # Build the Go binary if it doesn't exist
        binary_path = os.path.join(self.root, binary_name)
        if not os.path.exists(binary_path):
            print(f"Building Go binary '{binary_name}'...")
            ldflags = f"-X main.version={tag} -X main.commit={commit} -s -w"
            subprocess.check_call(  # noqa: S603
                ["go", "build", f"-ldflags={ldflags}", "-o", binary_path, go_package],
                cwd=go_dir,
            )

        build_data["shared_scripts"] = {binary_name: binary_name}
