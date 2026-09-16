"""Run repository investigation directly through the shared Agent runtime."""

import argparse
import asyncio
from collections import deque

from onyx.agents.events import AgentEvent
from onyx.agents.models import RunResult
from onyx.coding_agent.agent import BASH_TOOL_SENTINEL_ID, CodingAgent, _setup_session
from onyx.db.engine.sql_engine import SqlEngine
from onyx.llm.factory import get_default_llm, get_llm_token_counter
from onyx.llm.models import UserMessage
from onyx.prompts.coding_agent.coding_agent import MAX_CODING_AGENT_CYCLES
from onyx.tools.tool_implementations.bash.bash_tool import BashTool


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repo as 'owner/name', https URL, or git@ URL",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="The question to ask the coding agent about the repo",
    )
    parser.add_argument(
        "--github-token",
        default=None,
        help="Optional GitHub PAT (private repos / higher rate limit)",
    )
    parser.add_argument(
        "--dump-packets",
        action="store_true",
        help="Print agent events that were streamed during the run",
    )
    parser.add_argument(
        "--max-packets-shown",
        type=int,
        default=50,
        help="Cap on how many packets to print when --dump-packets is set",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    SqlEngine.set_app_name("coding_agent_test")
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    llm = get_default_llm()
    events: deque[AgentEvent] = deque(maxlen=args.max_packets_shown)
    with _setup_session(repo=args.repo, github_token=args.github_token) as session_id:
        feature = CodingAgent(
            repo=args.repo,
            llm=llm,
            token_counter=get_llm_token_counter(llm),
            user_identity=None,
            bash_tool=BashTool(tool_id=BASH_TOOL_SENTINEL_ID, session_id=session_id),
        )

        async def execute() -> RunResult:
            run = feature.agent.start(
                max_steps=MAX_CODING_AGENT_CYCLES + 1,
                messages=[UserMessage(content=args.query)],
            )
            if args.dump_packets:
                run.subscribe(events.append)
            try:
                return await run.wait()
            finally:
                if not await run.wait_for_idle(timeout=60):
                    raise TimeoutError("Coding tools have not released their workspace")

        result = asyncio.run(execute())
        print(result.output.text)
    for event in events:
        print(event.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
