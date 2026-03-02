"""Big ASCII art splash widget for Onyx CLI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.widgets import Static


ONYX_LOGO = r"""
   ██████╗ ███╗   ██╗██╗   ██╗██╗  ██╗
  ██╔═══██╗████╗  ██║╚██╗ ██╔╝╚██╗██╔╝
  ██║   ██║██╔██╗ ██║ ╚████╔╝  ╚███╔╝
  ██║   ██║██║╚██╗██║  ╚██╔╝   ██╔██╗
  ╚██████╔╝██║ ╚████║   ██║   ██╔╝ ██╗
   ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝
"""

TAGLINE = "Your terminal interface for Onyx"


class SplashWidget(Static):
    """Displays the Onyx ASCII art logo."""

    DEFAULT_CSS = """
    SplashWidget {
        width: 100%;
        content-align: center middle;
        text-align: center;
        color: #7C6AEF;
        padding: 1 0;
    }
    """

    def __init__(self) -> None:
        super().__init__(ONYX_LOGO)


class SplashScreen(Vertical):
    """Full splash screen with logo and tagline."""

    DEFAULT_CSS = """
    SplashScreen {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 2;
    }

    SplashScreen .tagline {
        text-align: center;
        color: #A0A0A0;
        padding: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        with Center():
            yield SplashWidget()
        yield Static(TAGLINE, classes="tagline")
