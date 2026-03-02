"""First-run onboarding flow for Onyx CLI.

Runs as plain terminal I/O before the TUI launches, similar to
Claude Code / Codex CLI onboarding.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import webbrowser

from rich.console import Console
from rich.text import Text

from onyx_cli.config import OnyxCliConfig, save_config

console = Console()

# The logo lines (no markup, raw characters) — used to measure height.
_LOGO_LINES = [
    r"   ██████╗ ███╗   ██╗██╗   ██╗██╗  ██╗",
    r"  ██╔═══██╗████╗  ██║╚██╗ ██╔╝╚██╗██╔╝",
    r"  ██║   ██║██╔██╗ ██║ ╚████╔╝  ╚███╔╝ ",
    r"  ██║   ██║██║╚██╗██║  ╚██╔╝   ██╔██╗ ",
    r"  ╚██████╔╝██║ ╚████║   ██║   ██╔╝ ██╗",
    r"   ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝",
]

_TAGLINE = "Your terminal interface for Onyx"


def _get_terminal_height() -> int:
    """Get the terminal height, defaulting to 24."""
    return shutil.get_terminal_size((80, 24)).lines


def _get_terminal_width() -> int:
    """Get the terminal width, defaulting to 80."""
    return shutil.get_terminal_size((80, 24)).columns


def _print_splash() -> None:
    """Print the ONYX logo centered vertically and horizontally on a full terminal screen."""
    term_h = _get_terminal_height()
    term_w = _get_terminal_width()

    logo_height = len(_LOGO_LINES)
    tagline_height = 1
    # logo + 1 blank + tagline
    content_height = logo_height + 1 + tagline_height

    top_padding = max((term_h - content_height) // 2, 1)

    # Clear screen
    console.print("\n" * (term_h - 1), end="")

    # Top padding
    for _ in range(top_padding):
        console.print()

    # Logo — center each line horizontally
    for line in _LOGO_LINES:
        pad = max((term_w - len(line)) // 2, 0)
        console.print(f"{' ' * pad}[bold #7C6AEF]{line}[/]", highlight=False)

    # Blank line + tagline
    console.print()
    tag_pad = max((term_w - len(_TAGLINE)) // 2, 0)
    console.print(f"{' ' * tag_pad}[dim]{_TAGLINE}[/dim]", highlight=False)

    # Bottom padding to fill the rest of the screen
    remaining = term_h - top_padding - content_height
    for _ in range(max(remaining, 0)):
        console.print()


def run_onboarding(existing_config: OnyxCliConfig | None = None) -> OnyxCliConfig | None:
    """Run the interactive onboarding flow in the terminal.

    Returns the validated config, or None if the user cancels.
    """
    config = existing_config or OnyxCliConfig()

    _print_splash()

    # Pause briefly so the user sees the splash, then continue below it
    console.print()
    console.print("  Welcome to [bold]Onyx CLI[/bold].\n", highlight=False)

    # ── Server URL ───────────────────────────────────────────────────
    try:
        server_url = _prompt("  Onyx server URL", default=config.server_url)
    except (KeyboardInterrupt, EOFError):
        return None

    # ── API Key ──────────────────────────────────────────────────────
    console.print(
        "\n  [dim]Need an API key? Press Enter to open the admin panel in your browser,[/dim]"
        "\n  [dim]or paste your key below.[/dim]\n",
        highlight=False,
    )

    try:
        api_key = _prompt_secret("  API key", default=config.api_key)
    except (KeyboardInterrupt, EOFError):
        return None

    if not api_key:
        # Open browser to API key page
        url = f"{server_url.rstrip('/')}/admin/api-key"
        console.print(f"\n  Opening [link={url}]{url}[/link] ...")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        console.print("  [dim]Copy your API key, then paste it here.[/dim]\n")
        try:
            api_key = _prompt_secret("  API key")
        except (KeyboardInterrupt, EOFError):
            return None

        if not api_key:
            console.print("\n  [red]No API key provided. Exiting.[/red]")
            return None

    # ── Test Connection ──────────────────────────────────────────────
    config = OnyxCliConfig(
        server_url=server_url,
        api_key=api_key,
        default_persona_id=config.default_persona_id,
    )

    console.print("\n  [yellow]Testing connection...[/yellow]", highlight=False)

    from onyx_cli.api_client import OnyxApiClient

    async def _test() -> tuple[bool, str]:
        client = OnyxApiClient(config)
        try:
            return await client.test_connection()
        finally:
            await client.close()

    success, detail = asyncio.run(_test())

    if success:
        save_config(config)
        console.print(f"  [bold green]{detail}[/bold green]\n")
        _print_quick_start()
        return config
    else:
        console.print(f"  [bold red]Connection failed.[/bold red] {detail}\n")
        console.print("  [dim]Run [bold]onyx-cli configure[/bold] to try again.[/dim]")
        return None


def _prompt(label: str, default: str = "") -> str:
    """Prompt for a value with an optional default shown in brackets."""
    if default:
        raw = console.input(f"{label} [dim]\\[{default}][/dim]: ")
        return raw.strip() or default
    else:
        raw = console.input(f"{label}: ")
        return raw.strip()


def _prompt_secret(label: str, default: str = "") -> str:
    """Prompt for a secret value (not masked, since Rich doesn't support it,
    but we avoid echoing defaults)."""
    hint = " [dim]\\[saved][/dim]" if default else ""
    raw = console.input(f"{label}{hint}: ")
    return raw.strip() or default


def _print_quick_start() -> None:
    console.print("  [bold]Quick start[/bold]\n", highlight=False)
    console.print("  Just type to chat with your Onyx assistant.\n", highlight=False)
    rows = [
        ("/help", "Show all commands"),
        ("/attach", "Attach a file"),
        ("/persona", "Switch assistant"),
        ("/new", "New conversation"),
        ("/sessions", "Browse previous chats"),
        ("Esc", "Cancel generation"),
        ("Ctrl+D", "Quit"),
    ]
    for cmd, desc in rows:
        console.print(f"    [bold]{cmd:<12}[/bold] [dim]{desc}[/dim]", highlight=False)
    console.print()
