"""Tests for the pptx skill's ``scripts/chart.py`` styling helper.

matplotlib is a sandbox dependency, not a backend one, so the whole
module is skipped when it isn't importable. The helper isn't on the
backend import path either — it's loaded from its on-disk skill location.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

_PPTX_SKILL_DIR = Path(__file__).parents[4] / "onyx" / "skills" / "builtin" / "pptx"


def _load_chart_module() -> ModuleType:
    path = _PPTX_SKILL_DIR / "scripts" / "chart.py"
    spec = importlib.util.spec_from_file_location("pptx_chart", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


chart = _load_chart_module()


def test_deck_style_applies_palette_and_font() -> None:
    palette = ["1E2761", "#CADCFC", "F96167"]
    with chart.deck_style(palette=palette, font="Montserrat"):
        colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        assert colors == ["#1E2761", "#CADCFC", "#F96167"]
        assert plt.rcParams["font.family"][0] == "Montserrat"
        assert plt.rcParams["axes.spines.top"] is False
        assert plt.rcParams["axes.spines.right"] is False
    assert plt.rcParams["font.family"][0] != "Montserrat"


def test_save_for_slide_writes_png_at_2x_pixel_dimensions(
    tmp_path: Path,
) -> None:
    out = tmp_path / "chart.png"
    with chart.deck_style(palette=["1E2761"], font="Inter"):
        fig, ax = plt.subplots(layout="constrained")
        ax.bar(["Q1", "Q2"], [1, 2])
        chart.save_for_slide(fig, str(out), width_in=6, height_in=3.5)

    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.size == (
            int(6 * chart.SLIDE_DPI),
            int(3.5 * chart.SLIDE_DPI),
        )
