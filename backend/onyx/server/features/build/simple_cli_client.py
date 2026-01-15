import asyncio
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import AsyncGenerator
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk import Message
from claude_agent_sdk import query
from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import ContentBlock
from claude_agent_sdk.types import TextBlock
from claude_agent_sdk.types import ThinkingBlock
from claude_agent_sdk.types import ToolResultBlock
from claude_agent_sdk.types import ToolUseBlock
from pydantic import BaseModel
from pydantic import ConfigDict

from onyx.configs.app_configs import PERSISTENT_DOCUMENT_STORAGE_PATH
from onyx.utils.logger import setup_logger

SANDBOX_BASE_PATH = "/Users/chrisweaver/data/sandboxes"
OUTPUTS_TEMPLATE_PATH = "/Users/chrisweaver/data/outputs_template/outputs"

logger = setup_logger()

# Type for message emitter callback - called with each message as it arrives
MessageEmitter = Callable[[Message], None]


class Sandbox(BaseModel):
    """Sandbox for running the Next.js dev server and the Claude agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    nextjs_process: subprocess.Popen[bytes] | None = None


# =============================================================================
# Agent Runner - Uses SDK types directly
# =============================================================================


async def run_claude_agent(
    task: str, path: str | Path
) -> AsyncGenerator[Message, None]:
    """
    Run the Claude agent and yield SDK message types.

    Args:
        task: The task/prompt for the agent
        path: Working directory for the agent

    Yields:
        Message: SDK message types (AssistantMessage, ResultMessage, etc.)
    """
    all_tools = ["Read", "Edit", "Bash", "Glob", "Grep"]

    async for message in query(
        prompt=task,
        options=ClaudeAgentOptions(
            allowed_tools=all_tools,
            permission_mode="bypassPermissions",
            cwd=path,
            setting_sources=["project"],
        ),
    ):
        yield message


def message_to_dict(message: Message) -> dict[str, Any]:
    """Convert an SDK message to a dictionary for serialization."""
    return asdict(message)


def content_block_to_dict(block: ContentBlock) -> dict[str, Any]:
    """Convert a content block to a dictionary for serialization."""
    return asdict(block)


def print_message(message: Message) -> None:
    """Pretty-print an SDK message to stdout."""
    if isinstance(message, AssistantMessage):
        for block in message.content:
            print_content_block(block)

    elif isinstance(message, ResultMessage):
        print("\n" + "=" * 60)
        print(f"RESULT: {message.subtype}")
        print("=" * 60)
        if message.total_cost_usd is not None:
            print(f"  Cost: ${message.total_cost_usd:.4f}")
        if message.duration_ms is not None:
            print(f"  Duration: {message.duration_ms}ms")
        if message.num_turns is not None:
            print(f"  Turns: {message.num_turns}")
        if message.is_error:
            print("  ERROR: True")
        if message.session_id:
            print(f"  Session ID: {message.session_id}")
        if message.result:
            print(f"  Result: {message.result}")

    else:
        # Unknown message type - dump as dict
        print("\n" + "~" * 60)
        print(f"MESSAGE: {type(message).__name__}")
        print("~" * 60)
        formatted = json.dumps(asdict(message), indent=4, default=str)
        for line in formatted.split("\n"):
            print(f"  {line}")


def print_content_block(block: ContentBlock) -> None:
    """Pretty-print a content block to stdout."""
    if isinstance(block, TextBlock):
        print("\n" + "=" * 60)
        print("TEXT:")
        print("=" * 60)
        print(block.text)

    elif isinstance(block, ThinkingBlock):
        print("\n" + "=" * 60)
        print("THINKING:")
        print("=" * 60)
        print(block.thinking)

    elif isinstance(block, ToolUseBlock):
        print("\n" + "-" * 60)
        print(f"TOOL CALL: {block.name}")
        print("-" * 60)
        print(f"  ID: {block.id}")
        if block.input:
            print("  INPUT:")
            formatted_input = json.dumps(block.input, indent=4)
            for line in formatted_input.split("\n"):
                print(f"    {line}")

    elif isinstance(block, ToolResultBlock):
        print("\n" + "+" * 60)
        print("TOOL RESULT:")
        print("+" * 60)
        print(f"  Tool Use ID: {block.tool_use_id}")
        if block.is_error:
            print("  IS ERROR: True")
        if block.content:
            print("  CONTENT:")
            if isinstance(block.content, str):
                # Truncate long content
                content = block.content
                if len(content) > 500:
                    content = content[:500] + "... (truncated)"
                print(f"    {content}")
            else:
                formatted = json.dumps(block.content, indent=4, default=str)
                for line in formatted.split("\n"):
                    print(f"    {line}")

    else:
        # Unknown block type
        print("\n" + "~" * 60)
        print(f"BLOCK: {type(block).__name__}")
        print("~" * 60)
        formatted = json.dumps(asdict(block), indent=4, default=str)
        for line in formatted.split("\n"):
            print(f"  {line}")


def wait_for_server(
    url: str,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> bool:
    """
    Wait for a server to become available by polling.

    Args:
        url: The URL to poll
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds

    Returns:
        True if server is up, False if timed out
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            pass
        time.sleep(poll_interval)
    return False


class SimpleCLIClient:
    """Client for communicating with the Simple CLI."""

    def __init__(
        self,
        file_system_path: Path | str = PERSISTENT_DOCUMENT_STORAGE_PATH,
        outputs_template_path: Path | str = OUTPUTS_TEMPLATE_PATH,
        sandbox_base_path: Path | str = SANDBOX_BASE_PATH,
    ):
        self.file_system_path = (
            file_system_path
            if isinstance(file_system_path, Path)
            else Path(file_system_path)
        )
        self.outputs_template_path = (
            outputs_template_path
            if isinstance(outputs_template_path, Path)
            else Path(outputs_template_path)
        )
        self.sandbox_base_path = (
            sandbox_base_path
            if isinstance(sandbox_base_path, Path)
            else Path(sandbox_base_path)
        )

    def run_cli_agent(
        self,
        sandbox_id: str,
        task: str,
        emitter: MessageEmitter | None = None,
    ) -> Sandbox:
        """
        Run the CLI agent in a sandbox.

        Args:
            sandbox_id: Unique identifier for the sandbox
            task: The task/prompt for the agent
            emitter: Optional callback that receives each message as it arrives.
                     If not provided, messages are printed to stdout.
        """
        # set up the sandbox
        sandbox_path = self.sandbox_base_path / sandbox_id
        sandbox_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Sandbox path: {sandbox_path}")

        # set up the file system - create a read-only symlink to the source files
        file_system_link = sandbox_path / "files"
        if not file_system_link.exists():
            file_system_link.symlink_to(self.file_system_path, target_is_directory=True)

        # set up the output directory - copy the template
        output_dir = sandbox_path / "outputs"
        if not output_dir.exists():
            shutil.copytree(self.outputs_template_path, output_dir, symlinks=True)

        # start the Next.js dev server on port 3002
        web_dir = output_dir / "web"
        if not web_dir.exists():
            raise RuntimeError("Web directory does not exist")

        # Clear Next.js cache to avoid stale paths from template
        next_cache = web_dir / ".next"
        if next_cache.exists():
            shutil.rmtree(next_cache)

        logger.info("Starting Next.js dev server on port 3002...")
        nextjs_process = subprocess.Popen(
            ["npm", "run", "dev", "--", "-p", "3002"],
            cwd=web_dir,
        )
        # Wait for the server to be ready
        server_url = "http://localhost:3002"
        logger.info(f"Waiting for Next.js server at {server_url}...")
        if wait_for_server(server_url, timeout=60.0):
            logger.info(f"Next.js dev server is ready at {server_url}")
        else:
            logger.error(
                f"Next.js dev server failed to start within 60 seconds. "
                f"Process still running: {nextjs_process.poll() is None}"
            )
            raise RuntimeError("Next.js dev server failed to start")

        # build the instructions file - copy CLAUDE.template.md to CLAUDE.md
        claude_md_path = sandbox_path / "CLAUDE.md"
        if not claude_md_path.exists():
            template_path = Path(__file__).parent / "CLAUDE.template.md"
            shutil.copy(template_path, claude_md_path)

        logger.info(f"Running agent with task: {task}")

        # Use provided emitter or fall back to print_message
        message_handler = emitter if emitter is not None else print_message

        # run the agent and emit messages as they arrive
        async def _run_and_emit() -> None:
            async for message in run_claude_agent(task=task, path=sandbox_path):
                message_handler(message)

        sandbox = Sandbox(path=sandbox_path, nextjs_process=nextjs_process)

        asyncio.run(_run_and_emit())

        return sandbox

    @classmethod
    def cleanup_sandbox(cls, sandbox: Sandbox) -> None:
        nextjs_process = sandbox.nextjs_process
        if nextjs_process is not None:
            logger.info("Terminating Next.js dev server...")
            nextjs_process.terminate()
            try:
                nextjs_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Next.js server did not terminate, killing...")
                nextjs_process.kill()
            logger.info("Next.js dev server stopped")

        # Clean up the sandbox contents
        sandbox_path = sandbox.path
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)
            logger.info(f"Deleted sandbox at: {sandbox_path}")


if __name__ == "__main__":
    client = SimpleCLIClient()
    sandbox_id = f"sandbox-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    sandbox = client.run_cli_agent(
        sandbox_id,
        "".join(
            [
                "Build a dashboard that shows/categorizes the new things added to the repo. "
                "Specifically want to know how many of each 'tag' went in (e.g. feat, fix, chore, etc.). "
                "Allow me to set the group by period (e.g. day, week, month)",
            ]
        ),
    )

    # Wait for user input before cleanup
    input("\nPress Enter to delete the sandbox and exit...")

    # Clean up the sandbox
    SimpleCLIClient.cleanup_sandbox(sandbox)
