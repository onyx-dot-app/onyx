"""Offline tests for the CLI wheel build hook (no Go toolchain required)."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

CLI_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CLI_DIR.parent


def load_build_hook():
    """Import the build hook with lightweight stand-ins for build-only deps."""
    manygo = types.ModuleType("manygo")
    manygo.is_goos = lambda value: value in {"windows", "linux", "darwin"}
    manygo.is_goarch = lambda value: value in {"amd64", "arm64"}
    manygo.get_platform_tag = lambda *, goos, goarch: f"{goos}-{goarch}"

    stubs = {"manygo": manygo}
    for name in (
        "hatchling",
        "hatchling.builders",
        "hatchling.builders.hooks",
        "hatchling.builders.hooks.plugin",
    ):
        stub = types.ModuleType(name)
        stub.__path__ = []
        stubs[name] = stub

    interface = types.ModuleType("hatchling.builders.hooks.plugin.interface")
    interface.BuildHookInterface = type("BuildHookInterface", (), {})
    stubs[interface.__name__] = interface

    spec = importlib.util.spec_from_file_location(
        "onyx_hatch_build_test", CLI_DIR / "hatch_build.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class TestCliWheelBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_hook_module = load_build_hook()

    def build_target(self, *, goos=None, host_os="posix", binary_exists=False):
        module = self.build_hook_module
        hook = module.CustomBuildHook()
        hook.config = {"binary_name": "onyx-cli", "tag_prefix": "cli"}
        build_data = {}

        env = {"GOARCH": "amd64", "GITHUB_REF_NAME": "cli/v1.4.4"}
        if goos is not None:
            env["GOOS"] = goos

        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(module.os, "name", host_os),
            mock.patch.object(
                module.os.path, "exists", return_value=binary_exists
            ) as exists,
            mock.patch.object(module.subprocess, "check_call") as build,
        ):
            hook.initialize("1.4.4", build_data)

        self.assertFalse(build_data["pure_python"])
        if goos:
            self.assertEqual(build_data["tag"], f"py3-none-{goos}-amd64")
        else:
            self.assertNotIn("tag", build_data)
        self.assertEqual(exists.call_count, 1)
        return build_data["shared_scripts"], exists.call_args.args[0], build

    def test_cross_compiled_windows_executable_has_extension(self):
        scripts, searched, build = self.build_target(goos="windows")
        self.assertEqual(searched, "onyx-cli.exe")
        self.assertEqual(scripts, {"onyx-cli.exe": "onyx-cli.exe"})
        self.assertEqual(build.call_args.args[0][-2:], ["-o", "onyx-cli.exe"])

    def test_native_windows_without_goos_has_extension(self):
        scripts, _, build = self.build_target(host_os="nt")
        self.assertEqual(scripts, {"onyx-cli.exe": "onyx-cli.exe"})
        self.assertEqual(build.call_args.args[0][-2:], ["-o", "onyx-cli.exe"])

    def test_explicit_non_windows_target_on_windows_host(self):
        scripts, _, build = self.build_target(goos="linux", host_os="nt")
        self.assertEqual(scripts, {"onyx-cli": "onyx-cli"})
        self.assertEqual(build.call_args.args[0][-2:], ["-o", "onyx-cli"])

    def test_existing_target_binary_skips_build(self):
        scripts, _, build = self.build_target(goos="windows", binary_exists=True)
        self.assertEqual(scripts, {"onyx-cli.exe": "onyx-cli.exe"})
        build.assert_not_called()

    def test_release_cleans_both_binary_names_between_targets(self):
        workflow = (REPO_ROOT / ".github/workflows/release-cli.yml").read_text()
        cleanup_lines = [
            line.strip()
            for line in workflow.splitlines()
            if line.strip().startswith("rm -f onyx-cli")
        ]
        self.assertTrue(cleanup_lines, "release must clear cached CLI binaries")
        self.assertTrue(
            all(line == "rm -f onyx-cli onyx-cli.exe" for line in cleanup_lines)
        )


if __name__ == "__main__":
    unittest.main()
