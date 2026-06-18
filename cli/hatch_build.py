from __future__ import annotations

import os
import subprocess
from typing import Any

import manygo
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Build hook to compile the Go binary and include it in the wheel."""

    def initialize(self, version: Any, build_data: Any) -> None:  # noqa: ARG002
        """Build the Go binary before packaging."""
        build_data["pure_python"] = False

        # Set platform tag for cross-compilation
        goos = os.getenv("GOOS")
        goarch = os.getenv("GOARCH")
        wheel_platform_tag = os.getenv("ONYX_CLI_WHEEL_PLATFORM_TAG")
        if wheel_platform_tag:
            if goos != "linux":
                msg = "ONYX_CLI_WHEEL_PLATFORM_TAG is only supported with GOOS=linux"
                raise ValueError(msg)
            build_data["tag"] = f"py3-none-{wheel_platform_tag}"
        elif manygo.is_goos(goos) and manygo.is_goarch(goarch):
            build_data["tag"] = "py3-none-" + manygo.get_platform_tag(
                goos=goos,
                goarch=goarch,
            )

        # Get config and environment
        binary_name = self.config["binary_name"]
        tag_prefix = self.config.get("tag_prefix", binary_name)
        tag = os.getenv("GITHUB_REF_NAME", "dev").removeprefix(f"{tag_prefix}/")
        commit = os.getenv("GITHUB_SHA", "none")

        if os.getenv("ONYX_CLI_REUSE_BINARY") == "1":
            if not os.path.exists(binary_name):
                msg = f"ONYX_CLI_REUSE_BINARY=1 set, but {binary_name!r} does not exist"
                raise FileNotFoundError(msg)
            print(f"Reusing Go binary '{binary_name}'...")
        else:
            print(f"Building Go binary '{binary_name}'...")
            ldflags = f"-X main.version={tag} -X main.commit={commit} -s -w"
            env = os.environ.copy()
            if goos == "linux":
                env.setdefault("CGO_ENABLED", "0")
            subprocess.check_call(  # noqa: S603
                ["go", "build", f"-ldflags={ldflags}", "-o", binary_name],
                env=env,
            )

        build_data["shared_scripts"] = {binary_name: binary_name}
