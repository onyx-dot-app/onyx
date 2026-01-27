#!/usr/bin/env python3
"""Test script for ACPAgentClient with opencode CLI.

Usage:
  # From backend directory:
  PYTHONPATH=. python onyx/server/features/build/sandbox/local/test_agent_client.py

  # Or with specific message:
  PYTHONPATH=. python onyx/server/features/build/sandbox/local/test_agent_client.py "What files are in this directory?"

  # With specific working directory:
  PYTHONPATH=. python onyx/server/features/build/sandbox/local/test_agent_client.py --dir /path/to/project "List files"
"""

import argparse
import shutil
import tempfile
from pathlib import Path

from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart

try:
    from onyx.server.features.build.sandbox.local.agent_client import ACPAgentClient
except ImportError:
    from agent_client import ACPAgentClient  # type: ignore


def test_with_opencode_acp(message: str, working_dir: str | None = None) -> None:
    """Test ACPAgentClient with the opencode CLI using ACP protocol."""
    print("=" * 60)
    print("Testing ACPAgentClient with opencode acp")
    print("=" * 60)

    # Use provided working dir or create temp dir
    if working_dir:
        work_dir = Path(working_dir)
        if not work_dir.exists():
            print(f"Working directory does not exist: {working_dir}")
            return
        cleanup_dir = False
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="opencode-test-"))
        cleanup_dir = True
        print(f"Created temp working directory: {work_dir}")

    try:
        print(f"\nStarting ACPAgentClient in: {work_dir}")

        # Use context manager - handles start/stop automatically
        with ACPAgentClient(cwd=str(work_dir)) as client:
            print(
                f"Agent: {client.agent_info.get('name', 'unknown')} "
                f"v{client.agent_info.get('version', '?')}"
            )
            print(f"Session ID: {client.session_id}")

            print(f"\nSending message: {message}")
            print("-" * 60)

            text_buffer = ""
            event_count = 0

            for event in client.send_message(message, timeout=120.0):
                event_count += 1

                if isinstance(event, AgentMessageChunk):
                    content = event.content
                    if content.type == "text":
                        text_buffer += content.text
                        print(content.text, end="", flush=True)

                elif isinstance(event, AgentThoughtChunk):
                    content = event.content
                    if content.type == "text":
                        print(f"\n[Thought: {content.text[:100]}...]", flush=True)

                elif isinstance(event, ToolCallStart):
                    print(
                        f"\n[Tool Call: {event.title} ({event.kind}) "
                        f"- {event.tool_call_id}]",
                        flush=True,
                    )

                elif isinstance(event, ToolCallProgress):
                    title_str = f"{event.title} " if event.title else ""
                    print(
                        f"\n[Tool Result: {title_str}{event.status} "
                        f"- {event.tool_call_id}]",
                        flush=True,
                    )

                elif isinstance(event, AgentPlanUpdate):
                    steps = event.plan.entries if event.plan else []
                    print(f"\n[Plan: {len(steps)} steps]", flush=True)

                elif isinstance(event, CurrentModeUpdate):
                    print(f"\n[Mode: {event.current_mode_id}]", flush=True)

                elif isinstance(event, PromptResponse):
                    print(f"\n\n[Done - stop_reason: {event.stop_reason}]")

                elif isinstance(event, Error):
                    print(f"\n[Error: {event.message}]")

                else:
                    print(f"\n[Unknown event]: {event}", flush=True)

            print("-" * 60)
            print(f"\nReceived {event_count} events total")
            if text_buffer:
                print(f"Total text length: {len(text_buffer)} chars")

    except RuntimeError as e:
        print(f"\nError: {e}")

    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback

        traceback.print_exc()

    finally:
        if cleanup_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
            print(f"\nCleaned up temp directory: {work_dir}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test ACPAgentClient with opencode CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with opencode CLI (default message)
  python test_agent_client.py

  # Test with specific message
  python test_agent_client.py "What is 2+2?"

  # Test with specific working directory
  python test_agent_client.py "List files" --dir /path/to/project
        """,
    )
    parser.add_argument(
        "message",
        type=str,
        nargs="?",
        default="What is 2+2? Reply briefly with just the number.",
        help="Message to send to opencode",
    )
    parser.add_argument(
        "--dir",
        type=str,
        metavar="PATH",
        help="Working directory for opencode (default: temp dir)",
    )

    args = parser.parse_args()

    print("\nACP Agent Client Test Suite")
    print("===========================\n")

    test_with_opencode_acp(args.message, args.dir)

    print("\n\nDone!")


if __name__ == "__main__":
    main()
