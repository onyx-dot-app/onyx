"""Entry point for the Onyx CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from onyx_cli import __version__


def main() -> None:
    """Main entry point for the onyx-cli command."""
    parser = argparse.ArgumentParser(
        prog="onyx-cli",
        description="Terminal UI for chatting with Onyx",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"onyx-cli {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # chat (default) - launch TUI
    subparsers.add_parser("chat", help="Launch the interactive chat TUI (default)")

    # configure - interactive config setup
    subparsers.add_parser("configure", help="Configure server URL and API key")

    # ask - one-shot question
    ask_parser = subparsers.add_parser("ask", help="Ask a one-shot question (non-interactive)")
    ask_parser.add_argument("question", help="The question to ask")
    ask_parser.add_argument("--persona-id", type=int, default=None, help="Persona/assistant ID to use")
    ask_parser.add_argument("--json", action="store_true", dest="json_output", help="Output raw JSON events")

    args = parser.parse_args()

    if args.command == "configure":
        _run_configure()
    elif args.command == "ask":
        asyncio.run(_run_ask(args.question, args.persona_id, args.json_output))
    else:
        # Default: launch TUI (covers both "chat" and no subcommand)
        _run_chat()


def _run_chat() -> None:
    """Launch the interactive Textual TUI.

    If not yet configured, runs onboarding in the terminal first.
    """
    from onyx_cli.config import config_exists, load_config
    from onyx_cli.onboarding import run_onboarding

    config = load_config()

    # First-run: onboarding in the terminal before TUI launches
    if not config_exists() or not config.is_configured():
        config = run_onboarding(config)
        if config is None:
            return

    from onyx_cli.app import OnyxApp

    app = OnyxApp(config=config)
    app.run()


def _run_configure() -> None:
    """Run interactive configuration setup (same as first-run onboarding)."""
    from onyx_cli.config import load_config
    from onyx_cli.onboarding import run_onboarding

    config = load_config()
    run_onboarding(config)


async def _run_ask(question: str, persona_id: int | None, json_output: bool) -> None:
    """Run a one-shot question and print the answer."""
    from onyx_cli.api_client import OnyxApiClient
    from onyx_cli.config import load_config
    from onyx_cli.models import (
        ErrorEvent,
        MessageDeltaEvent,
        StopEvent,
    )

    config = load_config()
    if not config.is_configured():
        print("Error: Onyx CLI is not configured. Run 'onyx-cli configure' first.", file=sys.stderr)
        sys.exit(1)

    pid = persona_id if persona_id is not None else config.default_persona_id

    client = OnyxApiClient(config)
    try:
        async for event in client.send_message_stream(
            message=question,
            persona_id=pid,
        ):
            if json_output:
                print(json.dumps(event.model_dump(), default=str))
            else:
                match event:
                    case MessageDeltaEvent():
                        print(event.content, end="", flush=True)
                    case ErrorEvent():
                        print(f"\nError: {event.error}", file=sys.stderr)
                        sys.exit(1)
                    case StopEvent():
                        break

        if not json_output:
            print()  # Final newline
    finally:
        await client.close()


if __name__ == "__main__":
    main()
