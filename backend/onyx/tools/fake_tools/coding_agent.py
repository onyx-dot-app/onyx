import time
from collections.abc import Iterator
from contextlib import contextmanager

from onyx.coding_agent.mock_tools import BASH_TOOL_CMD_KEY
from onyx.coding_agent.mock_tools import GENERATE_ANSWER_TOOL_NAME
from onyx.coding_agent.models import CodingAgentSpecialToolCalls
from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.tools.tool_implementations.bash.bash_tool import BashToolOverrideKwargs
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.utils.github import download_github_repo
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Allow up to an hour for the agent to investigate the repo
CODING_AGENT_SESSION_TTL_SECONDS = 60 * 60
# Per-bash-command timeout. Capped at the code-interpreter service's
# max_exec_timeout_ms (60s by default; configurable via MAX_EXEC_TIMEOUT_MS).
CODING_AGENT_BASH_TIMEOUT_MS = 60 * 1000
# Hard wall-clock timeout for the whole agent run
CODING_AGENT_FORCE_ANSWER_SECONDS = 25 * 60
# Same cap applies to setup commands (tarball extract). If a repo extract
# legitimately takes more than 60s, raise MAX_EXEC_TIMEOUT_MS on the
# code-interpreter service rather than this constant.
CODING_AGENT_SETUP_TIMEOUT_MS = 60 * 1000
# Tarball is staged at this path inside the session workspace
REPO_TARBALL_PATH = "repo.tar.gz"
# Sentinel tool_id used when constructing the in-memory BashTool. Bash sub-tool
# calls are not persisted to the DB through this loop, so the id is unused.
BASH_TOOL_SENTINEL_ID = 0
MAX_FINAL_ANSWER_TOKENS = 4000


@contextmanager
def _setup_session(
    repo: str,
    github_token: str | None,
) -> Iterator[str]:
    """Download ``repo``, create a code-interpreter session with the tarball
    staged + extracted, yield the session id, and delete the session on exit.

    Creates its own :class:`CodeInterpreterClient` internally and tears it
    down on exit, so callers only deal with the ``session_id``.
    """
    repo_bytes = download_github_repo(repo, github_token=github_token)

    with CodeInterpreterClient() as client:
        ci_file_id = client.upload_file(repo_bytes, REPO_TARBALL_PATH)
        session_info = client.create_session(
            ttl_seconds=CODING_AGENT_SESSION_TTL_SECONDS,
            files=[{"path": REPO_TARBALL_PATH, "file_id": ci_file_id}],
        )
        session_id = session_info.session_id
        logger.info("Created coding agent session %s", session_id)

        try:
            # GitHub tarballs always have exactly one top-level dir;
            # --strip-components=1 extracts the contents directly into cwd so the
            # agent's bash calls see the repo root immediately.
            extract_cmd = (
                f"tar -xzf {REPO_TARBALL_PATH} --strip-components=1 "
                f"&& rm {REPO_TARBALL_PATH} && ls"
            )
            extract_result = client.execute_bash_in_session(
                session_id=session_id,
                cmd=extract_cmd,
                timeout_ms=CODING_AGENT_SETUP_TIMEOUT_MS,
            )
            if extract_result.exit_code != 0:
                raise RuntimeError(
                    f"Failed to extract repository tarball: {extract_result.stderr}"
                )
            logger.info("Extracted repo into session %s", session_id)
            yield session_id
        finally:
            try:
                client.delete_session(session_id)
                logger.info("Deleted coding agent session %s", session_id)
            except Exception as e:
                # Don't let cleanup failure mask any exception from the body.
                # The session has a TTL so the pod will eventually be reaped.
                logger.warning(
                    "Failed to delete coding agent session %s: %s", session_id, e
                )


def _run_bash_call(
    bash_tool: BashTool,
    tool_call: ToolCallKickoff,
) -> str:
    """Dispatch a single bash tool call and return the LLM-facing response."""
    cmd = tool_call.tool_args.get(BASH_TOOL_CMD_KEY)
    if not isinstance(cmd, str):
        logger.warning(
            "[coding_agent] bash tool call %s missing/non-string %r argument; "
            "got %r",
            tool_call.tool_call_id,
            BASH_TOOL_CMD_KEY,
            cmd,
        )
        return f'{{"error": "missing or non-string {BASH_TOOL_CMD_KEY!r} argument"}}'

    logger.info(
        "[coding_agent] bash %s: %s",
        tool_call.tool_call_id,
        cmd,
    )
    start = time.monotonic()
    response = bash_tool.run(
        placement=tool_call.placement,
        override_kwargs=BashToolOverrideKwargs(),
        **{BASH_TOOL_CMD_KEY: cmd},
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "[coding_agent] bash %s done in %dms (response %d chars)",
        tool_call.tool_call_id,
        duration_ms,
        len(response.llm_facing_response),
    )
    return response.llm_facing_response


def check_special_tool_calls(
    tool_calls: list[ToolCallKickoff],
) -> CodingAgentSpecialToolCalls:
    think_tool_call: ToolCallKickoff | None = None
    generate_answer_tool_call: ToolCallKickoff | None = None

    for tool_call in tool_calls:
        if tool_call.tool_name == THINK_TOOL_NAME:
            think_tool_call = tool_call
        elif tool_call.tool_name == GENERATE_ANSWER_TOOL_NAME:
            generate_answer_tool_call = tool_call

    return CodingAgentSpecialToolCalls(
        think_tool_call=think_tool_call,
        generate_answer_tool_call=generate_answer_tool_call,
    )
