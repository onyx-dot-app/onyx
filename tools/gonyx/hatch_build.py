from __future__ import annotations

import os
import subprocess
from typing import Any

import manygo
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Build hook to compile the Go binary and include it in the wheel."""

    def initialize(self, version: Any, build_data: Any) -> None:
        """Build the Go binary before packaging."""
        build_data["pure_python"] = False

        # Set platform tag for cross-compilation
        goos = os.getenv("GOOS")
        goarch = os.getenv("GOARCH")
        if goos and goarch:
            build_data["tag"] = "py3-none-" + manygo.get_platform_tag(
                goos=goos, goarch=goarch
            )

        # Get config and environment
        binary_name = self.config.get("binary_name", "gonyx")
        commit = os.getenv("GITHUB_SHA", "none")

        # Build the Go binary if it doesn't exist
        if not os.path.exists(binary_name):
            print(f"Building Go binary '{binary_name}'...")
            subprocess.check_call(  # noqa: S603
                [
                    "go",
                    "build",
                    f"-ldflags=-X main.version={version} -X main.commit={commit} -s -w",
                    "-o",
                    binary_name,
                ],
            )

        # Include the binary in the wheel
        build_data["force_include"][binary_name] = binary_name
