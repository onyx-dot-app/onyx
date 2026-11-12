"""Shared Helm renderer for Craft chart tests."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from tests.common.paths import find_ancestor_containing

_REPO_ROOT: Path = find_ancestor_containing("deployment/helm/charts/onyx")
_CHART_DIR: Path = _REPO_ROOT / "deployment" / "helm" / "charts" / "onyx"
_DEFAULT_KUBE_VERSION_ARGS: list[str] = ["--kube-version", "1.33.0"]
_HELM_TEST_SECRET_ARGS: list[str] = [
    "--set-string",
    "auth.sandboxPushSecret.values.private_key=test-private-key",
]


def _chart_args_with_default_kube_version(
    extra_args: list[str] | None = None,
) -> list[str]:
    if extra_args is not None and "--kube-version" in extra_args:
        return list(extra_args)
    return [*_DEFAULT_KUBE_VERSION_ARGS, *(extra_args or [])]


def skip_or_fail(reason: str) -> NoReturn:
    """Skip locally, but fail in CI — a shard that renders nothing must not
    report green."""
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def helm_template_command(extra_args: list[str] | None = None) -> list[str]:
    helm: str | None = shutil.which("helm")
    if helm is None:
        skip_or_fail("helm binary not available")
    return [
        helm,
        "template",
        "onyx",
        str(_CHART_DIR),
        "-n",
        "onyx",
        "-f",
        str(_CHART_DIR / "values-ci.yaml"),
        *_chart_args_with_default_kube_version(extra_args),
        *_HELM_TEST_SECRET_ARGS,
    ]


def render_chart(
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        helm_template_command(extra_args), capture_output=True, text=True
    )
