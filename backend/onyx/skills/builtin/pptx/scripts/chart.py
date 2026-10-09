"""Deck-styled matplotlib baseline for slide charts.

Usage (from the session workspace):

    import sys
    sys.path.insert(0, ".opencode/skills/pptx/scripts")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from chart import deck_style, save_for_slide

    with deck_style(palette=["1E2761", "CADCFC", "F96167"], font="Montserrat"):
        fig, ax = plt.subplots(layout="constrained")
        ax.bar(["Q1", "Q2", "Q3", "Q4"], [4500, 5500, 6200, 7100])
        ax.set_title("Quarterly Sales")
        save_for_slide(fig, "outputs/sales.png", width_in=6, height_in=3.5)

See charts.md for chart-type selection, sizing, and slide placement.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from cycler import cycler
from matplotlib.figure import Figure

SLIDE_DPI = 200


def _hex(color: str) -> str:
    return color if color.startswith("#") else f"#{color}"


@contextmanager
def deck_style(
    palette: list[str],
    font: str = "Inter",
    background: str | None = None,
    text_color: str = "334155",
    grid_color: str = "CBD5E1",
) -> Iterator[None]:
    text = _hex(text_color)
    grid = _hex(grid_color)
    face = "none" if background is None else _hex(background)
    rc: dict[str, Any] = {
        "axes.prop_cycle": cycler(color=[_hex(c) for c in palette]),
        "font.family": [font, "DejaVu Sans"],
        "font.size": 14,
        "axes.titlesize": 18,
        "axes.titleweight": "bold",
        "axes.labelsize": 14,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "legend.fontsize": 12,
        "text.color": text,
        "axes.labelcolor": text,
        "xtick.color": text,
        "ytick.color": text,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": grid,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": grid,
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "lines.linewidth": 2.5,
        "lines.markersize": 7,
        "figure.facecolor": face,
        "axes.facecolor": face,
        "savefig.facecolor": face,
        "legend.frameon": False,
    }
    with plt.rc_context(rc):
        yield


def save_for_slide(fig: Figure, path: str, width_in: float, height_in: float) -> None:
    """Save ``fig`` as a PNG sized for placement at width_in x height_in inches.

    Renders at 2x resolution (``SLIDE_DPI``); place the PNG at exactly
    ``width_in`` x ``height_in`` on the slide (e.g. pptxgenjs ``addImage``
    ``w``/``h``) so text renders at the sizes chosen in ``deck_style``.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.set_size_inches(width_in, height_in)
    fig.savefig(path, dpi=SLIDE_DPI)
    plt.close(fig)
