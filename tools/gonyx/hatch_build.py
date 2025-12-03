from __future__ import annotations

import os
import subprocess

import manygo
from hatchling.builders.hooks.plugin import interface


class GoBinaryBuildHook(interface.BuildHookInterface):
    def initialize(self, version, build_data) -> None:  # noqa: ANN001, ARG002
        build_data["pure_python"] = False
        goos = os.getenv("GOOS")
        goarch = os.getenv("GOARCH")
        if goos and goarch:
            build_data["tag"] = "py3-none-" + manygo.get_platform_tag(goos=goos, goarch=goarch)  # type: ignore[invalid-argument-type]
        binary_name = self.config["binary_name"]
        tag = os.getenv("GITHUB_REF_NAME", "dev").lstrip("gonyx/")
        commit = os.getenv("GITHUB_SHA", "none")

        if not os.path.exists(binary_name):
            print(f"Building Go binary '{binary_name}'...")
            subprocess.check_call(  # noqa: S603
                [
                    "go",
                    "build",
                    f"-ldflags=-X main.version={tag} -X main.commit={commit} -s -w",
                    "-o",
                    binary_name,
                ],
            )

        build_data["shared_scripts"] = {binary_name: binary_name}
