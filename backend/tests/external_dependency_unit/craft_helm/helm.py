"""Rendering the chart, for the tests in this shard.

Shared because "can this run here?" has exactly one right answer and it is easy
to get wrong: a missing helm binary or unbuilt chart dependencies mean the test
cannot run, while any other helm failure is the chart being broken. A render
test that reports a broken chart as a skip is worse than no test, so that
distinction lives here rather than in each module.

Callers own their own chart arguments — the values a suite needs to render its
template are its own business.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import NoReturn

import pytest

from tests.common.paths import find_ancestor_containing

REPO_ROOT = find_ancestor_containing("deployment/helm/charts/onyx")
CHART_DIR = REPO_ROOT / "deployment" / "helm" / "charts" / "onyx"

# Substrings helm uses when the gitignored subchart tarballs are absent.
_MISSING_DEPS_MARKERS = (
    "found in Chart.yaml, but missing in charts/",
    "missing in charts/ directory",
    "no cached repository",
)


def skip_or_fail(reason: str) -> NoReturn:
    """Skip locally, but fail in CI — a shard that renders nothing must not
    report green."""
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def handle_render_failure(stderr: str) -> NoReturn:
    """A missing-deps error means we can't run here; anything else is a real
    chart defect and must not be laundered into a skip."""
    if any(marker in stderr for marker in _MISSING_DEPS_MARKERS):
        skip_or_fail(f"chart dependencies not built: {stderr.strip()}")
    pytest.fail(f"helm template failed: {stderr.strip()}")


def template_cmd(chart_args: list[str]) -> list[str]:
    """The base ``helm template`` invocation, plus the caller's arguments."""
    helm = shutil.which("helm")
    if helm is None:
        skip_or_fail("helm binary not available")
    return [
        helm,
        "template",
        "onyx",
        str(CHART_DIR),
        "-n",
        "onyx",
        "-f",
        str(CHART_DIR / "values-ci.yaml"),
        *chart_args,
    ]


def run(
    chart_args: list[str], template: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Render, returning the result unjudged — for callers that assert on how a
    render failed, or on it rendering nothing at all."""
    cmd = template_cmd(chart_args)
    if template is not None:
        cmd += ["--show-only", template]
    return subprocess.run(cmd, capture_output=True, text=True)


def render(chart_args: list[str], template: str) -> str:
    """One template's manifests, failing the test if the chart is broken."""
    result = run(chart_args, template)
    if result.returncode != 0:
        handle_render_failure(result.stderr)
    return result.stdout
